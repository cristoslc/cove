#!/usr/bin/env python3
"""Sync authoritative image pins into the deployed compose `.env`.

Why this exists
---------------
The wheel replaces the compose tree (and `group_vars/all.yml`) on promote, but
the deployed `.env` is preserved across re-extraction
(`cli/cove/stateless.py:RUNTIME_PRESERVED_FILES`). Docker Compose interpolates
`${FORGEJO_IMAGE:-...}` from that `.env` ahead of the compose default, so a pin
bump in the wheel changed only the fallback, never the value Compose read.
`cove update` saw the pin change, converged, and applied nothing. This script
is the per-converge repair path: bringup runs it on every `cove up`, including
the bring-up `cove update` triggers.

Contract
--------
* Keys in the pin map are authoritative from the wheel and are written on every
  converge.
* Only keys in the operator override allowlist are left alone. The allowlist is
  named in `group_vars/all.yml` (`cove_image_env_operator_overrides`) and can be
  extended in `host_vars/<hostname>.yml`, which `cove up` never overwrites.
* An allowlist entry that is not a pin key fails loud (typo protection).
* Unrelated lines and their order are preserved; an unchanged file is not
  rewritten (a no-op converge must not churn).

Usage
-----
    sync_env.py <env-file> <pins-json> [<comma-separated-overrides>]

`pins-json` is a JSON object mapping env key to value, rendered by Ansible.
Prints `changed` or `unchanged`; exits 2 on invalid input.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Iterable, Mapping

_KEY_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")
_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=")


class PinSyncError(ValueError):
    """Invalid pin map or allowlist; the caller must not apply anything."""


def _validate(pins: Mapping[str, str], overrides: Iterable[str]) -> set[str]:
    if not pins:
        raise PinSyncError("no image pins supplied")
    for key, value in pins.items():
        if not isinstance(key, str) or not _KEY_RE.match(key):
            raise PinSyncError(f"invalid env key: {key!r}")
        if not isinstance(value, str) or not value:
            raise PinSyncError(f"pin {key} has an empty value")
        if "\n" in value or "\x00" in value:
            raise PinSyncError(f"pin {key} contains a newline or NUL")
    override_set = set(overrides)
    unknown = sorted(key for key in override_set if key not in pins)
    if unknown:
        raise PinSyncError(
            "operator override names keys that are not image pins: "
            + ", ".join(unknown)
        )
    return override_set


def _atomic_write(path: Path, text: str) -> None:
    """Write `text` 0600 via a same-directory rename, never a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", text=True)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def sync_pins(
    env_path: Path,
    pins: Mapping[str, str],
    overrides: Iterable[str] = (),
) -> bool:
    """Re-sync `pins` into `env_path`, skipping `overrides`. Return changed."""
    override_set = _validate(pins, overrides)
    existed = env_path.exists()
    previous = env_path.read_text() if existed else ""

    out: list[str] = []
    seen: set[str] = set()
    changed = not existed

    for line in previous.splitlines():
        match = _LINE_RE.match(line)
        key = match.group(1) if match else None
        if key in pins and key not in override_set:
            if key in seen:
                changed = True
                continue
            seen.add(key)
            replacement = f"{key}={pins[key]}"
            if line != replacement:
                changed = True
            out.append(replacement)
        else:
            out.append(line)

    for key, value in pins.items():
        if key in override_set or key in seen:
            continue
        out.append(f"{key}={value}")
        changed = True

    if not changed:
        return False

    _atomic_write(env_path, "\n".join(out).rstrip("\n") + "\n")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("env_file", type=Path)
    parser.add_argument("pins_json", help="JSON object of KEY -> value")
    parser.add_argument(
        "overrides",
        nargs="?",
        default="",
        help="comma-separated env keys the operator owns",
    )
    args = parser.parse_args(argv)

    try:
        loaded = json.loads(args.pins_json)
        if not isinstance(loaded, dict):
            raise PinSyncError("pins JSON must be an object")
        pins = {str(key): str(value) for key, value in loaded.items()}
    except json.JSONDecodeError as exc:
        print(f"sync_env: invalid pins JSON: {exc}", file=sys.stderr)
        return 2
    except PinSyncError as exc:
        print(f"sync_env: {exc}", file=sys.stderr)
        return 2

    overrides = [key for key in args.overrides.split(",") if key]
    try:
        changed = sync_pins(args.env_file, pins, overrides)
    except PinSyncError as exc:
        print(f"sync_env: {exc}", file=sys.stderr)
        return 2

    print("changed" if changed else "unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
