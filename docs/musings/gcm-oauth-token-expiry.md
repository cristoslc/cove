# GCM OAuth Token Expiry: Why `git push` Fails After Cove Restarts

**Date:** 2026-06-25
**Status:** musing

## Symptom

```
$ git push
remote: Credentials are incorrect or have expired.
fatal: Authentication failed for 'https://git.cove/cristos/...'
```

Occurs frequently after `cove up` (Forgejo restart) and sometimes even while Cove is running. The workaround is `fj auth add-key`, which works because it creates a long-lived application token. But the question is: why does the OAuth flow through GCM fail?

## Diagnosis

### GCM is working — it returns a token

```
$ echo "protocol=https\nhost=git.cove\n" | git credential fill
protocol=https
host=git.cove
username=OAUTH_USER
password=eyJ...  ← valid JWT
```

GCM's Generic provider retrieves the credential from the macOS keychain. No error there.

### The access token has a 1-hour lifetime

```json
{
  "gnt": 1,     // grant type
  "tt": 0,      // token type: 0 = access, 1 = refresh
  "exp": 1782406256,  // 2026-06-25 12:50:56
  "iat": 1782402656   // 2026-06-25 11:50:56
}
// lifetime: 3600 seconds = 60 minutes
```

### A refresh token exists with a 30-day lifetime

```json
{
  "gnt": 1,
  "tt": 1,      // token type: refresh
  "cnt": 73,
  "exp": 1785030656,  // 2026-07-25 21:50:56
  "iat": 1782402656
}
// lifetime: 730 hours = ~30 days
```

Both tokens are stored in the macOS keychain:
- `git:https://git.cove` → access token (1hr TTL)
- `git:https://refresh_token.git.cove` → refresh token (30 day TTL)

### GCM trace confirms the problem

```
Host provider override was set id='generic'
Host provider 'Generic' was selected.
Looking for existing credential in store with service=https://git.cove account=...
Existing credential found.
```

GCM's **Generic** host provider is a static credential store. It stores whatever `fj auth login` gives it and returns it verbatim on `git credential fill`. It has **no OAuth refresh logic** — it doesn't know that the stored password is a JWT with an expiry, and it doesn't know how to use the refresh token to obtain a new access token.

## Root Cause

The architecture has a **credential lifecycle mismatch**:

1. `fj auth login` performs an OAuth flow against Forgejo, obtaining a short-lived access token (1hr) and a long-lived refresh token (30 days).
2. `fj auth login` stores both tokens in GCM's credential store via `git credential store`.
3. GCM's Generic provider treats them as static username/password — it has no concept of token expiry or refresh.
4. After 1 hour, the access token expires. GCM still returns it. Forgejo rejects it.
5. The refresh token sits unused in the keychain.

This is not a GCM bug — it's a design gap. The Generic provider is exactly that: generic. It doesn't implement OAuth 2.0 token refresh. That's what the GitHub-specific provider does (it knows how to use `gh` as a credential helper, which handles OAuth refresh). For Forgejo/git.cove, there is no equivalent provider.

### Why it correlates with `cove up`

When Forgejo restarts, it may invalidate existing access tokens (depending on JWT signing key rotation or session state). Even if the token hasn't hit its 1hr TTL, a restart can render it invalid. GCM returns the cached (now-invalid) token, and Forgejo rejects it.

### Why `fj auth add-key` works

`fj auth add-key` creates a long-lived **application token** (not an OAuth token). These don't have the 1hr TTL problem — they're valid until revoked. GCM stores it as a static credential, and since it doesn't expire within a session, the static-store model works.

## Is There a Better GCM Provider?

GCM ships with three built-in host providers: **GitHub**, **GitLab**, **Azure Repos**, and a fallback **Generic** provider. The question is whether any of them can handle OAuth refresh for git.cove.

### GitLab provider — has refresh, won't detect git.cove

The GitLab provider (`GitLab.dll`) has full OAuth lifecycle management:

```csharp
// GitLabHostProvider.GetCredentialAsync (simplified):
if (credential?.Account == "oauth2" && await IsOAuthTokenExpired(...))
    credential = null;  // discard expired token

if (credential == null) {
    // Try refresh token
    string refreshToken = store.Get(refreshService, userName)?.Password;
    if (refreshToken != null)
        credential = await RefreshOAuthCredentialAsync(input, refreshToken);
}
credential ??= await GenerateCredentialAsync(input);  // interactive fallback
```

