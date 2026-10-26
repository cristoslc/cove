# Changelog

All notable changes to Cove are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 0.15.7 (2026-10-26)

### Added
- **Bifrost gateway (LiteLLM replacement candidate, additive phase)** — a new `bifrost` compose profile running Bifrost transports v2.3.2 (digest-pinned, multi-arch manifest verified) alongside the live LiteLLM services: no removal, no cutover, no client re-point. The nine tier aliases re-express as CEL routing rules with ordered fallback chains (Synthetic subscription → ollama-cloud metered → a streaming-only "infinite" backstop instance gating non-streaming traffic structurally). Governance (single virtual key, auth-by-default, `enforce_auth_on_inference`) lives in a file-seeded `config.json` (`source_of_truth: "config.json"`) plus a pre-seeded SQLite config store (a file-only boot cannot carry governance). New `cove bifrost` verb group (up/down/status/logs; never auto-started by `cove up`), `bifrost.cove`/`bifrost.cove.local` nginx vhost + landing card, cert SANs, hosts entry, bringup seeding (private `0700` data dir, first-boot config/dnsmasq seeds, private env files), and a DNS-choke egress allowlist: the gateway's resolver pins a hardened dnsmasq sink (read-only, caps-dropped, no ports) serving exactly `api.synthetic.new` and `ollama.com`. The ollama-cloud key stays projected by the workstation lane (pass-through, no new custody). Upstream publishes no image signatures/provenance (finding recorded in docs/services/bifrost.md), so the digest pin plus the 48-72h vendor hold are the anchors. The file-seeded virtual key authenticates on v2.3.2 (spike finding resolved; live-smoke proved). Cutover remains gated on four pending operator decisions (pgdata disposal, key-rotation timing, 1Password item retention, drain window). See [docs/services/bifrost.md](docs/services/bifrost.md) and [the exit musing](docs/musings/litellm-exit.md).

## 0.15.6 (2026-10-26)

### Security
- **Public repo scrub completed: operator-identifying config removed from tree and history** — the public GitHub repo had carried user-specific config in tree and full git history since 2026-05-09: a committed copy of the 1Password seed template (`compose/seeds/vault-user.yaml`) embedding the operator hostname (rendered here as `<hostname>`) and the operator username. Correction after verification: the committed blob was the **unrendered template** — its password field held the literal placeholder `{{generate:32}}` — so no credential value was ever committed to history; a rendered copy carrying a real value existed only as an untracked local file. The repo was deleted, recreated at the same name, and repopulated from `git filter-repo`-rewritten history: the seed file is absent from all history, and the hostname, personal email address, `/Users/<name>` home paths, a tailscale node-name fragment, two machine-specific files (`compose/host_vars/<hostname>.yml`, `compose/dnsmasq/cove.conf`), six compiled blobs, and two committed Go binaries carrying home build paths are replaced or removed across every blob and rewritten tag. Zero historical release assets were re-attached — fresh releases follow the normal post-merge flow. This release is the first one published from the rewritten history.

### Removed
- **`cove up` no longer provisions a Vault UI user** — the `provision_vault_user.yml` call is removed from the `cove up` chain (`bootstrap_vault.yml` + `provision_forgejo.yml` remain). The playbook and `compose/seeds/vault-user.yaml.example` stay in-tree as reference with ownership headers: vault-user provisioning is **workstation-lane-owned** from now on, and `cove up` must never render the seed with a per-run generated password — the old flow created a new same-titled 1Password item on every run (the duplicate observed 2026-10-23) and drifted the Vault UI credential from the credential of record, leaving `cove up` failing at the provision step since then. `.gitignore` explicitly pins the rendered seed path (`compose/seeds/vault-user.yaml`) and adds `cli/.pytest_cache/`.

### Fixed
- **`cove creds vault-put` never prints the resolved secret** — the command cached the op:// reference but wrote the 1Password-resolved value bare to stdout, which put a live credential value into an agent transcript during dedupe verification (2026-10-26). stdout now carries the batch-pull-style `****************` mask. The three internal consumers that parsed the value from stdout (`cove tunnel up`, `cove litellm up`, `cove speedtest up` up-flows) now resolve it in-process via `cove.vault_cache.vault_put_op_ref`, so the secret never travels through stdout at all.

