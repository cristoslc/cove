# Plan: Forgejo 16 upgrade (15.0.11 → 16.0.7) and staging rehearsal

Status: **plan + rehearsal, not an executed upgrade.** No live container was stopped, recreated, or reconfigured to produce this document. The pin in `compose/group_vars/all.yml` is deliberately unchanged on this branch; the change is specified below and applied by the upgrade PR once the operator rules.

Related decision: `dec_yxyfqoe7zbnl` — move Cove's authority forge to Forgejo 16.0.7, one major at a time, not 17. Work proceeds on that recommendation until the ruling arrives.

## Why this upgrade is not obviously right

Forgejo 16.0 is a non-LTS release. Its published support window ended **2026-10-29**, and 16.0.7 (released 2026-10-26) is the final 16.x patch. The pin Cove runs today, 15.0.11, is the LTS line supported until **2027-07-15**. Forgejo 17.0.1 is current.

Consequences:

- Landing on 16.0.7 puts Cove on an unsupported major on day one. From then on, security fixes arrive only by moving to 17.
- Staying on 15.0.11 keeps a supported LTS until mid-2027. There is no forced move today.
- The value of the 16 step is as a rehearsal for 17: it exercises one major of schema migrations and the config-shape changes at a point where the fallback (pin back to 15) still works.

That does not overturn the ruling. It does mean the 16 upgrade is a bridge with a follow-on 17 upgrade implied, and the operator should decide the 17 timing at the same time. If Cove will not move to 17 within a few weeks of landing on 16, the supported choice is to stay on 15.0.11 and rehearse 16 in staging only.

## Current state (measured 2026-11-10)

| Item | Value |
| --- | --- |
| Declared pin | `forgejo_image_tag: "15.0.11"` in `compose/group_vars/all.yml` |
| Compose fallback | `codeberg.org/forgejo/forgejo:15.0.11` in `compose/docker-compose.yml` |
| Running image | `codeberg.org/forgejo/forgejo:15.0.11`, container `cove-forgejo`, healthy |
| Database | SQLite, `~/Documents/cove-data/forgejo/gitea/gitea.db`, schema version 305, `PRAGMA quick_check` = `ok` |
| Data volume | 38,952,960 bytes DB; 6.3 GB `git/` (repositories + LFS); 722 MB `gitea/` |
| Rows | 4 users, 64 repositories, 6 access tokens, 510 Actions runs, 0 mirrors |
| Compose network | `cove_default`, subnet `192.168.147.0/24`, gateway `192.168.147.1`; forgejo `192.168.147.4`, nginx `192.168.147.12` |
| `app.ini` | `/data/gitea/conf/app.ini`, hand-shaped at first boot, 70 non-empty lines |

Relevant live `app.ini` lines (secrets redacted):

```ini
[security]
INSTALL_LOCK = true
REVERSE_PROXY_LIMIT = 1
REVERSE_PROXY_TRUSTED_PROXIES = *

[oauth2]
ACCESS_TOKEN_EXPIRATION_TIME = 2592000
```

## 1. Pre-flight: backup that is provably restorable

### What to back up

The forge's whole state lives under one host directory:

| Path | Why |
| --- | --- |
| `forgejo/gitea/gitea.db` (+ `-wal`, `-shm`) | users, repos, issues, PRs, tokens, Actions history. WAL mode, so the two sidecar files are part of the database. |
| `forgejo/git/repositories` | the bare repositories themselves |
| `forgejo/git/lfs` | LFS objects |
| `forgejo/gitea/conf/app.ini` | `SECRET_KEY`, `INTERNAL_TOKEN`, `LWT_JWT_SECRET`, OAuth settings, the trusted-proxy line |
| `forgejo/gitea/jwt`, `forgejo/gitea/ssh` | signing and host keys |
| `forgejo/gitea/attachments`, `avatars`, `packages` | user-visible payloads (not needed to boot, needed to look whole) |

Do **not** use `forgejo dump` as the restore path. The upstream upgrade guide states its SQL dump has long-standing bugs when re-injected, and SQLite needs no dump at all because the file is the database. Copy files.

### How to take it

The consistent way is a synchronized point-in-time copy. Either stop the forge for the copy window, or take a SQLite hot-backup snapshot while it runs. The hot backup is what the rehearsal used and it needs no downtime:

