# Unattended 1Password access

Cove reads and writes 1Password in two situations, and they need different mechanisms.

## Interactive: the CLI

`cove creds vault-put`, `vault-get`, `batch-pull` and the provisioning plays shell out to `op`. On macOS that is the biometric path: the desktop app authorizes the read, and a warm local cache means a converge never needs it. This is the default and it needs no setup.

## Unattended: the official SDK

The CLI keeps no session between agent calls: inside an agent shell `op whoami` reports "account is not signed in", so anything that must run without a human present cannot use it. The ruled path (decision `dec_fgl9wusck656`) is the official SDK behind a scoped **service account**:

1. Create a service account in 1Password under Developer tools, scoped to the vaults Cove needs.
2. Export its token as `OP_SERVICE_ACCOUNT_TOKEN` in the environment of whatever runs unattended.
3. Install the optional extra: `uv pip install onepassword-sdk` (or `onepassword-sdk>=0.4.2,<1`).

With the token present **and the SDK installed**, `cove` prefers the SDK for reads: `vault-put`, `batch-pull` and the provisioning plays resolve references through it instead of `op`. Without the token they use the CLI path unchanged.

The token alone is not enough to select the SDK, because the SDK is an optional extra (`cove[onepassword]`) that nothing installs by default. Exporting a token onto a machine without it would otherwise take the working path away: `op` resolves the same reference from that same token, with no prompt and no session. Selection therefore checks both, and a token without the extra reads through the CLI rather than failing.

Both paths were proven against one item on 2026-11-20: `op read` and the SDK returned values of the same length with the same SHA-256 prefix.

Writing an item unattended uses the SDK as well:

```shell
# the value comes from a file so it never appears in a process list
cove creds item-put --vault Private --title "Renovate Bot (git.cove)" \
  --field token --value-file /tmp/forgejo-token
```

It prints the action (`created` or `updated`) and the item id, never the value. An existing title is updated in place; a missing field is appended.

## What was rejected, and why

- **The community MCP server.** A single-maintainer package holding vault access inside the agent, with the same token requirement. Convenient, but the code that can read every granted item is not ours to review.
- **1Password Connect.** A self-hosted server plus a long-lived Connect token, gated on a plan tier that includes it. Heavier than the task.

## Boundaries

- The token is a service account credential, not a personal session. Scope it to the vaults Cove needs and nothing else, and treat it like any other credential: rotate on exposure, revoke when a host is retired.
- A missing token is a loud failure naming the variable. Nothing silently falls back to an unsanitized path, and nothing hangs waiting for a prompt.

## Two seams, not one

- **Readers** talk to the OpenBao store. Services render from it and other lanes' tooling reads it; nothing that consumes a secret knows where it came from.
- **The populator** talks to the durable vault. `cli/cove/secret_providers.py` holds that seam: a `SecretProvider` protocol, a registry by URI scheme, and one implementation per way a machine can authenticate.

Today both implementations speak `op://`, because they are two ways to reach the same backend: the CLI when a human is present, the SDK when a service-account token is. A different backend is one new class plus its scheme; the store, its contents and every consumer stay as they are. A reference with an unknown scheme is refused by name rather than guessed at.

## One vault setting

The vault every reference names is one variable, `COVE_OP_VAULT`. Both halves read it: `cli/cove/creds.py` builds `OP_REFS` from it, and `compose/group_vars/all.yml` renders `op_vault` from the same value, which `cove up` passes through to Ansible.

```shell
# the default when unset
COVE_OP_VAULT=Private

# after moving items to a vault a service account can read
export COVE_OP_VAULT="<vault name>"
```

A vault move is therefore one exported variable plus a converge, not thirteen reference edits. An empty value falls back to `Private` rather than naming a blank vault. Warming the cache afterwards still needs a working read path (a signed-in CLI or `OP_SERVICE_ACCOUNT_TOKEN`), because every reference under the new name is a cache miss by definition.

## What Cove needs from the vault

References resolve by **item title and field id**, so a vault move has to carry the items whole: moving one and retitling it breaks the reference that names it.

Read on every converge or service start:

- `Forgejo {hostname} Admin` — `password`, the forge admin login.
- `Vault {hostname} {username}` — `password`, the OpenBao userpass entry.
- `Cove Admin` — `username` and `password`, the shared service admin identity (ADR-017), read by Bifrost and Speedtest.
- `Bifrost Gateway` — `encryption_key` and `admin_password`.
- `Cove LLM Proxy Client Key` — `client_key`, the token clients present at `llmproxy.cove`.
- `Speedtest Tracker` — `app_key`.
- `Renovate Bot (git.cove)` — `token`, read by the nightly merge automation.

Read only when the matching service exists:

- `MinIO {hostname} Root` — `password`. No MinIO service is in this stack today, so the reference is dormant.
- `Zrok Account` — `account_token` and `share_token`. Read only when the `tunnel` profile runs.

Every one of these is a **read**. Cove writes to 1Password only through `cove creds item-put`, which is a rotation action a person runs, so a service account granted **read-only** on the vault is sufficient for unattended operation.

That makes a narrow vault the right shape: one vault holding exactly the items above, granted to the service account and nothing else. The account cannot see the rest of the account's vaults, and a leak of its token exposes only the credentials Cove already reads on every converge.
