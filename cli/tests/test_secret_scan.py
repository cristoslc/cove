"""Contract tests for the secret-scanning gate.

Why the gate exists: the `MBPBK-CLI-2026-05-23` Forgejo token sat in two tracked
documents in plain text for months and nothing blocked it at the door. It was
found by hand, rotated on 2026-11-02, and redacted afterwards.

These tests pin the shape that makes the gate trustworthy: a double pin on the
scanner (version and asset checksum), a range scan rather than a full-history
scan (the revoked literal stays in old commits by design), redaction so a
finding cannot echo the secret into a job log, and allowlists that each carry a
reason instead of blanket path exemptions.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest


def _project_root() -> Path:
    start = Path(__file__).resolve().parent
    for _ in range(6):
        if (start / ".forgejo" / "workflows").is_dir():
            return start
        start = start.parent
    raise RuntimeError(f"Cannot find project root from {__file__}")


WORKFLOW = _project_root() / ".forgejo" / "workflows" / "secret-scan.yml"
CONFIG = _project_root() / ".gitleaks.toml"


def _workflow() -> str:
    if not WORKFLOW.is_file():
        pytest.fail(f"{WORKFLOW} is missing: the secret-scanning gate is gone")
    return WORKFLOW.read_text(encoding="utf-8")


def _config() -> dict:
    if not CONFIG.is_file():
        pytest.fail(f"{CONFIG} is missing: the scanner runs without allowlists")
    with open(CONFIG, "rb") as f:
        return tomllib.load(f)


def test_scanner_is_pinned_by_version_and_asset_checksum() -> None:
    text = _workflow()
    assert re.search(r'GITLEAKS_VERSION:\s*"\d+\.\d+\.\d+"', text), (
        "the scanner version must be pinned; an unpinned download can shift "
        "rules under the gate"
    )
    assert re.search(r'GITLEAKS_SHA256:\s*"[0-9a-f]{64}"', text), (
        "the downloaded asset must carry a pinned SHA-256, not just a version"
    )
    assert "sha256sum -c -" in text, "the checksum must actually be verified"


def test_gate_scans_a_commit_range_and_redacts_findings() -> None:
    text = _workflow()
    assert "--log-opts" in text, "a range scan is required, not a tree scan"
    assert "merge-base" in text, (
        "the pull-request range must start at the merge base with the base "
        "branch, or a merge commit re-scans unrelated commits"
    )
    assert "--redact" in text, "a finding must never echo the secret into logs"
    assert "--exit-code 1" in text, "a finding must fail the job"
    assert "--config .gitleaks.toml" in text, "the job must use the pinned config"


def test_gate_does_not_rescan_all_history() -> None:
    text = _workflow()
    assert "detect --source . --log-opts" in text, (
        "a full-history scan would fail forever on the revoked literal that "
        "was deliberately left in old commits"
    )


def test_allowlists_are_specific_and_explained() -> None:
    allowlists = _config().get("allowlists", [])
    assert allowlists, "expected explicit allowlists for the known false positives"
    for entry in allowlists:
        assert entry.get("description"), (
            f"every allowlist needs a reason, got {entry!r}"
        )
        for pattern in entry.get("paths", []):
            assert pattern not in ("", ".", "/", ".*"), (
                f"blanket path allowlist {pattern!r} would hide real leaks"
            )
        for pattern in entry.get("regexes", []):
            assert pattern not in ("", ".*"), (
                f"blanket regex allowlist {pattern!r} would hide real leaks"
            )

    joined = " ".join(str(entry) for entry in allowlists)
    for expected in ("docs/troves", "sk-abcdef123", "age1"):
        assert expected in joined, (
            f"the documented false positive {expected!r} lost its allowlist "
            "entry; the gate would fail on it for the wrong reason"
        )


def test_default_rules_stay_enabled() -> None:
    assert _config().get("extend", {}).get("useDefault") is True, (
        "the config must extend gitleaks' default rules rather than replace "
        "them with a hand-rolled subset"
    )
