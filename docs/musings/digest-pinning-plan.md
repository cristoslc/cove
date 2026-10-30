---
title: "Digest pinning every Cove service after Renovate lands"
date: 2026-10-30
status: Proposal (plan, docs only)
thread: thr_d58th7263x
related:
  - docs/guides/stack-update-guide.md
  - docs/musings/2026-09-26-vendor-update-policy.md
  - docs/musings/2026-09-26-cove-update-command.md
  - compose/group_vars/all.yml
  - compose/docker-compose.yml
  - compose/tunnel.yml
  - cli/cove/pins.py
  - cli/cove/update.py
---

# Digest pinning every Cove service

Planning document only. No pin changed, no compose edited, no container touched. The work it describes runs after the Renovate task lands; this document assumes Renovate is the discovery and PR layer and the tagged-release flow is the apply layer.

## Decision in one paragraph

Pin every externally sourced image as `tag@sha256:<index digest>`, and digest-pin every `FROM` line in the Dockerfiles cove builds. Keep the tag in the reference for readability. Renovate proposes digest changes, the age gate and the release flow apply them, and `cove update` converges the stack. The `--pull always` converge stops being an update mechanism and becomes a no-op for pinned images. One defect must be fixed before any pin lands on an existing host: image pins in the wheel do not reach the deployed stack, because `compose/bringup.yml` writes the image variables into `.env` on first boot only and never re-syncs them (see "The delivery defect that outranks the pin format").

## Why now, and the tension stated honestly

Floating tags have been load-bearing in Cove, not accidental. The trigger for this plan, recorded in the task brief rather than in this repo's history, is `forgejo:15` floating and a `docker compose pull` picking up `15.0.11`, whose rebuilt image carried the Brotli backport that closed CVE-2026-111497. That is exactly what a digest pin removes: a pull fetches one digest, so a same-tag rebuild stops arriving, including a security base rebuild.

That is the trade being bought deliberately. A digest pin converts "the vendor can change what runs here at any time" into "nothing changes without a reviewed PR". The cost is latency on the one class of change where speed matters most. The plan therefore does not merely delete the old mechanism. It replaces it with three parts that must all exist before the first pin lands:

1. Renovate notices that a tag now resolves to a new digest and opens a PR.
2. The age gate decides how long that PR waits, with a short path for security.
3. The release flow ships the merged pin, and the converge applies it.

If any part is missing, pinning is a regression. The delivery defect below is the part that is missing today.

## What the repo actually has

Method: ran `uv run --directory cli python -m cove.pins "$PWD/compose"`, then read every compose file, `compose/group_vars/all.yml`, every Dockerfile, and the satellite image references. The inventory tool is the same one `cove --sbom` and `scripts/sbom.sh` consume (`cli/cove/pins.py`).

### Headline

There are 14 service image references in the compose set. Ten are pulled from a registry and four are built locally.

