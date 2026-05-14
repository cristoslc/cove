"""Local file cache for op:// references to minimize biometric prompts."""

import json
import os
import platform
import subprocess
import threading
from pathlib import Path
from typing import Optional

LOCK = threading.Lock()

_CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "cove"
_CACHE_FILE = _CACHE_DIR / "op-cache.json"


def _load() -> dict:
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save(data: dict) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.parent.chmod(0o700)
    tmp = _CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.chmod(0o600)
    tmp.replace(_CACHE_FILE)


def get(op_ref: str) -> Optional[str]:
    with LOCK:
        return _load().get(op_ref)


def put(op_ref: str, value: str) -> None:
    with LOCK:
        data = _load()
        data[op_ref] = value
        _save(data)


def batch_pull(op_refs: list[str]) -> dict[str, str]:
    missing = []
    with LOCK:
        data = _load()
        for ref in op_refs:
            if ref not in data:
                missing.append(ref)
    if not missing:
        return {ref: data[ref] for ref in op_refs}

    reads = " && echo && ".join(
        f"op read --no-newline -- '{ref}'" for ref in missing
    )
    script = f"set -e; {reads}"

    if platform.system() != "Darwin":
        proc = subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        if proc.returncode == 0:
            values = proc.stdout.split("\n")
        else:
            proc = subprocess.run(
                ["op", "run", "--", "bash", "-c", script],
                capture_output=True, text=True, stdin=subprocess.DEVNULL,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"Batch op read failed\nstderr: {proc.stderr.strip()}"
                )
            values = proc.stdout.split("\n")
    else:
        proc = subprocess.run(
            ["op", "run", "--", "bash", "-c", script],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"Batch op read failed\nstderr: {proc.stderr.strip()}"
            )
        values = proc.stdout.split("\n")

    result = {}
    for i, ref in enumerate(missing):
        if i < len(values):
            value = values[i]
            put(ref, value)
            result[ref] = value

    with LOCK:
        data = _load()
        for ref in op_refs:
            if ref not in result and ref in data:
                result[ref] = data[ref]

    return result
