---
title: "OpenBao: the Cove secrets server"
created: 2026-10-31
status: Active
---

# OpenBao: the Cove secrets server

Cove's secrets store is **OpenBao 2.7.x**, running as the compose service `vault`, on the host `vault.cove` / `vault.cove.local`. The service name, container name (`cove-vault`), ingress vhost, certificate SANs, and `/etc/hosts` entries are unchanged from the HashiCorp Vault era, so nothing outside this document needs to learn a new name.

The decision, the evidence, and the alternatives are in [the openbao vs vault brief](../musings/openbao-vs-vault.md) ([#126](../../pulls/126)). The short version: Cove's Vault pin was Vault 1.20, whose OSS line stopped receiving patches on 2025-09-24, and every call Cove makes is documented and unchanged in OpenBao 2.7.x.

## Surface

| Aspect | Value |
|---|---|
| Image | `openbao/openbao:2.7.2@sha256:5046911075e137e154ce49ab051502f4ec7cf367d484ae4a4dce665d9b90561f` |
| Pin | `compose/group_vars/all.yml` (`vault_image_tag` + `vault_image_digest`) |
| Container | `cove-vault` (`VAULT_CONTAINER_NAME` in the rendered compose `.env`) |
| Service / host | `vault` / `vault.cove`, `vault.cove.local`, `vault.cove.<machine-slug>` |
| Ingress | nginx vhost, proxy target `vault:8200`; no direct host port |
| Storage | Raft at `${COVE_DATA_ROOT}/vault/data`, mounted at `/openbao/data` |
| Config | `compose/vault/vault.hcl`, mounted at `/openbao/config/vault.hcl` |
| Seal | Shamir, 5 shares / 3 threshold |
| Keys | `cove/vault/unseal-1..5` and `cove/vault/root-token` in the OS keystore (Keychain / `secret-tool`) |
| KV | KV v2 mount at `secret/`, holding `op-cache/` |
| UI | `https://vault.cove/ui/`, userpass login (workstation lane) |
| Healthcheck | `bao status -address=http://127.0.0.1:8200` |

The image is an OCI index, not a single-arch manifest. `docker buildx imagetools inspect` reports `linux/amd64` (`sha256:a78eb12a...`) and `linux/arm64` (`sha256:dcf8c714...`) plus four other architectures. Cove's hosts are amd64 or arm64, both covered by the index digest above.

### What consumes it

Only the operator's CLI and the Ansible playbooks talk to the secrets server. The KV cache backs credential resolution for `cove up`, `cove creds`, `cove tunnel`, `cove litellm`, `cove bifrost`, `cove speedtest`, and the Forgejo admin provisioning playbook. No service container reads it at runtime.

## Why OpenBao

- **Patched versions.** OpenBao ships minors every 2 to 3 months and patch releases roughly monthly. Cove's previous pin, Vault 1.20.4, was the last OSS patch on 2025-09-24.
- **License.** MPL-2.0, inherited from the pre-BSL Vault tree, against Vault's BSL 1.1.
- **API compatibility.** Every call Cove makes is the same in 2.7.x: `sys/health`, `sys/seal-status`, `sys/init`, `sys/unseal` (with `reset`), `sys/mounts`, `sys/auth`, `sys/policies/acl`, KV v2 at `secret/data/...`, userpass login, and the `X-Vault-Token` header. The image also ships `/usr/bin/vault` as a symlink to `bao`.
- **Supply chain.** Signed, SBOM'd releases with Sigstore bundles and a digest-pinned Alpine base.

The cost is cadence, not code: OpenBao supports the newest minor only, so the pin gets bumped roughly quarterly. See [the stack update guide](../guides/stack-update-guide.md).

## Configuration

`compose/vault/vault.hcl` is unchanged in shape from the Vault era, with three deliberate differences:

```hcl
storage "raft" {
  path    = "/openbao/data"   # image default path; was /vault/data
  node_id = "cove-1"
}

listener "tcp" {
  address     = "0.0.0.0:8200"
  tls_disable = "true"
}

api_addr     = "http://127.0.0.1:8200"
cluster_addr = "https://127.0.0.1:8201"
ui           = true
```

1. The raft path is `/openbao/data`, the image's default tree.
2. `disable_mlock` is gone. OpenBao 2.0 removed mlock, so the directive is obsolete, and the `IPC_LOCK` capability is no longer granted.
3. The compose service runs as the operator's uid/gid (`VAULT_UID` / `VAULT_GID`, rendered by `bringup.yml`) with `SKIP_CHOWN=1`. The image's own `openbao` user is uid 100, and the bind-mounted data directory is operator-owned, so running as the operator keeps the data writable without chowning host paths. This is the same convention Forgejo uses with `FORGEJO_UID` / `FORGEJO_GID`.

The image's entrypoint always passes `-config=/openbao/config`, so `command: ["server"]` picks up the mounted file without an explicit `-config` argument.

## Operations

```
cove vault status     # initialized + unsealed, sealed, or not initialized
cove vault unseal     # read Shamir keys from the OS keystore and unseal
cove vault up         # converge the container, wait for the API, unseal if sealed
```

`cove up` calls the same unseal path as its last step. A sealed server after a reboot is normal: the keys live in the keystore, the data lives on disk, and unsealing is one command.

`COVE_VAULT_KEYSTORE_PREFIX` overrides the keystore namespace (default `cove/vault`). Use it to point a rehearsal or test instance at scratch entries so it never reads or overwrites the live unseal material.

### Observed OpenBao behaviours worth knowing

- **Health is 429 for a few seconds after unseal.** Single-node raft reports `standby: true` and HTTP 429 while it elects a leader, then settles at 200. The body still carries `initialized` and `sealed`, so every CLI unseal path is unaffected. `cove status` reports `initialized, standby` for that window instead of the old `Connection refused`.
- **A brand-new mount is not instantly routable.** A KV write issued immediately after `POST /v1/sys/mounts/secret` returned HTTP 400 once in rehearsal; the same write succeeded a second later. Re-seeding waits for the mount before the first write.
- **Token prefixes differ.** OpenBao 2.7.2 issues tokens with an `s.` prefix; Vault used `hvs.`. Cove treats the token as an opaque string, so only keystore contents change.

## Migrating a live host from Vault 1.20

This is a **fresh init**, not a storage upgrade. OpenBao makes no storage-compatibility guarantee for Vault raft data, and the only dataset is a rebuildable cache whose entries carry the `op_ref` they came from. The old data directory and the archived keystore entries are the rollback.

**Who must be present:** the operator, for one 1Password unlock (re-seeding reads every cached reference), for the keychain writes, and to confirm the UI login. There is no unattended version of this.

### Pre-flight

1. Confirm every cached entry carries an `op_ref`. With the current root token, walk `secret/metadata/op-cache` recursively and read each entry. Any entry without `op_ref` is a hand-written secret and must be exported before cutover. In rehearsal every entry had one.
2. Export the reference list so the replay is mechanical. Read the root token from the keystore into a shell variable (never echo it), then walk the tree:
   ```
   TOKEN=$(security find-generic-password -a "$USER" -s cove/vault/root-token -w)
   curl -s -H "X-Vault-Token: $TOKEN" \
     "https://vault.cove.local/v1/secret/metadata/op-cache?list=true" | jq -r '.data.keys[]'
   # recurse into each vault/item, then read each field's metadata:
   curl -s -H "X-Vault-Token: $TOKEN" \
     "https://vault.cove.local/v1/secret/data/op-cache/<vault>/<item>/<field>" \
     | jq -r '.data.data.op_ref'
   ```
   Save the `op_ref` strings to a file. No secret values are in that file.
3. Archive the old keystore entries. A fresh init overwrites `cove/vault/unseal-1..5` and `cove/vault/root-token`, and the old Vault needs them to unseal after a rollback:
   ```
   # macOS: repeat for unseal-1..5 and root-token
   security find-generic-password -a "$USER" -s cove/vault/unseal-1 -w \
     | xargs -I{} security add-generic-password -U -a "$USER" -s cove/vault-legacy/unseal-1 -w {}
   ```
   On Linux, use `secret-tool lookup` into `secret-tool store service cove/vault-legacy/...`.
4. Install the release that carries the OpenBao pin (`cove update`, or the documented reinstall). Do not converge yet.

### Cutover

1. Stop the service and move the old data aside. Keep it, do not delete it:
   ```
   docker stop cove-vault
   mv "$HOME/Documents/cove-data/vault/data" "$HOME/Documents/cove-data/vault/data.vault-1.20-$(date +%Y%m%d)"
   mkdir -p "$HOME/Documents/cove-data/vault/data"
   ```
2. Converge. `cove up` starts OpenBao with the new pin and leaves it uninitialized:
   ```
   cove up
   cove vault status        # exits non-zero: "Vault is running but not initialized" is expected here
   ```
3. Initialize and unseal with the existing playbook. It writes 5/3 Shamir shares and the root token to `cove/vault/*`, creates the KV v2 mount at `secret/`, and unseals:
   ```
   ansible-playbook -i inventory.yml bootstrap_vault.yml
   cove vault status        # initialized, unsealed
   ```
4. Replay the cache. `vault-put` always re-reads 1Password by contract, and `batch-pull` only fills the local cache, so Vault must be refilled with `vault-put`:
   ```
   while IFS= read -r ref; do cove creds vault-put "$ref"; done < op-refs.txt
   ```
   Expect one biometric prompt per entry unless the 1Password CLI session is already unlocked.
5. Re-provision the userpass UI login from the workstation lane, reusing the existing 1Password item:
   ```
   ansible-playbook -i inventory.yml provision_vault_user.yml
   ```
6. Verify: `cove vault status`, a UI login at `https://vault.cove/ui/`, and one `cove creds vault-get` round trip for a reference that was replayed.

### Rollback

The old data directory and the archived keystore entries were never written to by OpenBao.

1. Stop the container and restore the old data:
   ```
   docker stop cove-vault
   mv "$HOME/Documents/cove-data/vault/data" "$HOME/Documents/cove-data/vault/data.openbao-$(date +%Y%m%d)"
   mv "$HOME/Documents/cove-data/vault/data.vault-1.20-<stamp>" "$HOME/Documents/cove-data/vault/data"
   ```
2. Revert the pin to the previous release (reinstall the prior wheel, or restore `cli/` and `compose/` at the last tag and reinstall).
3. Converge, then restore the live keystore namespace from the archive (copy `cove/vault-legacy/*` back to `cove/vault/*`), and unseal:
   ```
   cove up
   cove vault unseal
   cove vault status
   ```
4. Delete `data.openbao-<stamp>` once the rollback is confirmed.

Because the rollback only reverts a pin and restores a directory, it is materially safer than an in-place storage upgrade, whose rollback would be a snapshot restore.

## Tests

`cli/tests/test_openbao.py` pins the image identity, the compose service shape (user override, no `IPC_LOCK`, `/openbao` mounts, `bao` healthcheck), the config shape (no `disable_mlock`, raft path, listener, UI), the keystore prefix override, and the standby health mapping. The Vault API call sites are covered by `test_vault.py`, `test_vault_unseal.py`, and `test_vault_cache.py`, which are API-shape tests and unchanged by the swap.
