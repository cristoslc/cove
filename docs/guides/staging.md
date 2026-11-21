# Isolated Staging

How `scripts/staging/deploy-isolated.sh` runs a branch beside the live stack, what it provisions, what it deliberately leaves out, and what a vault-dependent test must do.

## What runs

The deploy starts the branch as a second Docker Compose project named `cove-staging`, in the same Docker daemon as the live project. It does not run `cove up` and does not re-render live nginx.

| Item | Value |
|-|-|
| Compose project | `cove-staging` |
| Ingress | `https://127.0.0.1:9443` (the only published host port) |
| Container names | `cove-staging-*` |
| Data root | `COVE_STAGING_DATA_ROOT` (must contain `staging`, must not overlap the live root) |
| Teardown | `scripts/staging/teardown.sh` removes the project, its volumes, and the data root |

The isolation contract is enforced by `cli/tests/test_staging_isolation.py`:

- every container name is `cove-staging-*`,
- every host port is remapped or removed,
- no bind mount resolves under the live data root,
- the staging data root is deleted by teardown.

## What the deploy provisions

The script reproduces the parts of `compose/bringup.yml` that the staging E2E needs, without Ansible and without 1Password:

- **Compose services** from the branch's `docker-compose.yml` plus `docker-compose.staging.yml`.
- **Certificates** copied read-only from the live root when present, otherwise a self-signed pair generated into the staging root.
- **nginx config** rendered from the branch template, with a throwaway staging `llmproxy` edge key.
- **ToolHive seed** (curated registry, default permission profile, control-plane config) under the staging root.
- **Forgejo runner config** rendered for the `cove-staging_default` network.
- **Docker socket gid**, resolved once and written to `staging.env` as both `FORGEJO_RUNNER_DOCKER_GID` and `TOOLHIVE_DOCKER_GID`.
- **The `vault` container**, started with an empty data directory.

## What the deploy does not provision

There is no Ansible run, no `cove up`, and no OS keystore access. In particular:

- OpenBao is **not initialized**, **not unsealed**, and gets **no KV entries**.
- No unseal keys or root token are written anywhere.
- Forgejo users, Bifrost keys, the Speedtest app key, and the tunnel token are not provisioned.
- The live credential cache is not copied.

The vault container therefore stays sealed. Its compose healthcheck reports `unhealthy`, and `GET /v1/sys/health` through `vault.cove` returns HTTP 501 with `initialized: false`. That is expected, not a failed provision.

## Why the vault is optional (option 2)

The staging decision offered two choices: initialize a throwaway vault, or leave the dependency optional. Isolated staging takes the second.

Evidence for the choice:

- **No tier-2 test reads Vault KV.** The isolated target is ADE and ToolHive. Neither compose service receives `VAULT_ADDR` or `VAULT_TOKEN`, and the vault vhost is not used by any assertion beyond the boundary test below.
- **The live KV content is not a fixed seed.** The paths Cove reads are `secret/data/op-cache/...`, a cache filled from 1Password references. Seeding them would mean replaying the credential provisioning path, including 1Password, inside a script that deliberately avoids both.
- **The throwaway keys would need a second lifecycle.** Option 1 needs init, unseal, mount creation, KV writes, and key storage scoped to the staging root, plus teardown coverage for all of it. That is a provisioning path, not a small seed.

The boundary is executable in the tier: `cli/tests/test_e2e_vault_staging.py` asserts that `vault.cove` reaches OpenBao and that OpenBao reports `initialized: false` and `sealed: true`. If someone later provisions the staging vault, that test fails and points at this document.

## Rule for a vault-dependent test

A test that genuinely needs a KV entry must skip with a named reason. It must not let a sealed or uninitialized vault surface as a 500, a 502, or an "unknown" failure.

```python
import pytest


def require_staging_vault() -> None:
    body = vault_health()  # GET /v1/sys/health through vault.cove
    if not body.get("initialized") or body.get("sealed"):
        pytest.skip(
            "staging vault is not provisioned: OpenBao is uninitialized and "
            "sealed by design (option 2). To enable this check, initialize and "
            "seed the staging vault, then update docs/guides/staging.md."
        )
```

The reason must name what was missing and how to enable it. A skip that only says "vault unavailable" does not meet the bar.

## Run it

```shell
scripts/staging/teardown.sh <branch>          # start from a clean root
scripts/staging/deploy-isolated.sh <branch>   # prints https://127.0.0.1:9443
scripts/staging/e2e.sh                        # tier 2 against 9443
scripts/staging/teardown.sh <branch>          # remove project, volumes, data
```

A healthy run prints the provisioning boundary line, then passes:

- `test_e2e_ade_staging.py`: 3 tests.
- `test_e2e_toolhive_staging.py`: 3 tests.
- `test_e2e_vault_staging.py`: 2 tests.

## Failure modes and what they mean

| Symptom | Meaning |
|-|-|
| `cove-staging-toolhive` restarting, logs say `no container runtime available` | The container lacks the socket gid. Check `TOOLHIVE_DOCKER_GID` in the generated `staging.env` against the socket's group inside the VM. |
| `mcp.cove/health` returns 502 | ToolHive is down or restarting. The deploy prints a warning when its bounded health wait expires; the E2E then fails loudly. |
| `cove-staging-vault` reports `unhealthy` | Expected. The vault is sealed because staging does not initialize it. |
| `vault.cove` returns 501 with `initialized: false` | Expected. This is the option 2 boundary. |
| The deploy reports `staging and live data roots overlap` | The configured staging and live roots are equal, nested, or aliased. Fix `COVE_STAGING_DATA_ROOT`; nothing was removed. |
