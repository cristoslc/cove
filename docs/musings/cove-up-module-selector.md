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

## Questions this opens

- Should selection change **behavior** (which playbooks run) or just confirm a fixed
  pipeline? Currently `up` runs bringup + bootstrap_vault + provision_vault_user +
  provision_forgejo unconditionally. Does selecting "speedtest" add its provisioning,
  or does speedtest's env-key problem get fixed in bringup so the checkbox is purely
  cosmetic?
- The real bug from the session is that `cove up` doesn't provision optional modules'
  secrets into the compose `.env` on re-runs (`.env` render is first-boot-only). That's
  a defect independent of the UX idea — worth a separate fix/ADR regardless.
- Relationship to the older `cove-default-command-ux.md` TUI musing: this is a lighter
  ask (interactive confirm on `up`, not a full command center). Might be a stepping
  stone — a checkbox confirm is a small Textual/`questionary` dependency, not the full
  mode-based TUI.

## Related

- `cove-default-command-ux.md` — bare `cove` as a TUI command center; the checkbox on
  `up` could be the first interactive surface.
- `cove-up-sudo-friction.md`, `cove-up-become-prompt-spam.md` — related `cove up`
  ergonomics.
- Optional-profile model: `cli/cove/cli.py` `_detect_running_optional_profiles`,
  `cli/cove/status.py` `OPTIONAL_SERVICES`.
