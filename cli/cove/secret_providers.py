"""The provider seam: how a durable vault fills Cove's local store.

Two different seams, deliberately:

* **Readers** talk to the OpenBao store. Services render from it, other lanes'
  tooling reads it, and nothing that consumes a secret knows which backend
  produced it.
* **The populator** talks to whatever durable vault the machine actually has.
  This module is that second seam: it turns a native reference into a value, so
  a machine with 1Password, and later a machine with something else, can fill
  the same store with the same shapes.

Adding a backend is one provider class and its URI scheme. Nothing on the
reader side changes, and the store's contents stay comparable because each
entry records the native reference it came from.
"""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Protocol, runtime_checkable

import click

# Schemes this build can resolve. A reference with any other scheme is refused
# loudly rather than guessed at, so adding a backend is an explicit act.
SUPPORTED_SCHEMES: tuple[str, ...] = ("op",)


@runtime_checkable
class SecretProvider(Protocol):
    """A durable vault that can resolve a native reference."""

    name: str
    schemes: tuple[str, ...]

    def read(self, ref: str) -> str: ...

    def validate(self, ref: str) -> None: ...


class OnePasswordSdk:
    """Unattended path: the official SDK behind a scoped service account."""

    name = "1password-sdk"
    schemes = ("op",)

    def validate(self, ref: str) -> None:
        _require_scheme(ref, self.schemes)
        if not os.environ.get("OP_SERVICE_ACCOUNT_TOKEN", "").strip():
            raise click.ClickException(
                "OP_SERVICE_ACCOUNT_TOKEN is not set, so the unattended 1Password "
                "path cannot be used. Unset it to fall back to the CLI, or export "
                "a service account token."
            )

    def read(self, ref: str) -> str:
        from cove.op_sdk import resolve

        return resolve(ref)


class OnePasswordCli:
    """Interactive path: `op`, which the desktop app authorizes."""

    name = "1password-cli"
    schemes = ("op",)

    def validate(self, ref: str) -> None:
        _require_scheme(ref, self.schemes)

    def read(self, ref: str) -> str:
        self.validate(ref)
        # On non-macOS try bare op first (works with service account tokens).
        if platform.system() != "Darwin":
            proc = subprocess.run(
                ["op", "read", "--no-newline", "--", ref],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
            )
            if proc.returncode == 0:
                return proc.stdout

        # Primary path (macOS and fallback): op run wraps in a single biometric prompt.
        proc = subprocess.run(
            ["op", "run", "--", "op", "read", "--no-newline", "--", ref],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"op read failed for {ref}\nstderr: {proc.stderr.strip()}")
        return proc.stdout


def _require_scheme(ref: str, schemes: tuple[str, ...]) -> None:
    if not ref.startswith(tuple(f"{scheme}://" for scheme in schemes)):
        supported = ", ".join(f"{scheme}://" for scheme in SUPPORTED_SCHEMES)
        raise click.ClickException(
            f"unsupported secret reference {ref!r}; this build resolves {supported}"
        )


def provider_for(ref: str) -> SecretProvider:
    """Pick the provider for a reference.

    A service account token selects the unattended SDK path; without one, the
    interactive CLI path. Both speak the same `op://` scheme, so the choice is
    about how the machine authenticates, not about where the secret lives.
    """
    _require_scheme(ref, SUPPORTED_SCHEMES)
    if os.environ.get("OP_SERVICE_ACCOUNT_TOKEN", "").strip():
        return OnePasswordSdk()
    return OnePasswordCli()


def read_secret(ref: str) -> str:
    """Resolve one native reference through the selected provider."""
    provider = provider_for(ref)
    provider.validate(ref)
    return provider.read(ref)
