# Plan: Forgejo 17 upgrade (rehearsal method)

Status: **method and rehearsal record, not an upgrade.** On 2026-11-10 the operator ruled `dec_3zkrzkwwdu50` (`stay-15-lts`): Cove keeps `forgejo_image_tag: "15.0.11"`, the LTS line supported to 2027-07-15. No pin change, no production compose change, no release accompanies this document.

## Support windows

| Line | Status on 2026-11-10 | Supported until |
| --- | --- | --- |
| 15.0.11 | LTS, the current pin | 2027-07-15 |
| 16.0.7 | non-LTS | ended 2026-10-29, do not land on |
| 17.0.1 | stable, released 2026-10-26 | 2027-01-28 |
| 18.0 | next LTS, first quarter 2027 | about 2028-04 |

The move has to be planned before 2027-07-15. If it happens after 17's window closes, the target is 18 LTS rather than 17. The brief that requested this document gave 17.0.1 support as 2028-01-28; `forgejo.org/releases` and the v17.0 announcement table both publish 2027-01-28 (three months plus two weeks for a non-LTS stable), so this table uses the published date. Recheck the releases page when planning, because the window moves with each patch.

## Rehearsal method

Never rehearse a major bump on the live stack. Run the candidate as the isolated staging project (`-p cove-staging`, nginx on `https://127.0.0.1:9443`, data under `~/Documents/cove-data-staging`) against a copy of the live data. The staging harness fixes this method depends on are described in the last section.

### 1. Snapshot the live database

Use SQLite's backup API on a read-only connection. It folds the WAL into one consistent file and writes nothing to the live database.

```shell
STAGE="$HOME/Documents/cove-data-staging"
mkdir -p "$STAGE/forgejo/gitea" "$STAGE/forgejo/git"
sqlite3 "file:$HOME/Documents/cove-data/forgejo/gitea/gitea.db?mode=ro" \
  ".backup '$STAGE/forgejo/gitea/gitea.db'"
sqlite3 "$STAGE/forgejo/gitea/gitea.db" "PRAGMA quick_check;"     # expect: ok
```

Copy the rest of the forge state except the database sidecars, then clone the repositories. `cp -cR` is an APFS clonefile, so the 6 GB tree costs no extra disk.

```shell
rsync -a --exclude 'gitea.db' --exclude 'gitea.db-wal' --exclude 'gitea.db-shm' \
  "$HOME/Documents/cove-data/forgejo/gitea/" "$STAGE/forgejo/gitea/"
cp -cR "$HOME/Documents/cove-data/forgejo/git/repositories" "$STAGE/forgejo/git/"
cp -cR "$HOME/Documents/cove-data/forgejo/git/lfs"          "$STAGE/forgejo/git/"
```

The copy contains password hashes. It stays inside the staging root and is never committed.

### 2. Bring the staging forge up on the candidate image

`deploy-isolated.sh` takes no image argument, and the compose files read `${FORGEJO_IMAGE:-…}`. The shell environment outranks `--env-file` for compose interpolation, so one run is enough:

```shell
FORGEJO_IMAGE=codeberg.org/forgejo/forgejo:<candidate> \
  scripts/staging/deploy-isolated.sh <branch>
```

The script renders the staging `.env`, seeds certs and ToolHive, and brings up the project. It prints `https://127.0.0.1:9443` on success.

### 3. Run the validation set

| # | Check | Pass condition |
| --- | --- | --- |
| 1 | `docker exec cove-staging-forgejo forgejo --version` | candidate version |
| 2 | `forgejo doctor check --all` | no problems |
| 3 | `select version from version;` on the staging DB | note the schema version before and after |
| 4 | Web login | session established, no 500 |
| 5 | HTTPS clone, then push a scratch branch | both succeed |
| 6 | Open a PR from the scratch branch | PR created |
| 7 | OAuth TTL | real authorization-code exchange returns `expires_in` equal to `ACCESS_TOKEN_EXPIRATION_TIME` |
| 8 | Runner | registers, declares, and runs one job for each of the three workflows |
| 9 | `provision_forgejo.yml --check` and `provision_pages.yml --check` | `changed=0` (live only; the plays hardcode the live container) |

Measure the OAuth TTL from a token exchange, not from `app.ini`. The file can hold a value the running instance no longer reads. The 2026-11-10 rehearsal found a stale key of exactly that shape in the other direction: only `[oauth2] ACCESS_TOKEN_EXPIRATION_TIME` exists in 16, and the exchange returned 2,592,000 seconds.