```shell
DEST=~/Documents/cove-data/backups/forgejo-15.0.11-$(date +%Y%m%d-%H%M%S)
mkdir -p "$DEST"
# SQLite backup API: opens the live DB read-only and writes a single consistent copy,
# folding the WAL into the destination. No write to the live database.
sqlite3 "file:$HOME/Documents/cove-data/forgejo/gitea/gitea.db?mode=ro" ".backup '$DEST/gitea.db'"
rsync -a "$HOME/Documents/cove-data/forgejo/git/repositories" "$DEST/repositories"
rsync -a "$HOME/Documents/cove-data/forgejo/git/lfs" "$DEST/lfs"
rsync -a "$HOME/Documents/cove-data/forgejo/gitea/conf" "$DEST/conf"
```

If the operator prefers a hard freeze, `docker stop cove-forgejo` first and copy `gitea.db` with its sidecars; a stopped SQLite database copies as a file. Restart with `docker start cove-forgejo`, not a converge.

### How to prove the backup is restorable before touching anything

Three checks, cheapest first. All three ran in the rehearsal.

1. **Integrity and shape of the copy.**
   ```shell
   sqlite3 "$DEST/gitea.db" "PRAGMA quick_check;"                  # expect: ok
   sqlite3 "$DEST/gitea.db" "select count(*) from user; select count(*) from repository;"
   ```
   Compare the counts with the live database. A mismatch means the copy is not a snapshot.

2. **Repositories are readable, not just present.**
   ```shell
   for r in "$DEST"/repositories/*/*.git; do git -C "$r" rev-parse --is-bare-repository >/dev/null || echo "BROKEN $r"; done
   ```
   `git fsck` on 64 repositories takes minutes; sample the largest two plus `cove`.

3. **Boot the copy.** Mount the copy into a throwaway container of the *old* image and check that it serves and authenticates:
   ```shell
   docker run --rm -d --name forgejo-restore-check \
     -v "$DEST/gitea:/data/gitea" -v "$DEST/repositories:/data/git/repositories" \
     -p 127.0.0.1:3999:3000 codeberg.org/forgejo/forgejo:15.0.11
   curl -sf http://127.0.0.1:3999/api/healthz
   ```
   A restore that only reaches `/api/healthz` is not proven: healthz answered 200 during the 2026-11-06 wedge while the API was dead. Log in through the web UI, or call an authenticated API endpoint, before calling the backup good.

Only after step 3 passes does the upgrade window start.

### Queue flush

Upstream asks for `forgejo manager flush-queues` before a major upgrade, because queues carry serialized payloads that are not guaranteed to survive a version change:

```shell
docker exec --user git cove-forgejo forgejo --config /data/gitea/conf/app.ini manager flush-queues
```

If it times out, rerun with `--timeout 10m`. This is a live-stack command for the upgrade window, not for the rehearsal.

## 2. Config deltas from 16.0

### 2.1 `REVERSE_PROXY_TRUSTED_PROXIES = *` is gone from the container default

Upstream removed the `*` line from the image's `/etc/templates/app.ini` (breaking security fix, forgejo#12782, CVE-2026-20896). On a fresh install the effective default becomes `127.0.0.0/8,::1/128`.

Cove's nginx is **not** on loopback. It reaches forgejo from the compose bridge (`192.168.147.12` → `192.168.147.4` today), so a forgejo running with the new default ignores `X-Forwarded-For` and records every request as coming from nginx. `X-Real-IP` is sent too, but `REVERSE_PROXY_LIMIT = 1` makes Forgejo read the forwarded chain, not the socket peer.

Two different situations, and the distinction matters:

- **Existing install (this machine):** `/data/gitea/conf/app.ini` already contains `REVERSE_PROXY_TRUSTED_PROXIES = *`, written at first boot from the 15 template. The entrypoint does not rewrite or prune it on upgrade, so client IPs stay correct and nothing breaks. The cost is that the CVE-2026-20896 hardening does not actually apply here: Cove still trusts any peer that can reach port 3000.
- **Fresh install (new machine from the wheel after the pin moves):** app.ini is generated from the 16 template, has no trusted-proxy line, and the effective default is loopback-only. Without an override, every nginx-proxied request logs the proxy IP.

CVE-2026-20896 needs `[service].ENABLE_REVERSE_PROXY_AUTHENTICATION = true` to be exploitable (header `X-WebAuth-User`). Cove never sets it, so the impersonation path is closed by configuration, not by the trusted-proxy value. That is why leaving `*` in place is not an emergency, and why narrowing it is still the right follow-up.

Recommended change, applied with the pin bump:

```yaml
FORGEJO__security__REVERSE_PROXY_TRUSTED_PROXIES: ${FORGEJO_REVERSE_PROXY_TRUSTED_PROXIES:-10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8,::1/128}
```

Why a private-range list rather than one CIDR: the compose network subnet here is `192.168.147.0/24`, a value Docker allocates and can change when the network is recreated. Pinning that exact `/24` in a static config makes client-IP logging silently regress the next time the network lands on a different subnet. The private ranges cover Colima's allocation and the usual `172.x` bridge, and they are safe here because port 3000 is not published (only SSH 2222 leaves the container).

On an existing install this env value does **not** rewrite app.ini; `REVERSE_PROXY_TRUSTED_PROXIES = *` wins until the line is removed by hand or by a bringup task. Treat the app.ini line as an IaC gap: the value belongs in `compose/docker-compose.yml` plus a bringup step that removes the stale key. The rehearsal measured that the stale `*` is harmless on 16, so this can ship after the pin bump rather than with it.

### 2.2 Centralized git hooks

Upstream stopped writing per-repository hooks and hook samples (`forgejo#12335`, `forgejo#10397`); hooks now live in one central directory. Forgejo's own hooks keep working, and custom server-side hooks stay where they are. The cleanup is optional and only saves space (about 20 KiB per repo).

On Cove, `$REPO_PATH` is the host directory `~/Documents/cove-data/forgejo/git/repositories`. Safety check first — if this prints nothing, there are no custom hooks:

```shell
find "$REPO_PATH" -maxdepth 5 -wholename "*/hooks/*" -type f -size +0 \
  | grep -v '\.sample$' \
  | xargs -d '\n' grep -L "AUTO GENERATED BY GITEA"
```

Then remove only generated hooks and samples:

```shell
find "$REPO_PATH" -maxdepth 5 -wholename "*/hooks/*" -type f \
  | xargs -d '\n' grep -l "AUTO GENERATED BY GITEA" \
  | xargs -d '\n' rm
find "$REPO_PATH" -maxdepth 4 -name "*.sample" -type f -delete
```

Do not run the upstream `-mindepth 3 -maxdepth 3 -name hooks -exec rm -rf` form until the custom-hook probe is empty on this instance. It deletes custom hooks too.

### 2.3 `description` files

Forgejo no longer creates them. They are unused by Forgejo and safe to delete:

```shell
find "$REPO_PATH" -mindepth 3 -maxdepth 3 -name description -type f -delete
```

### 2.4 `app.ini` key renames

- `ACCESS_TOKEN_EXPIRATION_IN` is gone. The v16 configuration cheat sheet lists only `[oauth2] ACCESS_TOKEN_EXPIRATION_TIME` (seconds, default 3600). Cove's live app.ini already uses the surviving key with `2592000` (30 days), so the 30-day TTL is config-correct on 16. Confirm after boot that a newly minted token still reports a 30-day expiry (see the validation checklist).
- JWT signing configuration was unified into `[pfx]SIGNING_ALGORITHM`, `[pfx]SECRET`, `[pfx]SECRET_URI`, `[pfx]SIGNING_PRIVATE_KEY_FILE`. Upstream explicitly preserves the existing behavior for `[oauth2]` (prefix `JWT_`), `[actions]` (prefix `ID_TOKEN_`), and `[server]` (prefix `LFS_JWT_`). Cove's `[oauth2] JWT_SECRET` and `[server] LFS_JWT_SECRET` are therefore read unchanged; no rename needed.
- No other key in Cove's app.ini appears in the 16.0 release notes' breaking list.

### 2.5 Mirror SSRF hardening

