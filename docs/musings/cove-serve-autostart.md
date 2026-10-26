---
title: "cove serve — login-time stack autostart"
created: 2026-10-22
status: Decided
---

# Musing: `cove serve` — login-time stack autostart

**Status:** Decided (2026-10-22, operator) — implemented on PR #84
**Date:** 2026-10-22

## Decision (2026-10-22, operator)

Three open questions were put to the operator; this records the rulings and the
implementation that follows from them.

1. **Verb: `cove serve start|stop|status`.** As recommended. `stop` also takes
   `--off` as an accepted alias matching `cove update auto --off`. The login
   payload is the hidden `cove serve run`.
2. **Unseal placement: a dedicated `cove vault unseal` verb** wrapping
   `ensure_unsealed()`. The operator's added rationale: it also allows unsealing
   **without** re-running `cove up`. In `cove up`, the unseal is the **last**
   step and its failure is **NON-FATAL** — it prints a warning naming
   `cove vault unseal` and continues. This is an **operator-directed semantic
   change to PR #79/#83**: `_unseal_restarted_vault`'s `ClickException` on
   unseal failure becomes that warning, and the tests asserting the exception
   are updated to assert the warning.
3. **Keychain policy (revised after the operator challenged bounded-retry):**
   retry **only** the window where Vault is not yet answering — the container
   boot race — and the moment there is a definitive answer, act immediately.
   Once Vault answers: sealed → attempt unseal; unseal failure → the non-fatal
   warning from decision 2. Unreachable after the bound → the same non-fatal
   warning. **Rationale: the retry absorbs the boot race, not the keychain;
   everything definitive resolves fast.** A locked keychain is a definitive
   answer (Vault answers, the keystore read fails), so it must not burn the
   boot-race window — no minute-long wait on a locked keychain.

**Implemented in:** `cli/cove/serve.py` (agent), `cli/cove/vault.py` (unseal
verb + `unseal_or_warn`), `cli/cove/cli.py` (`cove up` last-step non-fatal
unseal), `cli/tests/test_serve.py`, `cli/tests/test_vault.py`.

## The gap in one line

After a reboot the containers come back on their own, but **Vault comes back sealed and nothing unseals it**, so the operator still has to run `cove up` by hand to get a working stack.

## Why the stack half-returns today

Three layers decide whether Cove survives a reboot, and only the first one is automatic:

- **Containers.** Every service in `compose/docker-compose.yml` is `restart: unless-stopped`, so the Containers come back when the Docker engine restarts. This is the entire reboot mechanism Cove has today.
- **The engine.** Cove installs no login or boot agent for the container runtime. On macOS the engine coming back is the runtime's own login service doing it (OrbStack on the machine class this thread runs on; Colima is the fallback). `cove up` auto-starts Colima only when no daemon answers, and it registers nothing to start at login.
- **Vault unseal.** This is the piece with no automatic path. Vault has no auto-unseal configured: it is Shamir-sealed, the three unseal keys live in the OS keychain, and a (re)started Vault is sealed until something calls `vault operator unseal`.

The unseal logic that exists today does not cover a reboot:

- `compose/bootstrap_vault.yml` unseals a sealed-but-initialized Vault (it reads the keys from the keychain and POSTs `/v1/sys/unseal`). But it only runs when `cove up` runs **with** provisioning, and provisioning begins with `cove creds batch-pull`, which needs a 1Password prompt. Unattended, that path is unavailable.
- `cove up --no-provision` is the unattended path. It heals a sealed Vault only through `_unseal_restarted_vault()`, and that is gated on `_vault_restarted_since(vault_before)`, where `vault_before` is snapshotted **immediately before** the compose run. A reboot restart happened long before `cove up` runs, so the snapshot already reflects the rebooted (sealed) container, the comparison comes back unchanged, and the heal does not fire.

Net: `cove up --no-provision` after a reboot converges everything except Vault, and Vault stays sealed. That is the three seal incidents this week, and it is what `cove serve` exists to close.

## 1. Command surface

### The shipped shape

```
cove serve start      # register the login agent (idempotent re-register)
cove serve stop       # bootout + remove the plist
cove serve stop --off # same, for symmetry with `cove update auto --off`
cove serve status     # is the agent installed and loaded?
cove serve run        # HIDDEN: the agent payload (runtime, up, unseal)
```

