"""Deterministic credential sourcing for the Cove stack.

Credentials reach containers from exactly two places: the compose ``.env``
(substituted into ``${NAME}`` lines) and a service's declared ``env_file``
(literal file contents). The ambient process environment must never override
either one.

``docker compose`` interpolates the invoking shell ahead of the compose
``.env``, so an exported credential variable silently wins over the file of
record. That is a provenance defect (a value nobody manages goes live) and a
converge-churn vector: the value is part of every affected service's config
hash, so converges from differently-equipped shells recreate containers even
when nothing else changed (2026-10-27, sibling of the #105 dir-alternation
churn).

This module is the single source of truth for the credential surface:

* :data:`CREDENTIAL_ENV_NAMES` — every credential-ish variable the compose set
  consumes. Keep it in sync with ``compose/bringup.yml`` (``credential_env_names``
  is asserted equal in the test suite).
* :func:`scrubbed_environment` — the child environment handed to ``docker
  compose`` / ``ansible-playbook``; credential names are removed.
* :func:`credential_from_ambient` — provisioning helpers read an ambient
  credential only when the operator opted in, so ambient values cannot be
  copied into a file of record by accident.

The ambiguity policy is warn-and-continue: a differing ambient value is named
loudly with both fingerprints (never the values) and the run proceeds on the
file value. Refusing outright would block every converge from a developer
shell that exports a provider key for unrelated tooling, while the defect this
closes is silent custody, not the existence of ambient state. An operator who
really wants the ambient value to win sets ``COVE_ALLOW_AMBIENT_CREDENTIALS``.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import click

#: Every credential-ish variable the compose set consumes or materializes.
#: Includes env-file-only credentials (SYNTHETIC_API_KEY, the Bifrost client
#: virtual key): those cannot be ambient-overridden by Compose itself, but the
#: CLI's provisioning helpers read the same names from the ambient env.
CREDENTIAL_ENV_NAMES: tuple[str, ...] = (
    "SYNTHETIC_API_KEY",
    "OLLAMA_API_KEY",
    "LITELLM_MASTER_KEY",
    "LITELLM_DB_PASSWORD",
    "LITELLM_UI_USERNAME",
    "LITELLM_UI_PASSWORD",
    "BIFROST_ENCRYPTION_KEY",
    "BIFROST_ADMIN_USERNAME",
    "BIFROST_ADMIN_PASSWORD",
    "BIFROST_CLIENT_VIRTUAL_KEY",
    "SPEEDTEST_APP_KEY",
    "SPEEDTEST_ADMIN_EMAIL",
    "SPEEDTEST_ADMIN_PASSWORD",
    "ZROK_ACCOUNT_TOKEN",
)

#: Opt-in: let the ambient environment override the files of record again.
ALLOW_AMBIENT_ENV = "COVE_ALLOW_AMBIENT_CREDENTIALS"

_TRUTHY = {"1", "true", "yes", "on"}

# (name, ambient fingerprint, file fingerprint) already reported this process.
_WARNED: set[tuple[str, str, str]] = set()


@dataclass(frozen=True)
class AmbientConflict:
    """A credential exported in the ambient env that the files do not agree on."""

    name: str
    ambient_fingerprint: str
    file_label: str | None
    file_fingerprint: str | None


def reset_warning_state() -> None:
    """Forget which conflicts were already reported (tests, long-lived callers)."""
    _WARNED.clear()


def ambient_credentials_allowed() -> bool:
    """True when the operator deliberately opted into ambient credentials."""
    return os.environ.get(ALLOW_AMBIENT_ENV, "").strip().lower() in _TRUTHY


def fingerprint(value: str) -> str:
    """A short, non-reversible identifier for a credential value."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def resolve_data_root(env_path: Path) -> Path:
    """The data root Compose would use: explicit env, then ``env_path``, then default.

    ``COVE_DATA_ROOT`` is deliberately NOT scrubbed: it is a path, not a
    credential, and the existing compose-source guards depend on the ambient
    value winning when it is non-empty.
    """
    explicit = os.environ.get("COVE_DATA_ROOT")
    if explicit:
        return Path(explicit).expanduser()
    try:
        lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        lines = []
    for line in lines:
        if line.startswith("COVE_DATA_ROOT="):
            value = line.split("=", 1)[1].strip().strip("\"'")
            if value:
                return Path(value).expanduser()
    return Path.home() / "Documents" / "cove-data"


