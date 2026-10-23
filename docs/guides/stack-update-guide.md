# Stack Update Runbook

This is the master runbook for keeping every container image, build base, and pinned dependency in the Cove stack current. It carries the update SLA, the pin inventory, the upgrade procedure, the SBOM process, and the automated audit design. When a version-bump PR needs a procedure, it starts here.

## Update SLA

Every upstream update is classified by semver change of the pin. The classification drives the deadline:

| Class | Meaning | SLA | Response |
| --- | --- | --- | --- |
| **Patch** | Third path segment changes (`v0.86.0` → `v0.86.1`, `1.20.1` → `1.20.2`) | Merged within **1 day** of release | Standard bump PR, evidence per below |
| **Minor** | Second segment changes within the same major (`1.84.0` → `1.85.0`) | Merged within **3 days** | Standard bump PR, changelog summary required |
| **Major** | First segment changes (`forgejo:15` → `forgejo:16`) | **No auto-bump.** The audit workflow files an issue tagged `major-bump` instead of a PR | Operator review: gap analysis before any PR |

Major-bump responses are loud on purpose: the audit script emits a warning block into the weekly report, and the issue template requires a gap analysis (breaking-change notes from upstream release notes, data-migration steps, config-shape changes, and a test impact list) before a bump PR is opened.

Two cross-cutting rules apply to all classes: a new third-party release waits **48-72 hours** after release before the bump PR is opened (supply-chain hold, borrowed from the [LiteLLM upgrade procedure](../services/litellm-proxy.md)), and security advisories against a pinned current version override the wait and the SLA class (fix ships as a patch-class bump immediately).

Evidence required in every bump PR body, so the reviewer automation can judge it mechanically: upstream release or changelog link, old pin → new pin with old and new digest, SLA classification (patch/minor/major), and the SBOM delta (`sbom/` diff for the touched image). The PR body template lives at `scripts/version-audit/templates/bump-pr-body.md`.

## Pin inventory

Single source of truth for image pins is `compose/` (bundled into the `cove` wheel). The machine-readable inventory is generated from it, never duplicated: `uv run --directory cli python -m cove.pins --json`.

| Component | Pinned ref | Pin location | Pin kind |
| --- | --- | --- | --- |
| Forgejo | `codeberg.org/forgejo/forgejo:15` | `compose/group_vars/all.yml` (`forgejo_image_tag`) | Major-line tag; **digest empty today, drift risk** |
| nginx | `nginx:1.27-alpine` | `compose/group_vars/all.yml` (`nginx_image`) | Minor-line tag |
| dnsproxy (DoH) | `adguard/dnsproxy:v0.86.0@sha256:4d65bafbf246b206a1af35d4263a86c35451d957458c7836304199f1cd2c1535` | `compose/docker-compose.yml` | Tag + digest |
| Vault | `hashicorp/vault:1.20@sha256:268bb80aa9c6d13d65fcfa05c0c268caca068952240a8087291a6ce0b66e3a10` | `compose/group_vars/all.yml` (`vault_image_tag` + `vault_image_digest`) | Tag + digest |
| Postgres (litellm-db) | `postgres:16-alpine` | `compose/docker-compose.yml` | Major-line tag; **no digest, drift risk** |
| Forgejo runner | `data.forgejo.org/forgejo/runner:11` | `compose/docker-compose.yml` (`FORGEJO_RUNNER_IMAGE`) | Major-line tag |
| Speedtest Tracker | `lscr.io/linuxserver/speedtest-tracker:v1.15.1-ls177` | `compose/docker-compose.yml` (`SPEEDTEST_IMAGE`) | Tag |
| ToolHive | `ghcr.io/stacklok/toolhive:v0.51.4@sha256:5e1e2536…` | `compose/docker-compose.yml` (`TOOLHIVE_IMAGE`) | Tag + digest |
| Headroom | `ghcr.io/chopratejas/headroom:latest@sha256:50b85d8e…` | `compose/docker-compose.yml` (`HEADROOM_IMAGE`) | Digest-pinned (`latest` tag is incidental) |
| zrok2 tunnel | `openziti/zrok2:2.0.4` | `compose/tunnel.yml` (`TUNNEL_IMAGE`) | Tag |
| LiteLLM (built) | `cove-litellm:1.84.0`, from `python:3.13-slim`, `litellm==1.84.0` hash-pinned | `compose/litellm/Dockerfile` | Own build; app pin is the SLA subject |
| ADE (built) | `cove-ade:0.44.0`, from `node:24-bookworm-slim`, `bb-app==0.44.0` | `compose/ade/Dockerfile` + `ADE_BB_APP_VERSION` | Own build; app pin is the SLA subject |
| dnsmasq (built) | from `alpine:3.21` | `compose/dnsmasq/Dockerfile` | Own build; base pin is the SLA subject |
| Config resolver podlets | `npx`-invoked, no image pin | `compose/toolhive/registry.json` | Per-server refs pinned by tag in registry |