Of the ten registry images, four carry a digest today (`vault`, `dnsproxy`, `toolhive`, `bifrost`) and six float (`forgejo`, `forgejo-runner`, `nginx`, `litellm-db`, `speedtest-tracker`, `tunnel`). The tunnel declaration floats, but its runtime image is per-arch digest-pinned by the CLI, so only the declaration needs work. Of the five Dockerfile `FROM` lines, one is digest-pinned (`bifrost`'s Alpine base) and four float over three distinct base repositories (`node:24-bookworm-slim`, `python:3.13-slim` in two stages, `alpine:3.21`).

### Registry images

"Who can change it" counts the parties that can change what the reference resolves to. A digest reduces that to registry storage integrity; a tag leaves the publisher and the registry in the path.

| Service | Declared reference | Declared in | Pin kind | Floats today | Today's update path | Who can change it | Silent rebuild risk | Digest precedent in repo |
|---|---|---|---|---|---|---|---|---|
| forgejo | `codeberg.org/forgejo/forgejo:15` | `compose/group_vars/all.yml:5-7`, default at `compose/docker-compose.yml:5`, rendered into `.env` at `compose/bringup.yml:812` | major-line tag, `forgejo_image_digest` empty | yes | `pull always` on the scheduled update; no pin bump | 2 (Forgejo project, Codeberg registry) | **high**: stateful (SQLite + git repos), and the worked example is exactly this tag | none on Codeberg; Docker Hub precedents do not transfer |
| forgejo-runner | `data.forgejo.org/forgejo/runner:11` | `compose/docker-compose.yml:208`, default at `compose/bringup.yml:849` | major-line tag | yes | `pull always` | 2 (Forgejo project, data.forgejo.org) | medium: CI only, no persistent data | none on that host |
| nginx | `nginx:1.27-alpine` | `compose/group_vars/all.yml:53`, default at `compose/docker-compose.yml:49`, rendered at `compose/bringup.yml:824` | minor-line tag | yes (1.27.x) | `pull always` | 3 (nginx maintainers, Docker Official Images build, Docker Hub) | medium: ingress for every vhost | Docker Hub pattern exists (`vault`, `dnsproxy`) |
| vault | `hashicorp/vault:1.20@sha256:268bb80a…` | `compose/group_vars/all.yml:18-20`, tag-only fallback at `compose/docker-compose.yml:121` | tag + digest | no | manual pin bump | 1 (registry storage) | low | **yes**, the original digest pin |
| litellm-db (postgres) | `postgres:16-alpine` | `compose/docker-compose.yml:148` | major-line tag | yes | `pull always` | 3 (Postgres, Docker Official Images, Docker Hub) | **high**: stateful pgdata; a same-major rebuild can change behavior | Docker Hub pattern exists |
| dnsproxy | `adguard/dnsproxy:v0.86.0@sha256:4d65bafb…` | `compose/docker-compose.yml:103` | tag + digest | no | manual pin bump | 1 (registry storage) | low | **yes**; the CHANGELOG records this as the last `latest` image (`CHANGELOG.md:124`) |
| speedtest-tracker | `lscr.io/linuxserver/speedtest-tracker:v1.15.1-ls177` | `compose/docker-compose.yml:238`, default at `compose/bringup.yml:835` | specific tag, no digest | a re-push of that tag would float | tag bump, or `pull always` | 2 (LinuxServer, lscr.io) | low: optional profile, SQLite in `/config` | none on lscr.io |
| toolhive | `ghcr.io/stacklok/toolhive:v0.51.4@sha256:5e1e2536…` | `compose/docker-compose.yml:273`, default at `compose/bringup.yml:839` | tag + digest | no | manual pin bump | 1 (registry storage) | low | **yes**, GHCR precedent |
| tunnel (zrok2) | `openziti/zrok2:2.0.4` | `compose/tunnel.yml:12-17`, `compose/docker-compose.yml:362` | tag in the declaration; runtime pin is per-arch digest in `cli/cove/tunnel.py:15-24` | the declaration floats; the runtime does not | `cove tunnel up` selects a per-arch digest; the tag is bumped by hand | 2 (OpenZiti, Docker Hub) | low: optional, stateless sidecar | **yes at runtime**, per-arch map |
| bifrost | `maximhq/bifrost:v2.3.2@sha256:f5b18826…` | `compose/docker-compose.yml:446`, default at `compose/bringup.yml:843` | tag + digest | no | manual pin bump | 1 (registry storage) | low | **yes**; the comment records that upstream publishes no signatures or provenance |

### Locally built images and their bases

Built images are not pull-addressable, so the pull policy does not govern them. Their `FROM` lines are the supply-chain surface, and so are the package fetches inside the build.

| Image | Build context | Image tag | `FROM` base | Base pinned? | Other build-time fetches | Update path today |
|---|---|---|---|---|---|---|
| ade | `compose/ade/Dockerfile` | `cove-ade:0.44.0` (`compose/docker-compose.yml:334`) | `node:24-bookworm-slim` (`:1`) | no | `apt-get install` (`:10`), `npm install -g bb-app@0.44.0` plus transitive npm deps (`:13`), `ARG BB_APP_VERSION` (`:3`) | `cove ade update` writes the pin into `.env` (`docs/services/ade.md:128-133`) |
| litellm | `compose/litellm/Dockerfile` | `cove-litellm:1.84.0` (`compose/docker-compose.yml:172`, duplicated at `compose/litellm/docker-compose.yml`) | `python:3.13-slim` twice (`:1`, `:11`) | no | `apt-get install` (`:3`, `:13`), `pip install "litellm[proxy]==1.84.0" prisma` (`:6`, `prisma` unpinned) | rebuild by hand |
| dnsmasq | `compose/dnsmasq/Dockerfile` | no `image:` key, compose generates the name | `alpine:3.21` (`:1`) | no | `apk add --no-cache dnsmasq` (`:2`, unpinned package) | rebuild by hand |
| bifrost-dns | `compose/bifrost/Dockerfile` | `cove-bifrost-dns:0.1.0` (`compose/docker-compose.yml:403`) | `alpine:3.23.7@sha256:ff7f0c72…` (`:6`) | **yes** | `apk upgrade --no-cache` plus `apk add dnsmasq=2.91-r1` (`:11`; package pinned, upgrade not) | rebuild by hand |

### Satellite image references outside compose

These are not compose services but they are image references the compose set pulls or launches at runtime, so they belong in the inventory.

| Reference | Where | Pulled by | Pin kind | Renovate sees it? |
|---|---|---|---|---|
| `gitea/runner-images:ubuntu-latest` | `compose/provision_forgejo.yml:446` (runner label mapping) | the Forgejo runner, per job | floating tag by contract | no |
| `docker.io/mcp/filesystem:1.0.2` | `compose/toolhive/registry.json:17` | ToolHive, as a sibling container | tag | no |
| `ghcr.io/stackloklabs/gofetch/server:1.0.5` | `compose/toolhive/registry.json:54` | ToolHive, as a sibling container | tag | no |
| `ghcr.io/stacklok/dockyard/uvx/mcp-server-time:2026.8.18` | `compose/toolhive/registry.json:91` | ToolHive, as a sibling container | tag | no |

Headroom is not in this inventory. It was removed because the pinned LiteLLM has no Headroom integration (`CHANGELOG.md:25`; the decision brief records PR #117 at `docs/musings/bifrost-headroom-decision.md`).

## The pin strategy

### Format

Every registry image becomes `name:tag@sha256:<index digest>`. The tag stays so a human can read the reference and so a rollback can name the line it restores. The digest is the multi-arch manifest-list digest, not a per-architecture digest, so one line works on amd64 and arm64. This matches the existing `vault`, `dnsproxy`, `toolhive`, and `bifrost` pins, which a registry check on 2026-10-30 confirmed are index digests. The zrok2 tunnel keeps its per-arch map in `cli/cove/tunnel.py` because `cove tunnel up` deliberately chooses the child digest for the host architecture; the declaration in `compose/tunnel.yml` should still carry the index digest so Renovate has something to update.

The format works on every registry in the inventory. Checked on 2026-10-30 with an OCI manifest request: `codeberg.org/forgejo/forgejo:15` returns an OCI image index with six platform manifests, `data.forgejo.org/forgejo/runner:11` returns an index, `ghcr.io/stacklok/toolhive:v0.51.4` returns an index whose digest equals the declared pin, and `lscr.io/linuxserver/speedtest-tracker:v1.15.1-ls177` returns an index with four manifests. No registry in the set requires a per-arch pin.

Every `FROM` line becomes the same form. `compose/bifrost/Dockerfile:6` is the precedent. Pinning the base does not pin the build's package fetches, and the plan says so out loud rather than implying reproducibility it does not have.

### One pin per image

Right now several pins exist in more than one place:

- `forgejo`, `nginx`, and `vault` are declared in `compose/group_vars/all.yml` and repeated as defaults in `compose/docker-compose.yml` and in the `.env` template in `compose/bringup.yml:812-852`.
- `litellm` is declared in `compose/docker-compose.yml:172` and again in `compose/litellm/docker-compose.yml`.
- `speedtest-tracker`, `toolhive`, `bifrost`, and `forgejo-runner` have defaults in both the compose file and the `.env` template.

A digest bump that updates one copy and not the others produces a stack whose declared pin and rendered `.env` disagree. The plan collapses each image to one authoritative line and makes the others derive from it, or fails loud when they are missing. The existing `vault` split (`vault_image_tag` plus `vault_image_digest`) should become a single `vault_image` line for the same reason: two keys are two chances to update half a pin.

### The delivery defect that outranks the pin format

This is the finding that decides whether the rest of the plan works.

`compose/bringup.yml:806-856` renders the compose `.env` with `when: not (compose_dir ~ "/.env") is exists`, so it runs on first boot only. The image variables are written there (`:812-852`). The later re-sync tasks cover only `ADE_PORT`, `ADE_CONTAINER_NAME`, `NGINX_CONF_DIR`, and `DNSMASQ_CONF_DIR` (`:860-888`); no image variable is re-synced. `.env` is also in `RUNTIME_PRESERVED_FILES` (`cli/cove/stateless.py:28-33`), so re-extracting the wheel never rewrites it.

The consequence: on an existing machine, `docker compose` interpolates `${FORGEJO_IMAGE:-…}` from the `.env` written at first boot. A pin bump in `compose/group_vars/all.yml` or in the wheel's bundled compose changes the fallback, not the value compose reads. `docs/services/forgejo.md:57` already states this for group_vars changes, and `docs/services/ade.md:128-133` names `.env` as the supported runtime override that bringup deliberately does not rewrite.

`cove update` does not close the gap either. Its convergence check compares the deployed compose tree with the wheel's tree (`cli/cove/update.py:199-210`), which includes `group_vars/all.yml`, so a pin bump correctly reports "convergence pending". Bringup then runs, the containers are compared against the unchanged `.env` value, and nothing changes. The run reports success while the new pin never applied. That is the worst kind of failure: a pin that looks applied in the repo and is not applied on the host.

Today this defect is invisible because `--pull always` re-pulls the floating tag. After digest pinning it becomes the difference between "pinned" and "pinned in theory".

Two fixes are possible. The first is to re-sync every image variable into `.env` on each converge, following the ADE pattern already in `compose/bringup.yml:860-870`. The second is to stop writing image variables into `.env` at all and let the wheel's compose defaults be authoritative, with a one-time cleanup of the existing keys. The first is smaller, preserves deliberate per-host overrides (`cove ade update` and `cove tunnel up` write them), and matches the existing design. The plan recommends the first, with a test that fails when a rendered `.env` image value diverges from the pin.

### What happens to `pull always`

`compose/group_vars/all.yml:43` sets `pod_pull_policy: missing` for normal `cove up`, and `compose/bringup.yml:994` passes it to `docker compose up -d --pull`. The scheduled quiet update is the only path that forces `always`, through `COVE_PULL_POLICY` (`cli/cove/update.py:290-296`, consumed at `cli/cove/cli.py:474-478`).

With digest pins that forced pull becomes a verification, not an update. It fetches the exact digest already named, which is either present (no-op) or missing (fetch once). It cannot deliver new content because the content is named. Two consequences:

1. The comment at `cli/cove/cli.py:474-475` and the CHANGELOG line at `CHANGELOG.md:157` that explain the forced pull as the way floating tags receive patches become wrong and must change with the pins. Leaving them is how a future reader reintroduces floating tags to "fix" an update that does not arrive.
2. `--pull always` on a digest pin turns registry garbage collection into a converge failure. If the registry drops an old digest, a forced pull fails even though the local image is intact. The safer setting for pinned services is `missing` or no forced pull, because a changed digest in the compose spec already triggers a pull when the image is absent locally. This needs a staging check before it is switched, but the direction is clear: the forced pull exists to defeat digest pinning, and it should not survive it.

### What changes in `cove up` and `cove update`

| Surface | Today | After pinning |
|---|---|---|
| `cove up` (default) | `--pull missing`; a floating tag is not refreshed | unchanged; a changed digest is pulled because it is absent locally |
| `cove update --quiet` | forces `--pull always` so floating tags receive patches | the forced pull no longer delivers patches; the merged pin in the new wheel is what changes |
| Pin delivery | wheel pin + floating tag pull | wheel pin + `.env` re-sync + digest pull |
| Convergence gate | compares compose trees, excludes `.env` | must also guarantee the `.env` re-sync ran, or the gate can report pending forever while applying nothing |
| Rollback | restore the tag, converge | restore the previous `tag@digest` (or the tag), converge, rebuild for local images |

### Code and doc changes the pin task needs

These are prerequisites, not part of this docs-only deliverable.

1. `compose/bringup.yml`: re-sync image variables into `.env` on every converge, or remove them from the `.env` contract. This is the blocking one.
2. `compose/bringup.yml`: remove the duplicated image defaults at `:812-852` or derive them from the single pin.
3. `cli/cove/pins.py`: the inventory deduplicates by `(name, kind)` (`:160-166`), so `compose/dnsmasq/Dockerfile`'s `alpine:3.21` base disappears behind `compose/bifrost/Dockerfile`'s `alpine:3.23.7@sha256:…`. One of the two bases is invisible to the SBOM and the audit. Fix the key before relying on the inventory as the completeness check.
4. `compose/litellm/docker-compose.yml`: decide whether it is live or historical. Today it duplicates the LiteLLM pin and is still read by `cli/cove/pins.py:34-38`.
5. `cli/cove/cli.py:474-475` and `CHANGELOG.md:157`: rewrite the "floating tags are force-re-pulled" rationale.
6. `docs/guides/stack-update-guide.md:21-41`: the pin inventory table and its "known drift risks" paragraph become stale the moment the first pin lands. The update SLA at `:5-19` also needs a digest row, because a same-tag digest is neither a patch nor a minor by semver.
7. `docs/services/ade.md:121-133` and `docs/services/forgejo.md:57`: the "pinned, never floating" and first-boot `.env` statements stay true but need to say how a pin now reaches an existing host.

## Renovate mapping

Renovate is not configured in this checkout yet; the only occurrences of the word are in the vendor-policy musing and the LiteLLM hardening musing. The mapping below is against Renovate's documented managers and extractors, and every "sees it" claim should be confirmed with a dry run on the first PR the sibling task produces.

Two extractor facts drive much of the table. The Docker Compose manager parses `${VAR:-image:tag}` and replaces only the default value inside the braces (Renovate's `splitImageParts`), so cove's whole-image defaults are visible. The Dockerfile manager extracts `FROM` and also `apk`/`deb` installs, but marks those installs `unknown-registry` and skips them (`dockerfile/extract.ts`), and it has no `pip` or `npm` extractor for `RUN` lines.

| Reference group | Manager | Sees it? | `pinDigests` covers it? | Digest-only update expressible? | Residual |
|---|---|---|---|---|---|
| `compose/docker-compose.yml` images | `docker-compose` (default pattern matches the filename) | yes, including the `${VAR:-default}` form | yes | yes, `digest` config object | built services (`ade`, `litellm`, `bifrost-dns`, `dnsmasq`) are filtered out because they have `build:` |
| `compose/litellm/docker-compose.yml` | `docker-compose` | yes | yes | yes | duplicate of the main LiteLLM pin; two PRs for one bump unless grouped |
| `compose/tunnel.yml` | `docker-compose` | **no**, the filename does not match the default compose-file pattern (the name must contain `compose`) | n/a | n/a | add `managerFilePatterns` for `tunnel.yml`, or move the pin into a matched file |
| `compose/group_vars/all.yml` pins | none | **no** | n/a | n/a | custom regex manager. Collapse `vault_image_tag` + `vault_image_digest` into one line first, or the auto-replace must span two lines |
| `compose/bringup.yml` defaults | none | **no** | n/a | n/a | remove them (preferred) or accept drift |
| `compose/*/Dockerfile` `FROM` | `dockerfile` | yes | yes | yes | none; this is the clean part |
| `compose/litellm/Dockerfile` pip pin and `prisma` | none | **no** | n/a | n/a | custom regex manager for `litellm[proxy]==…`; `prisma` is unpinned and needs a version or a lock |
| `compose/ade/Dockerfile` `ARG BB_APP_VERSION` | none | **no** | n/a | n/a | custom manager with the `npm` datasource; add a lock or accept transitive drift |
| `compose/bifrost/Dockerfile` `apk add dnsmasq=2.91-r1` | `dockerfile` (apk extractor) | extracts, then skips as `unknown-registry` | n/a | **no** | human bump, or a custom manager pinned to the Alpine release |
| `cli/cove/tunnel.py` `ZROK2_DIGESTS` | none | **no** | n/a | n/a | custom regex manager cannot express per-arch children cleanly; keep a human step and a test linking the map to the declared index digest |
| `compose/toolhive/registry.json` OCI refs | none | **no** | n/a | n/a | custom JSON manager or human step; three refs, all tags |
| `compose/provision_forgejo.yml` job image | none | **no** | n/a | n/a | see "What must stay floating" |
| security labelling for any of the above | n/a | n/a | n/a | n/a | `vulnerabilityAlerts` reads GitHub Dependabot alerts only, and this repo's canonical remote is Forgejo. Renovate cannot label a container digest as security. See the next section. |

### Coverage gaps, restated

Renovate will see most of the compose surface on day one. It will not see: the tunnel compose file by filename, the group_vars pins, the duplicated bringup defaults, the pip and npm build pins, the tunnel per-arch map, the three ToolHive registry refs, or the runner job image. Of those, only the group_vars pins and the tunnel file matter for the six floating registry images. The rest are build-pin or satellite-pin residuals that need a human or a custom manager, and they should be listed in the runbook rather than assumed covered.

## The zero-day trade-off, quantified as policy

### Why a digest pin delays a security rebuild

A same-tag rebuild is invisible to a digest pin. The vendor re-pushes `15`, the new manifest has a new digest, and nothing in Cove fetches it, because Cove asks for the old digest by name. The rebuild arrives only when Renovate notices the tag moved, opens a digest PR, a human or automation merges it, a release ships it, and a host converges. Every one of those steps is a delay that did not exist when a pull was enough.

The compensating gain is that no rebuild, benign or malicious, can arrive unannounced. The vendor-policy musing already commits Cove to a 72-hour security SLA from advisory to wheel (`docs/musings/2026-09-26-vendor-update-policy.md:103-116`) and to a 48-72 hour hold on fresh releases (`docs/guides/stack-update-guide.md:17`). Digest pinning makes that policy mechanical instead of aspirational. The question is only how the short path is triggered.

### Why Renovate cannot supply the security label

Renovate's `vulnerabilityAlerts` is documented as GitHub-only: it reads Dependabot alerts, and its `supportedPlatforms` is `github`. Cove's canonical remote is Forgejo, and Dependabot does not scan container images for OS packages in any case. The Docker datasource has no advisory linkage. So a Renovate digest PR knows that a tag moved, not why. It cannot say "this rebuild fixes a CVE".

Cove already has the missing signal: `scripts/sbom.sh` runs Trivy, and the release flow already attaches SBOMs. The security path should be scan-driven, not vendor-label-driven:

1. A scheduled Trivy scan of each pinned digest reports new CVEs against the running image.
2. When a CVE appears, the operator checks whether a newer digest for the same tag exists. Renovate usually has that digest PR open already, held by the age gate.
3. The operator labels it security, merges it, releases, and converges. Because the age gate is a Renovate-side control on Renovate-authored branches, an operator-authored or operator-pushed security PR is not gated by it at all.

This is the honest limit: an unlabelled, unscanned rebuild is treated as routine. The scan is what keeps that from being the common case.

### Age-gate split

| Class | Example | Age gate | Merge target | Who can trigger |
|---|---|---|---|---|
| Security digest, labelled | a rebuild that fixes a CVE, or a scan hit with a fixing digest available | none | 4 hours from label | operator, after the Trivy signal or an advisory |
| Routine same-tag digest | vendor re-pushes a tag for any non-security reason, or a security rebuild nobody labelled | 3 days on Docker Hub; not enforceable elsewhere | 1 day (patch-equivalent) | Renovate |
| Routine tag bump (patch/minor) | `1.27.4` to `1.27.5` | 3 days on Docker Hub | 1 day patch, 3 days minor, per `docs/guides/stack-update-guide.md:9-13` | Renovate |
| Major | `forgejo:15` to `16` | n/a | no auto-bump, operator session | operator |

The age gate is real only where the registry returns a release timestamp. Renovate documents that the Docker datasource supplies one on Docker Hub (`tag_last_pushed`) and that GHCR, Quay, and ECR do not. Codeberg and `data.forgejo.org` are not Docker Hub either, and `lscr.io` is a separate registry host. With the default `minimumReleaseAgeBehaviour=timestamp-required`, digest updates on those registries are held forever, which would silently freeze `forgejo`, `forgejo-runner`, `toolhive`, and `speedtest-tracker`. Those managers need `timestamp-optional`, and their hold becomes a calendar schedule rather than a publish-age guarantee. Say that plainly in the runbook rather than pretending the gate is uniform.

There is a second subtlety on Docker Hub: a digest update ages against the tag's `tag_last_pushed`, so a security rebuild restarts the three-day clock. The age gate cannot tell a benign re-push from a security one, which is exactly why the labelled short path has to exist.

### Worst-case time to fix

| Scenario | Today | Proposed |
|---|---|---|
| Security rebuild, auto-update enabled | at most about 24 hours (next daily quiet run at 09:17, `CHANGELOG.md:157`), no review, no gate | about 8 hours when the advisory is known at once (detection, 4-hour merge, release, converge), about 12 hours when a 6-hour Trivy scan is what catches it. Undetected: about 4 days (3-day age gate, 1-day merge, release) |
| Security rebuild, auto-update not enabled | never; `pod_pull_policy: missing` means nothing refreshes (`compose/group_vars/all.yml:43`) | same as above: the PR exists whether or not the host auto-updates |
| CVE published against the pinned digest, no rebuild yet | nothing notices until a pull happens to fetch a fix | Trivy scan notices within the scan interval; the fix still waits for the vendor's rebuild |
| Malicious or accidental rebuild of a floating tag | arrives on the next pull, unreviewed | cannot arrive without a PR; this is the gain |

The regression is narrow and nameable: an unlabelled security rebuild that no scan catches moves from about 24 hours to about 4 days. The gains are that the change is reviewable, that a malicious rebuild is blocked, and that hosts without auto-update are no longer unbounded. If that trade is unacceptable for a specific service, that service needs its own documented exception. No compose service has that claim today; the three non-compose surfaces that stay non-pinned are named in "What must stay floating".

## Migration order and rollback

### Phase 0: prerequisites (separate code PR, before any pin)

1. Re-sync image pins into `.env` on every converge, or remove them from the `.env` contract. Without this, every later step is decorative on existing hosts.
2. Add a red-first test that the rendered `.env` image values equal the pins after a converge.
3. Collapse split pins (`vault`, `forgejo`) into one `*_image` line each.
4. De-duplicate the `compose/bringup.yml` image defaults.
5. Fix the `pins.py` dedup so the inventory lists both Alpine bases.
6. Decide the fate of `compose/litellm/docker-compose.yml`.

Verification: the new test fails before the fix and passes after; a converge on an unchanged stack restarts nothing; `python -m cove.pins` lists every base.

### Phase 1: verify what is already pinned

`vault`, `dnsproxy`, `toolhive`, `bifrost`, and `bifrost`'s Alpine base need no change. Read back each running container's digest and compare it to the declared digest. This also proves the read-back method before it is used to judge a change.

### Phase 2: pin the six floating registry images

Order is by "what can a silent rebuild corrupt", not by how easy the edit is.

| Order | Service | Why here | Verify | Rollback |
|---|---|---|---|---|
| 1 | nginx | stateless, but it fronts everything; a bad image is instantly visible and instantly reversible | `hc.cove` returns 200; container ID unchanged on a no-op converge | restore the tag, converge |
| 2 | speedtest-tracker | optional profile, SQLite in `/config`, no migration on a digest re-pin | `cove speedtest status`; job history intact | restore the tag, converge |
| 3 | forgejo-runner | optional profile, no persistent data, but broken CI is a real outage | a trivial workflow runs; `forgejo-runner --version` matches | restore the tag, converge |
| 4 | tunnel (zrok2) | stateless sidecar; update the per-arch map and the declaration together | `cove tunnel status`; a share still resolves | restore the map entry and the tag, converge |
| 5 | litellm-db (postgres) | stateful pgdata; same major 16 so the risk is a surprise minor inside the tag | `pg_isready`; LiteLLM health endpoint | restore the tag, converge; pgdata is untouched by an image swap |
| 6 | forgejo | the worked example; all repos and the SQLite DB | `/api/healthz`; push and clone a repo | restore the previous digest, converge; keep the old image local |

Forgejo gets extra attention because it is the service that motivated the plan. The pin must be verified against the exact rebuild class that used to arrive by pull: read the running digest, compare it to the declared one, and record both in the PR that lands the pin. If a future security rebuild of `15` is needed, the path is the labelled PR, not a pull.

### Phase 3: pin the four floating `FROM` lines

`compose/dnsmasq/Dockerfile:1`, `compose/litellm/Dockerfile:1` and `:11`, and `compose/ade/Dockerfile:1`. These change nothing at runtime until the image is rebuilt, so verify by building in the isolated staging project, diffing the SBOM, and only then promoting. Pinning `python:3.13-slim` freezes the interpreter patch level, which is the point, and also means Python CVE fixes now arrive only through a digest bump. The age-gate policy applies to these builds too.

### Phase 4: close the Renovate gaps

Add the `tunnel.yml` pattern, the `group_vars` custom manager, the tunnel map manager or documented human step, the pip/npm build-pin managers, and a decision on the ToolHive registry refs and the runner job image. Each gap that stays open goes into `docs/guides/stack-update-guide.md` as a named manual step, not as an implied automation.

### Verification that applies to every step

- Read-back: `docker inspect --format '{{index .RepoDigests 0}}' <container>` equals the declared digest.
- Render check: `docker compose config` shows the pinned reference, with no stale `.env` value winning.
- No churn: a converge that changed no pin leaves container IDs unchanged. The repo already treats config-hash churn as a defect (the `NGINX_CONF_DIR` / `DNSMASQ_CONF_DIR` re-sync comment at `compose/bringup.yml:874-888` exists for exactly this reason).
- Health: the service's own endpoint, not just "container running".
- Staging: `scripts/staging/deploy-isolated.sh` and `scripts/staging/e2e.sh` before any merge that touches `compose/`.

### Rollback

Restore the previous reference in the one pin location, converge, and verify health. For a built image, restore the `FROM` and rebuild. Keep the previous image locally, the way `cove ade update` does, so rollback does not depend on the registry still serving the old digest. The rollback path depends on Phase 0: if the `.env` re-sync is missing, the rollback suffers the same delivery defect as the pin, which is another reason Phase 0 is blocking rather than nice to have.

## What must stay floating

The honest answer is that no compose service must stay floating. The same-tag rebuild delivery that floating provided is replaced by Renovate plus the scan loop, and a service that "needs" floating is a service whose security path has not been designed yet.

Three things stay non-pinned, and none of them is a compose service:

1. **The Forgejo runner's job image**, `gitea/runner-images:ubuntu-latest` (`compose/provision_forgejo.yml:446`). The label name is the contract: a workflow asks for `ubuntu-latest` and the runner maps that label to an image. Pinning the image freezes what the label means, so a workflow that asks for `ubuntu-latest` silently gets an old image, and the runner pulls it per job, outside the compose pull policy. This is a real supply-chain surface and deserves its own decision, but pinning it is not the same task as pinning compose services.
2. **The zrok2 per-arch digest map** (`cli/cove/tunnel.py:15-24`). It is not floating at runtime; it is pinned per architecture by the CLI. What floats is the declaration in `compose/tunnel.yml`, which should carry the index digest so Renovate has a target. Keep the per-arch map, add a test that ties each child digest to the declared index digest.
3. **Build-time package fetches.** `apt-get`, `apk upgrade`, `pip install`, and `npm install` run against live repositories at build time. Pinning the `FROM` does not pin them. This is not an image pin and should not be described as one. Closing it needs lockfiles or snapshot repositories, and it is a separate piece of work.

The three ToolHive registry OCI refs are a fourth candidate. They are tags today. They should be pinned inside `registry.json`, but they are runtime sibling pulls, not compose images, and Renovate needs a custom JSON manager to see them.

## Residual risks and open questions

1. **Registry garbage collection.** `--pull always` on a digest that the registry has dropped fails the converge. Verify in staging whether Compose falls back to the local image; if it does not, stop forcing the pull for pinned services.
2. **Index versus per-arch digests.** The plan uses index digests everywhere except the zrok2 CLI map. Confirm that every registry in the set serves a manifest list, not only per-arch manifests.
3. **Renovate hosting and cadence.** Detection latency is the first term in every time-to-fix number. Where Renovate runs (self-hosted against Forgejo, GitHub app, or a scheduled thread) and how often it runs are decisions the Renovate task must record.
4. **Registry access from Renovate.** Codeberg, `data.forgejo.org`, and `lscr.io` all need to be readable by the Renovate process. A failure here silently narrows coverage to Docker Hub.
5. **The `.env` re-sync versus deliberate overrides.** `cove ade update` and `cove tunnel up` write image pins into `.env` on purpose. A blanket re-sync must not clobber those two, or their rollback designs break.
6. **The duplicated LiteLLM compose file.** If it is dead, delete it. If it is live, a bump must touch both, and Renovate will open two PRs.
7. **The `pins.py` dedup bug.** Until it is fixed, the SBOM and the audit under-report, and a completeness test written against the inventory would pass while a base is missing.
8. **Scan coverage.** Trivy scans OS packages and language packages in the image. It will not tell you that a vendor rebuilt the image for a reason it did not publish. The scan closes the common case, not every case.

## Appendix: verification commands

Read-only checks the implementer can run per step. None of these mutate a container.

```bash
# Inventory as the SBOM and audit see it
uv run --directory cli python -m cove.pins "$PWD/compose"

# What a container is actually running
docker inspect --format '{{.Config.Image}} {{index .RepoDigests 0}}' cove-forgejo

# What compose would render, including .env interpolation
docker compose -f compose/docker-compose.yml --project-directory compose config | grep 'image:'

# Convergence with no pin change must not restart anything
docker compose -f compose/docker-compose.yml --project-directory compose ps --format json
```

The staging gate for any compose-touching change:

```bash
scripts/staging/deploy-isolated.sh <branch>
scripts/staging/e2e.sh
scripts/staging/teardown.sh <branch>
```