### Is `serve` the right verb?

Two naming forces pull in opposite directions, and the recommendation is a deliberate compromise.

- **For `cove serve`:** this is a distinct lifecycle concept ("the stack should be present after I log in"), not a one-shot bring-up. `cove up` already means "bring it up now"; overloading it with scheduling muddies a verb the operator uses constantly. A separate noun keeps `up`/`down` as the manual, in-session controls and `serve` as the durability control.
- **Against `serve`:** "serve" strongly implies a long-running foreground daemon, and this is **not** one. The agent is a one-shot `RunAtLoad` job that converges the stack and exits. The doc and the `--help` text must say "login-time one-shot, not a daemon" to stop the wrong mental model.
- **The alternative to weigh:** `cove up auto` / `cove up auto --off`, mirroring `cove update auto` exactly (the proven pattern: `<verb> auto` schedules `<verb>`, label `app.cove.update`, plist under `~/Library/LaunchAgents/`, log under `~/Library/Logs/`). The symmetry is real and appealing. It is rejected as the primary because the agent runs **more than `cove up`** (it ensures the runtime and performs the unseal); calling it `cove up auto` would under-describe the payload. Keep `cove update auto`'s *mechanism* verbatim, but give the new capability its own verb.

**Recommendation (accepted 2026-10-22):** ship `cove serve start|stop|status` as the operator surface, reuse the `cove update auto` implementation pattern wholesale (`_bootout()` + `launchctl bootstrap gui/<uid>` + a rendered plist + a `--off` alias on `stop`), and pick a fresh label (`app.cove.serve`) and log (`~/Library/Logs/cove-serve.log`). `cove up auto` was **rejected** as the primary verb for the reason above (the payload is more than `cove up`).

### Relation to `cove-config-command.md`

These are orthogonal axes that compose, and the design should keep them separate:

- **`cove serve`** answers *does the base stack come back after login/reboot at all?*
- **`cove config set auto-start <service>`** (the draft in `cove-config-command.md`) answers *which optional profiles join `cove up`* (litellm, speedtest, and friends).

`cove serve start` guarantees the base stack. If the operator also wants litellm to return, they set the `auto-start` preference, and the agent's `cove up` honors it. `serve` must **not** grow its own profile list; that stays with the other musing.

## 2. What the agent runs

### `RunAtLoad`, login not boot

The agent is a **user** LaunchAgent with `RunAtLoad` (no `StartCalendarInterval`, no `KeepAlive`), installed at `~/Library/LaunchAgents/app.cove.serve.plist`.

- **`RunAtLoad` fires at login**, when the user's launchd session comes up, not at kernel boot. This is not a limitation to work around; it is required. The Vault unseal keys live in the **login keychain**, which is unlocked by the login authentication itself. A LaunchDaemon would start earlier (at boot) but runs as root with no access to the user's login keychain, so it could not unseal. `RunAtLoad` is the only correct trigger, and it means "after the operator logs in," which is exactly when the engine's own login service has also started.
- **OrbStack vs Colima.** On the machine class this thread runs on, OrbStack's own login service brings the engine up; the agent should not fight it. The payload probes `docker info` first and only falls back to `colima start` when no daemon answers, mirroring the existing bringup probe/gate that exists precisely so a healthy non-Colima engine is never displaced.

### Payload (ordered)

- **Ensure the runtime.** Bounded poll of `docker info` (the engine may still be settling); if no daemon answers, attempt `colima start` once (the existing fallback). Never displace an engine that answers.
- **Converge:** `cove up --no-provision --non-interactive`.
  - `--no-provision` because `cove creds batch-pull` needs a 1Password biometric and there is no operator.
  - `--non-interactive` because there is no TTY, and it also skips the BECOME prompt.
  - Containers were already restored by `restart: unless-stopped` **before** the agent fires. `cove up` must **converge, not fight that**: it is idempotent, it re-renders the runtime files, and it leaves already-running containers alone unless a real pin or config changed.
