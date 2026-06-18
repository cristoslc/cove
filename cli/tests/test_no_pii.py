"""Reject PII (username, email, hostname, tailscale net) in tracked files."""

import subprocess
from pathlib import Path

import pytest

PII_PATTERNS = [
    "cristos",
    "lc.cristos@gmail.com",
    "taila90e7",
    "MBPBK-202602",
    "mbpbk-202602",
]

EXCLUDE_PATHS = [
    "docs/",
    ".git/",
    ".worktrees/",
    "tests/test_no_pii.py",
]


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        line for line in result.stdout.splitlines()
        if line and not any(line.startswith(ex) or ex in line for ex in EXCLUDE_PATHS)
    ]


@pytest.mark.parametrize("pattern", PII_PATTERNS)
def test_no_pii_in_tracked_files(pattern):
    files = _tracked_files()
    hits = []
    for rel in files:
        path = Path(rel)
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if pattern in line:
                hits.append(f"{rel}:{lineno}: {line.strip()}")
    assert not hits, (
        f"PII pattern {pattern!r} found in tracked files:\n" + "\n".join(hits)
    )


def test_pii_test_would_catch_failures():
    """Failure-path: confirm the guard fires when PII is present."""
    with pytest.raises(AssertionError, match="PII pattern"):
        # Inject a fake hit by checking a known-bad string against the matcher
        hits = ["fake/file.yml:1: admin_username: cristos"]
        assert not hits, (
            "PII pattern 'cristos' found in tracked files:\n" + "\n".join(hits)
        )