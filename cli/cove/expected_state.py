"""The expected-state file: what Cove last asked the stack to be.

The watchdog compares live container state against this file instead of
inferring intent from a running-to-stopped transition. A stop that happens
while the watchdog is down is invisible to a transition check but obvious
here, because the file is written by the command that asked for it:

* ``cove up``            -> core services expected running
* ``cove down``          -> everything expected stopped
* ``cove <service> up``  -> that service's containers expected running
* ``cove <service> down``-> that service's containers expected stopped
* ``cove update``        -> whatever its converge left

A converge that fails part-way leaves ``converge_incomplete: true`` and the
watchdog must page rather than act; guessing a half-applied expectation is the
same mistake as guessing a stop. A container absent from the file is unknown,
and unknown is never actionable.

The write is atomic (temp file in the same directory plus ``os.replace``) and
the file is 0600, because it describes the stack rather than carrying secrets.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATE_VERSION = 1

# Core: `cove up` starts these and any one of them stopping is a failure.
CORE_CONTAINERS = (
    "cove-forgejo",
    "cove-nginx",
    "cove-vault",
    "cove-dnsmasq",
    "cove-dnsproxy",
    "cove-ade-server",
)

# Optional services own their own containers and their own `up`/`down`.
SERVICE_CONTAINERS: dict[str, tuple[str, ...]] = {
    "ade": ("cove-ade-server",),
    "bifrost": ("cove-bifrost", "cove-bifrost-dns"),
    "secrets-guard": ("cove-secrets-guard",),
    "runner": ("cove-forgejo-runner",),
    "speedtest": ("cove-speedtest-tracker",),
    "toolhive": ("cove-toolhive",),
    "tunnel": ("cove-tunnel",),
    "vault": ("cove-vault",),
}

OPTIONAL_CONTAINERS = tuple(
    dict.fromkeys(
        container
        for containers in SERVICE_CONTAINERS.values()
        for container in containers
        if container not in CORE_CONTAINERS
    )
)


def state_path() -> Path:
    """Default location, beside ``hosts/`` and ``logs/``."""
    return Path.home() / ".config" / "cove" / "state" / "expected.json"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def read_expected(path: Path | None = None) -> dict | None:
    """Return the parsed file, or None when it does not exist or is unreadable."""
    target = path or state_path()
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        # A corrupt expectation is "unknown", never a licence to act.
        logging.getLogger(__name__).warning(
            "expected-state file at %s is unreadable; treating as unknown", target
        )
        return None


def _write(payload: dict, path: Path | None = None) -> Path:
    target = path or state_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp_name = tempfile.mkstemp(
        dir=target.parent, prefix=".expected-", suffix=".json"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return target


def _entries(services: dict[str, str], previous: dict | None) -> dict[str, dict[str, str]]:
    """Build service entries, keeping `since` when the expectation did not move."""
    prior = (previous or {}).get("services") or {}
    now = _now()
    entries: dict[str, dict[str, str]] = {}
    for name, expected in services.items():
        old = prior.get(name) or {}
        since = old.get("since", now) if old.get("expected") == expected else now
        entries[name] = {"expected": expected, "since": since}
    return entries


def _running_containers() -> set[str] | None:
    """Names of running containers, or None when Docker cannot be asked."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def record_up(path: Path | None = None) -> dict:
    """`cove up` succeeded: core running, optional as observed or as before."""
    previous = read_expected(path)
    running = _running_containers()
    expected: dict[str, str] = {name: "running" for name in CORE_CONTAINERS}
    prior = (previous or {}).get("services") or {}
    for name in OPTIONAL_CONTAINERS:
        if running is not None:
            expected[name] = "running" if name in running else "stopped"
        else:
            expected[name] = (prior.get(name) or {}).get("expected", "unknown")
    payload = {
        "version": STATE_VERSION,
        "updated_at": _now(),
        "reason": "up",
        "converge_incomplete": False,
        "services": _entries(expected, previous),
    }
    _write(payload, path)
    return payload


def record_down(path: Path | None = None) -> dict:
    """`cove down` succeeded: nothing is expected to run."""
    previous = read_expected(path)
    names = tuple(dict.fromkeys(CORE_CONTAINERS + OPTIONAL_CONTAINERS))
    payload = {
        "version": STATE_VERSION,
        "updated_at": _now(),
        "reason": "down",
        "converge_incomplete": False,
        "services": _entries({name: "stopped" for name in names}, previous),
    }
    _write(payload, path)
    return payload


def record_service(service: str, expected: str, path: Path | None = None) -> dict:
    """A per-service `up`/`down`; only that service's containers move."""
    if service not in SERVICE_CONTAINERS:
        raise KeyError(f"unknown service {service!r}")
    if expected not in ("running", "stopped"):
        raise ValueError(f"unexpected expectation {expected!r}")
    previous = read_expected(path) or {}
    services = {
        name: (entry or {}).get("expected", "unknown")
        for name, entry in (previous.get("services") or {}).items()
    }
    for name in SERVICE_CONTAINERS[service]:
        services[name] = expected
    payload = {
        "version": STATE_VERSION,
        "updated_at": _now(),
        "reason": f"service-{expected}",
        "converge_incomplete": False,
        "services": _entries(services, previous),
    }
    _write(payload, path)
    return payload


def record_incomplete(reason: str, path: Path | None = None) -> dict:
    """A converge failed part-way: keep the prior map, mark it unusable.

    The watchdog pages on this rather than acting, because a half-applied
    converge leaves a mix of old and new containers that no expectation
    describes.
    """
    previous = read_expected(path) or {}
    payload = {
        "version": STATE_VERSION,
        "updated_at": _now(),
        "reason": reason,
        "converge_incomplete": True,
        "services": previous.get("services") or {},
    }
    _write(payload, path)
    return payload


def wrap_converge(command, reason: str) -> None:
    """Wrap `cove up`/`cove down`: success records, failure marks incomplete."""
    original = command.callback

    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        try:
            result = original(*args, **kwargs)
        except BaseException:
            record_incomplete(reason)
            raise
        else:
            if reason == "up":
                record_up()
            else:
                record_down()
            return result

    command.callback = wrapper


def wrap_service(group, service: str) -> None:
    """Wrap a service group's `up` and `down` subcommands."""
    for command_name, expected in (("up", "running"), ("down", "stopped")):
        command = group.commands.get(command_name)
        if command is None:
            continue
        original = command.callback

        @functools.wraps(original)
        def wrapper(*args, _svc=service, _exp=expected, _orig=original, **kwargs):
            result = _orig(*args, **kwargs)
            record_service(_svc, _exp)
            return result

        command.callback = wrapper
