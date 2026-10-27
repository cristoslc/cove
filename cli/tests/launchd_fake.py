"""A minimal model of launchctl's registration semantics for the agent tests.

Real behavior this pins (2026-10-27):

  - `launchctl bootout gui/<uid> <label>` is INVALID: the second positional is
    a service PATH, so launchctl rejects it and the job stays loaded. Only the
    service-target form (`gui/<uid>/<label>`) unloads. This was the silent
    first half of "cove update auto dies with exit 5 on re-register".
  - `launchctl bootstrap` is NOT idempotent: a label that is already loaded
    exits 5 ("Input/output error"). Callers must bootout first.
  - `launchctl print gui/<uid>/<label>` exits 113 when the service is absent,
    which is how the code should ask launchd about actual state.

Only launchctl calls are modeled; every other command returns success so the
model can be dropped in as the whole `subprocess.run` fake for a registration
test.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

BOOTSTRAP_ALREADY_LOADED = 5
BOOTOUT_NOT_FOUND = 3
PRINT_NOT_FOUND = 113


def label_from_plist(path: Path) -> str:
    match = re.search(r"<key>Label</key>\s*<string>([^<]+)</string>", path.read_text())
    if not match:
        raise AssertionError(f"no Label key in {path}")
    return match.group(1)


class FakeLaunchd:
    """`subprocess.run` stand-in that tracks which labels are loaded."""

    def __init__(self) -> None:
        self.loaded: set[str] = set()
        self.calls: list[list[str]] = []

    def __call__(self, cmd, *args, **kwargs):
        argv = [str(part) for part in cmd]
        self.calls.append(argv)
        if not argv or argv[0] != "launchctl":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        action = argv[1] if len(argv) > 1 else ""
        if action == "bootout":
            return self._bootout(argv)
        if action == "bootstrap":
            return self._bootstrap(argv)
        if action == "print":
            return self._print(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def _bootout(self, argv):
        if len(argv) < 3:
            return SimpleNamespace(returncode=1, stdout="", stderr="usage")
        target = argv[2]
        service_target = target.startswith("gui/") and "/" in target[len("gui/"):]
        if service_target:
            label = target.rsplit("/", 1)[1]
            if label in self.loaded:
                self.loaded.discard(label)
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            return SimpleNamespace(
                returncode=BOOTOUT_NOT_FOUND,
                stdout="",
                stderr="Could not find service",
            )
        # Domain target plus a service PATH: a bare label is not a path, so
        # launchctl fails and leaves the job loaded. This is the defect shape.
        return SimpleNamespace(
            returncode=5, stdout="", stderr="Boot-out failed: 5: Input/output error"
        )

    def _bootstrap(self, argv):
        if len(argv) < 4:
            return SimpleNamespace(returncode=1, stdout="", stderr="usage")
        label = label_from_plist(Path(argv[3]))
        if label in self.loaded:
            return SimpleNamespace(
                returncode=BOOTSTRAP_ALREADY_LOADED,
                stdout="",
                stderr="Bootstrap failed: 5: Input/output error",
            )
        self.loaded.add(label)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def _print(self, argv):
        label = argv[2].rsplit("/", 1)[-1]
        loaded = label in self.loaded
        return SimpleNamespace(
            returncode=0 if loaded else PRINT_NOT_FOUND,
            stdout="" if not loaded else f"{label} = {{\n}}\n",
            stderr="",
        )
