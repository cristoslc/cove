---
title: "cove config — Persistent User Preferences"
created: 2026-08-12
authored-by: deepseek-v4-flash:cloud
status: Draft
---

# cove config — Persistent User Preferences

## The Idea

A `cove config` command to set persistent preferences, e.g.:

```
cove config set auto-start litellm
cove config set auto-start speedtest
cove config get auto-start
cove config list
```

The motivating example: "I always want litellm and headroom to start up with `cove up`."

## Current State

Optional services (LiteLLM/Headroom, Speedtest Tracker) are **compose profiles** — they do NOT start with `cove up`. They're started explicitly:

- `cove litellm up` → `docker compose --profile litellm up -d`
- `cove speedtest up` → `docker compose --profile speedtest up -d`

`cove up` runs `bringup.yml` (Ansible) which brings up the base stack only. There is no mechanism today to make an optional service start automatically.

## What "config" Means Here

This is **user preference**, not infrastructure state. It's distinct from:

- **host_vars** (`~/.config/cove/state/hosts/<hostname>.yml`) — auto-detected PII overlay (admin username/email, op vault, ts dns name). Machine identity, not preference.
- **compose `.env`** — runtime copies regenerated from the wheel. Not hand-edited.
- **1Password creds** — secrets, provisioned via `cove creds`.

A preference like "auto-start litellm" is neither a secret nor machine identity — it's a per-user choice about which optional harbor services should come up by default.

## Design Questions

### Where does the config live?

Options:

1. **`~/.config/cove/config.yml`** — a new top-level user config file, sibling to `state/` and `compose/`. Clean separation: `compose/` = infra (regenerated from wheel), `state/` = machine identity, `config.yml` = user preference.
2. **Inside host_vars** — reuse the existing per-host YAML. But host_vars is auto-generated and "re-running `cove up` will NOT overwrite" — mixing preference into it muddies the auto-detect contract.
3. **Inside compose `.env`** — but `.env` is a runtime copy regenerated from the wheel; hand-editing it is explicitly a smell.

Option 1 is cleanest. It's user-owned, survives reinstall (it's not in the wheel), and is per-machine (matches how host_vars are per-host).

### How does `cove up` consume it?

`cove up` currently runs `bringup.yml` with `-e @host_vars_file`. To honor auto-start, `cove up` would need to:

- Read `~/.config/cove/config.yml`
- If `auto-start: [litellm, speedtest]`, append the corresponding `--profile` flags to the compose bring-up, OR pass the profiles into Ansible so `bringup.yml` starts them.

The compose profiles are already declared (`profiles: ["litellm"]`, `profiles: ["speedtest"]`). The cleanest hook: `cove up` computes the union of base + auto-start profiles and passes it to the compose/Ansible bring-up. This keeps the profile declaration as the single source of truth for *what* a service is; config only decides *whether* it's on by default.

### What's the scope of "config"?

Keep it narrow at first — a key/value store for a small, known set of preferences:

- `auto-start` — list of optional services to bring up with `cove up`
- Possibly later: `default-command` (see `cove-default-command-ux.md`), log verbosity, etc.

Don't build a general-purpose config system. YAGNI — start with the one real need (auto-start) and grow only with evidence.

### Validation

`cove config set auto-start litellm` should validate that `litellm` is a known optional service (matches a compose profile). Fail loud on unknown values — don't silently accept a typo that `cove up` then ignores.

## Open Questions

- Should `auto-start` be a list, or a set of boolean flags (`auto-start.litellm: true`)? A list is simpler to type; booleans are more extensible per-service.
- Should `cove up` also *stop* auto-start services that the user later removes from config? Or only ever add? (Probably only add — `cove down` is the explicit stop.)
- Does the config need to be per-host or global? If a user wants litellm on the desktop but not a laptop, per-host matters. But that may be over-engineering for now.
- Interaction with `cove litellm up` / `cove speedtest up` — should those commands *also* persist the preference (i.e. `cove litellm up` implies "and keep doing this")? Or stay explicit?

## Related Musings

- `litellm-headroom-context-proxy.md` — why LiteLLM/Headroom is an optional harbor service
- `litellm-hardening.md` — the security posture that makes it safe to auto-start
- `cove-default-command-ux.md` — the broader question of what `cove` does by default; config could feed into that
- `cove-up-sudo-friction.md` / `cove-up-become-prompt-spam.md` — friction in `cove up`; auto-start adds services to that path, so worth re-reading