Git mirror HTTP operations no longer follow redirects (breaking security fix, forgejo#13129). A mirror of a renamed or transferred repository now fails instead of following the redirect. Cove has **0 rows in the `mirror` table**, so this is a no-op here. Recheck before upgrading on a machine that has mirrors.

### 2.6 Two API/workflow behavior changes

- Pull-request API responses return the API URL in `url` instead of the web URL (breaking bug fix, forgejo#12643). Anything that consumed `url` as a browser link needs the `html_url` field.
- Scheduled workflows now use the correct `${{ forgejo.ref }}` (breaking bug fix, forgejo#13081). Cron-triggered jobs that pinned a ref may behave differently.

Cove's three workflows (`no-pii`, `secret-scan`, `renovate`) are push/PR triggered except `renovate`, which is scheduled. Renovate does not read `forgejo.ref`, so no change is expected; the checklist verifies by running them.

### 2.7 Removed feature

EXIF stripping on avatar upload is removed for license reasons. Uploaded avatars keep their metadata; there is no setting to restore the old behavior and no action for Cove.

### 2.8 The Actions registration-token endpoint is GET-only

`POST /api/v1/admin/actions/runners/registration-token` answers `405` on 16.0.7 with `Allow: GET`; `GET` returns the token. `provision_forgejo.yml` already omits `method:` and therefore GETs, so it needs no change. Any script or runbook that POSTs to that path does.

## 3. The pin change

Two lines, and they must agree or a fresh machine and an existing machine diverge:

```diff
--- a/compose/group_vars/all.yml
+++ b/compose/group_vars/all.yml
@@
-forgejo_image_tag: "15.0.11"
+forgejo_image_tag: "16.0.7"
 forgejo_image_digest: ""
 forgejo_image: "codeberg.org/forgejo/forgejo:{{ forgejo_image_tag }}"
```

```diff
--- a/compose/docker-compose.yml
+++ b/compose/docker-compose.yml
@@
-    image: ${FORGEJO_IMAGE:-codeberg.org/forgejo/forgejo:15.0.11}
+    image: ${FORGEJO_IMAGE:-codeberg.org/forgejo/forgejo:16.0.7}
```

`forgejo_image_digest` stays empty, as it is today. Filling it is the separate digest-pin work in `docs/musings/digest-pinning-plan.md`; the 16.0.7 index digest observed on this machine is `sha256:c0fddfc04075e4198cc8e075fe6a1182984a5a7d5951c3a3c39b7fba2f10fbce`.

Delivery to an existing host is the wheel re-sync path, not a hand edit of `~/.config/cove/compose/.env`: `FORGEJO_IMAGE` is in the authoritative set that `compose/scripts/sync_env.py` rewrites on every converge (see `docs/guides/stack-update-guide.md`). After merge and promote, the next `cove up` re-extracts compose resources and recreates only the forgejo container. That recreate is the upgrade boot and starts the schema migrations.

## 4. Validation checklist

Run against staging first, then against live during the upgrade window. Every item is pass/fail; "looks fine" is not a result.

| # | Check | Command / action | Pass condition |
| --- | --- | --- | --- |
| 1 | Process is 16 | `docker exec cove-forgejo forgejo --version` | reports `16.0.7` |
| 2 | Health endpoint | `curl -sf -H 'Host: git.cove' https://127.0.0.1/api/healthz` | 200 |
| 3 | Doctor | `docker exec --user git cove-forgejo forgejo doctor check --all` | no problems reported |
| 4 | Web login | browser to `https://git.cove.local/`, admin login | dashboard renders, no 500 |
| 5 | HTTPS clone | `git clone https://git.cove.local/<owner>/cove.git /tmp/clone-check` | clone succeeds |
| 6 | HTTPS push | commit to a scratch branch in the clone and push | push accepted, branch visible in UI |
| 7 | OAuth TTL still 30 days | mint a token, read its expiry over the API, and compare `app.ini` | expiry ≈ now + 2592000 s; `ACCESS_TOKEN_EXPIRATION_TIME = 2592000` still present |
| 8 | Runner registered | Forgejo → Site administration → Actions → Runners | `cove-forgejo-runner` online, labels intact |
| 9 | Runner executes a job | trigger a workflow on a scratch branch | job picked up and finishes green |
| 10 | `no-pii` parses | open the workflow run list for a PR/push to main | workflow appears, no parse error |
| 11 | `secret-scan` parses | same | workflow appears, no parse error |
| 12 | `renovate` parses | Actions → scheduled workflow list, or run it manually | workflow listed, no parse error |
| 13 | Pages provisioning idempotent | `ansible-playbook -i inventory.yml provision_pages.yml --check` | `changed=0` |
| 14 | Forgejo provisioning idempotent | `ansible-playbook -i inventory.yml provision_forgejo.yml --check` | `changed=0`, and the preview names no unexpected token revocation |
| 15 | Client IP still real | request through nginx, then read the forgejo access log or `X-Forwarded-For` handling | client IP, not the nginx container IP |
| 16 | Token mint + immediate use | mint a token with `docker exec ... admin user generate-access-token --raw`, then `GET /api/v1/user` with it in the same run | 200, not `access token does not exist` (see 7.3) |

`forgejo doctor check --all` is the cheapest early warning: it catches a database migration that half-applied before a user sees it.

## 5. Rollback

Forgejo migrations are forward-only. The version stamp lives in the database, and a 15 binary refuses to start against a database stamped by 16 — this is upstream's anti-downgrade guard, not a recoverable state. So:

- **Before the first boot of 16**, rollback is a pin flip: restore `15.0.11` in both files, rebuild the wheel, reinstall, converge. Nothing in the data changed yet.
- **After the first boot of 16**, rollback is a database restore: stop forgejo, put back the pre-upgrade `gitea.db` (and `repositories`/`lfs` if the forge wrote anything), then pin back to 15.0.11 and start. Any commit, issue, or PR created after the 16 boot is lost unless it was exported. That is why the backup is taken in the same window as the upgrade and why the validation checklist runs immediately after boot, not "later".

Exact rollback sequence:

```shell
cove forgejo down                       # or: docker stop cove-forgejo
rsync -a --delete "$BACKUP/repositories/" "$HOME/Documents/cove-data/forgejo/git/repositories/"
rsync -a --delete "$BACKUP/lfs/"          "$HOME/Documents/cove-data/forgejo/git/lfs/"
cp "$BACKUP/gitea.db" "$HOME/Documents/cove-data/forgejo/gitea/gitea.db"
rm -f "$HOME/Documents/cove-data/forgejo/gitea/gitea.db-wal" \
      "$HOME/Documents/cove-data/forgejo/gitea/gitea.db-shm"
# restore the 15.0.11 pin in both files, rebuild the wheel, reinstall, then:
cove up
```

Do not run `cove down` casually: it stops the whole stack. The forgejo-only stop above is the narrow action.

## 6. Staging rehearsal

The rehearsal runs the isolated staging project (`-p cove-staging`, nginx on `https://127.0.0.1:9443`) from `scripts/staging/deploy-isolated.sh`. The live stack is not stopped, converged, re-rendered, or reconfigured.

### 6.1 Seeding the staging root with live data

The harness copies certs and DNS config out of the live root but seeds no service data. Seeding is therefore a manual step before the first deploy, into `~/Documents/cove-data-staging/forgejo/`:

```shell
STAGE="$HOME/Documents/cove-data-staging"
mkdir -p "$STAGE/forgejo/gitea" "$STAGE/forgejo/git"
sqlite3 "file:$HOME/Documents/cove-data/forgejo/gitea/gitea.db?mode=ro" ".backup '$STAGE/forgejo/gitea/gitea.db'"
rsync -a --exclude 'gitea.db' --exclude 'gitea.db-wal' --exclude 'gitea.db-shm' \
  "$HOME/Documents/cove-data/forgejo/gitea/" "$STAGE/forgejo/gitea/"
cp -cR "$HOME/Documents/cove-data/forgejo/git/repositories" "$STAGE/forgejo/git/"
cp -cR "$HOME/Documents/cove-data/forgejo/git/lfs"          "$STAGE/forgejo/git/"
```

`cp -cR` is an APFS clone: the 6.3 GB copy is cost-free on disk because the blocks are shared read-only.

The harness does not delete the staging root, so a seeded root survives redeploys. That is both the mechanism and the hazard: once upgraded by 16, the staging database is stamped and cannot be booted by 15 again without re-seeding from the live copy.

### 6.2 Running the rehearsal on 16.0.7 without editing the harness

The compose files read `${FORGEJO_IMAGE:-…}`, and the shell environment outranks `--env-file` for compose interpolation, so the image can be overridden for one run:

```shell
FORGEJO_IMAGE=codeberg.org/forgejo/forgejo:16.0.7 \
  scripts/staging/deploy-isolated.sh <branch>
```

This is a rehearsal-only override. It changes no file and therefore cannot leak into a converge.

### 6.3 What the harness cannot do without a change

The harness accepted the live-data copy, but not unchanged. Five gaps surfaced, all on the staging side:

1. **No data-seeding hook.** The copy is manual (6.1). It works because the script never deletes `$COVE_STAGING_DATA_ROOT`, but nothing records that the root is now a stamped copy of a live database. A `--seed-from-live` flag that copies the database and repositories when the staging root is empty would make the rehearsal repeatable instead of manual.
2. **The forge's `ROOT_URL` is wrong.** `staging.env` carries no `FORGEJO_ROOT_URL`, so the compose fallback `http://localhost:3000/` is applied through `environment-to-ini` and overwrites the copied `app.ini`. Every absolute URL, redirect, and clone URL points at `localhost:3000`, and the login page shows Forgejo's "configured to be served on a different URL" warning. Smallest fix: add `FORGEJO_ROOT_URL=https://git.cove.local:9443/`, `FORGEJO_DOMAIN=git.cove.local`, and `FORGEJO_SSH_DOMAIN=git.cove.local` to the `staging.env` heredoc.
3. **The runner cannot reach the Docker socket.** `staging.env` carries no `FORGEJO_RUNNER_DOCKER_GID`, so the compose default `991` applies, while this machine's live `.env` uses `0` (the Colima socket is `root:root` 660). The runner crash-loops with `permission denied ... /var/run/docker.sock`. Smallest fix: copy the live `.env` value into `staging.env`.
4. **The runner's job containers join the live network.** `compose/forgejo-runner/config.yml` hardcodes `container.network: "cove_default"`. A staging runner started from that file spawns job containers on the **live** compose network. Smallest fix: render the runner config per project (substitute `cove-staging_default`) into the staging data root and mount it in `deploy-isolated.sh`.
5. **The health gate is blocked by ToolHive.** `deploy-isolated.sh` adds `--profile mcp` whenever the branch declares it, and then requires `cove-staging-toolhive` to be healthy. On this machine ToolHive crash-loops with `no container runtime available`, so the script exits 1 even though nginx, ade, and forgejo are healthy. Smallest fix: make the ToolHive health requirement conditional on the toolhive container having started successfully, or allow `STAGING_SKIP_MCP_HEALTH=1`.

None of these were worked around by touching live. The rehearsal used shell-environment overrides and one compose override file under `$TMPDIR`:

- `FORGEJO_IMAGE`, `FORGEJO_ROOT_URL`, `FORGEJO_DOMAIN`, `FORGEJO_SSH_DOMAIN` exported into the deploy script's environment (compose interpolation takes the shell over the `--env-file`).
- `FORGEJO_RUNNER_DOCKER_GID=0` for the runner service.
- `$TMPDIR/runner-override.yml` remounting `/config.yml` from a copy with the staging network name.

## 7. Findings

### 7.1 The upgrade itself is a clean binary swap for this data set

- `forgejo --version` reports `16.0.7+gitea-1.22.0` on the copy of the live database.
- `forgejo doctor check --all` ran 27 checks and reported `OK` on every one, including the 64-repository checks (hook files, commit-graphs, git-daemon-export-ok).
- The database schema version stayed **305** before and after boot. No migration ran between 15.0.11 and 16.0.7 for this database. The rollback rule still stands (a future patch can migrate, and the guard is about migrations, not about this build), but the practical risk of a post-boot rollback on this exact pair is lower than the general rule implies.
- The copied `app.ini` was not rewritten in a harmful way: `REVERSE_PROXY_TRUSTED_PROXIES = *` and `ACCESS_TOKEN_EXPIRATION_TIME = 2592000` both survived. The environment-to-ini pass did rewrite `ROOT_URL`/`DOMAIN` from the compose env (see 6.3 item 2), which is a staging-env gap, not an upgrade effect.

### 7.2 `REVERSE_PROXY_TRUSTED_PROXIES` behaves exactly as predicted, with one correction

The brief's premise ("Cove sets no override, so nginx-proxied requests would see the proxy as the client") is true for a **fresh** install and false for **this** install. The live `app.ini` already writes `REVERSE_PROXY_TRUSTED_PROXIES = *`, and the 16 entrypoint preserved it. Client IPs therefore stay correct on upgrade. The real consequence is the reverse: the CVE-2026-20896 hardening does not apply to Cove until that line is replaced. Since `ENABLE_REVERSE_PROXY_AUTHENTICATION` is unset (false), the impersonation path stays closed; narrowing the list is a follow-up, not an upgrade blocker. The staging run confirmed the line survives and that the app serves normally with it.

### 7.3 Authentication and tokens

- Web login works on 16.0.7 with the live admin identity and the pre-upgrade password (the copied user table authenticated unchanged).
- OAuth2 access tokens still expire in **2592000 seconds** (30 days): a full authorization-code exchange through the staging instance returned `expires_in: 2592000`. The TTL is effective, not just present in the file.
- Personal access tokens minted by the `forgejo admin user generate-access-token` CLI path were rejected with `access token does not exist` for several minutes after the staging container was recreated mid-rehearsal, and were accepted immediately after a `docker restart` of the forge. The token hash in the database matched the printed token exactly (PBKDF2-SHA256, 10,000 iterations, 50-byte output), so the token was valid; the running server was not seeing it. A token minted after the restart was recognised at once. This needs a check on live, because `provision_forgejo.yml` mints a token and calls the API in the same converge: add "mint a token via the CLI and call `/api/v1/user` with it in the same run" to the upgrade-window checklist. If it reproduces on live, the converge fails at the first API call and the safe response is to restart forgejo and rerun the play, not to mint more tokens.
- The Actions **runner registration token endpoint changed method**: `POST /api/v1/admin/actions/runners/registration-token` now answers `405` with `Allow: GET`, and `GET` returns the token. `provision_forgejo.yml` already uses the default `GET`, so it needs no change. Any script or doc that POSTs does.

### 7.4 Actions

- The staging runner registered against 16.0.7 and was declared online with the same two labels the live runner uses.
- A test branch opened as PR #170 in the staging copy triggered both pull-request workflows. `no-pii` finished green in 13 s and `secret-scan` green in 4 s, both on `gitea/runner-images:ubuntu-latest`. Both workflows parse and execute on 16.
- `renovate` is listed on the repository's Actions page under 16, so its YAML parses. It was not dispatched: it is a scheduled job that needs `RENOVATE_TOKEN` and would run a dry-run plan against the staging instance, neither of which adds evidence for a pin bump.
- The runner gap in 6.3 item 4 is a real isolation defect in the harness: without the per-project config override, that successful job would have run its container on the live `cove_default` network.

### 7.5 Provisioning and pages plays were not rehearsed

`provision_forgejo.yml` and `provision_pages.yml` cannot run against the staging project as-is: both hardcode the live container name (`cove-forgejo`), the live API URL, the `cove` CLI/Vault cache, and 1Password references. Running them would be a live write. They also cannot be pointed at staging without a variable for the container name and API base. So idempotency on 16 is **unverified** by this rehearsal and must be checked in the upgrade window with `--check` against live (check mode performs no writes; the play's read probes are explicitly `check_mode: false`).

Related blocker observed during this work: the 1Password CLI on this machine currently reports **no accounts configured**, so `cove creds` cache misses fail. A converge that needs a 1Password read will fail until the CLI is re-linked to the desktop app.

### 7.6 Credential drift found during validation

The operator's 1Password item `op://Cristos-Personal/Forgejo <hostname> Admin/password` does not authenticate on the live forge. The password cached in Vault under Cove's configured reference, `op://Private/Forgejo <hostname> Admin/password` (lowercase machine name, as `ansible_hostname` renders it), does (verified with a full web login, value never printed). The live password hash is unchanged since before this rehearsal. The likely cause is that the item moved vaults (or its password rotated) while Cove's `op_vault` still points at `Private`, and the cache-first provisioning path never noticed. This matters for the upgrade window: confirm the working credential before starting, or the login checklist item fails for reasons unrelated to Forgejo.

### 7.7 Support status is the decision the plan cannot make

16.0.7 is the last 16.x release and 16.x reached end of life on 2026-10-29. The upgrade succeeds technically, but it lands on an unsupported major while the current LTS remains supported to 2027-07-15. If the 17 move is not scheduled, the supported configuration is to stay on 15.0.11 and keep this plan as the rehearsal record. This does not change the recommendation in `dec_yxyfqoe7zbnl` (one major at a time), but it does mean the 16 step should be paired with a 17 plan rather than treated as a destination.

## 8. Commands used

Rehearsal, in order. All paths are on the workstation; no command below targets the live stack except reads.

```shell
# 1. Verify the live database reads clean and note the schema version
sqlite3 "file:$HOME/Documents/cove-data/forgejo/gitea/gitea.db?mode=ro" "PRAGMA quick_check;"
sqlite3 "file:$HOME/Documents/cove-data/forgejo/gitea/gitea.db?mode=ro" "select version from version;"

# 2. Seed the staging root from the live copy (DB via SQLite backup API, repos via APFS clone)
STAGE="$HOME/Documents/cove-data-staging"
mkdir -p "$STAGE/forgejo/gitea" "$STAGE/forgejo/git"
sqlite3 "file:$HOME/Documents/cove-data/forgejo/gitea/gitea.db?mode=ro" ".backup '$STAGE/forgejo/gitea/gitea.db'"
rsync -a --exclude 'gitea.db' --exclude 'gitea.db-wal' --exclude 'gitea.db-shm' \
  "$HOME/Documents/cove-data/forgejo/gitea/" "$STAGE/forgejo/gitea/"
cp -cR "$HOME/Documents/cove-data/forgejo/git/repositories" "$STAGE/forgejo/git/"
cp -cR "$HOME/Documents/cove-data/forgejo/git/lfs"          "$STAGE/forgejo/git/"

# 3. Pull the target image (read-only w.r.t. the stack)
docker pull codeberg.org/forgejo/forgejo:16.0.7

# 4. Deploy the isolated staging project on 16.0.7 with the staging-consistent URL env
FORGEJO_IMAGE=codeberg.org/forgejo/forgejo:16.0.7 \
FORGEJO_ROOT_URL=https://git.cove.local:9443/ \
FORGEJO_DOMAIN=git.cove.local \
FORGEJO_SSH_DOMAIN=git.cove.local \
STAGING_HEALTH_TIMEOUT=90 \
  scripts/staging/deploy-isolated.sh bb/forgejo-16-upgrade-plan-and-staging-rehearsal-thr_i84cgxx2tw
# exits 1 only because cove-staging-toolhive crash-loops (see 6.3 item 5)

# 5. Verify the upgrade and the data copy
docker exec cove-staging-forgejo forgejo --version
docker exec --user git cove-staging-forgejo forgejo --config /data/gitea/conf/app.ini doctor check --all
sqlite3 "$STAGE/forgejo/gitea/gitea.db" "select version from version;"
docker exec cove-staging-forgejo sh -c 'grep -n "REVERSE_PROXY_TRUSTED_PROXIES\|ACCESS_TOKEN_EXPIRATION" /data/gitea/conf/app.ini'

# 6. Web login (session), then API access with a CLI-minted token
#    (password and token kept in 0600 files under $TMPDIR, never printed)
curl -sk -c "$JAR" https://git.cove.local:9443/user/login -o /dev/null
curl -sk -b "$JAR" -c "$JAR" --data-urlencode "user_name=cristos" --data-urlencode "password=$PW" \
  https://git.cove.local:9443/user/login -w '%{http_code}\n'
curl -sk -H "Authorization: token $TOKEN" https://git.cove.local:9443/api/v1/user

# 7. OAuth2 TTL: create an app, complete the authorization-code flow, read expires_in
#    (scripted with Python; the token exchange returned expires_in=2592000)
curl -sk -X POST -H "Authorization: token $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"rehearsal-ttl","redirect_uris":["https://git.cove.local:9443/"],"confidential_client":true}' \
  https://git.cove.local:9443/api/v1/user/applications/oauth2

# 8. Runner: fetch the registration token (GET, not POST on 16), register, start with the
#    staging-network config override and the live socket gid
curl -sk -H "Authorization: token $TOKEN" \
  https://git.cove.local:9443/api/v1/admin/actions/runners/registration-token
docker run --rm --network cove-staging_default -v "$STAGE/forgejo-runner:/data" \
  data.forgejo.org/forgejo/runner:11 /bin/forgejo-runner register --no-interactive \
  --instance http://forgejo:3000/ --token "$REG" --name cove-staging-rehearsal \
  --labels "ubuntu-latest:docker://gitea/runner-images:ubuntu-latest,docker:docker://gitea/runner-images:ubuntu-latest"
FORGEJO_RUNNER_DOCKER_GID=0 docker compose -p cove-staging --env-file "$STAGE/staging.env" \
  --project-directory compose -f compose/docker-compose.yml -f compose/docker-compose.staging.yml \
  -f "$TMPDIR/runner-override.yml" --profile runner up -d forgejo-runner

# 9. Clone, push, open a PR, and watch the workflows run
git -c credential.helper="store --file=$CRED" -c http.sslVerify=false clone --depth 1 \
  --single-branch https://git.cove.local:9443/cristos/cove.git "$TMPDIR/rehearsal-clone"
git -c credential.helper="store --file=$CRED" -c http.sslVerify=false push -u origin rehearsal/forgejo-16-smoke
curl -sk -X POST -H "Authorization: token $TOKEN" -H "Content-Type: application/json" \
  -d '{"head":"rehearsal/forgejo-16-smoke","base":"main","title":"Rehearsal: Forgejo 16 smoke (do not merge)"}' \
  https://git.cove.local:9443/api/v1/repos/cristos/cove/pulls
curl -sk -H "Authorization: token $TOKEN" \
  https://git.cove.local:9443/api/v1/repos/cristos/cove/commits/<sha>/status
docker logs --tail 20 cove-staging-forgejo-runner
```

`-c http.sslVerify=false` is a workstation artifact: the staging nginx serves the live mkcert pair, and this git install's CA bundle does not trust the local root. The browser and curl accept it. No production step should disable TLS verification.