### Changed
- **The no-PII gate is widened to the whole repo and un-blinded** — `cli/tests/test_no_pii.py` now scans every git-tracked file (pytest previously ran from `cli/`, so its repo-root `docs/` exclusion never matched and docs were never scanned), `compose/`, `CHANGELOG.md`, and the bundled wheel resources (`cli/cove/resources/compose/`); `docs/troves/` (third-party web snapshots) and `sbom/` (generated SBOMs carrying upstream authors' emails) are excluded as third-party content. The gate's own pattern list no longer embeds real operator values: the hostname sentinel is a machine-model + 6-digit-tail regex, bare-username matching became context rules (`Vault <machine> <user>` 1Password item titles, `/Users/<name>` home paths, personal mailbox domains), and a structural rule admits only `*.example` files under `compose/seeds/`. Synthetic placeholders like `<hostname>` are legitimate repo content and no longer act as false-positive sentinels (the gate had been red in-tree since the placeholder convention reached `cove/resolver.py`'s docstring); it is green on the 0.15.6 tree.

## 0.15.5 (2026-10-22)

### Security
- **Speedtest Tracker pin `v1.14.5-ls162` → `v1.15.1-ls177` (PHP 8.5.8 → 8.5.12)** — the pinned image shipped PHP 8.5.8, vulnerable to the PHP2Shell unauthenticated RCE pair (CVE-2026-109618, CVE-2026-109619); the new tag ships PHP 8.5.12, the fixed release. This is a security-override patch-class bump, so the repo's 48-72h supply-chain hold did not apply. The deployed `~/.config/cove/compose/.env` `SPEEDTEST_IMAGE` override (which takes precedence over the compose default and is only rendered on first boot) was advanced to the new pin alongside this change.

## 0.15.4 (2026-10-22)

### Security
- **Removed an operator hostname (`<hostname>`) that shipped in the 0.15.3 wheel and repository** — the 0.15.3 resolver module's docstring and one test fixture embedded the real machine hostname; the repo's own no-PII gate caught it on the release tree (it had passed on the PR branch before the files were finalized). Docstring now uses a `<hostname>` placeholder and the test fixture a neutral name. The 0.15.3 release artifacts on both hosts are superseded by 0.15.4; anyone holding a 0.15.3 wheel should replace it. No other PII pattern was affected.

## 0.15.3 (2026-10-22)

### Fixed
- **`cove up` now keeps Vault unsealed even when the compose run itself recreates it** — the unseal health probe covered only ~5s, while a freshly recreated Vault takes tens of seconds to answer; the probe now covers ~30s (15 attempts, 2s apart, 2s timeout, still returning immediately on first answer and bounded so unattended runs cannot hang). Detection semantics unchanged: untouched Vault is never probed, uninitialized is skipped, unreachable-after-window warns, unseal failure fails loud.
- **`cove up` re-points macOS scoped-resolver files (`/etc/resolver/cove*`) at the current `dnsmasq_port`** — the resolver files were installed out of band and `cove up` never refreshed them, so the 0.15.2 port move left them at 5353 while dnsmasq listened on 5354 and the macOS resolver path went silently dead. The bringup now finds every `/etc/resolver/cove*` file (Darwin-only, `become` mirroring the existing `/etc/hosts` task, idempotent port-line replace, non-fatal when unprivileged) and re-points them; `cove status` additionally reports any resolver-port drift with the exact corrective one-liner.

## 0.15.2 (2026-10-22)

### Fixed
- **dnsmasq's published host port moves from 5353 to 5354** — on macOS hosts a third-party process commonly squats UDP 5353 (e.g. GLKVM Helper binds `*:5353/udp`), which starves the runtime's UDP forwarder and leaves the `/etc/resolver/cove` path dead even with a correct `/udp` publish. The port is now single-sourced from `group_vars/all.yml` (`dnsmasq_port: 5354`): the compose publish default, the macOS resolver template, the Linux fleet-forwarder template, the rendered config page, and `.env.example` all derive from it, and a consistency test fails if any of them drift. Container-side port stays 5353; only the host-facing publish moves.
- New `TestDnsmasqPortConsistency` tests guard the coupling (red-first: planting a disagreeing group var failed exactly the intended assertions).

## 0.15.1 (2026-10-21)

### Fixed
- **`cove update` no longer crashes in its post-install pin-compare** — the wheel path returned by the install step pointed into a temp directory that Python deleted the moment the install function returned, so the pin-compare opened a dangling path (`FileNotFoundError` on every update run; the install itself succeeded, as did `cove --version`). The wheel's temp dir is now released by the update flow after the convergence gate decides, a wheel missing at compare time raises a named `ClickException` instead of a traceback, and the built wheel lands outside the throwaway git worktree so worktree cleanup cannot take it. Fixes #80.
- **Wheels built by `cove update` carry the bundled compose pins again** — the temp-worktree build skipped `sync_compose_resources.py`, and since `cli/cove/resources/compose/` is gitignored every wheel `cove update` built shipped with an empty bundled compose set, which would have made every update wrongly read as pending convergence. The build now runs the tag's own sync script first, mirroring the promote flow.

## 0.15.0 (2026-10-21)

### Added
- **`cove --sbom`** — print-only inventory of the pinned artifacts, parsed live from `compose/` (group_vars authoritative where it carries a pin; `python -m cove.pins --json` for the machine-readable form). Deliberately an about item, not a command with state: it prints the pin matrix and exits, and bare `cove` still shows help. Generation stays a development step: `scripts/sbom.sh` writes CycloneDX via trivy into `sbom/`, committed inside version-bump PRs so the PR diff is the SBOM delta.
- **Stack-update runbook** — `docs/guides/stack-update-guide.md` carries the update SLA (patch merged within a day, minor within 3, major filed as a gap-analysis issue instead of a PR), the master pin inventory, the per-component upgrade procedure, the SBOM process, and the design for the Forgejo `version-audit` workflow plus the BB reviewer automation (planned; activation documented there).
- **Compose-source guards: refuse a source that would collapse binds or hijack the live stack** — a compose dir whose `.env` (or process environment) has no non-empty `COVE_DATA_ROOT` / `FORGEJO_DATA_ROOT` now aborts loudly before Ansible or Docker run instead of interpolating empty and collapsing every `${COVE_DATA_ROOT}/x` bind to container-absolute `/x`; a compose dir that declares the live `name: cove` while pointing at a different data root is refused unless `COVE_ALLOW_FOREIGN_DATA_ROOT` is set. Covers `cove up`, `cove down`, `cove uninstall --all`, every service `up`/`down` (ade, speedtest, toolhive, runner, litellm, tunnel), plus an Ansible pre-flight assert in `bringup.yml` for a direct `ansible-playbook` run. Remediation for incident 20261018-015539.

### Fixed
- **dnsmasq publishes UDP alongside TCP on 5353** — the compose `ports:` entry was TCP-only (`0.0.0.0:${DNSMASQ_PORT:-5353}:5353`, no `/udp`), so Docker never forwarded UDP and macOS's `/etc/resolver/cove` (`nameserver 127.0.0.1`, `port 5353`) got no answer for any `*.cove` name; resolution silently survived on `/etc/hosts` aliases. Both protocols now publish (DNS is UDP-first; TCP stays for large/truncated responses). Note for other Cove machines: a host process squatting UDP 5353 still blocks delivery at the OS level — the publish is necessary but the port must also be free.
- **Compose re-extraction preserves the inode of every unchanged bundled file, and only containers holding genuinely changed files restart** — the old prune deleted all non-preserved entries and re-copied the full bundle, giving every file a fresh inode; any container binding a bundled file then held a stale, unlinked inode after the next extraction (nginx 404'd its own landing page and configs). Pruning is now content-aware: byte- and mode-identical files keep their inode, directories recurse instead of being removed wholesale, and `cove up` restarts only containers whose bound files actually changed. The runtime root CA (`certs/rootCA.pem`) is preserved across extractions and every compose-dir file bind's source type is validated pre-flight. Remediation for incidents 20261019-155756 and 20261019-201500.
- **`cove up` unseals Vault after any restart or recreate of its container, whatever caused it** — the heal previously fired only when the CLI itself restarted Vault for a changed `vault.hcl`, so a compose-initiated recreate (rotated credential in `.env`, bundle change, bringup handler) left Vault sealed after `up` reported success (two live occurrences, 2026-10-20/21). `cove up` now snapshots Vault's container identity (Id + StartedAt) before the compose run and unseals from the OS keystore when it changed; the health probe is bounded so unattended runs cannot hang, unseal failures fail loud, and an untouched Vault is never probed.
- **The landing page's LiteLLM card links to the admin console (`/ui/`), not the API root.**

### Security
- **`adguard/dnsproxy` pinned `latest` → `v0.86.0@sha256:4d65bafb…`** — the DoH sidecar was the last image in the stack floating on `:latest`, violating the documented no-latest posture; the pinned tag and current `latest` share the same image-index digest, so no runtime change occurs.

### Changed
- **Container-touching tests are opt-in behind `COVE_ALLOW_LIVE_TESTS`** — tests marked `@pytest.mark.live` (anything touching a real container or the running stack) skip by default with a skip message naming the flag, and an autouse guard aborts on any stack-mutating `docker` command from an un-opted-in test, so an unfiltered `pytest` can no longer recreate the live stack (remediation for incident 20261018-015539). The `-m` filter selects tiers; it is not what keeps the stack safe.
- **`scripts/release.sh` attaches the committed `sbom/*.cdx.json` snapshots to releases on both hosts** and fails loud when the snapshot directory is empty (run them with `scripts/sbom.sh` first).

## 0.14.1 (2026-10-17)

### Fixed
- **Long-running LiteLLM streams no longer hit nginx's 60-second proxy timeout** — LiteLLM ingress now uses the same 3600-second read/send timeouts and disabled response buffering as Cove's other streaming routes.
- **Compose resource re-extraction preserves runtime `.env` and generated nginx config** — resource updates keep the persistent environment file and current `nginx/default.conf` inode in place while refreshing bundled source and pins, including when a resource copy fails. `cove up` remains responsible for rendering the current nginx config.

## 0.14.0 (2026-10-17)

### Added
- **Update-safe local LiteLLM configuration overlays** — Cove now bundles generic proxy defaults and composes them with persistent per-machine operator configuration. Existing `config.yaml` customizations migrate once into `config.local.yaml`, which survives future bundled-default updates. Model deployments, aliases, load balancing, fallback policy, and credentials remain local and outside the repo/wheel; credentials use environment references backed by the private `local.env` or the operator's secret workflow.

### Fixed
- **`cove update` no longer treats `.env.example` as a pin change** — the wheel's packaging omits the dotfile while the synced resources and deployed checkouts include it, so wheel-vs-deployed comparison always differed by one file (live-verified: dev-checkout `--check` said pending while the stack was converged). `.env.example` documents the override surface; it, like `.env`, never counts as pending. Related packaging defects (dotfile omission, `build/lib` wheels pollution) documented in `docs/tech-debt/wheel-packaging-hygiene.md`.

- **`cove ade update` rollback restored the wrong state — claimed rollback while the failed version kept running** (found live updating bb-app 0.44.0 → 0.46.0): when `.env` never recorded `ADE_IMAGE` (pin from bringup defaults only), the rollback kept the new image and compose, seeing no spec change, skipped recreation. The pre-update container image is now captured before any recreation and always restored, with the version pin derived from it, and the rollback recreates with `--force-recreate` (`_previous_image()` contract-tested, red-first).
- **bb-app >= 0.46 host allowlist broke ade health checks via nginx** (live: `forbidden_host` on `Host: ade.cove` — bb-app now accepts only localhost/IPs/`BB_APP_URL`'s hostname). The ade compose service declares `BB_APP_URL: ${ADE_APP_URL:-https://ade.cove}`; without it the 0.46.0 web UI and ingress health probe 403.

### Changed
- **`cove update` brings up only what it changes — and only what is running** — convergence runs bring-up only when the release's bundled compose differs from what is deployed (real pin change; `.env` overrides and gitignored runtime artifacts like the rendered nginx config, dnsmasq config, and credential seeds never count), and only when cove containers are already running. A downed stack is never resurrected by an update (`cove up` remains the explicit way to start it), and a converged stack skips the multi-minute bring-up entirely. `cove update --check` now reports the running stack and whether convergence is pending. The new wheel's bundled pins are compared from the wheel itself (post-install), since the running process still holds the old code.

## 0.13.0 (2026-10-13)

### Added
- **`cove ade update`** — keep bb current in cove without leaving the IaC rails. Resolves the target (npm latest or explicit `--version`), writes the pin + image tag into the compose `.env` (a persistent override — bringup never rewrites those keys), rebuilds the image, recreates the container (data volume untouched), waits for `/health` through nginx, and **rolls back automatically** on failed health (previous image tag stays local, so rollback is `cove ade update --version <old>`). `--check` reports running vs pinned vs latest without changing anything. The server is the bb version anchor: it serves its own tarball to enrolled machines and daemons self-update to its protocol, so updating the server updates the harness.
- **`cove ade status` version visibility** — prints the running bb-app version (parsed from the container image tag) and warns when it diverges from the `.env` pin ("run `cove ade up`/`update` to converge"), keeping the override surface honest against the wheel default.

- **`cove update`** — one command, one source of truth: install the latest **tagged** cove release, then converge the whole stack (containers, images, migrations) to the pins that release ships, via the normal bring-up flow. Forgejo data migrations and Vault upgrades ride inside it. Never trunk — the wheel attached to a tagged release is the only artifact `update` consumes. `cove update --check` reports installed vs latest vs running pins, changing nothing. Per-service escape hatches (`cove ade update --version X`) remain for targeted pins and rollbacks.
- **`cove update auto`** — schedules `cove update --quiet` daily via launchd (default 09:17; `--off` removes it). The opt-in **is** the approval: after setup there is no operator in the loop. Quiet runs skip the BECOME prompt (`--non-interactive` up-path; elevation tasks are idempotent no-ops on established machines) and force re-pull so floating tags (`forgejo:15`, nginx) actually receive upstream patches instead of freezing at first pull.
- **Musing** — `docs/musings/2026-09-26-cove-update-command.md`: the vendor-update commitment, the staleness audit (Forgejo one major behind, LiteLLM ~18 minors), and the design record including the superseded first draft.

### Changed
- `cove up` gained `--non-interactive` (skips the BECOME prompt; for scheduled use) and honors `COVE_PULL_POLICY` so updates can force image re-pulls.

### Fixed
- **`cove ade` health probes used the dead 8443 port** — the ade-update branch predates the pf shim drop: `cove ade status` reported UNREACHABLE on healthy machines and `cove ade update`'s health-wait would always fail (spurious rollback). `ade.py` now uses `constants.NGINX_HTTPS_PORT` (nginx owns 443), like litellm/speedtest/toolhive. Regression test added (red-first).

## 0.12.1 (2026-10-08)

### Security
- **urllib3 bumped 2.7.0 → 2.8.0 in `cli/uv.lock`** — closes all three open Dependabot alerts on the GitHub default branch (2 high, 1 moderate): GHSA-vxq7-64xx-v4gw (unbounded chunk-size line buffering in `HTTPResponse.stream()`/`read_chunked()`), GHSA-8988-9cw3-xx77 (HTTPS proxy TLS configuration may be ignored or overridden), GHSA-gh4c-6fx4-qh6g (chunked deflate streaming infinite loop). All three are patched in 2.8.0. Note: `uv tool install` resolves fresh at install time and already had 2.8.0 on machines installed from in the last day; the lock is the canonical pin and the thing Dependabot scans.

## 0.12.0 (2026-10-08)

### Changed
- **nginx owns port 443 directly — the pf 443→8443 shim is gone** — compose now publishes `0.0.0.0:443:443` (nginx was already listening on 443 inside the container; only the host facing port was wrong). Bringup no longer installs a macOS pf redirect for `localhost:443 → 8443` on every `cove up`, and no longer wires a `tailscale serve` listener on 443. `NGINX_HTTPS_PORT` is removed from `.env`/Ansible; the single source of truth is `cove.constants.NGINX_HTTPS_PORT = 443`, re-exported by `cove.status`. All CLI probes (`cove status`, `cove litellm status`, `cove speedtest status`, `cove toolhive status`) go through nginx via that constant — nothing in the CLI hardcodes 8443 anymore. Contract tests pin the compose publish, the port coupling points, and that `scripts/staging/*` no longer reference 8443; the legacy in-live staging default moves to `https://127.0.0.1:443`. Rationale: pf rules do not survive reboot and silently failed (`failed_when: false`), so `https://git.cove/` and friends were unreachable from the browser even while `cove status` (probing 8443 directly) reported green. This lands the reviewed sashay `drop-pf-shim-nginx-owns-443` (Forgejo chronicle 2026-09-19; three review rounds converged, approved).

## 0.11.1 (2026-10-08)

### Fixed
- **ToolHive never started: the curated registry was mounted as a file into a directory that does not exist** — 0.11.0's compose bind-mounted `registry.json` straight to `/registry/registry.json`, but the distroless `thv` rootfs (v0.51.4) ships no `/registry` directory and Docker cannot create one for file→file binds, so the container exited 127 with a "not a directory" mount error. The mount is now a directory bind (`${COVE_DATA_ROOT}/toolhive:/registry:ro`; Docker creates the destination and the seed file appears at `/registry/registry.json`), and bringup's render task re-runs when the seed file is missing or when `thv`'s persisted config has blanked `local_registry_path` (a second way the curated registry went dark). Contract tests updated to the directory-bind shape.
- **bringup forced Colima on macOS, resurrecting the VM behind the operator's back** — every `cove up` ran `colima start` + `docker context use colima` unconditionally, re-pinning the engine to Colima and rewriting the Docker context in `~/.docker/config.json`. Bringup now probes `docker info` first: an answerable daemon wins as-is, Colima is only started as a fallback when no engine responds.
- **forgejo-runner and toolhive restart-looped on non-Colima engines** — the compose env hardcoded Colima's docker.sock group id (991), while OrbStack's socket is `root:root` (gid 0), so gid-filtered access failed. Bringup now detects the live daemon's in-VM socket gid (scratch `stat` container) and syncs `FORGEJO_RUNNER_DOCKER_GID` / `TOOLHIVE_DOCKER_GID` into `.env` on every `cove up`. Two bringup contract tests pin the manifest.

## 0.11.0 (2026-10-02)

### Added
- **`cove sudo disable`** — removes `/etc/sudoers.d/cove` so `cove up` prompts for the BECOME password again. Prompt-free when passwordless sudo is already in place (or running as root); one sudo password prompt otherwise. After removal the functional check runs again, so the reported state is the truth even if some other `NOPASSWD: ALL` grant exists outside the cove drop-in (it says so and points at `sudo -l` rather than claiming success). Fails loud if the removal itself fails. Complements the retire-the-grant direction in `docs/musings/cove-up-sudo-friction.md`.

### Changed
- **`cove sudo enable` replaces `cove sudo setup`** — the sudo group is now a true toggle triad (`enable` / `disable` / `status`), matching the repeatable on/off reality instead of one-time-provisioning framing. `setup` remains as a hidden alias with identical behavior for existing references and muscle memory; status remediation messages, help texts, and the repo AGENTS.md now point at `enable`. Folded into 0.11.0 before its first tag, so no released version changes shape.

## 0.10.1 (2026-10-02)

### Fixed
- **`cove sudo status` could never report the drop-in installed** — the check ran `visudo -c -f /etc/sudoers.d/cove` unprivileged, but the drop-in is root:wheel 0440, so visudo always failed with EACCES and `cove up` prompted for the BECOME password even after a successful `cove sudo setup`. The check is now functional: `sudo -n -l` (never prompts, mutates nothing) must list a `NOPASSWD: ALL` grant; the listing is parsed, not just the exit code, so a recently cached sudo timestamp cannot fake a pass.
- **`sudo cove sudo setup` installed the grant for root** — under sudo, `getpass.getuser()` returns root, so the rendered drop-in granted root `NOPASSWD: ALL` and silently dropped the operator's grant (the reason `cove up` re-prompted after a root-run setup). Setup now targets `SUDO_USER`, skips the password prompt when already root, and echoes the grant target.
- **A typed BECOME password never reached sudo** — `cove up` set `ANSIBLE_BECOME_PASSWORD`, which matches no ansible-core setting; the sudo become plugin reads `ANSIBLE_BECOME_PASS` (ansible/plugins/become/sudo.py), so sudo ran with empty stdin and every become task died with `sudo: a password is required` even with the correct password typed. The env var is renamed on both the prompt and passwordless paths (an empty value stays falsy to the plugin, so no password is handed to sudo under the drop-in).

## 0.10.0 (2026-09-28)

### Added
- **ToolHive MCP gateway (`cove toolhive`)** — optional `mcp` profile service at `https://mcp.cove/`; Cove's only MCP surface (LiteLLM's MCP endpoints stay disabled for CVE-2026-42271). One pinned `thv` control-plane container (read-only docker.sock, loopback-bound UI/API) manages sibling MCP-server containers constrained by permission profiles and explicit mounts; curated IaC registry (`compose/toolhive/registry.json`: filesystem/fetch/time seed servers, tag-pinned, remote fetch off for offline-first); nginx vhost returns 403 for everything except exact-match `/health` (private-range ACL) — the UI/API route opens in Phase 2 behind an auth layer. `cove toolhive up|down|status|logs`, `cove up --all` includes it; staging E2E (`deploy-isolated.sh` profile wiring, tier-2 auth-posture tests, teardown profile guard). Docs: `docs/services/toolhive.md`; plan: `docs/plans/toolhive-mcp-gateway.md` (Forgejo PR #59).

## 0.9.1 (2026-09-28)

### Fixed
- **`cove up` failed at the nginx reload handler after a template re-render** — `open() "/etc/nginx/conf.d/default.conf" failed (2: No such file or directory)`. On macOS/Colima, file bind-mounts pin the host inode at container creation, and bringup's `template`/`copy` renders are atomic (rename → new inode), so the running cove-nginx mount served a stale inode (link-count 0) and `nginx -s reload` — which re-opens every config file — died with ENOENT, killing `cove up` at the handler flush. The handler now restarts the container (re-resolves the bind by path, ~1s blip) instead of exec-reloading; a bringup structure test pins the contract. Live-stack remediation: `docker restart cove-nginx`.

### Added
- **Tech-debt note on dual-host release drift** — `docs/tech-debt/dual-host-release-drift.md`: releases must exist on both GitHub and Forgejo (tags/releases/wheels currently diverge between the hosts; the stale goreleaser workflow can only fail); fix shape for automated dual-host publishing. v0.9.1 is the first release cut manually on both hosts as the stopgap.

## 0.9.0 (2026-09-26)

### Added
- **`cove up --all`** — launches every optional service along with the default ones. The bringup pod starts Runner with the core services (ADE is core since 0.8.0); the LiteLLM and Speedtest flows run right after the provisioning chain, so their 1Password/Vault credentials are prepared before their containers start (Vault must be up for `vault-get`/`vault-put`). The tunnel stays out — shares are created interactively with `cove tunnel up`. A credential failure on one optional service is reported without aborting the bringup (optional stays optional, same contract as `cove status`).

## 0.8.0 (2026-09-25)

### Changed
- **ADE is a core service** — `cove up` now starts the ADE bb server by default; no `cove ade up` second step (operator decision, ADR-018 day-one intent: "bb as the default harness, the way Vault is the default vault"). The `ade` compose profile is gone; a stopped ADE fails `cove status` like any core service; `cove ade down` stops it until the next `cove up`. `cove ade up` remains and is now service-scoped (`docker compose up -d --build ade`). First `cove up` after upgrade builds the ADE image (a few minutes).
- **bb-app pin 0.43.4 → 0.44.0** — aligned with the operator's installed bb. Load-bearing for Phase 2 enrollment: bb machines install the server's own tarball (`/install/bb-app.tgz`) and a daemon never auto-downgrades to an older server protocol.

### Added
- **Phase 2 cutover runbook** — `docs/services/ade.md` (Machines): migrate `~/.bb` into the container volume, quit bb, enroll the Mac's daemon via `bb machine enroll --bootstrap-file` (bootstrap from `ade.cove` → Settings → Machines). Enrollment remains an explicit operator step — it stops the host bb server.

## 0.7.1 (2026-09-25)

### Fixed
- **`cove up` failed on existing deployments after the 0.7.0 promote** — `MISSING: ade.cove` at TLS-cert validation. The cert task's `creates:` guard skipped the (already drift-aware) `cove certs sign` on machines whose cert predated ADE Phase 1, leaving validation no healing path. The sign task now runs on every `cove up`: `sign_cert` regenerates when the requested SAN set diverges from the installed cert and settles idempotent otherwise; the regenerated leaf triggers an nginx reload (notify), and the fail-loud validation remains the safety net. Two deeper fixes surfaced: the SAN comparison never matched IP entries (requested strings vs parsed `IPv4Address` objects — every real SAN list regenerated forever until normalized), and `cove certs sign` printed `Signed:` unconditionally, so Ansible could not distinguish changed from skipped (`Up-to-date:` added; bringup's `changed_when` keys off it). Validation's host list is now parity-checked against the sign argv in tests so the two can never silently diverge again.
- **`cove --version` drift** (shipped in 0.7.0) — version now read from package metadata instead of a hardcoded literal.

## 0.7.0 (2026-09-25)

- **ADE — Agentic Development Environment, Phase 1** (`cove ade`, PR #55, ADR-018) — the pinned `bb-app` server as an optional profiled service (`cove ade up|down|status|logs`), served at `https://ade.cove/` through nginx with WebSocket upgrade support and an ingress allow-list (loopback, private ranges, tailnet CGNAT; public internet denied). Data under `${cove_data_root}/ade/`; the port has a single source of truth (`ade_port`, threaded through the compose env, the container healthcheck, and the nginx upstream). Staging E2E now runs as an isolated compose project (`cove-staging`, nginx on 127.0.0.1:9443) so branch E2E no longer disturbs the live stack. See [docs/services/ade.md](docs/services/ade.md).

## 0.6.0 (2026-09-23)

- **`cove tunnel`** — managed public relay via zrok2 (PR #53). `cove tunnel up/ls/down/reset-token` with an interactive service picker, interactive token onboarding (1Password via ADR-017), platform-aware per-arch image pinning, Cove-rendered nginx share routes (rendered mid-stream, removed on Ctrl-C), orphan-share cleanup on `up`, clickable `?interstitial=1` links, and full Ctrl-C teardown. Docs: `docs/services/tunnel.md`.

## [0.5.1] — 2026-09-22

### Added
- **Node/Electron CA trust documentation** on the `ca.cove` config page (`/config/`) — Node.js and Electron never read the OS trust store, so TLS to `*.cove` names fails even after the OS trusts the Cove CA. The page now documents `NODE_EXTRA_CA_CERTS`, a download-first path (`curl -kL -o cove-root-ca.pem https://ca.cove/config/ca`), durable OS-store alternatives (macOS `security add-trusted-cert`, Linux `update-ca-certificates`), and the `launchctl setenv` non-durability caveat. See issue [#51](https://git.cove.local/cristos/cove/issues/51).
- **Forgejo Actions Runner service** (`cove runner up|down|status|logs`) — optional profiled CI runner that polls Forgejo for Actions workflows and executes them in Docker sibling containers. Outbound-only, no nginx route, no 1Password seed. Registration handled by `provision_forgejo.yml` IaC. See [docs/services/forgejo-runner.md](docs/services/forgejo-runner.md).
- **Forgejo webhook allowlist** (`webhook.ALLOWED_HOST_LIST`) — explicit, configurable compose env var defaulting to `loopback` (upstream default `external` blocked all loopback/private webhook delivery, breaking local receivers like tidesman). Widen per-receiver via `FORGEJO_WEBHOOK_ALLOWED_HOST_LIST=loopback,<host-or-cidr>`. See [docs/services/forgejo.md](docs/services/forgejo.md) and issue [#44](https://git.cove.local/cristos/cove/issues/44).

### Fixed
- **cryptography CVE-2026-69247** (GHSA-g6cj-pr64-35w5, Bleichenbacher oracle in `pkcs7_decrypt_*`) — dependency floor raised to `cryptography>=50.0.0` (patched release), lock resolves 50.0.1, so the pinned version cannot regress.
- **Runtime `.env` preserved across compose re-extraction** — `extract_resources()` no longer deletes the deployed `.env` on a promote (the 2026-09-02 incident: promote wiped `.env`, a bare `docker compose up` then booted Forgejo against an empty data mount). `cove up` additionally fails loud before bringup if `docker compose config` reports unset `*_DATA_ROOT` variables. See `docs/tech-debt/extract-resources-deletes-env.md`.
- **Bringup bind-mount dir guard** — bringup fails loudly if Docker auto-created directories at file-mount targets.

## [0.5.0] — 2026-08-14

### Added
- **`cove status` shows stopped optional services** — status output no longer hides profiled optionals; `cove up` reconciles the running ones. Stopped optionals no longer fail the status exit code.

### Fixed
- **`cove up` BECOME password prompted once** — not once per playbook.
- **Speedtest Tracker admin env re-injected on re-run**; `DISPLAY_TIMEZONE` set. `APP_KEY` no longer clobbered; Cove Admin secrets pulled in one batch.

## [0.4.1] — 2026-08-12

### Fixed
- **idna Dependabot vulnerability** (GHSA-65pc-fj4g-8rjx, CVSS 5.3) — bumped transitive `idna` to `>=3.15` (resolves to 3.18) and added an explicit `idna>=3.15` constraint to `cli/pyproject.toml` as a regression guard.

## [0.4.0] — 2026-08-12

### Added
- **Speedtest Tracker service** (`cove speedtest up|down|status|logs`) — optional profiled service monitoring the operator's WAN link (uptime, latency, download/upload bandwidth, jitter, packet loss) via scheduled Ookla `speedtest` CLI runs. Accessible at `https://speedtest.cove/` through nginx ingress. Default schedule: 8 daytime runs (`0 7,9,11,13,15,17,19,21 * * *`).
- **IaC provisioning** for Speedtest Tracker — admin email/password sourced from the shared **`Cove Admin`** 1Password item (keyed to `https://cove.local/`, ADR-017); APP_KEY in the `Speedtest Tracker` item (keyed to `https://speedtest.cove.local/`); fail-loud if the Cove Admin item is missing.
- **ADR-017** — Unified Cove Admin Identity: all Cove services share the `admin@cove.local` identity.
- **Cove Pages portal** — `pages.cove` autoindex portal listing owners/sites, plus an autoindex JSON API.
- **nginx auto-reload** — `cove up` re-renders the nginx config and auto-reloads via a handler.

### Changed
- **IaC bias codified in AGENTS.md** — the `cove` wheel is the single self-contained source of truth for compose; reinstalling `cove` pulls updated compose; no runtime files outside the install.
- **Docker Compose `--profile` flag ordering** fixed — `--profile` must precede the subcommand (Docker Compose 5.4.0); `cove speedtest up` / `cove litellm up` corrected.
- **Vault double-slash URL** fixed — `vault_cache.py` and `vault_unseal.py` no longer build `https://vault.cove.local//v1/...` (Vault returned 404).

### Fixed
- Speedtest APP_KEY format (`base64:` prefix required by Laravel).
- Speedtest `.env` created with 0600 mode (was world-readable on fresh creation).

## [0.3.0] — 2026-07-29

### Added
- **Landing page** at `cove.local` — service portal with status indicators, links to all Cove services, config, and CA download. `cove`/`cove.local` are no longer Forgejo aliases.

### Changed
- **Primary domain migration to `*.cove.local`** — all default service URLs, CLI constants, templates, and documentation now prefer `*.cove.local` over `*.cove`. The `*.cove` domains remain as nginx aliases, cert SANs, and DNS entries for backward compatibility (Phase 4 will remove them).

## [0.2.0] — 2026-07-26

### Added
- **LiteLLM proxy service** — hardened LLM proxy with nginx route whitelisting, TLS via cove certs, optional compose profile (`litellm`), and CLI management (`cove litellm up|down|status|logs`). Accessible at `https://litellm.cove/`.
- **LiteLLM admin UI** — PostgreSQL-backed (`cove-litellm-db` container) with Prisma migrations, master-key auth, `UI_USERNAME`/`UI_PASSWORD` env vars.
- **Staging pipeline** — `scripts/staging/` (`setup.sh`, `deploy.sh`, `e2e.sh`, `teardown.sh`) for branch-to-staging deploy and E2E before merge. Tier-2 test marker (`staging`) separated from tier-1 (`e2e`).
- **Model management** — `STORE_MODEL_IN_DB` enabled for UI-based model config; Ollama Cloud providers (deepseek-v4-flash, deepseek-v4-pro, glm-5.1, glm-5.2, kimi-k2.6, kimi-k2.7-code).
- **MinIO root credential** seeded into `OP_REFS` and credential bootstrap.
- **ADR-015** (IaaS graduation test) and **ADR-016** (two-tier service adoption rubric).
- Vault CLI test coverage: 7 new tests for TLS verification and default-address behavior.

### Changed
- **Vault CLI default address** now `https://vault.cove/` (was `http://127.0.0.1:8200`, which was unreachable because the vault container's port 8200 is not published to the host). TLS verified against the cove root CA (`~/.config/cove/pki/rootCA.pem`); falls back to the system trust store if the CA file is missing.
- **LiteLLM nginx ingress** uses a variable + resolver for the upstream so an optional LiteLLM service doesn't break nginx startup.
- `PROXY_BASE_URL=https://litellm.cove` so login redirects use HTTPS.

### Fixed
- `cove creds vault-get` / `vault-put` no longer fail with `ConnectionRefusedError` — now routed through the nginx ingress at `https://vault.cove/`.
- Tailscale daemon-dead condition no longer fatal; content-hash version detection added.
- LiteLLM config mounted from cove data root (read-write, first-boot render, user-mutable).
- LiteLLM binds `0.0.0.0` inside the container; wrong-host test now expects `ConnectionError`.
- Ansible callback error suppressed; Colima/Forgejo readiness waits added.

### Known issues
- 9-10 LiteLLM tests in `tests/test_litellm.py` fail on `main` due to config drift between the compose/nginx template and the test-encoded posture (see `docs/tech-debt/litellm-test-drift.md`). Unrelated to the vault fix.

## [0.1.0] — 2026-05-07

Initial public release of the Cove CLI.

[0.5.1]: https://git.cove.local/cristos/cove/releases/tag/v0.5.1
[0.5.0]: https://git.cove.local/cristos/cove/releases/tag/v0.5.0
[0.4.1]: https://git.cove.local/cristos/cove/releases/tag/v0.4.1
[0.3.0]: https://git.cove.local/cristos/cove/releases/tag/v0.3.0
[0.2.0]: https://git.cove.local/cristos/cove/releases/tag/v0.2.0
[0.1.0]: https://git.cove.local/cristos/cove/releases/tag/v0.1.0
