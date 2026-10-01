"""Passwordless sudo for `cove up` become tasks.

Installs a validated sudoers drop-in at /etc/sudoers.d/cove so Ansible's
become tasks (/bin/sh -c wrappers, which can't be matched by per-command
grants) run without a BECOME password prompt. The drop-in is NOPASSWD: ALL
for the operator's user only, mirroring compose/files/cove-sudoers.

Safety: the rendered file is validated with `visudo -c -sf` BEFORE install;
the installer stages it as *.tmp and only moves it into place after the
staged copy also validates.
"""

from __future__ import annotations

import getpass
import subprocess
import tempfile
from importlib.resources import files
from pathlib import Path

import click

SUDOERS_PATH = Path("/etc/sudoers.d/cove")


def _rendered_sudoers() -> str:
    raw = files("cove.resources.compose.files").joinpath("cove-sudoers").read_text()
    return raw.replace("YOUR_USERNAME", getpass.getuser())


def passwordless_sudo_ok() -> bool:
    """True when the cove sudoers drop-in is installed and validates."""
    if not SUDOERS_PATH.exists():
        return False
    return subprocess.run(
        ["visudo", "-c", "-f", str(SUDOERS_PATH)],
        capture_output=True,
    ).returncode == 0


def setup_sudoers() -> None:
    rendered = _rendered_sudoers()
    with tempfile.NamedTemporaryFile("w", suffix=".sudoers", delete=False) as tmp:
        tmp.write(rendered)
        tmp_path = Path(tmp.name)
    try:
        pre = subprocess.run(
            ["visudo", "-c", "-sf", str(tmp_path)], capture_output=True, text=True
        )
        if pre.returncode != 0:
            raise click.ClickException(
                f"Rendered sudoers failed validation, not installed:\n{pre.stdout}{pre.stderr}"
            )
        sudo_password = getpass.getpass(f"sudo password for {getpass.getuser()}: ")
        install = subprocess.run(
            [
                "sudo", "-S", "-p", "", "sh", "-c",
                f'cp {tmp_path} {SUDOERS_PATH}.tmp && '
                f'chmod 440 {SUDOERS_PATH}.tmp && '
                f'visudo -c -f {SUDOERS_PATH}.tmp && '
                f'mv {SUDOERS_PATH}.tmp {SUDOERS_PATH} && '
                f'rm -f {tmp_path}',
            ],
            input=sudo_password + "\n",
            text=True,
            capture_output=True,
        )
        if install.returncode != 0:
            raise click.ClickException(
                "sudoers install failed:\n"
                f"{install.stdout}{install.stderr}".replace(sudo_password, "")
            )
    finally:
        tmp_path.unlink(missing_ok=True)
    click.echo(f"Passwordless sudo installed at {SUDOERS_PATH} (validated with visudo).")
    click.echo("`cove up` no longer prompts for the BECOME password.")


@click.group(name="sudo", help="Manage passwordless sudo for cove become tasks.")
def sudo() -> None:
    """Passwordless sudo is installed via /etc/sudoers.d/cove; see `cove sudo setup`."""


@sudo.command("setup")
def sudo_setup() -> None:
    """Install /etc/sudoers.d/cove for passwordless `cove up` (one sudo prompt).

    Validates the drop-in with visudo before and after the install, and stages
    it as a .tmp file that is only moved into place once it validates.

    Examples:

        cove sudo setup
    """
    setup_sudoers()


@sudo.command("status")
def sudo_status() -> None:
    """Check whether passwordless sudo for cove is in place.

    Examples:

        cove sudo status
    """
    if passwordless_sudo_ok():
        click.echo("Passwordless sudo is in place (cove up will not prompt).")
    else:
        click.echo("Passwordless sudo is NOT in place; cove up prompts for a BECOME password.")
        click.echo("Run `cove sudo setup` to install it.")