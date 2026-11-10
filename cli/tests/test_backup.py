"""`cove backup`: consistent snapshots written into the data dir.

The property that matters is that a snapshot is taken by SQLite, verified, and
only then renamed into place, and that retention never deletes the newest.
"""

from __future__ import annotations

import subprocess

import pytest
from click.testing import CliRunner

from cove import backup as backup_module


class FakeDocker:
    def __init__(self, listing: str = "", size: str = "4096") -> None:
        self.listing = listing
        self.size = size
        self.scripts: list[str] = []
        self.removed: list[str] = []

    def __call__(self, *args: str, check: bool = True):
        if args[0] == "exec" and "rm" in args:
            self.removed.append(args[-1])
            return subprocess.CompletedProcess(args, 0, "", "")
        script = args[-1] if args else ""
        if script.startswith("ls -1"):
            return subprocess.CompletedProcess(args, 0, self.listing, "")
        if script.startswith("wc -c"):
            return subprocess.CompletedProcess(args, 0, self.size + "\n", "")
        self.scripts.append(script)
        return subprocess.CompletedProcess(args, 0, "", "")


def test_snapshot_backs_up_verifies_then_renames(monkeypatch):
    fake = FakeDocker(listing="/data/gitea/snapshots/gitea-20260101T000000Z.db\n")
    monkeypatch.setattr(backup_module, "_docker", fake)
    report = backup_module.snapshot(keep=7)
    script = fake.scripts[0]
    assert 'sqlite3 /data/gitea/gitea.db ".backup ' in script, script
    assert "integrity_check" in script and "grep -qx ok" in script, script
    assert "mv " in script and script.index("integrity_check") < script.index("mv "), (
        "the file must be verified before it is renamed into place"
    )
    assert report["path"].startswith("/data/gitea/snapshots/gitea-")
    assert report["path"].endswith(".db")
    assert report["bytes"] == 4096


def test_retention_keeps_the_newest_and_removes_the_oldest(monkeypatch):
    listing = "\n".join(
        f"/data/gitea/snapshots/gitea-2026010{day}T000000Z.db" for day in (1, 2, 3, 4)
    )
    fake = FakeDocker(listing=listing + "\n")
    monkeypatch.setattr(backup_module, "_docker", fake)
    report = backup_module.snapshot(keep=2)
    assert fake.removed == [
        "/data/gitea/snapshots/gitea-20260101T000000Z.db",
        "/data/gitea/snapshots/gitea-20260102T000000Z.db",
    ]
    assert report["kept"] == [
        "/data/gitea/snapshots/gitea-20260103T000000Z.db",
        "/data/gitea/snapshots/gitea-20260104T000000Z.db",
    ]


def test_a_snapshot_older_than_the_keep_counts_keeps_nothing_extra(monkeypatch):
    fake = FakeDocker(listing="/data/gitea/snapshots/gitea-20260101T000000Z.db\n")
    monkeypatch.setattr(backup_module, "_docker", fake)
    backup_module.snapshot(keep=7)
    assert fake.removed == []


def test_keep_must_be_positive(monkeypatch):
    monkeypatch.setattr(backup_module, "_docker", FakeDocker())
    with pytest.raises(Exception):
        backup_module.snapshot(keep=0)


def test_cli_now_prints_the_host_path(monkeypatch):
    fake = FakeDocker(listing="")
    monkeypatch.setattr(backup_module, "_docker", fake)
    outcome = CliRunner().invoke(backup_module.backup, ["now"])
    assert outcome.exit_code == 0, outcome.output
    assert "snapshot: " in outcome.output and ".db (" in outcome.output


def test_plist_carries_the_daily_schedule_and_the_command():
    plist = backup_module._render_plist(3, 15)
    assert "<key>StartCalendarInterval</key>" in plist
    assert "<key>Hour</key><integer>3</integer>" in plist
    assert "<key>Minute</key><integer>15</integer>" in plist
    assert "<string>backup</string>" in plist
    assert "<string>now</string>" in plist


def test_install_writes_the_plist_and_bootstraps(monkeypatch, tmp_path):
    target = tmp_path / "app.cove.backup.plist"
    monkeypatch.setattr(backup_module, "PLIST_PATH", target)
    calls: list[tuple] = []
    monkeypatch.setattr(backup_module, "_bootout", lambda label: calls.append(("bootout", label)))
    monkeypatch.setattr(
        backup_module, "_bootstrap", lambda label, plist: calls.append(("bootstrap", label, plist))
    )
    outcome = CliRunner().invoke(backup_module.backup, ["install", "--hour", "4", "--minute", "30"])
    assert outcome.exit_code == 0, outcome.output
    assert target.is_file()
    assert ("bootout", backup_module.LAUNCHD_LABEL) in calls
    assert ("bootstrap", backup_module.LAUNCHD_LABEL, target) in calls


def test_install_rejects_an_impossible_time(monkeypatch, tmp_path):
    monkeypatch.setattr(backup_module, "PLIST_PATH", tmp_path / "x.plist")
    outcome = CliRunner().invoke(backup_module.backup, ["install", "--hour", "24"])
    assert outcome.exit_code != 0
