"""Regression guard for the bundled-compose drift guard itself.

`cli/cove/resources/compose/` is a gitignored build artifact produced by
`cli/scripts/sync_compose_resources.py` (run by the `build_py` hook in
`cli/setup.py` before every wheel build). Nothing regenerates it on `git pull`,
so an existing checkout carries a stale copy after any `compose/` change lands.

The deploy artifact is the *wheel*, not that in-tree intermediate: `cove up` /
`cove update` extract `~/.config/cove/compose/` from the wheel. So the per-feature
`TestResourcesSync` guards must validate the file set inside a freshly built
wheel, not the gitignored copy on disk.

These tests pin that behavior:

  - a stale in-tree artifact must NOT fail the guards (the Mode-1 regression:
    a pulled `compose/` change used to break the gate in existing checkouts);
  - the built wheel must still contain every guarded file byte-identical to
    `compose/` (a real packaging gap must still be caught).

Run:  pytest cli/tests/test_resources_drift.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    start = Path(__file__).resolve().parent
    for _ in range(6):
        if (start / "compose" / "inventory.yml").exists():
            return start
        start = start.parent
    raise RuntimeError(f"Cannot find project root from {__file__}")


REPO_ROOT = _repo_root()
CLI_DIR = REPO_ROOT / "cli"
COMPOSE_DIR = REPO_ROOT / "compose"
IN_TREE_ARTIFACT = CLI_DIR / "cove" / "resources" / "compose"

# The three per-feature drift guards, each of which must agree on the state of
# a missing/stale bundled artifact.
GUARD_NODE_IDS = [
    "tests/test_ade.py::TestResourcesSync::test_ade_bundled_resources_in_sync",
    "tests/test_speedtest.py::TestResourcesSync::test_resources_tree_in_sync",
    "tests/test_runner.py::TestResourcesSync::test_resources_tree_in_sync",
]


@pytest.fixture()
def stale_intree_artifact():
    """Plant deliberately stale bytes in the gitignored in-tree artifact.

    The file `docker-compose.yml` is guarded by all three drift guards, so a
    stale copy is exactly the Mode-1 symptom (a `compose/` change landed without
    a local re-sync). Restores the pristine artifact on teardown.
    """
    created_dir = not IN_TREE_ARTIFACT.exists()
    target = IN_TREE_ARTIFACT / "docker-compose.yml"
    original = target.read_bytes() if target.exists() else None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"# STALE: not synced from compose/ (regression fixture)\n")
    try:
        yield target
    finally:
        if original is None:
            if created_dir:
                import shutil

                shutil.rmtree(IN_TREE_ARTIFACT, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
        else:
            target.write_bytes(original)


def _run_guards() -> subprocess.CompletedProcess:
    """Run only the three drift guards in a child pytest (same interpreter).

    Delegating to a child keeps the guards' real module-level constants
    (`COMPOSE_DIR`) in play instead of monkeypatching them, so this reproduces
    the operator-visible gate behavior exactly.
    """
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            *GUARD_NODE_IDS,
        ],
        cwd=str(CLI_DIR),
        capture_output=True,
        text=True,
    )


def test_guards_agree_when_intree_artifact_absent():
    """Mode-2: a missing in-tree artifact must not make the guards disagree.

    Before this change `test_speedtest` FAILED while the other two SKIPPED on
    the same missing directory. All three now validate the built wheel, so an
    absent local copy yields the same passing result for each.
    """
    import shutil

    existed = IN_TREE_ARTIFACT.exists()
    backup = IN_TREE_ARTIFACT.with_suffix(".bak-drift")
    if existed:
        shutil.move(str(IN_TREE_ARTIFACT), str(backup))
    try:
        result = _run_guards()
        assert result.returncode == 0, (
            "guards disagreed / failed with the in-tree artifact absent;\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
        assert "skipped" not in result.stdout.lower(), (
            "guards must reach a definite verdict, not skip:\n" + result.stdout
        )
    finally:
        if existed and backup.exists():
            shutil.move(str(backup), str(IN_TREE_ARTIFACT))


def test_stale_intree_artifact_does_not_fail_guards(stale_intree_artifact):
    """Mode-1 regression: a stale in-tree artifact must not break the gate.

    The guards must validate the built wheel (the deploy artifact), which is
    always rebuilt from `compose/`, so a stale local copy is irrelevant.
    """
    result = _run_guards()
    assert result.returncode == 0, (
        "bundled-resource guards failed on a stale in-tree artifact;\n"
        "they must validate the freshly built wheel, not the gitignored copy.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )


def test_wheel_bundle_matches_compose_source(bundled_compose):
    """Positive invariant: the built wheel carries every guarded file exactly.

    Catches a real deploy-level gap (a file the wheel fails to package), which
    the in-tree comparison could not reach because it never looked at the wheel.
    """
    guarded = {
        "docker-compose.yml",
        "bringup.yml",
        "provision_forgejo.yml",
        "ade/Dockerfile",
        "nginx/default.conf.j2",
        "nginx/landing.html",
    }
    missing = sorted(rel for rel in guarded if rel not in bundled_compose)
    assert not missing, f"wheel is missing bundled resources: {missing}"
    for rel in sorted(guarded):
        src = (COMPOSE_DIR / rel).read_bytes()
        assert bundled_compose[rel] == src, (
            f"wheel bundled resource {rel} differs from compose/{rel}"
        )
