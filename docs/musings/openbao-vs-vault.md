---
title: "OpenBao vs Vault for Cove: decision brief"
created: 2026-10-29
status: Draft
---

# OpenBao vs Vault for Cove: decision brief

**Recommendation: migrate to OpenBao, but as a fresh-init swap rather than an in-place upgrade, and only after a rehearsal on the isolated staging stack.** The strongest argument is not the license. It is that the do-nothing branch already requires leaving Vault 1.20, because that line stopped receiving OSS patches on 2025-09-24 while every other surface in Cove kept moving.

Nothing in this brief has been implemented. No compose file, container, volume, seal state, or credential was touched. All Cove facts below were read from the working tree at the time of writing; all external claims carry a source link in [Sources](#sources).

## 1. What Cove's Vault actually is today

### The headline

Vault in Cove is not a secrets platform. It is a single-node, Raft-backed KV v2 store with one mount (`secret/`) holding one dataset (`op-cache/`), plus a userpass login used only for the web UI. The only thing that talks to it over the network is the operator's own CLI on the host and Ansible playbooks run by `cove up`. No service container reads Vault at runtime, and no Forgejo workflow does either.

Two consequences follow, and they drive everything in section 2:

- **Blast radius is the CLI, not the running stack.** Killing Vault breaks credential resolution for `cove up`, `cove creds`, `cove tunnel`, `cove litellm`, `cove bifrost`, `cove speedtest` and the Forgejo admin provisioning playbook. Forgejo, nginx, pages, the runner, ToolHive and ADE keep serving.
- **The stored data is a rebuildable cache.** Every KV entry holds `{value, op_ref}`, where `op_ref` is the 1Password reference it came from. A migrated or empty Vault is re-seedable by replaying those refs, and a second copy of the values already lives in `~/.cache/cove/op-cache.json`.

### Surface inventory

| Surface | What it is | What breaks without it | Portability to OpenBao |
|---|---|---|---|
| `vault` compose service (`compose/docker-compose.yml`) | `hashicorp/vault:1.20`, tag and digest pinned in `compose/group_vars/all.yml` (`vault_image_tag`, `vault_image_digest`), 512M limit, `IPC_LOCK`, healthcheck `vault status` | every cache read and write on the host | image and healthcheck swap; the OpenBao image also ships `/usr/bin/vault` as a symlink to `bao`, so even the current healthcheck command resolves |
| `compose/vault/vault.hcl` | `storage "raft"` at `/vault/data`, `node_id = "cove-1"`, listener `0.0.0.0:8200` with `tls_disable`, `api_addr`/`cluster_addr`, `ui = true`, `disable_mlock = true` | storage layout, listener, UI | identical schema; `disable_mlock` was declared obsolete in OpenBao 2.0, so drop it and the `IPC_LOCK` capability rather than rely on it; default paths differ (`/openbao/config`, `/openbao/data`) and the image runs as a non-root user |
| `compose/bootstrap_vault.yml` | detects init state, `sys/init` 5 shares / 3 threshold, writes keys and root token to the OS keystore, ensures the KV v2 mount at `secret/`, unseals | first boot never initializes, no keys anywhere, `cove creds` has no token | same endpoints (`/v1/sys/init`, `/v1/sys/unseal`, `/v1/sys/mounts/secret`); keystore namespace should change to avoid mixing token formats |
| `compose/provision_vault_user.yml` | enables `userpass`, writes an `admins` ACL with `path "*"`, creates the UI user; workstation-lane-owned since 0.15.6, deliberately not run by `cove up` | UI login only; the root token from the keystore still works for API use | same endpoints; re-running is a one-command step for the workstation lane |
| `cove vault up` / `status` / `unseal` (`cli/cove/vault.py`) | converge the container, wait on health, unseal only when sealed, fail loud | the operator's single recovery command after a reboot or recreate | logic unchanged; labels and messages only |
| `cli/cove/vault_unseal.py` | `GET /v1/sys/health`, `POST /v1/sys/unseal` with `{"reset": true}` then three keys read from the OS keystore | every unseal path: autostart, `cove up` heal, manual | same API semantics (`reset` and `key` are both documented in OpenBao) |
| `cli/cove/vault_cache.py` | KV v2 writes to `secret/data/op-cache/<vault>/<item>/<field>`, payload `{value, op_ref}`, root token from keystore or `VAULT_TOKEN`, auto-unseal retry on HTTP 503 | the credential cache behind Forgejo, tunnel, LiteLLM, llmproxy, Bifrost and Speedtest provisioning | identical API surface: same KV v2 path shape, same `X-Vault-Token` header, same 503 meaning |
| `cove creds vault-get` / `vault-put` / `batch-pull` | local cache first, then Vault; `vault-put` always re-reads 1Password (issue #93) | credential resolution and rotation sync | unchanged. Note `batch-pull` fills only the local cache, never Vault |
| nginx vhost + per-machine wildcard (`compose/nginx/default.conf.j2`) | `vault.cove` / `vault.cove.local` and `vault.cove.<slug>` proxied to `vault:8200`, cert SANs from `bringup.yml`, `/etc/hosts` entry | UI and API ingress | unchanged if the compose service name and hostnames stay `vault` / `vault.cove` |
| `cove status` (`cli/cove/status.py`) | three-state probe of `/v1/sys/health` (200 unsealed, 501 uninitialized, 503 sealed) | the converge status gate and `cove serve` reporting | identical status codes |
| OS keystore entries `cove/vault/unseal-1..5`, `cove/vault/root-token` | Shamir shares and root token in Keychain / secret-tool | unseal and CLI authentication | a fresh init writes new values; a distinct namespace avoids ambiguity during rollback |
| Tests | 41 Vault-specific test functions across `test_vault.py`, `test_vault_unseal.py` and `test_vault_cache.py`, out of 25 test modules that mention Vault; `test_staging_isolation.py` names `cove-vault` | CI coverage and the staging isolation guard | mostly portable; the `live`-marked ones are the ones that would catch a real regression |

### Two inventory findings worth stating plainly

- **`docs/architecture.md` oversells the dependency.** It describes pipelines reading secrets from Vault, but there is no `.forgejo/workflows` and no in-repo workflow that authenticates to Vault. The documented aspiration is not a current consumer, so it is not a migration blocker.
- **There is no `docs/services/vault.md`.** Vault is the only core service without a service doc, which means the migration would have to write the reference documentation that has been missing all along rather than rewrite one.

## 2. OpenBao against that surface

### 2.1 License, governance, cadence

- **License.** MPL-2.0, inherited from the pre-BSL Vault tree ([LICENSE](https://raw.githubusercontent.com/openbao/openbao/main/LICENSE), confirmed as `MPL-2.0` by the GitHub API). This is the same fork rationale the LiteLLM exit rested on: Vault's LICENSE now reads "Business Source License", with **International Business Machines Corporation** named as licensor and the licensed work defined as "Vault Version 1.15.0 or later" ([Vault LICENSE](https://github.com/hashicorp/vault/blob/main/LICENSE)).
- **Governance.** OpenBao is a project of LF Projects, LLC (Series of LF Projects) and an **OpenSSF Sandbox project** since 2025-06-17 ([announcement](https://openbao.org/blog/openbao-joins-the-openssf/), [OpenSSF project page](https://openssf.org/projects/openbao/)). Decisions run through a TSC plus a Dev WG charter ([community docs](https://openbao.org/community/)).
- **Cadence.** Minor releases roughly every 2 to 3 months, patches roughly monthly: 2.5.0 (2026-02-04), 2.6.0 (2026-07-14), 2.7.0 (2026-09-23), and paired security releases on the same day (2.7.1 + 2.6.4 on 2026-10-01, 2.7.2 + 2.6.5 on 2026-10-26) ([releases](https://github.com/openbao/openbao/releases)).
- **Version gap.** Latest OpenBao is **2.7.2 (2026-10-26)**. Cove pins Vault **1.20**, whose last OSS release was **1.20.4 on 2025-09-24**; the OSS line then moved to 1.21.4 (2026-03-05) and 2.0.0 (2026-04-14), now 2.2.1 (2026-10-22) ([Hashicorp release API](https://api.releases.hashicorp.com/v1/releases/vault?limit=20&license_class=oss), [Vault v2.2.1](https://github.com/hashicorp/vault/releases/tag/v2.2.1)). The pin is about 13 months past its final patch.
- **Support policy.** OpenBao supports the newest minor only; the project cut a courtesy 2.6.5 but states that "v2.6.x series is officially unsupported upstream" in the October advisories, and its support policy says users not on the latest release will be asked to reproduce on it ([Support & EoL policy](https://openbao.org/community/policies/support/)). That is a materially different operating posture from "pin once and forget", and it is a real recurring cost, not a formality.

### 2.2 Compatibility, call by call

The project's own migration policy is explicit: aim for **API compatibility only**, not seal or storage compatibility ([Migration policy](https://openbao.org/community/policies/migration/)). The in-place guide adds the operational caveat that it was tested against **Vault 1.14.1 OSS only** and that "OpenBao makes no guarantees about storage compatibility with Vault" ([In-Place Migration Guide](https://openbao.org/docs/guides/migration/)).

Cove does not need seal or storage compatibility, so what matters is the API layer. Checked against the current docs, every call Cove makes is present and unchanged:

| Cove call | OpenBao status | Source |
|---|---|---|
| `GET /v1/sys/health` with `initialized` / `sealed` / `version` | identical, same default codes (200 / 429 / 501 / 503) | [health API](https://openbao.org/docs/api/system/health/) |
| `POST /v1/sys/unseal` with `{"reset": true}` then `{"key": ...}` | identical, `reset` documented and takes precedence over `key` | [unseal API](https://openbao.org/docs/api/system/unseal/) |
| Shamir 5/3 init and unseal | supported; the in-place guide is written for Shamir, no auto-unseal | [migration guide](https://openbao.org/docs/guides/migration/) |
| KV v2 at `secret/data/...`, mount via `POST /v1/sys/mounts/secret` with `options.version: "2"` | identical engine and path shape | [KV v2 API](https://openbao.org/docs/api/secret/kv/kv-v2/) |
| `userpass` auth and the UI login | built in and documented (not one of the engines moved out to `openbao-plugins`) | [auth methods](https://openbao.org/docs/auth/) |
| Web UI at `ui = true` | present since 2.2.0 ("Reintroduction of the WebUI"); absent in 2.0 GA and 2.1.1 | [2.2.x notes](https://openbao.org/community/release-notes/2-2-0/) |
| `storage "raft"` block, `node_id`, listener, `api_addr`, `cluster_addr` | identical schema | [raft storage](https://openbao.org/docs/configuration/storage/raft/) |
| `X-Vault-Token` request header | still the header name in current docs | [auth concepts](https://openbao.org/docs/auth/) |

Divergences that touch Cove, none of them blocking:

- **Token shape.** OpenBao issues `sbr.`-prefixed tokens instead of Vault's `hvs.` form; old tokens keep working until their TTL ([migration guide](https://openbao.org/docs/guides/migration/)). Cove treats the token as an opaque string, so only the keystore contents change, and only on a fresh init.
- **`disable_mlock`** was made obsolete in 2.0.0 when mlock was removed ([2.0.0 notes](https://openbao.org/community/release-notes/2-0-0/)). It should be deleted along with the `IPC_LOCK` capability, not carried forward as if it still did something.
- **Container shape.** The image runs as a non-root `openbao` user, keeps config under `/openbao/config`, and ships a `/usr/bin/vault` symlink to `bao` ([Dockerfile](https://github.com/openbao/openbao/blob/main/Dockerfile)). Cove's bind mounts at `/vault/config` and `/vault/data`, owned by the operator, would have to move and be owned by the container user, or the container would have to run as root, which defeats the point.
- **Plugins.** OpenBao ships fewer built-ins than Vault; a mount whose plugin is missing starts as a stub and reads "no value found" ([migration guide](https://openbao.org/docs/guides/migration/)). Cove mounts only `kv`, so this is a non-issue here, and it is the reason the "just point it at the old data" path is riskier than it looks in general.

### 2.3 Migration shape and rollback

Because storage compatibility is not offered from 1.20 and not guaranteed at all, the honest migration is **fresh init + replay**, not an in-place binary swap:

1. Add the OpenBao image pin next to the Vault pin, with a distinct data directory. Leave `$COVE_DATA_ROOT/vault/` untouched.
2. `bao operator init` 5/3, writing unseal shares and the root token under a new keystore namespace (for example `cove/openbao/*`) so the two token generations never mix.
3. Create the KV v2 mount at `secret/` and re-seed. The re-seed is scriptable from the data itself: before cutover, walk `secret/metadata/op-cache/` recursively, read each entry's `op_ref`, and replay it through `cove creds vault-put`, which re-reads 1Password by contract. Expect one biometric batch.
4. Re-run userpass provisioning from the workstation lane (same 1Password item, new password written through the existing seed flow).
5. Flip the compose service image, the healthcheck, the config path and the data volume, then converge.
6. **Rollback** is "revert the pin and converge": the old Vault volume was never written to, its unseal keys are still in the keystore, and the CLI's local cache is untouched. This is a materially safer rollback than an in-place upgrade, where the only rollback is restoring a snapshot.

What the migration cannot avoid: the operator has to be present for one 1Password unlock, one init, and one unseal-key storage step. There is no unattended version of this, and any plan that claims otherwise is wrong.

### 2.4 Security record and supply chain

The advisory history is the least flattering part of the file, and it needs to be read correctly rather than scored.

- **Volume.** 51 published GitHub security advisories between 2025-06-25 and 2026-10-26: 6 critical, 10 high, 18 medium, 17 low (GitHub advisories API for `openbao/openbao`). Six criticals in sixteen months is not a quiet record.
- **The criticals.** RCE via `sys/storage/raft/snapshot-force` plugin catalog restore (CVE-2026-104090, GHSA-j6wc-jpvg-xfxq), token creation through internal operation dispatching (CVE-2026-104088, GHSA-rh46-vc3j-w2w3), recovery-mode token leak via timing (CVE-2026-63132, GHSA-34fc-gh42-pj53), two OIDC callback/XSS issues (CVE-2026-33757, CVE-2026-33758), and operator-to-host code execution (CVE-2025-54997, GHSA-xp75-r577-cvhp).
- **How much of it is Vault's.** 13 of the 51 say outright that "this vulnerability is original to HashiCorp Vault", including the raft-snapshot RCE and the ACL bypass class. HashiCorp's own bulletin feed shows the same issues on the same dates: HCSEC-2026-41 is that raft RCE, HCSEC-2026-43 is the ACL policy bypass, both published 2026-10-07 ([HashiCorp security bulletins for Vault](https://discuss.hashicorp.com/tag/security-vault)). A like-for-like count is not available, because HashiCorp publishes bundled bulletins while OpenBao publishes one GHSA per issue; comparing 51 advisories to 30 bulletins would be a category error. What the record does support: **switching vendors does not buy a better vulnerability rate, it changes who ships the fix, and to which versions.** Vault 1.20 is not one of those versions.
- **Fix latency.** Fixes ship in dated patch releases, not backlogs: the September batch landed in 2.7.0 + 2.6.3 on release day, the October batches in 2.7.1 + 2.6.4 and 2.7.2 + 2.6.5. The stated CVE process targets 7 days to confirm and a 90-day maximum to patch, with pre-announcement for high and critical issues ([CVE process](https://openbao.org/community/policies/cve/)).
- **Supply chain, which is where OpenBao is clearly ahead.** Every release publishes per-artifact SBOMs, GPG signatures and Sigstore bundles; the binary artifacts' keyless signatures are bound to the release workflow and branch identity, so `cosign verify-blob` fails if the build came from anywhere other than `main` or `release/*` ([install docs](https://openbao.org/docs/install/)). The image build pins its Alpine base by digest, and the Dockerfile normalizes the binary layer so one release binary has one digest across registries ([Dockerfile](https://github.com/openbao/openbao/blob/main/Dockerfile)). The project also tracks the OpenSSF OSPS baseline ([policy](https://openbao.org/community/policies/osps-baseline/)). For comparison, Cove's current Vault pin is a tag plus digest with no verification step of its own.
- **Maintainer concentration.** Two organization-level admins, four organization-level maintainers, and a set of repository committers ([MAINTAINERS.md](https://github.com/openbao/openbao/blob/main/MAINTAINERS.md)). Thin against a corporate team, and the reason the "bus factor" line belongs in the risk column rather than the comfort column.

### 2.5 What it costs

- **Code.** 20 non-test Python modules, 25 test modules, 21 compose files, 81 markdown files (excluding `docs/troves`) and 4 scripts mention Vault by name (`git grep -l -i vault`). Most mentions are prose or an incidental constant, and most of the markdown is history (musings, plans, chronicles) that should stay as written. The semantic work is narrow: the three `vault*.py` modules keep their logic and change paths, labels and keystore names; `status.py`, `constants.py` and the staging isolation list change one identifier each.
- **Compose and bringup.** One image pin, one healthcheck, one config mount path, one data path, one `IPC_LOCK` removal, one container name. The `.env` keys (`VAULT_IMAGE`, `VAULT_CONTAINER_NAME`) are regenerated by `bringup.yml`, so the deployed `.env` follows the pins with no manual edit.
- **Ingress.** Zero change if the service stays named `vault` and the host stays `vault.cove`. Renaming both would also mean new cert SANs, a new `/etc/hosts` line, a new nginx block and a new set of doc references, for no functional gain. Recommendation: keep the route, rename only what the operator sees in `docker ps`.
- **Docs.** `docs/architecture.md` (Vault context, storage row, implementation row), six service docs that reference the Vault cache, `AGENTS.md`, and the missing `docs/services/vault.md`. That last one should be written as `docs/services/openbao.md` and cover the same ground.
- **Tests.** 41 Vault-specific tests, of which the `live`-marked ones are the real gate, plus the staging container-name assertion. The staging harness already runs an isolated project on port 9443, which makes a full rehearsal possible without touching the live stack.
- **What stays identical.** The `op-cache` path scheme, the `{value, op_ref}` payload, the keystore read pattern, the 503-triggers-unseal retry, the CLI verb names, the local cache, the ingress host, the certs, and every consumer call site's signature.

### 2.6 The honest counter-case

The case for staying is not weak, and three parts of it survive scrutiny:

- **BSL binds redistribution, not local use.** Vault's additional use grant permits production use that does not consist of offering the licensed work as a hosted service ([Vault LICENSE](https://github.com/hashicorp/vault/blob/main/LICENSE)). Cove runs Vault on the operator's own machine for one operator. On the license question alone, staying is legally safe, and the LiteLLM analogy does not transfer cleanly: LiteLLM shipped a compromised release, Vault has not.
- **Maturity and single-operator simplicity.** Vault 1.20 is a known quantity with years of field use, a UI the operator already knows, and a config Cove has not had to think about. OpenBao's churn is real: minors every 2 to 3 months, previous minors unsupported, and 51 advisories to read.
- **Migration risk under the credential path.** The `op-cache` sits beneath every credential resolution in Cove. A botched cutover is not a broken dashboard, it is a platform that cannot provision Forgejo or start a proxy.

The part of the counter-case that does **not** survive is "the 1.20 pin is current enough". It is not: 1.20.4 was the last OSS patch on 2025-09-24, the line is two majors behind, and the October 2026 fixes (including the raft-snapshot RCE and the ACL bypass) shipped to 2.x and 1.21 only. Staying on the current pin is not a conservative choice, it is an unpatchable one. Staying while upgrading to Vault 2.2.1 is defensible, and it is the real alternative to weigh, not "do nothing".

## 3. Recommendation

**Migrate to OpenBao 2.7.x as a fresh-init swap, with the Vault volume retained untouched as the rollback.**

Claim, evidence, and what would change the answer:

- **Claim: the status quo is the riskiest option.** Evidence: the 1.20 OSS line ended at 1.20.4 (2025-09-24) while HashiCorp's 2026 bulletins shipped fixes to current versions only. Moving to Vault 2.2.1 and moving to OpenBao 2.7.2 are both major-version moves; one of them also exits the BSL vendor. What would change this: evidence that HashiCorp still patches 1.20 OSS, or a decision that this Vault instance's content is not worth patching at all (hard to defend for the store that gates every other credential).
- **Claim: the API surface is a drop-in.** Evidence: every call Cove makes is documented and unchanged in 2.7.x (health, unseal with reset, KV v2, mounts, userpass, UI), and the image symlinks `vault` to `bao`. What would change this: a rehearsal failure on any of those six calls, especially a `sys/unseal` reset or a UI login that behaves differently behind nginx.
- **Claim: the migration is cheap because the payload is a cache.** Evidence: each entry carries its own `op_ref`, so the replay is mechanical; rollback is a revert plus a converge against an untouched volume. What would change this: discovering KV entries with no `op_ref` (hand-written secrets), which would have to be exported explicitly before cutover. That check is step zero of any implementation.
- **Claim: the security trade is a wash on vulnerabilities and a gain on supply chain.** Evidence: 51 advisories with 13 explicitly inherited from Vault, versus signed, SBOM'd, branch-bound releases and a digest-pinned image build. What would change this: an OpenBao-specific compromise (a bad release, a signing-key incident) of the kind that triggered the LiteLLM exit, or a maintainer collapse that leaves the October advisories unpatched.
- **Claim: the recurring cost is upgrade cadence.** OpenBao supports the newest minor only. Cove would move from "pin once" to "converge the pin every quarter or so". That is the honest price of the recommendation, and it is a governance change, not a technical one: it needs a standing line in the vendor-update discipline that already exists for other services.

**Not recommended:** an in-place binary swap of the running 1.20 data. The upstream guide tested 1.14.1, makes no storage-compatibility guarantee, and the one dataset it would carry is reproducible anyway. The risk buys nothing.

**Also not recommended as the primary reason:** the BSL. It is true, it is the same direction as the LiteLLM exit, and it is not sufficient on its own, because local single-operator use is inside the grant.

### Open questions for the operator

1. Does a quarterly-ish minor bump for the secrets server fit the operating model, or is "patch never" the intended posture? The answer decides whether OpenBao's support policy is a fix or a new burden.
2. Is the userpass UI login still wanted? If the UI is only for occasional inspection, the migration could drop `userpass` and the workstation-lane provisioning step entirely and use the keystore root token for API work. That is a smaller surface, but it removes the browser login the operator may actually use.
3. Should the rehearsal happen on the isolated staging stack (`scripts/staging/deploy-isolated.sh`, port 9443) before any live change? This brief assumes yes, and the staging harness exists precisely so the answer can be yes without risk.

## Sources

- OpenBao project: <https://openbao.org/>, <https://github.com/openbao/openbao>, <https://openbao.org/blog/openbao-joins-the-openssf/>, <https://openssf.org/projects/openbao/>
- OpenBao license: <https://raw.githubusercontent.com/openbao/openbao/main/LICENSE>
- In-place migration guide: <https://openbao.org/docs/guides/migration/>
- Migration policy (API-only compatibility): <https://openbao.org/community/policies/migration/>
- Support and EoL policy: <https://openbao.org/community/policies/support/>
- CVE process: <https://openbao.org/community/policies/cve/>
- Release checklist: <https://openbao.org/community/policies/release/>
- OSPS baseline policy: <https://openbao.org/community/policies/osps-baseline/>
- 2.0.0 notes (mlock removal): <https://openbao.org/community/release-notes/2-0-0/>
- 2.2.0 notes (WebUI reintroduction): <https://openbao.org/community/release-notes/2-2-0/>
- 2.7.0 notes: <https://openbao.org/community/release-notes/2-7-0/>
- Known issues (mlock/securebits): <https://openbao.org/community/known-issues/>
- Install, registries, cosign verification: <https://openbao.org/docs/install/>
- Health API: <https://openbao.org/docs/api/system/health/>
- Unseal API: <https://openbao.org/docs/api/system/unseal/>
- KV v2 API: <https://openbao.org/docs/api/secret/kv/kv-v2/>
- Auth methods: <https://openbao.org/docs/auth/>
- Raft storage config: <https://openbao.org/docs/configuration/storage/raft/>
- Upgrade guide: <https://openbao.org/docs/guides/upgrade/>
- Releases and assets: <https://github.com/openbao/openbao/releases>, <https://github.com/openbao/openbao/releases/tag/v2.7.2>
- Dockerfile and entrypoint: <https://github.com/openbao/openbao/blob/main/Dockerfile>, <https://github.com/openbao/openbao/blob/main/.release/docker/docker-entrypoint.sh>
- Maintainers: <https://github.com/openbao/openbao/blob/main/MAINTAINERS.md>
- OpenBao advisories referenced: <https://github.com/openbao/openbao/security/advisories/GHSA-j6wc-jpvg-xfxq>, <https://github.com/openbao/openbao/security/advisories/GHSA-rh46-vc3j-w2w3>, <https://github.com/openbao/openbao/security/advisories/GHSA-34fc-gh42-pj53>, <https://github.com/openbao/openbao/security/advisories/GHSA-7q7g-x6vg-xpc3>, <https://github.com/openbao/openbao/security/advisories/GHSA-cpj3-3r2f-xj59>, <https://github.com/openbao/openbao/security/advisories/GHSA-xp75-r577-cvhp>, <https://github.com/openbao/openbao/security/advisories/GHSA-fg5x-7whg-6c28>
- Vault license (BSL 1.1, licensor IBM): <https://github.com/hashicorp/vault/blob/main/LICENSE>
- Vault release history and dates: <https://api.releases.hashicorp.com/v1/releases/vault?limit=20&license_class=oss>, <https://github.com/hashicorp/vault/releases/tag/v2.2.1>
- HashiCorp Vault security bulletins: <https://discuss.hashicorp.com/tag/security-vault>
