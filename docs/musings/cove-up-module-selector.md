---
title: "cove up module selector"
created: 2026-08-22
authored-by: deepseek-v4-flash:cloud
status: Draft
---

# `cove up` presents a checkbox list of cove modules to start/restart

## Motivation (from a real incident)

Two cove services came back unhealthy after a Docker daemon restart (~3h uptime, all
containers restarted within the same second — not a `cove up`):

- **Vault** — resealed on restart (Shamir, no auto-unseal). A `cove up` would have
  re-unsealed it via `bootstrap_vault.yml` keystore keys, but nothing ran.
- **Speedtest Tracker** — halted because `SPEEDTEST_APP_KEY` is empty in the deployed
  compose `.env`. `bringup.yml` renders that `.env` **only on first boot**
  (`when: not (compose_dir ~ "/.env") is exists`), so the empty value persists.
  `cove up`'s credential path (`cove creds batch-pull`) writes to the local cache but
  never injects the key into the compose `.env`; only `cove speedtest up` does that.

So a plain `cove up` restored the core platform but silently left optionals (and an
unsealed Vault state) as they were. The operator had to know to run `cove speedtest up`
separately.

## The idea

`cove up` should present an **interactive checkbox list** of cove modules to start /
restart, including optional modules, then act only on the selected ones.

Something like:

```
$ cove up
Which cove modules should be running?

  [x] forgejo      (core)    running, healthy
  [x] nginx        (core)    running, healthy
  [x] vault        (core)    running, SEALED   ← up would unseal
  [x] dnsmasq      (core)    running, healthy
  [x] dnsproxy     (core)    running, healthy
  [ ] litellm      (optional)  stopped        ← up would start + provision
  [ ] speedtest    (optional)  running, unhealthy (missing APP_KEY)
  [ ] ntfy         (optional)  not installed

  (enter) accept   (space) toggle   (a) all   (n) none   (q) quit
```

- **Core modules** pre-checked and non-deselectable (or show as informational) — you
  can't `cove up` without them.
- **Optional modules** reflect their live state: running ones pre-checked so they get
  reconciled with current config; stopped ones unchecked so a `cove up` doesn't
  surprise-start them — matching today's "reconcile-running, leave-stopped" model
  (`_detect_running_optional_profiles` + `cove_profiles`).
- Healthy-but-anomalous states (Vault sealed, speedtest missing APP_KEY) surface as a
  hint on the row, so the operator sees *why* a module needs the restart.
- `cove up --all` / `--core-only` / `--yes` keep it scriptable; default with a TTY is
  the interactive list.

## What selection means

Selection **changes behavior**: only the modules you select get started / reconciled /
provisioned. A checkbox that only confirms a fixed pipeline adds nothing — `cove up`
already has `--yes` semantics if we want a non-interactive fixed run.

Core modules (forgejo, nginx, vault, dnsmasq, dnsproxy) are always started; the checkbox
reconciles and provisions. Optional modules only start/reconcile if checked. Crucially,
**each optional module is provisioned by the same path its own `cove <module> up` uses** —
e.g. selecting speedtest in `cove up` must run the same `_ensure_app_key()` flow that
`cove speedtest up` runs, so a started speedtest is never launched with an empty
`SPEEDTEST_APP_KEY`. The checkbox is an aggregation of the per-module `up` commands, not a
new provisioning path.

## Non-gap: optional modules' provisioning

The speedtest APP_KEY being empty in `.env` after a plain `cove up` is **not a defect**.
Speedtest is optional; its owner command `cove speedtest up` provisions the key into the
compose `.env` and starts it. That's the correct, single entry point for an optional
service — the incident was a stale empty `.env`, not a broken normal flow. The only time
`cove up` must care is if it's allowed to *start* speedtest (i.e. the checkbox selects it);
then it reuses the existing `_ensure_app_key()` path rather than introducing a second one.

## Questions this opens

- How does `cove up` know each module's "own" provisioning? Presumably a per-module
  provider that both `cove <module> up` and the `up` selector call, so there's one
  provisioning path per module, not two.
- Relationship to the older `cove-default-command-ux.md` TUI musing: this is a lighter
  ask (interactive confirm on `up`, not a full TUI). Might be a stepping stone — a
  checkbox confirm is a small Textual/`questionary` dependency, not the full mode-based
  TUI.

## Related

- `cove-default-command-ux.md` — bare `cove` as a TUI command center; the checkbox on
  `up` could be the first interactive surface.
- `cove-up-sudo-friction.md`, `cove-up-become-prompt-spam.md` — related `cove up`
  ergonomics.
- Optional-profile model: `cli/cove/cli.py` `_detect_running_optional_profiles`,
  `cli/cove/status.py` `OPTIONAL_SERVICES`.
