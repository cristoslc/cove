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
     profile-gated services (speedtest, litellm, headroom) are never brought
     up by `cove up` — even if the operator wants them on. There's no
     detection of "these optional services are already running, fold them in."
- **Impact:** Operator must remember the separate `cove speedtest up` /
  `cove litellm up` commands; `cove status` gives no guidance; `cove up`
  silently skips optional services. We hit this live: after `cove up`, the
  speedtest container wasn't recreated with the timezone fix because it's
  profile-gated.
- **Fix approach:**
  1. **status:** for each `OPTIONAL_SERVICES` entry, if the container is not
     running, emit a distinct state (e.g. `ok=False` with a hint like
     `Run \`cove speedtest up\``) so the operator sees what's off and how to
     start it. Map container → launch command.
  2. **up:** detect which optional services are already running (or desired via
     config — see `docs/musings/cove-config-command.md` auto-start) and pass
     the union of their profiles to the compose bring-up (e.g.
     `COMPOSE_PROFILES=speedtest,litellm docker compose up -d`), so `cove up`
     reconciles them instead of skipping them.
- **Risk:** Not fixed inline because it spans status + up + bringup and
  interacts with the `cove config` auto-start musing (which proposes a
  preference for which optional services start by default). A naive "fold in
  all running profiles" could surprise the operator by starting services they
  deliberately stopped. Needs a decision on the desired default (all running?
  config-driven?).