### 4. Rollback

Forgejo migrations are forward-only, and the database version stamp makes a downgrade binary refuse to start. Before the first boot of the candidate, rollback is a pin flip. After the first boot, rollback is a restore of the pre-upgrade snapshot (database plus repositories), and anything written since that boot is lost.

## What 16.0.7 measured on 2026-11-10

This is the template result the 17 move should be compared against. The live stack was never stopped, converged, or reconfigured.

- 16.0.7 booted the live data copy. `forgejo doctor check --all` passed 27 of 27 checks across 64 repositories.
- The database schema version stayed **305** before and after boot. No migration ran between 15.0.11 and 16.0.7 for this data set.
- Web login with the existing admin identity, HTTPS clone, HTTPS push, and PR creation all worked.
- The OAuth2 code exchange returned `expires_in: 2592000` (30 days), and `ACCESS_TOKEN_EXPIRATION_TIME = 2592000` survived in `app.ini`.
- The runner registered against the candidate and ran the repository's real workflows: `no-pii` green in 13 s and `secret-scan` green in 4 s, both on `gitea/runner-images:ubuntu-latest`. Job containers were created on `cove-staging_default`, not the live network.
- All three workflows parse: `no-pii`, `secret-scan`, and the scheduled `renovate` (which also ran on schedule during the rehearsal).
- Trusted proxy. The rehearsal predates #173. On that stack the live `app.ini` value (`*`) survived the upgrade, so client IPs did not regress. Since #173 the compose file declares the ingress address (`NGINX_IP`, default `172.28.0.10`) and sets `FORGEJO__security__REVERSE_PROXY_TRUSTED_PROXIES` to it, with the project network pinned to `172.28.0.0/24`. That is the better shape, and it makes the staging project's own subnet and trusted-proxy value a hard requirement (see below), not an optional nicety.
- The provisioning and pages plays were **not** rehearsed: they hardcode the live container name, API URL, `cove` CLI cache, and 1Password references. Check them with `--check` in the upgrade window.
- The Actions runner registration-token endpoint is `GET` on 16 (`POST` returns 405). `provision_forgejo.yml` already uses GET.

## Staging harness fixes this method relies on

The four gaps found by the 16 rehearsal, plus one introduced when #173 pinned the live subnets, are fixed in `scripts/staging/deploy-isolated.sh` and are version-independent:

- **Root URL.** `staging.env` now carries `FORGEJO_ROOT_URL=https://git.cove.local:<staging port>/`, plus `FORGEJO_DOMAIN` and `FORGEJO_SSH_DOMAIN`. Without them the forge applied the compose fallback `http://localhost:3000/`, and every absolute URL and redirect pointed at the wrong origin.
- **Runner socket gid.** The script resolves `FORGEJO_RUNNER_DOCKER_GID` from the environment, then the live `.env`, then a read-only socket probe, and writes it into `staging.env`. The compose default `991` does not match this machine's root-owned Colima socket and produced `permission denied` crash loops.
- **Runner network.** `compose/forgejo-runner/config.yml` hardcodes `container.network: cove_default`, the live network. The script renders a per-project copy with `cove-staging_default` into the staging root and mounts it over `/config.yml` through a data-root compose override.
- **ToolHive health gate.** The base stack (nginx, ADE, forgejo) is still required and still fails loud. ToolHive now gets a bounded wait (default 120 s) and an explicit warning instead of turning a healthy deploy into a 600 s timeout and exit 1. `STAGING_REQUIRE_MCP_HEALTH=1` restores the fatal gate for CI.
- **Network subnets.** The base compose pins the live ingress to `172.28.0.0/24` (nginx `172.28.0.10`) and the bifrost egress to `172.43.0.0/24`. A second project cannot hold the same subnet, and the nginx `ade.cove`/`bifrost.cove` ACLs only accept private ranges. The script's data-root override gives staging `172.29.0.0/24` (inside `172.16.0.0/12`) and `172.46.0.0/24` for egress, sets `NGINX_IP` and `FORGEJO_TRUSTED_PROXY` to `172.29.0.10`, and recreates a staging network left on an older dynamic subnet because Compose does not do that itself.

The harness still has no seeding hook: step 1 is manual. It is also why the staging root must never be reused for a second candidate without re-seeding, once a candidate has stamped the database.
