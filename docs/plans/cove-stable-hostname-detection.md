# Plan: Stable Hostname Detection for Cove Credential/State Keying

## Problem

`cove up` and `cove creds batch-pull` derive the machine hostname from
`platform.node()` (`cli/cove/creds.py:29`, `cli/cove/state.py:81`). On
macOS, when the kernel `HostName` is unset, `platform.node()` returns the
**DHCP-assigned hostname**, which changes across networks.

This machine's kernel hostname currently resolves to `Mac.lan` while its
stable macOS name (System Settings > General > About) is `MBPBK-202602`.
Consequence: `batch-pull` looks up `op://Private/Forgejo Mac Admin/password`
(doesn't exist) instead of `op://Private/Forgejo MBPBK-202602 Admin/password`,
and `ensure_host_vars` writes/reads the wrong `state/hosts/Mac.yml` instead
of `state/hosts/MBPBK-202602.yml`. `cove up` fails at the credential-pull
stage with `Batch op read failed`.

## Root cause

The hostname source of truth is wrong. The kernel hostname
(`platform.node()`) is a drifted, network-dependent value. macOS exposes a
stable per-machine name via `scutil --get LocalHostName` (the same name the
user sees in General settings), which does not follow DHCP.

## Fix

Add a single shared `detect_hostname()` function in
`cli/cove/stateless.py` (the shared detection/resolution module) that:

1. On macOS, returns `scutil --get LocalHostName` (stripped of any
   domain suffix), falling back to `platform.node().split(".")[0]` if
   `scutil` is unavailable or fails.
2. On other platforms, returns `platform.node().split(".")[0]`.

Wire it into both call sites:
- `cli/cove/state.py` `ensure_host_vars` — picks the correct host_vars file.
- `cli/cove/creds.py` `HOSTNAME` — builds correct `op://Private/...`
  refs.

## Tests

- New `TestDetectHostname` in `cli/tests/test_state.py`:
  - prefers macOS LocalHostName over platform.node
  - strips domain suffix
  - falls back to platform.node on scutil failure
  - non-macOS uses platform.node
- Update existing `TestEnsureHostVars` mocks from `platform.node` to
  `detect_hostname`.

## Out of scope

- Renaming the machine or 1Password items (no longer needed once detection
  is stable).
- Deleting the stale `~/.config/cove/state/hosts/Mac.yml` (operator action,
  separate concern).
- `cli/uv.lock` version bump drift (unrelated; left on `main`).