**Known drift risks to close** (tracked for the next audit cycle): `forgejo_image_digest` is empty, `postgres:16-alpine` has no digest, and the two major-line runner pins (`forgejo:15`, `runner:11`) rely on Codeberg and data.forgejo.org not retagging.

## Upgrade procedure

Standard per-service flow (the LiteLLM doc was the first instance and remains the reference shape):

1. Within the SLA window (and after the 48-72h hold), open a bump branch. The Forgejo audit workflow opens these automatically and names them `bump/<component>-<old>-to-<new>`.
2. Locate the pin with the table above and change it in that one file only. Digest-pinned components get a fresh digest copied from the registry (multi-arch index digest, verified the way ToolHive's pin was: verify the index covers the machine's arch).
3. Regenerate the SBOM snapshot for the touched image with `scripts/sbom.sh <component>` and commit the diff.
4. Run the unit gate: `uv run --directory cli pytest -x -q -m "not e2e and not staging"`.
5. Open the PR with the evidence block (SLA section above). The reviewer automation evaluates it; tier-2 staging (`scripts/staging/e2e.sh`) runs before any merge that touches `compose/`.
6. Merge, then promote: sync compose resources, build the wheel, reinstall, and attach the regenerated SBOMs to both release hosts via `scripts/release.sh` (see [dual-host release rules](../../AGENTS.md)).

Rollback for a bad bump: restore the previous pin in the same pin-location file, `cove down` the affected service, `cove up`, verify its health check. Built images (`cove-litellm`, `cove-ade`, `cove-dnsmasq`) additionally need `docker compose build` before up.

## SBOM process

Cove takes its SBOM as part of development, not as a runtime product:

- `scripts/sbom.sh` generates CycloneDX via `trivy image --format cyclonedx` for every pin in the inventory (or one component when named), into `sbom/<component>.cdx.json`.
- Snapshots are **committed at bump time**, inside the bump PR. The PR diff then is the SBOM delta for that release.
- Release packaging: `scripts/release.sh` attaches the current `sbom/` set to the release on both hosts (Forgejo + GitHub), so each release carries its SBOM.
- A built image (LiteLLM, ADE, dnsmasq) additionally gets a BuildKit attestation at build time (`docker buildx build --sbom=true`) for the images we own.
- View without generating anything: `cove --sbom` prints the pin matrix as an about item (the SBOM is informational, never a state change). Machine-readable form: `python -m cove.pins --json`. Generation never runs from the runtime CLI; it is a development step.

## cove update

`cove update` upgrades the installed tool to the latest released version and relaunches:

1. Queries the release hosts (GitHub first, Forgejo fallback) for the latest released wheel.
2. Compares with the installed version. Up to date → no-op, exit 0.
3. Otherwise downloads the wheel to a temp dir and runs `uv tool install --force --from <wheel>`.
4. Reminds that `cove off` is not required: the next `cove up` re-extracts compose resources from the new wheel automatically (version-based upgrade detection), then re-renders nginx and reloads the stack.

`cove upgrade` is an alias, because both spellings are natural.

## Automated audit (R5 design)

Two cooperating parts, neither of which runs ad-hoc commands in a container:

- **Forgejo Actions `version-audit` workflow** (planned path `.forgejo/workflows/version-audit.yml`; not active yet — activation needs a runner token secret, see below): resolves every pin from `python -m cove.pins --json` against its upstream registry, classifies patch/minor/major, and for patch/minor opens a `bump/*` PR carrying the evidence block; for major files the gap-analysis issue instead. Until the workflow lands, the audit is manual against this runbook. The runner service itself is the existing `cove-runner` stack service.
- **BB reviewer automation** (scheduled thread, 2-4x daily): reads open `bump/*` PRs via the Forgejo API, checks the evidence block, SLA age, and unit-gate status, and approves compliant PRs. Merge and release require the tier-2 staging gate to have passed; non-compliant or stuck PRs produce an ntfy alert rather than a merge. Merge rights for the automation are restricted to `bump/*` PRs by branch filter so a runaway bump cannot escalate its own permissions.

## Related docs

- [LiteLLM upgrade procedure](../services/litellm-proxy.md) — reference service doc
- [Dual-host release drift](../tech-debt/dual-host-release-drift.md) — why `scripts/release.sh` publishes to both hosts
- [Staging E2E](../../AGENTS.md) — tier-2 gate rules