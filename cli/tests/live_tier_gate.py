"""Opt-in gate for container-touching Cove tests.

Incident 20261018-015539 (sev-1): an unfiltered ``pytest`` run in a Cove
checkout executed ``TestE2ESpeedtestStack::test_speedtest_up_starts_container``,
which invoked the real ``cove speedtest up`` and recreated the live Compose
stack from the worktree's compose directory. Every bind mount collapsed and the
forge went dark. The pipeline that allowed it was a *pytest marker* kept out of
the run by a ``-m "not e2e and not staging"`` filter — a selection mechanism,
not a safety mechanism. One omitted flag reached the Docker daemon.

This module makes live operations opt-in, in two layers:

1. **The gate (primary).** Any test marked ``@pytest.mark.live`` is *skipped*
   unless ``COVE_ALLOW_LIVE_TESTS`` is set to a truthy value. A bare ``pytest``
   therefore cannot run it; the operator must ask. The skip reason names the
   variable, so the message itself is the instruction.

2. **The guard (backstop, inheritance).** While the opt-in is *not* set, an
   autouse fixture (see ``conftest.py``) wraps ``subprocess`` so that any
   attempt to run a *mutating* docker command raises
   ``LiveContainerAccessError``. A future test that touches containers but
   forgets the marker is caught rather than mutating the stack. Read-only
   commands (``docker compose config``, ``docker inspect``, ``docker info``)
   stay allowed so the default gate is unaffected.

The marker alone would not scale: it still depends on the author remembering to
apply it and on the reader noticing. The guard means the *default* run fails
loudly the moment container mutation is attempted, without anyone remembering
anything.
"""

from __future__ import annotations

import os
import shlex
import subprocess

import pytest


#: Environment variable the operator sets to run live/container-touching tests.
LIVE_OPT_IN_ENV = "COVE_ALLOW_LIVE_TESTS"

#: Pytest marker carried by tests that require a live stack or touch containers.
LIVE_MARKER = "live"

_TRUTHY = {"1", "true", "yes", "on"}

# Compose verbs that change container state (or hand a shell a live container).
# Scoped to operations that change which containers exist / are running — the
# incident class (a compose `up` from the wrong dir recreated the live stack).
# Read/inspect verbs (`exec`, `logs`, `ps`, `config`, `build`, `pull`) are
# deliberately NOT here: `docker compose config` and `docker inspect` are used by
# the default gate, and `exec` does not change the set of running containers.
_MUTATING_COMPOSE_VERBS = {
    "up", "down", "start", "stop", "restart", "kill", "rm", "create", "run",
    "pause", "unpause", "scale",
}

# Compose global flags that consume the following token as a value. Without
# this, the value (e.g. the `speedtest` in `--profile speedtest`) is mistaken
# for the verb.
_COMPOSE_VALUE_FLAGS = {
    "--profile", "--project-directory", "--project-name", "-p", "--ansi",
    "--progress", "--parallel", "-f", "--file", "--env-file",
}

# `docker <verb>` forms that change container state.
_MUTATING_DOCKER_VERBS = {
    "run", "create", "start", "stop", "restart", "kill", "rm", "pause",
    "unpause", "update",
}


class LiveContainerAccessError(RuntimeError):
    """Raised when an un-opted-in test tries to mutate a container."""


def live_tests_allowed(env: dict | None = None) -> bool:
    """True when ``COVE_ALLOW_LIVE_TESTS`` is set to a truthy value."""
    if env is None:
        env = os.environ
    return env.get(LIVE_OPT_IN_ENV, "").strip().lower() in _TRUTHY


def skip_reason() -> str:
    """The message shown when a ``live`` test is skipped. Names the variable."""
    return (
        f"live/container-touching test skipped: set {LIVE_OPT_IN_ENV}=1 to run "
        f"it against the live Cove stack (marker: {LIVE_MARKER})"
    )


def _argv_tokens(argv) -> list[str]:
    if argv is None:
        return []
    if isinstance(argv, (str, bytes, os.PathLike)):
        text = argv.decode() if isinstance(argv, bytes) else str(argv)
        try:
            return shlex.split(text)
        except ValueError:
            return text.split()
    try:
        return [str(a) for a in argv]
    except TypeError:
        return []


def _is_docker(token: str) -> str | None:
    """Classify a token as the docker entrypoint. Returns 'compose' for the
    legacy ``docker-compose`` binary, 'docker' for ``docker``, else None."""
    base = os.path.basename(token)
    if base == "docker-compose":
        return "compose"
    if base == "docker":
        return "docker"
    return None


def _compose_verb(rest: list[str]) -> str | None:
    """The first positional word after `compose`, skipping global flags and
    the values they consume (e.g. `--profile speedtest` does not make
    `speedtest` the verb)."""
    i = 0
    while i < len(rest):
        token = rest[i]
        if token.startswith("-"):
            flag = token.split("=", 1)[0]
            if "=" in token:
                i += 1
            elif flag in _COMPOSE_VALUE_FLAGS:
                i += 2  # flag + its value
            else:
                i += 1  # boolean flag
            continue
        return token
    return None


def is_mutating_container_command(argv) -> bool:
    """True when ``argv`` runs a docker command that can change container or
    host state. Read-only renders and inspection return False."""
    tokens = _argv_tokens(argv)
    for i, token in enumerate(tokens):
        kind = _is_docker(token)
        if kind is None:
            continue
        rest = tokens[i + 1:]
        if kind == "compose":
            return _compose_verb(rest) in _MUTATING_COMPOSE_VERBS
        # kind == "docker"
        if rest and rest[0] == "compose":
            return _compose_verb(rest[1:]) in _MUTATING_COMPOSE_VERBS
        # Plain `docker <verb>`: skip global flags (e.g. `docker -H x run`).
        words = [w for w in rest if not w.startswith("-")]
        return bool(words) and words[0] in _MUTATING_DOCKER_VERBS
    return False


def _wrap(original):
    def guarded(*args, **kwargs):
        argv = args[0] if args else kwargs.get("args")
        if is_mutating_container_command(argv):
            raise LiveContainerAccessError(
                f"refusing to run a mutating container command without "
                f"{LIVE_OPT_IN_ENV}=1: {argv!r}"
            )
        return original(*args, **kwargs)

    return guarded


def install_container_mutation_guard(monkeypatch) -> None:
    """Wrap ``subprocess`` entry points so mutating docker commands raise.

    Pass a pytest ``monkeypatch`` (or any object with ``setattr``); the wrapping
    is undone when the owning fixture/fixture-scope ends."""
    for name in ("run", "Popen", "call", "check_call", "check_output"):
        original = getattr(subprocess, name, None)
        if original is None:
            continue
        monkeypatch.setattr(subprocess, name, _wrap(original))


def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers",
        f"{LIVE_MARKER}: requires a live Cove stack or touches containers; "
        f"skipped unless {LIVE_OPT_IN_ENV} is set",
    )


def pytest_collection_modifyitems(config, items) -> None:
    if live_tests_allowed():
        return
    for item in items:
        if item.get_closest_marker(LIVE_MARKER) is not None:
            item.add_marker(pytest.mark.skip(reason=skip_reason()))
