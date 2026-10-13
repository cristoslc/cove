"""`cove update` — vendor-style updates for cove itself and its stack.

One command, one source of truth: the released cove CLI version specifies the
pins (compose files, images, migrations ship in the wheel); `cove update`
installs the latest tagged release and converges everything to it via the
normal bring-up flow. `cove update auto` schedules that daily — the opt-in is
the approval.

Never trunk: the only artifact `update` consumes is the wheel built from a
tagged release (the sashay rule stands). See
docs/musings/2026-09-26-cove-update-command.md (Decision).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from shutil import which

import click

from cove import __version__

REPO_URL_ENV = "COVE_REPO_GIT"
LAUNCHD_LABEL = "app.cove.update"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
LOG_PATH = Path.home() / "Library" / "Logs" / "cove-update.log"


def _repo_url() -> str:
    """The cove repo remote URL. env override wins; otherwise the dev
    checkout's origin remote is the canonical source (the operator machine
    is where scheduled updates run). No hardcoded repo owner: the repo URL
    is machine truth, not wheel-bundled truth."""
    url = os.environ.get(REPO_URL_ENV)
    if url:
        return url
    checkout = Path.home() / "Documents" / "code" / "cove"
    result = subprocess.run(
        ["git", "-C", str(checkout), "remote", "get-url", "origin"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    raise click.ClickException(
        f"Cannot determine the cove repo remote URL (no origin remote at "
        f"{checkout}). Set {REPO_URL_ENV}=<url> and retry."
    )


def _latest_tag() -> str | None:
    """Highest vX.Y.Z tag on the repo remote, or None if unreachable."""
    try:
        repo_url = _repo_url()
    except click.ClickException:
        return None
    result = subprocess.run(
        ["git", "ls-remote", "--tags", repo_url, "refs/tags/v*"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return None
    tags = [
        m.group(1)
        for line in result.stdout.splitlines()
        if (m := re.match(r"refs/tags/v(\d+\.\d+\.\d+)$", line.split("\t", 1)[-1]))
    ]
    if not tags:
        return None

    def key(v: str):
        return tuple(int(p) for p in v.split("."))

    return max(tags, key=key)


def _version_tuple(v: str):
    try:
        return tuple(int(p) for p in v.split("."))
    except ValueError as exc:
        raise ValueError(f"not a semver: {v!r}") from exc


def _install_wheel(tag: str) -> None:
    """Build the wheel at `tag` in a throwaway worktree (mirrors the promote
    flow: sync compose resources -> build -> uv tool install --force) and
    fail loud if the build does not produce one."""
    with tempfile.TemporaryDirectory(prefix="cove-update-") as tmp:
        worktree = Path(tmp) / "repo"
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree), f"v{tag}"],
            check=True, capture_output=True, text=True,
        )
        try:
            subprocess.run(
                ["uv", "build", "--directory", str(worktree / "cli"),
                 "--wheel", "--out-dir", str(worktree / "dist")],
                check=True, capture_output=True, text=True,
            )
            wheels = sorted((worktree / "dist").glob("cove_cli-*.whl"))
            if not wheels:
                raise click.ClickException(
                    f"wheel build produced nothing for v{tag} — cannot update."
                )
            subprocess.run(
                ["uv", "tool", "install", "--force", str(wheels[-1])],
                check=True, capture_output=True, text=True,
            )
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                capture_output=True, text=True, check=False,
            )


def _check_container_pins() -> None:
    """Best-effort visibility: what the running containers actually are."""
    try:
        from cove.ade import _running_image

        image = _running_image()
    except Exception:
        image = None
    if image:
        click.echo(f"  ade container:      {image}")


def _do_update(check: bool, quiet: bool) -> None:
    installed = __version__
    latest = _latest_tag()

    if check:
        click.echo(f"  cove cli installed: {installed}")
        click.echo(f"  cove cli latest:    {latest or '(unreachable)'}")
        _check_container_pins()
        return

    if latest is None:
        raise click.ClickException(
            "Could not determine the latest cove release (the repo remote "
            f"is unreachable or unknown). Set {REPO_URL_ENV}=<url> or run "
            "from a machine with repo access."
        )

    newer = _version_tuple(latest) > _version_tuple(installed)
    if newer:
        click.echo(f"Updating cove: {installed} -> {latest}...")
        _install_wheel(latest)
        click.echo(f"Installed cove {latest}.")
    elif not quiet:
        click.echo(f"cove cli is up to date ({installed}).")

    # Converge the stack to the (possibly new) wheel's pins: bringup re-renders
    # the bundled compose resources and runs data migrations. Quiet mode is the
    # scheduled path: no TTY, no 1Password, no provisioning; floating tags are
    # force-re-pulled so they actually receive upstream patches.
    if quiet:
        env = dict(os.environ, COVE_PULL_POLICY="always")
        subprocess.run(
            [which("cove") or "cove", "up", "--no-provision", "--non-interactive"],
            stdin=subprocess.DEVNULL, env=env, check=False,
        )
    else:
        subprocess.run([_cove_bin(), "up"], check=False)


def _cove_bin() -> str:
    return which("cove") or "cove"


def _bootout() -> None:
    subprocess.run(
        ["launchctl", "bootout", f"gui/{os.getuid()}", LAUNCHD_LABEL],
        capture_output=True, text=True, check=False,
    )


def _render_plist(hour: int, minute: int) -> str:
    cove_bin = _cove_bin()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{cove_bin}</string>
        <string>update</string>
        <string>--quiet</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>{hour}</integer>
        <key>Minute</key><integer>{minute}</integer>
    </dict>
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


@click.group("update", invoke_without_command=True)
@click.option("--check", is_flag=True, help="Report staleness only; change nothing.")
@click.option("--quiet", is_flag=True, help="Non-interactive (scheduled runs).")
@click.pass_context
def update(ctx: click.Context, check: bool, quiet: bool):
    """Update cove: latest CLI release, then the stack to its pins.

    One command, one source of truth — the released cove version specifies
    the pins; `cove update` installs it and converges everything to it.
    Forgejo data migrations and Vault upgrades run inside the normal
    bring-up flow.
    """
    if ctx.invoked_subcommand is None:
        _do_update(check, quiet)


@update.command("auto")
@click.option("--off", "off_", is_flag=True, help="Remove the daily schedule.")
@click.option("--at", default="09:17", help="Daily time, HH:MM (default 09:17).")
def auto(off_: bool, at: str):
    """Schedule `cove update --quiet` daily. The opt-in IS the approval.

    Failures and rollbacks surface in the log; routine successes are silent.
    """
    if off_:
        _bootout()
        if PLIST_PATH.exists():
            PLIST_PATH.unlink()
        click.echo("Daily cove update removed.")
        return

    try:
        hour_s, minute_s = at.split(":")
        hour, minute = int(hour_s), int(minute_s)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        raise click.ClickException(f"Invalid --at {at!r} (expected HH:MM).")

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(_render_plist(hour, minute))
    _bootout()
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST_PATH)],
        check=True, capture_output=True, text=True,
    )
    click.echo(f"Daily cove update scheduled at {hour:02d}:{minute:02d} ({PLIST_PATH}).")