- **Unseal explicitly.** This is the whole point, and it cannot be left to `cove up --no-provision` as that command behaved before this change (see "Why the stack half-returns today"). Shipped: a dedicated verb, `cove vault unseal`, wrapping the existing `cove.vault_unseal.ensure_unsealed()`, which is also useful on its own to unseal without re-running `cove up`. The agent calls it after the converge. In the agent it is **non-fatal** (`unseal_or_warn`): a failure prints a warning naming `cove vault unseal` and marks the run failed (exit 1), but the converge has already happened. The standalone verb stays fail-loud.

The hidden `cove serve run` command is the payload the plist invokes (`ProgramArguments` ends `serve run`), so the ordering lives in one tested place rather than in a shell string.

### The unseal semantics to preserve

`ensure_unsealed()` already does the right thing: it reads `initialized`/`sealed` from `/v1/sys/health`, returns early when already unsealed, resets unseal progress, reads the three Shamir keys from the keychain, POSTs them, and re-checks. The verb reuses it unchanged.

The one change that rides along is **inside `cove up`**: the unseal is moved to the **last** step and its failure is **NON-FATAL** (decision 2). Before this, `_unseal_restarted_vault` raised a `ClickException` on a failed unseal, aborting the run before provisioning. Now it warns, and the end-of-`up` status gate is what surfaces a still-sealed Vault (`cove up` still exits non-zero there). This is an operator-directed amendment to the PR #79/#83 fail-loud semantics.

Ordering detail: unseal now runs **after** provisioning, so a failed unseal can no longer skip `bootstrap_vault.yml` — which matters because that playbook is the *other* unseal path (it heals a sealed initialized Vault on the provisioned flow). The `--no-provision` path (`cove update`, `cove serve run`) never runs it, which is exactly why the CLI heal exists.

## 3. Edge cases the design must address

### 3a. Keychain unlock timing at `RunAtLoad`

At login the login keychain is normally already unlocked (the user just authenticated). `_read_keystore()` shells `security find-generic-password -w`, and if the keychain is locked that read fails with `Keystore read failed`, which surfaces as a `RuntimeError` out of `ensure_unsealed()`.

**Decided (2026-10-22): the retry absorbs the boot race, not the keychain.** The bounded retry exists only for the window where Vault is not yet answering (the container has not finished starting); the moment Vault gives a definitive answer, the agent acts immediately.

- **Vault not answering yet** (connection refused / timeout inside the boot window): retry, bounded, then warn and stop. The bound is the existing `_VAULT_HEALTH_ATTEMPTS` × `_VAULT_HEALTH_RETRY_SECONDS` window (15 × 2s ≈ 30s of coverage), the same one PR #83 widened for a normal Vault boot.
- **Vault answers, sealed, unseal fails** (a locked keychain is this case — Vault answered; the keystore read failed): do **not** retry. Warn immediately, name `cove vault unseal`, exit non-zero. This is the operator's revision: retrying here would burn the boot-race window on a condition that retrying cannot fix.
- **Never** write the keys anywhere outside the keychain as a workaround, and **never** prompt (no TTY).

### 3b. Sudo

`cove up`'s privileged bringup tasks (`/etc/hosts`, the macOS scoped-resolver re-point, the trust-store install) are `become: true` and `failed_when: false`, and `--non-interactive` sets `ANSIBLE_BECOME_PASS=""` so Ansible never prompts. Two machine classes:

- **Passwordless drop-in present** (`cove sudo enable` installed `/etc/sudoers.d/cove`): the privileged tasks run, full convergence.
- **Absent:** the privileged tasks fail harmlessly, the resolver re-point is skipped, and `cove status` reports resolver drift with the corrective command.

Design rule: **skip-and-warn, never fail the whole autostart on a sudo task, never prompt.** The agent must not attempt to install the sudoers drop-in itself (that requires a password). `cove status` is the operator's signal that a machine has drifted to the "converge-minus-privileged" class.

### 3c. `cove update auto` coexistence

Two agents then exist: `app.cove.update` (daily `StartCalendarInterval`) and `app.cove.serve` (login `RunAtLoad`). They are independent, and both funnel through the same `cove up`, so there is no ordering requirement. Interactions to name explicitly:

