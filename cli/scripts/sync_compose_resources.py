#!/usr/bin/env python3
"""Sync compose/ -> cli/cove/resources/compose/ (exclude rendered + PII files)."""

from __future__ import annotations

import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = REPO_ROOT / "compose"
DST = REPO_ROOT / "cli" / "cove" / "resources" / "compose"

# The edge secrets check must scan with the SAME ruleset the commit-hook gate
# reads. That file is the repository's one `.gitleaks.toml`; the wheel is the
# runtime source of truth, so the ruleset travels with the bundled compose
# resources. `compose/secrets-guard/gitleaks.toml` is a GENERATED artifact
# (gitignored): copying it here is what keeps a single source instead of a
# second hand-maintained rules file.
RULES_SRC = REPO_ROOT / ".gitleaks.toml"
RULES_DST = DST / "secrets-guard" / "gitleaks.toml"

EXCLUDE_NAMES = {".env", "default.conf", "cove.conf", "llmproxy-auth.conf"}
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
    # A `go build` run in the scanner's directory drops its compiled binary
    # beside the sources. It is never a deploy artifact (the image builds its
    # own), and shipping it would put a machine-local path into the wheel.
    if relative == Path("secrets-guard") / "secrets-guard":
        return True
    return False


def sync_rules(src: Path = RULES_SRC, dst: Path = RULES_DST) -> Path:
    """Copy the repo's one gitleaks ruleset into the bundled compose dir.

    Raises rather than skipping: a wheel without the ruleset would build an
    edge scanner with no detection, which looks exactly like a clean scan.
    """
    if not src.is_file():
        raise SystemExit(f"gitleaks rules not found at {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    if dst.read_bytes() != src.read_bytes():  # pragma: no cover - defensive
        raise SystemExit(f"rules copy at {dst} does not match {src}")
    return dst


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
    sync_rules()
    print(f"Synced {SRC} -> {DST}")


if __name__ == "__main__":
    sync()