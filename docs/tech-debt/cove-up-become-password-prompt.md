# `cove up` prompts for BECOME password multiple times

- **Area:** `cli/cove/cli.py` — `cove up` Ansible orchestration
- **Severity:** minor
- **Discovered:** 2026-08-13 during the speedtest heal session
- **Root cause:** `cove up` runs **4 separate `ansible-playbook` invocations**
  (`bringup.yml`, `bootstrap_vault.yml`, `provision_vault_user.yml`,
  `provision_forgejo.yml`), each passed `-K` (`--ask-become-pass`) via
  `base_cmd` at `cli/cove/cli.py:136`. Ansible does not share the BECOME
  password across separate `ansible-playbook` processes, so the operator
  types the sudo password once per playbook — up to 4 times per `cove up`.
- **Impact:** Friction on every `cove up`. The operator expects a single sudo
  prompt but gets repeated ones.
- **Fix approach:** Two distinct paths, already explored in musings:
  1. **Cache the password once** (short-term): prompt once via `getpass`,
     set `ANSIBLE_BECOME_PASSWORD` in `ansible_env`, drop `-K`. See
     `docs/musings/cove-up-become-prompt-spam.md` for the full design.
  2. **Eliminate the `become: true` tasks** (root cause): the sudo dependency
     exists only because a stale stack (`ai-chatbot-caddy`) squatted `:443`,
     forcing a pf redirect + `/etc/hosts` edit that need host root. Once the
     port conflict is resolved and nginx binds `:443` directly, the
     `become: true` tasks disappear and so does the prompt. See
     `docs/musings/cove-up-sudo-friction.md` (reframed 2026-06-23).
- **Risk:** Not fixed inline because the two approaches are in tension — the
  env-var cache is a band-aid that keeps the sudo dependency alive, while the
  port-conflict fix removes it entirely. Choosing wrong (or doing both) risks
  scope creep. The sudo-friction musing explicitly rejects auto-installing
  `NOPASSWD: ALL` sudoers as a security regression.