- **Near-simultaneous runs.** If the operator logs in around the configured update hour, two `cove up` / Ansible runs can target the same compose project at once and race on recreate. **Deferred in this cut:** no lock is implemented yet. Both jobs are independent today, so this remains a known (narrow) gap; a lockfile/`flock` around the converge is the intended fix.
- **Pin changes.** The update job may install a new CLI release and change pins; the serve agent then converges to the new release. Same source of truth, so this is a feature, not a conflict.
- **Both must be non-interactive.** `cove update --quiet` already implies it; the serve agent pins `--non-interactive` directly.

### 3d. Unattended failure handling

- **Log.** One log at `~/Library/Logs/cove-serve.log`, mirroring `cove-update.log`: `StandardOutPath` and `StandardErrorPath` both point at it.
- **Bounded retries only for transient conditions** (engine not up yet, Vault not answering yet, keychain locked), each with a hard ceiling. Never an unbounded wait.
- **Routine success is silent; failures are one clear line.** Match the `cove update auto` contract ("the opt-in is the approval"): the operator set it up once and should not be asked each boot.
- **`cove status` is the post-boot truth.** The design asserts two things about it: a *successful* autostart ends with `cove status` all-green, and a *failed* autostart is visible there (Vault API failed, or resolver drift) rather than silent. Autostart never becomes the only place state is knowable.

### 3e. Linux portability (out of scope, but named)

The same shape maps to systemd: a user unit at `~/.config/systemd/user/cove-serve.service` with `WantedBy=default.target` (plus `loginctl enable-linger` so it runs without an interactive login), or a system unit if the engine is root-managed. `_read_keystore()` already handles Linux via `secret-tool`, and the login keyring unlock timing has the same caveat as macOS. Explicitly **out of scope** for this design; named so the abstraction is not accidentally macOS-shaped.

## 4. What it deliberately does NOT do

- **No `KeepAlive` watchdog.** A container dying mid-session is already covered by `restart: unless-stopped`. A Cove process that watches containers is a different design (see `cove-health-daemon.md`) and is not this.
- **No daemonizing `cove` itself.** The agent is a one-shot `RunAtLoad` job. Cove stays CLI-first; there is no long-running cove process.
- **No auto-start of optional profiles.** litellm, speedtest, runner, toolhive stay opt-in via the `cove-config-command.md` `auto-start` axis. `serve` only guarantees the base stack returns. (ADE is core since 0.8.0, so it returns via `cove up` — a consequence of the base stack, not a new capability here.)
- **No interactive prompts and no 1Password provisioning.** The agent runs `--no-provision`; it never triggers a biometric prompt.
- **No self-install of privileged bits.** The sudoers drop-in and trust-store install are the operator's explicit `cove sudo enable` action, never the agent's.

## 5. Decisions

All three questions were ruled on 2026-10-22 (see the Decision section at the top). Recorded in short:

- **Verb and UX:** `cove serve start|stop|status` (with `--off` on `stop`). `cove up auto` rejected.
- **Unseal placement:** dedicated `cove vault unseal` verb; in `cove up` the unseal is the last step and non-fatal.
- **Keychain policy:** retry the boot race only; a definitive answer acts immediately; a failed unseal warns and does not retry.

**Parked, not blocking (not implemented in this cut):** a converge lock for the `cove serve` + `cove update` overlap (see 3c); ntfy push on autostart failure (per the ntfy spoke); whether `cove serve start` should trigger one immediate converge so enabling it heals the *current* sealed state without waiting for a reboot; per-host versus global scope for the preference (ties into `cove-config-command.md`).

## Related

- `2026-09-26-cove-update-command.md` — the launchd pattern this reuses (`app.cove.update`, plist, log, `--off`), and the "the opt-in is the approval" contract.
- `cove-config-command.md` — the orthogonal "which optional profiles join `cove up`" axis.
- `cove-up-sudo-friction.md` — the reboot-friction history that assumed a Colima launchd autostart was enough; that assumption is the gap this design closes.
- `cove-health-daemon.md` — the watchdog design this deliberately does not become.
- `cove-secrets-in-keychain.md` — keychain and unseal-key lifecycle.
- `cove-dns-architecture.md` — the resolver state the privileged bringup tasks maintain.
