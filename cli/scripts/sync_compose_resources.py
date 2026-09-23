#!/usr/bin/env python3
"""Sync compose/ -> cli/cove/resources/compose/ (exclude rendered + PII files)."""

from __future__ import annotations

import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = REPO_ROOT / "compose"
DST = REPO_ROOT / "cli" / "cove" / "resources" / "compose"

EXCLUDE_NAMES = {".env", "default.conf", "cove.conf"}
EXCLUDE_SUFFIXES = {".env"}
EXCLUDE_DIRS = {"data", "logs", "raft", "__pycache__"}
EXCLUDE_HOST_VARS_YML = True
EXCLUDE_SEEDS_YAML = True  # seeds/*.yaml contains PII, only ship *.example


def _should_exclude(path: Path, relative: Path) -> bool:
    parts = relative.parts
    if parts[0] in EXCLUDE_DIRS:
        return True
    for part in parts[:-1]:
        if part in EXCLUDE_DIRS:
            return True
    name = path.name
    if name in EXCLUDE_NAMES:
        return True
    if name.endswith(".env"):
        return True
    if EXCLUDE_HOST_VARS_YML and parts[0] == "host_vars" and name.endswith(".yml"):
        return True
    if EXCLUDE_SEEDS_YAML and parts[0] == "seeds" and name.endswith(".yaml") and not name.endswith(".example"):
        return True
    return False


def sync() -> None:
    if not SRC.exists():
        # Building from an sdist (uv build sandbox): compose/ isn't packaged,
        # and the bundled resources are already synced. Nothing to do.
        if (Path(__file__).resolve().parent.parent / "cove" / "resources" / "compose").exists():
            print(f"compose/ not present (sdist build) — using bundled {DST}")
            return
        raise SystemExit(f"compose/ not found at {SRC}")
    if DST.exists():
        shutil.rmtree(DST)
    DST.mkdir(parents=True)
    for src in SRC.rglob("*"):
        if src.is_dir():
            continue
        relative = src.relative_to(SRC)
        if _should_exclude(src, relative):
            continue
        dst = DST / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    print(f"Synced {SRC} -> {DST}")


if __name__ == "__main__":
    sync()