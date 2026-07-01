# Cove Up BECOME Prompt Spam

## Symptom

`cove up` prompts for the BECOME password four separate times — once for
each Ansible playbook (bringup, bootstrap_vault, provision_vault_user,
provision_forgejo). This is annoying and breaks the flow.

## Root Cause

The `-K` (`--ask-become-pass`) flag is passed to each `ansible-playbook`
subprocess in `cli.py:_run_ansible`. Each subprocess is independent — there's
no cross-process password caching. Ansible's `-K` reads from the TTY, so each
invocation blocks for input.

The password is the same every time (the user's sudo password).

## Fix

Prompt once in the Python CLI, then pass it via environment variable:

```python
import getpass
import os

# Before the first _run_ansible call:
become_pass = getpass.getpass("BECOME password: ")
os.environ["ANSIBLE_BECOME_PASSWORD"] = become_pass

# Remove -K from base_cmd — the env var is picked up automatically.
```

Ansible checks `ANSIBLE_BECOME_PASSWORD` (or `ANSIBLE_BECOME_PASSWORD_FILE`)
before falling through to TTY prompt. All four subprocesses inherit the env
var silently.

## Edge Cases

- **`--no-sudo`**: When `--no-sudo` is passed, we set `ansible_become=no` and
  skip `-K`. In that case we should also skip the `getpass` prompt entirely.
- **Empty password**: `getpass` returns `""` if the user just presses Enter.
  Ansible will then prompt per-playbook anyway. We could loop until non-empty,
  but that's over-engineering — if the user has NOPASSWD sudo, they can use
  `--no-sudo` and the env var is harmless.
- **Logging**: The password is in the env var of the Python process. If `--log`
  is used, stdout/stderr are captured but the env var is not written to the
  log file. Still, the env var is visible in `/proc/self/environ` — acceptable
  for a local dev tool.

## Implementation

In `cli.py:up()`:

1. Before the `_run_ansible` loop, if `not no_sudo`, call `getpass` and set
   `os.environ["ANSIBLE_BECOME_PASSWORD"]`.
2. Remove `-K` from `base_cmd` unconditionally (the env var replaces it).
3. The `--no-sudo` path already sets `ansible_become=no` — no change needed.

This eliminates all four prompts, replacing them with a single one at the
very start of `cove up`.
