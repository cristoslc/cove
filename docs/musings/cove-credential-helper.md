# Cove Credential Helper: Bridging `fj` OAuth Tokens to `git`

**Date:** 2026-06-25
**Status:** musing → sashay

## Context

`git push` to `https://git.cove/...` fails with "Credentials are incorrect or have expired" after ~1 hour or after `cove up`. Root cause: GCM's Generic provider stores OAuth access tokens as static credentials — no expiry check, no refresh. The refresh token sits unused in the keychain.

Full diagnosis in [gcm-oauth-token-expiry.md](gcm-oauth-token-expiry.md).

## Decision: Cove-side Python helper

Rather than wait for an upstream `fj` Rust PR or a GCM patch, build a `cove creds git-helper` command that:

1. Reads `fj`'s `keys.json` (`~/Library/Application Support/Cyborus.forgejo-cli/keys.json`)
2. Looks up the OAuth login for the requested host
3. Checks if the access token is expired
4. If expired, refreshes via `POST /login/oauth/access_token` with `grant_type=refresh_token`
5. Writes the updated token back to `keys.json`
6. Outputs `git credential` protocol format to stdout

Configured via:
```
git config --global credential.https://git.cove.helper '!/path/to/cove creds git-helper'
```

## Why this works

- `fj` already has the OAuth refresh logic in `keys.rs:LoginInfo::refresh()` — we're replicating it in Python, not inventing it
- `keys.json` is a simple JSON file — no keychain access needed
- The `git credential` protocol is trivial: read `key=value\n` from stdin, write `key=value\n` to stdout
- Forgejo's OAuth endpoints are standard: `/login/oauth/authorize`, `/login/oauth/access_token`
- The client ID for git.cove is already in `fj`'s built-in list (or can be configured via `~/.config/forgejo-cli/client_ids`)

## Edge cases

- **No OAuth login for host:** fall through to GCM (exit 0 with no output — git will try the next helper)
- **Application token (not OAuth):** fall through to GCM (application tokens don't expire, GCM handles them fine)
- **Refresh fails (token revoked):** fall through to GCM, which will prompt for re-auth
- **`keys.json` doesn't exist:** fall through to GCM
- **Concurrent access to `keys.json`:** use atomic write (write to temp file, rename)

## Why not just use `fj`'s token directly?

`fj` stores tokens in `keys.json` but doesn't expose them via a `git credential` interface. We could shell out to `fj` for the refresh, but `fj` has no `refresh` subcommand — refresh only happens internally when `fj` makes API calls. So we need to do the HTTP call ourselves.

## Implementation plan

See [sashay-cove-credential-helper.md](../plans/sashay-cove-credential-helper.md).
