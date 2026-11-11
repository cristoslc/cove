# Sashay: `cove status` survives Linux DNS

**Trigger:** operator ran `cove status` on a Linux host (`TBR-T470-202610`) and got a traceback instead of a report.
**Blast radius:** low — read-only status output, no container, credential, or network state changes.
**Branch:** `bb/fix-linux-status-dns`

## Problem

`cove status` aborts with `FileNotFoundError: [Errno 2] No such file or directory: 'dscacheutil'` before printing any check result.

Root cause chain, confirmed against the installed wheel (0.15.15, byte-identical to `cli/cove/status.py`):

1. `_check_dns()` (`cli/cove/status.py:200-220`) always shells out to `dscacheutil`, a macOS Directory Services tool. Linux has no such binary, so `subprocess.run()` raises `FileNotFoundError` at `Popen`, before the child process exists.
2. The only handler is `except subprocess.TimeoutExpired`, so the `FileNotFoundError` escapes.
3. `check_all()` (`status.py:259-271`) appends results in a straight line and `cli.status()` (`cli/cove/cli.py:531-547`) does not guard the call, so the exception kills the entire report — including the container, nginx, Forgejo, and Vault checks that are platform-neutral.
4. Every `cove status` test patches `cove.status._check_dns` (`cli/tests/test_cli.py:1146`, `:1176`, `:1224`), so the real function has zero coverage on any platform.

Linux is a documented supported host (`docs/architecture.md:10`, "Colima (macOS) or Docker Engine (Linux)"), and `_check_resolver_port()` right next to the failing function already gates itself with `is_macos()` (`status.py:235`). The DNS check simply never got the same treatment.

## Fix design

Keep macOS behavior, add a real Linux path, and make a missing lookup tool a failed row instead of an exception.

- `_resolve_addresses(name)` — platform-aware lookup:
  - macOS: existing `dscacheutil -q host -a name <name>`, parse `ip_address:` lines.
  - non-macOS: `socket.getaddrinfo(name, None, type=socket.SOCK_STREAM)`, which uses NSS, so `/etc/hosts` and the local resolver both count.
- Pass condition: the name resolves to an address this host owns — loopback (`127.0.0.1`, `::1`) or a local interface address. The local set comes from loopback plus a UDP `connect()` to TEST-NET-1 (`192.0.2.1`), which asks the kernel for the primary source address and sends no packets. This accepts the LAN-IP `/etc/hosts` mapping a Linux host may legitimately use (`192.168.0.25 git.cove` on the reporting machine) while still rejecting a hijacked public answer.
- Failure handling: `subprocess.TimeoutExpired` and `OSError` (which covers `FileNotFoundError` and `socket.gaierror`) are caught per name, recorded, and rendered as `ok=False` with the underlying error text. The command reports an unhealthy row; it never raises.
- Hints become platform-aware: keep the `/etc/resolver` and `cove sudo enable` hints on macOS, use `/etc/hosts` guidance on Linux.

## Non-goals

- No change to resolver, dnsmasq, or `/etc/hosts` provisioning.
- No change to which checks run, or to their success criteria beyond the address-ownership rule above.
- No global try/except around `check_all()`: broad exception swallowing conflicts with the project's fail-loud rule. That structural gap is recorded as deferred tech debt instead.

## Tasks

1. Red: add `TestStatusDnsCheck` to `cli/tests/test_cli.py` covering macOS success, macOS missing binary, Linux loopback, Linux local-interface address, Linux non-local address, and Linux `gaierror`. All Linux-and-error tests fail against current code (the missing-binary test fails with `FileNotFoundError`).
2. Green: implement `_resolve_addresses()` and `_local_addresses()` in `cli/cove/status.py`, rewrite `_check_dns()` on top of them.
3. Write `docs/tech-debt/status-check-failure-isolation.md` recording the deferred `check_all()` isolation gap.
4. Run the required gate: `uv run --directory cli pytest -x -q -m "not e2e and not staging"`.
5. Publish the chronicle on the draft PR, hand to operator.

## Acceptance

- `cove status` on a Linux host with no `dscacheutil` prints a full report; the DNS row is `✓` when the name maps to this host and `✗` with an actionable hint when it does not.
- macOS behavior is unchanged: `dscacheutil` still gates the check, and a missing binary yields a failed row, not a traceback.
- The required non-E2E, non-staging suite passes.

## Deferred

- Isolating each check in `check_all()` so one raising check degrades to a failed row instead of aborting the report. Landed as `docs/tech-debt/status-check-failure-isolation.md` in this sashay.
