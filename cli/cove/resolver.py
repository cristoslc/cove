"""Keep macOS scoped-resolver files honest about the dnsmasq host port.

macOS routes ``*.cove`` / ``*.cove.<host>`` queries to Cove's dnsmasq through
scoped files under ``/etc/resolver`` (``nameserver <ip>`` + ``port <n>``).
Those files are installed out of band: ``bringup.yml`` renders the installer
script (``nginx/config/dns/macos.j2``) to the served config page, it never
runs it against the local host. Moving the published dnsmasq port therefore
left the on-disk files pointing at the old port while dnsmasq listened on the
new one, and the resolver path went silently dead even though the container
publish, the ``.env``, and the rendered script all agreed (2026-10-22:
5353 -> 5354, three ``cove up --no-provision`` runs left ``/etc/resolver/cove``
and ``/etc/resolver/cove.MBPBK-202602`` stale).

``bringup.yml`` now re-points every existing ``/etc/resolver/cove*`` file at
``dnsmasq_port`` on each ``cove up`` (Darwin-only, become, non-fatal). This
module is the ``cove status`` half: it reads the same single source of truth
(``group_vars/all.yml``) and the files on disk and reports any that still
disagree, so the drift cannot pass silently when the write path was
unavailable (a no-TTY run without passwordless sudo).
"""

from __future__ import annotations

import platform
import re
from pathlib import Path

RESOLVER_DIR = Path("/etc/resolver")
RESOLVER_FILE_PATTERN = "cove*"

# A scoped-resolver file's port line, e.g. "port 5354". Anchored per line so
# a "nameserver" line can never be mistaken for it.
_PORT_LINE_RE = re.compile(r"(?m)^[ \t]*port[ \t]+(\d+)[ \t]*$")


def is_macos() -> bool:
    return platform.system() == "Darwin"


def expected_dnsmasq_port(compose_dir: Path) -> int:
    """The published dnsmasq host port from the compose source's
    ``group_vars/all.yml`` — the single source of truth (``bringup.yml`` renders
    the compose ``.env`` ``DNSMASQ_PORT`` and its wait_for probe from it).

    Raises RuntimeError when the var is absent or malformed: guessing a port
    here would hide exactly the drift this check exists to catch.
    """
    path = Path(compose_dir) / "group_vars" / "all.yml"
    text = path.read_text(encoding="utf-8")
    match = re.search(r"^dnsmasq_port:\s*(\d+)\s*$", text, re.MULTILINE)
    if not match:
        raise RuntimeError(
            f"{path} does not define `dnsmasq_port: <int>`; cannot check the "
            "macOS resolver files against the published dnsmasq port"
        )
    return int(match.group(1))


def resolver_file_port(content: str) -> int | None:
    """The ``port`` value from a scoped-resolver file body, or None when the
    file has no such line (it is not a Cove resolver file)."""
    match = _PORT_LINE_RE.search(content)
    return int(match.group(1)) if match else None


def drifted_resolver_files(
    expected_port: int, *, resolver_dir: Path = RESOLVER_DIR
) -> dict[Path, int]:
    """Existing ``cove*`` files under ``resolver_dir`` whose ``port`` line
    disagrees with ``expected_port``, mapped to the port found.

    Files without a port line are not Cove resolver files and are ignored; a
    file that cannot be read as UTF-8 raises (fail loud) rather than being
    silently skipped.
    """
    drifted: dict[Path, int] = {}
    directory = Path(resolver_dir)
    if not directory.is_dir():
        return drifted
    for path in sorted(directory.glob(RESOLVER_FILE_PATTERN)):
        if not path.is_file():
            continue
        found = resolver_file_port(path.read_text(encoding="utf-8"))
        if found is not None and found != expected_port:
            drifted[path] = found
    return drifted


def resolver_drift(
    compose_dir: Path, *, resolver_dir: Path = RESOLVER_DIR
) -> tuple[int, dict[Path, int]] | None:
    """``(expected_port, drifted_files)`` when the macOS scoped-resolver files
    disagree with ``dnsmasq_port``; None when there is nothing to report.

    Propagates the RuntimeError from ``expected_dnsmasq_port`` (the caller
    decides how to surface an undeterminable expected port).
    """
    expected = expected_dnsmasq_port(compose_dir)
    drifted = drifted_resolver_files(expected, resolver_dir=resolver_dir)
    if not drifted:
        return None
    return expected, drifted


def corrective_command(expected_port: int, *, resolver_dir: Path = RESOLVER_DIR) -> str:
    """The exact one-liner that re-points every scoped-resolver file at
    ``expected_port`` (BSD sed — macOS-only, matching the check)."""
    return (
        "sudo sed -i '' -E 's/^port[[:space:]]+[0-9]+/port "
        f"{expected_port}/' {resolver_dir}/{RESOLVER_FILE_PATTERN}"
    )