def _read_env_file_value(path: Path, name: str) -> str | None:
    """Literal ``NAME=VALUE`` from an env file; never expands or echoes."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except (FileNotFoundError, IsADirectoryError):
        return None
    for line in lines:
        if line.startswith(f"{name}="):
            value = line.split("=", 1)[1].strip().strip("\"'")
            return value or None
    return None


def file_of_record_values(name: str, compose_dir: Path) -> dict[str, str]:
    """Every file the compose set resolves ``name`` from, in precedence order.

    ``.env`` is the Compose interpolation surface. ``litellm/local.env`` is the
    LiteLLM service's declared ``env_file`` and the source of record for the
    Synthetic key; ``bifrost/local.env`` is its projection. Values are never
    returned in warning text — only labels and fingerprints.
    """
    values: dict[str, str] = {}
    env_value = _read_env_file_value(compose_dir / ".env", name)
    if env_value is not None:
        values["compose .env"] = env_value
    data_root = resolve_data_root(compose_dir / ".env")
    for label, path in (
        ("litellm/local.env", data_root / "litellm" / "local.env"),
        ("bifrost/local.env", data_root / "bifrost" / "local.env"),
    ):
        value = _read_env_file_value(path, name)
        if value is not None:
            values[label] = value
    return values


def _conflict_for(name: str, ambient: str, compose_dir: Path) -> AmbientConflict | None:
    """The conflict record for one ambient credential, or None when it matches."""
    values = file_of_record_values(name, compose_dir)
    if not values:
        return AmbientConflict(
            name=name,
            ambient_fingerprint=fingerprint(ambient),
            file_label=None,
            file_fingerprint=None,
        )
    mismatched = [
        (label, value)
        for label, value in values.items()
        if value != ambient
    ]
    if not mismatched:
        return None
    label, value = mismatched[0]
    return AmbientConflict(
        name=name,
        ambient_fingerprint=fingerprint(ambient),
        file_label=label,
        file_fingerprint=fingerprint(value),
    )


def ambient_conflicts(compose_dir: Path) -> list[AmbientConflict]:
    """Every ambient credential whose value the files of record disagree with."""
    conflicts = []
    for name in CREDENTIAL_ENV_NAMES:
        ambient = os.environ.get(name)
        if not ambient:
            continue
        conflict = _conflict_for(name, ambient, compose_dir)
        if conflict is not None:
            conflicts.append(conflict)
    return conflicts


def warn_ambient_conflicts(conflicts: list[AmbientConflict]) -> None:
    """Print one loud line per conflict, naming the variable and fingerprints."""
    for conflict in conflicts:
        key = (
            conflict.name,
            conflict.ambient_fingerprint,
            conflict.file_fingerprint or "unset",
        )
        if key in _WARNED:
            continue
        _WARNED.add(key)
        if conflict.file_fingerprint is None:
            resolved = "no file of record declares it (the credential resolves to unset)"
        else:
            resolved = (
                f"the file of record {conflict.file_label} has fingerprint "
                f"{conflict.file_fingerprint}"
            )
        click.echo(
            "WARNING: ambient credential "
            f"{conflict.name} has fingerprint {conflict.ambient_fingerprint}, but "
            f"{resolved}. The ambient value is IGNORED: credentials come from the "
            "compose .env and service env files only. Set "
            f"{ALLOW_AMBIENT_ENV}=1 to let the ambient environment override "
            "deliberately.",
            err=True,
        )


def scrubbed_environment(compose_dir: Path, *, warn: bool = True) -> dict[str, str]:
    """The child environment for compose/Ansible: no ambient credentials.

    The files of record are the only credential inputs. When an ambient value
    disagrees with them, the divergence is reported loudly (fingerprints only)
    and the run continues on the file value. With
    ``COVE_ALLOW_AMBIENT_CREDENTIALS`` set, the ambient environment is returned
    unchanged so the operator's deliberate override still works.
    """
    env = dict(os.environ)
    if ambient_credentials_allowed():
        present = [name for name in CREDENTIAL_ENV_NAMES if env.get(name)]
        if present and warn:
            click.echo(
                "WARNING: " + ALLOW_AMBIENT_ENV + " is set; ambient credentials "
                "override the files of record for: " + ", ".join(present),
                err=True,
            )
        return env
    if warn:
        warn_ambient_conflicts(ambient_conflicts(compose_dir))
    for name in CREDENTIAL_ENV_NAMES:
        env.pop(name, None)
    return env


def credential_from_ambient(
    name: str, compose_dir: Path, *, warn: bool = True
) -> str | None:
    """An ambient credential for provisioning, only with the explicit opt-in.

    Provisioning helpers used to treat an exported variable as "operator set
    it, honor directly" and copy it into ``.env`` / ``local.env``. That makes
    ambient state custody silently. Without the opt-in the ambient value is
    never an input: the divergence is reported (fingerprints only) and the
    caller falls through to the existing file of record.
    """
    ambient = os.environ.get(name)
    if not ambient:
        return None
    if ambient_credentials_allowed():
        return ambient
    if warn:
        conflict = _conflict_for(name, ambient, compose_dir)
        if conflict is not None:
            warn_ambient_conflicts([conflict])
    return None


__all__ = [
    "ALLOW_AMBIENT_ENV",
    "AmbientConflict",
    "CREDENTIAL_ENV_NAMES",
    "ambient_conflicts",
    "ambient_credentials_allowed",
    "credential_from_ambient",
    "file_of_record_values",
    "fingerprint",
    "reset_warning_state",
    "resolve_data_root",
    "scrubbed_environment",
    "warn_ambient_conflicts",
]
