"""`cove serve` — autostart the cove stack at login.

Registers a `RunAtLoad` LaunchAgent (label `app.cove.serve`) that, at login,
ensures the Docker runtime is reachable, converges the stack with
`cove up --no-provision --non-interactive`, then unseals Vault. It mirrors the
proven `cove update auto` launchd pattern (`cli/cove/update.py`): render a plist
under `~/Library/LaunchAgents/`, `launchctl bootstrap` it into the user's
session, `launchctl bootout` on stop.

It runs at **login, not boot**: the Vault unseal keys live in the login
keychain, which only login authentication unlocks. A boot-time daemon could not
reach them. The agent is a one-shot job, not a daemon.

Design: docs/musings/cove-serve-autostart.md (Decided 2026-10-22).
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from shutil import which

import click

from cove.vault import unseal_or_warn

LAUNCHD_LABEL = "app.cove.serve"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
LOG_PATH = Path.home() / "Library" / "Logs" / "cove-serve.log"

# The Docker runtime probe window at login. The engine's own login service may
# still be starting when RunAtLoad fires, so probe before giving up — but stay
# bounded: the agent must always terminate.
DOCKER_PROBE_ATTEMPTS = 15
DOCKER_PROBE_INTERVAL_SECONDS = 2.0


def _cove_bin() -> str:
    return which("cove") or "cove"


def _launchctl(*args: str, check: bool) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["launchctl", *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=check,
    )


def _bootout() -> None:
    """Best-effort unload: booting out an unloaded label is not an error."""
    _launchctl("bootout", f"gui/{os.getuid()}", LAUNCHD_LABEL, check=False)


def _render_plist() -> str:
    cove_bin = _cove_bin()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_LABEL}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>ProgramArguments</key>
    <array>
        <string>{cove_bin}</string>
        <string>serve</string>
        <string>run</string>
    </array>
    <key>StandardOutPath</key><string>{LOG_PATH}</string>
    <key>StandardErrorPath</key><string>{LOG_PATH}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>HOME</key><string>{Path.home()}</string>
    </dict>
</dict>
</plist>
"""


@click.group("serve", help="Autostart the cove stack at login (RunAtLoad agent).")
def serve() -> None:
    """Register a login agent that converges the stack and unseals Vault."""


@serve.command("start")
def serve_start() -> None:
    """Register the login agent (idempotent: re-register replaces it).

    At each login the agent ensures the Docker runtime is reachable, runs
    `cove up --no-provision --non-interactive`, then unseals Vault. One-shot,
    not a daemon; the first real activation is the operator running this.

    Examples:

        cove serve start
    """
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(_render_plist())
    _bootout()
    _launchctl("bootstrap", f"gui/{os.getuid()}", str(PLIST_PATH), check=True)
    click.echo(f"Login autostart enabled ({PLIST_PATH}).")


@serve.command("stop")
@click.option("--off", "off_", is_flag=True,
              help="Accepted alias, matching `cove update auto --off`.")
def serve_stop(off_: bool) -> None:
    """Unload the login agent and remove its plist.

    Examples:

        cove serve stop

        cove serve stop --off
    """
    _ = off_  # `--off` is an accepted alias; removal is the same either way
    _bootout()
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
        click.echo(f"Login autostart disabled (removed {PLIST_PATH}).")
    else:
        click.echo("Login autostart was not installed; nothing to do.")


@serve.command("status")
def serve_status() -> None:
    """Report whether the login agent is installed and loaded.

    Examples:

        cove serve status
    """
    installed = PLIST_PATH.exists()
    loaded = LAUNCHD_LABEL in _launchctl("list", check=False).stdout
    click.echo(f"plist:   {'installed' if installed else 'absent'} ({PLIST_PATH})")
    click.echo(f"agent:   {'loaded' if loaded else 'not loaded'}")
    if installed and not loaded:
        click.echo("Run `cove serve start` to (re)load it.")


def _docker_daemon_answers() -> bool:
    result = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    return result.returncode == 0


def _wait_for_docker(*, attempts: int) -> bool:
    """Bounded poll for a Docker daemon. Returns True as soon as one answers."""
    for attempt in range(attempts):
        if _docker_daemon_answers():
            return True
        if attempt < attempts - 1:
            time.sleep(DOCKER_PROBE_INTERVAL_SECONDS)
    return False


def _ensure_docker_runtime() -> bool:
    """True when a Docker daemon answers.

    Probe first; fall back to `colima start` once **only** when nothing answers,
    so a healthy non-Colima engine (OrbStack, Docker Desktop) is never displaced.
    """
    if _wait_for_docker(attempts=DOCKER_PROBE_ATTEMPTS):
        return True
    if which("colima"):
        click.echo("No Docker daemon answered; starting Colima...")
        subprocess.run(
            ["colima", "start"], stdin=subprocess.DEVNULL, check=False
        )
        return _wait_for_docker(attempts=DOCKER_PROBE_ATTEMPTS)
    return False


@serve.command("run", hidden=True)
def serve_run() -> None:
    """The login agent payload: ensure the runtime, converge, unseal.

    Hidden: this is what the LaunchAgent invokes (`cove serve run`), not an
    operator command. Bounded and non-interactive by construction.
    """
    if not _ensure_docker_runtime():
        raise click.ClickException(
            "No Docker daemon answered; cannot autostart the stack. Start the "
            "engine (Docker Desktop, OrbStack, or `colima start`) and run "
            "`cove serve run` again."
        )

    result = subprocess.run(
        [_cove_bin(), "up", "--no-provision", "--non-interactive"],
        stdin=subprocess.DEVNULL,
        check=False,
    )
    up_ok = result.returncode == 0
    if not up_ok:
        click.echo(
            f"WARNING: `cove up` exited {result.returncode}; the stack may be "
            "incomplete. Check `cove status`.",
            err=True,
        )

    unsealed_ok = unseal_or_warn(context="Vault")
    if not (up_ok and unsealed_ok):
        raise SystemExit(1)
    click.echo("Login autostart complete: stack converged, Vault unsealed.")
