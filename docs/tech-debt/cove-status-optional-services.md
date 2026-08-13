# `cove status` doesn't surface optional services; `cove up` ignores running ones

- **Area:** `cli/cove/status.py`, `cli/cove/cli.py` (`up`), `compose/bringup.yml`
- **Severity:** minor
- **Discovered:** 2026-08-13 during the speedtest heal session
- **Root cause:** Two gaps in how optional (profile-gated) services are handled:
  1. **`cove status` hides them.** `_check_containers()` in `status.py:80-94`
     marks every `OPTIONAL_SERVICES` entry as `ok=True` regardless of whether
     it's running — a stopped optional service shows as "not running
     (optional)" with a ✓ and **no launch hint**. The operator can't tell
     from `cove status` what's off or how to start it.
  2. **`cove up` ignores already-running optional services.** `bringup.yml`
     runs `docker compose up -d` with no `--profile`/`COMPOSE_PROFILES`, so
     profile-gated services (speedtest, litellm, headroom) are never
     reconciled by `cove up`. If one is running, `cove up` leaves it stale
     (won't pick up compose changes like new env vars). We hit this live:
     after `cove up`, the speedtest container wasn't recreated with the
     timezone fix because it's profile-gated.
- **Impact:** Operator must remember separate `cove speedtest up` /
  `cove litellm up` commands to reconcile; `cove status` gives no guidance;
  `cove up` silently leaves running optional services stale.
- **Fix approach:** The model is simple:
  - **Optional + not running → leave alone.** `cove up` must not start
    profile-gated services the operator didn't start. (The prior model was
    dumb — it worried about "surprising the operator"; there's no surprise
    if you only reconcile what's already running.)
  - **Optional + running → reconcile.** `cove up` should detect which
    optional services are already running and pass their profiles to the
    compose bring-up (`COMPOSE_PROFILES=<running> docker compose up -d`)
    so they get recreated with current config.
  - **status:** for each `OPTIONAL_SERVICES` entry not running, emit a
    distinct state with a launch hint (`Run \`cove speedtest up\``) instead
    of a green ✓.
- **Risk:** Low — the rule is "reconcile what's running, leave the rest."
  No config/preference system needed for this; the `cove-config-command`
  auto-start musing is a separate concern (whether to *start* optionals by
  default, not whether to *reconcile* them once running).