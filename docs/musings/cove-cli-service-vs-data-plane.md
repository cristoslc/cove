# Cove CLI: Service Plane vs. Data Plane

The current CLI has an awkward split: `cove creds` mixes Vault-as-KV-store operations
(`vault-put`, `vault-get`) with 1Password-specific tooling (`batch-pull`, `1p-bulk-write`),
while Vault service operations (unseal, health) have no CLI at all — they're implicit
or buried in Ansible.

## The pattern

- **Service plane** = the software (`cove forgejo`, `cove vault`, `cove litellm`, `cove metamcp`)
  — lifecycle: up, down, status, logs, restart, provision
- **Data plane** = the abstraction (`cove secrets`, `cove llm`, `cove mcp`, `fj`)
  — data operations: get, put, list, import, chat, add-tool

The software name is the implementation detail. The abstraction name is the user-facing
concept — you want "secrets", not "Vault"; you want "LLM", not "LiteLLM".

When the data plane already has its own dedicated CLI (`fj` for Forgejo, `op` for
1Password), `cove` shouldn't duplicate it — just wrap it for automation.

## Proposed remapping

### `cove vault` (service plane — new)
- `cove vault status` — `vault_health()`, currently only in aggregate `cove status`
- `cove vault unseal` — `ensure_unsealed()`, currently automatic/lazy
- `cove vault token` — read/refresh root token from OS keystore
- `cove vault init` — bootstrap Vault (currently Ansible-only)

### `cove secrets` (data plane — replaces `cove creds vault-*`)
- `cove secrets get <key>` — read from Vault KV (current `vault-get`)
- `cove secrets put <key> <value>` — write to Vault KV (current `vault-put`)
- `cove secrets list` — list cached keys
- `cove secrets import 1p <ref>` — pull from 1Password (current `batch-pull`)
- `cove secrets import file <path>` — pull from encrypted file
- `cove secrets import age <path>` — pull from age-encrypted file

The provider model: `cove secrets` is always Vault KV on the backend, but you can
seed it from any source. 1Password becomes `cove secrets import 1p op://Private/...`
instead of `cove creds vault-put`. Adding age or sops as a provider doesn't change
the interface.

### `cove forgejo` (service plane — new)
- `cove forgejo status` — Forgejo API health (currently in aggregate `cove status`)
- `cove forgejo provision` — run `provision_forgejo.yml` (currently only via `cove up`)
- `cove forgejo admin-token` — get admin API token

Data plane is `fj` (separate CLI, already exists). No duplication.

### `cove litellm` (service plane — already exists)
- `cove litellm up / down / status / logs`

### `cove llm` (data plane — hypothetical)
- `cove llm chat` — interact with LLM through the proxy
- `cove llm models` — list available models
- `cove llm config` — manage model routing

### `cove metamcp` (service plane — hypothetical)
- `cove metamcp up / down / status / logs`

### `cove mcp` (data plane — hypothetical)
- `cove mcp add <tool>` — register an MCP tool
- `cove mcp remove <tool>` — unregister
- `cove mcp list` — list registered tools

### `cove 1p` (cross-cutting tool — replaces `cove creds 1p-*`)
- `cove 1p bulk-write <spec>` — generate/execute 1Password item creation script
- `cove 1p pull` — pull all known `op://` refs (alias for `cove secrets import 1p --all`)

## What dissolves

`cove creds` disappears entirely, replaced by:
- `cove secrets` for the Vault KV abstraction
- `cove 1p` for 1Password-specific tooling
- `cove vault` for Vault service lifecycle

## Design principle

`cove <software>` for lifecycle, `cove <abstraction>` for data. Cross-cutting tools
(1Password) get their own `cove <tool>` group. When a dedicated CLI already exists
(`fj`, `op`), `cove` wraps rather than replaces.
