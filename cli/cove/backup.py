"""Consistent, scheduled snapshots of the Forgejo database.

The operator's ruling (`dec_veynrmw7f17d`): rather than teaching the host backup
tool to dump first, write a consistent snapshot **into the data dir** and let
Time Machine and restic capture it with everything else. That removes the
coordination entirely: the backup tool copies a file that already opens.

``sqlite3 .backup`` runs inside the container against the live database, so the
snapshot is taken by SQLite itself rather than by copying files under a writer.
The result is verified with ``PRAGMA integrity_check`` and only then renamed
from ``.part`` to its final name, so a half-written snapshot never appears in
the backup set.

Repositories are ordinary files under the same data root and are already safe
to copy; this command is about the database, which is the part a naive copy can
tear.
"""

from __future__ import annotations

import datetime
import os
import subprocess
from pathlib import Path

import click

from cove.update import _bootstrap, _bootout, _cove_bin, _plist_path

CONTAINER = os.environ.get("FORGEJO_CONTAINER_NAME", "cove-forgejo")
SNAPSHOT_DIR = "/data/gitea/snapshots"
DATABASE = "/data/gitea/gitea.db"
DEFAULT_KEEP = 7
TIMEOUT_SECONDS = 900

LAUNCHD_LABEL = "app.cove.backup"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
LOG_PATH = Path.home() / "Library" / "Logs" / "cove-backup.log"
DEFAULT_HOUR = 3
DEFAULT_MINUTE = 15


def _timestamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=TIMEOUT_SECONDS,
        check=False,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise click.ClickException(
            "docker " + " ".join(args[:2]) + " failed: " + (detail[-1] if detail else "no output")
        )
    return result


def snapshot(container: str = CONTAINER, keep: int = DEFAULT_KEEP) -> dict:
    """Take one verified snapshot and prune older ones. Returns a report."""
    if keep < 1:
        raise click.ClickException("--keep must be at least 1")
    stamp = _timestamp()
    final = f"{SNAPSHOT_DIR}/gitea-{stamp}.db"
    part = final + ".part"
    script = (
        "set -eu; "
        f"mkdir -p {SNAPSHOT_DIR}; "
        f"rm -f {part}; "
        f'sqlite3 {DATABASE} ".backup {part}"; '
        f"sqlite3 {part} 'PRAGMA integrity_check;' | grep -qx ok; "
        f"mv {part} {final}"
    )
    _docker("exec", container, "sh", "-c", script)

    listing = _docker(
        "exec",
        container,
        "sh",
        "-c",
        f"ls -1 {SNAPSHOT_DIR}/gitea-*.db 2>/dev/null || true",
    )
    files = sorted(line.strip() for line in listing.stdout.splitlines() if line.strip())
    removed: list[str] = []
    for stale in files[:-keep]:
        _docker("exec", container, "rm", "-f", stale)
        removed.append(stale)

    size = _docker("exec", container, "sh", "-c", f"wc -c < {final}").stdout.strip()
    return {
        "path": final,
        "host_path": str(_host_snapshot_dir() / Path(final).name),
        "bytes": int(size or 0),
        "kept": files[-keep:],
        "removed": removed,
    }


def _host_snapshot_dir() -> Path:
    """Where the snapshot lands on the host, for the message only."""
    return Path.home() / "Documents" / "cove-data" / "forgejo" / "gitea" / "snapshots"


def _render_plist(hour: int, minute: int) -> str:
    cove_bin = _cove_bin()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_LABEL}</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>{hour}</integer>
        <key>Minute</key><integer>{minute}</integer>
    </dict>
    <key>ProgramArguments</key>
    <array>
        <string>{cove_bin}</string>
        <string>backup</string>
        <string>now</string>
    </array>
    <key>StandardOutPath</key><string>{LOG_PATH}</string>
    <key>StandardErrorPath</key><string>{LOG_PATH}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>{_plist_path(cove_bin)}</string>
        <key>HOME</key><string>{Path.home()}</string>
    </dict>
</dict>
</plist>
"""


@click.group("backup", help="Consistent Forgejo database snapshots in the data dir.")
def backup() -> None:
    """Write a snapshot inside the data dir; host backups capture it naturally."""


@backup.command("now")
@click.option("--keep", default=DEFAULT_KEEP, show_default=True, type=int, help="Snapshots to retain.")
def backup_now(keep: int) -> None:
    """Take one verified snapshot and prune older ones.

    Examples:

        cove backup now

        cove backup now --keep 14
    """
    report = snapshot(keep=keep)
    click.echo(f"snapshot: {report['host_path']} ({report['bytes']} bytes)")
    if report["removed"]:
        click.echo(f"pruned: {len(report['removed'])} older snapshot(s)")
    click.echo(f"retained: {len(report['kept'])}")


@backup.command("list")
def backup_list() -> None:
    """List the snapshots currently in the data dir."""
    listing = _docker(
        "exec", CONTAINER, "sh", "-c", f"ls -1 {SNAPSHOT_DIR}/gitea-*.db 2>/dev/null || true"
    )
    files = [line.strip() for line in listing.stdout.splitlines() if line.strip()]
    for name in sorted(files):
        click.echo(Path(name).name)
    if not files:
        click.echo("no snapshots yet; run `cove backup now`")


@backup.command("install")
@click.option("--hour", default=DEFAULT_HOUR, show_default=True, type=int)
@click.option("--minute", default=DEFAULT_MINUTE, show_default=True, type=int)
def backup_install(hour: int, minute: int) -> None:
    """Register a daily launchd agent that runs `cove backup now`.

    Examples:

        cove backup install

        cove backup install --hour 4 --minute 30
    """
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise click.ClickException("hour must be 0-23 and minute 0-59")
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(_render_plist(hour, minute))
    _bootout(LAUNCHD_LABEL)
    _bootstrap(LAUNCHD_LABEL, PLIST_PATH)
    click.echo(f"daily snapshot agent installed at {hour:02d}:{minute:02d} ({PLIST_PATH})")


@backup.command("uninstall")
def backup_uninstall() -> None:
    """Remove the daily snapshot agent. Snapshots already taken are kept."""
    _bootout(LAUNCHD_LABEL)
    PLIST_PATH.unlink(missing_ok=True)
    click.echo("daily snapshot agent removed")