This is exactly what we need. But its `IsSupported` method checks for `gitlab.*` in the hostname or `X-Gitlab-Feature-Category` header — neither of which git.cove provides. It won't auto-detect.

### Generic provider — has OAuth config, but `GetCredentialAsync` is the problem

The Generic provider's `GenerateCredentialAsync` **does** support OAuth with refresh tokens. It even has a well-known Gitea config that auto-detects via `Www-Authenticate: Basic realm="Gitea"` (which git.cove returns). It would set the correct endpoints (`/login/oauth/authorize`, `/login/oauth/access_token`) and the Gitea client ID.

**But** `GetCredentialAsync` is the critical difference:

```csharp
// GenericHostProvider.GetCredentialAsync:
ICredential credential = store.Get(service, userName);
if (credential == null)
    return await GenerateCredentialAsync(input);  // OAuth path — only on first use
else
    return new GetCredentialResult(credential);    // Returns stored token, NO expiry check
```

Once a credential is stored, the Generic provider returns it immediately — no expiry check, no refresh attempt. The OAuth refresh logic in `GenerateCredentialAsync` is never reached again. This is the root cause.

Compare: the GitLab provider checks expiry on every `get`, removes expired tokens, and tries refresh before falling back to interactive auth. The Generic provider does none of that.

### Why not just configure the GitLab provider for git.cove?

`credential.https://git.cove.provider=gitlab` would force it, but `IsSupported` would return `false` (hostname doesn't match `gitlab.*`), so GCM would fall back to Generic anyway. The provider override only works if the provider claims support.

### What about the Generic provider with explicit OAuth config?

Even with `credential.https://git.cove.oauthAuthzEndpoint` and `credential.https://git.cove.oauthTokenEndpoint` set, the Generic provider's `GetCredentialAsync` still returns the stored credential without checking expiry. The OAuth config only helps on the first `GenerateCredentialAsync` call.

## Possible Resolutions

### 1. `fj` credential helper with refresh logic (canonical fix)

`fj` could implement a `git credential` subcommand (like `gh auth git-credential`) that:
- On `get`: checks if the access token is expired, refreshes it using the refresh token if so, and returns a fresh token
- On `store`/`erase`: delegates to GCM or the keychain

Then configure: `credential.https://git.cove.helper=!/path/to/fj auth git-credential`

This mirrors how `gh` handles GitHub OAuth — `gh` is the credential helper, not GCM.

### 2. Use application tokens exclusively

Stop using `fj auth login` (OAuth) and use `fj auth add-key` (application token) as the primary auth method. This sidesteps the refresh problem entirely. The downside: application tokens don't auto-rotate, so they're less secure.

### 3. Extend access token lifetime in Forgejo

Configure Forgejo to issue access tokens with longer lifetimes (e.g., 24h or 7d). This reduces the frequency of expiry but doesn't solve the root cause — tokens will still expire eventually, and GCM won't refresh them.

### 4. Upstream fix to GCM's Generic provider

Add expiry-check-and-refresh logic to `GenericHostProvider.GetCredentialAsync`, mirroring what the GitLab provider does. This would benefit all Gitea/Forgejo users. The well-known Gitea config is already in place — it just needs the refresh loop.

### 5. Implement a GCM Forgejo host provider

Write a custom GCM host provider that understands Forgejo's OAuth endpoints and can perform token refresh. This is the most "correct" GCM-native approach but requires .NET development and distribution.

## Recommendation

Option 1 (`fj` credential helper) is the right architectural fix. It mirrors the proven `gh` pattern and keeps auth logic in the Forgejo CLI where it belongs. GCM's Generic provider is the wrong tool for OAuth — it's designed for static credentials (username/password, PATs), not token lifecycle management.

Option 4 (upstream GCM fix) would be the most broadly useful — it would fix this for all Gitea/Forgejo users, not just Cove. The well-known Gitea OAuth config already exists in GCM; the only missing piece is the expiry-check-and-refresh loop in `GetCredentialAsync`.

Until either is built, `fj auth add-key` is the pragmatic workaround. Consider documenting it as the recommended auth method for git.cove in the Cove setup guide.
