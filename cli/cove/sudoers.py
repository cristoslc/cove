"""Passwordless sudo for `cove up` become tasks.

Installs a validated sudoers drop-in at /etc/sudoers.d/cove so Ansible's
become tasks (/bin/sh -c wrappers, which can't be matched by per-command
grants) run without a BECOME password prompt. The drop-in is NOPASSWD: ALL
for the operator's user only, mirroring compose/files/cove-sudoers.

Safety: the rendered file is validated with `visudo -c -sf` BEFORE install;
the installer stages it as *.tmp and only moves it into place after the
staged copy also validates.

Checks are functional, not file-based: /etc/sudoers.d/cove is root-owned
0440, so an unprivileged `visudo -c -f` on it always fails with EACCES.
`passwordless_sudo_ok` therefore asks sudo itself (`sudo -n -l`) whether the
operator holds a NOPASSWD: ALL grant — exactly the condition that decides
whether Ansible become prompts.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import tempfile
from importlib.resources import files
from pathlib import Path

import click

SUDOERS_PATH = Path("/etc/sudoers.d/cove")


def _operator_username() -> str:
    """The user the NOPASSWD grant should target.

    `sudo cove sudo enable` runs as root, and getpass.getuser() then reports
    root — installing a grant for root would silently drop the operator's
    passwordless sudo (which is why `cove up` re-prompted after a root-run
    setup). SUDO_USER names the real operator in that case.
    """
    if os.geteuid() == 0 and os.environ.get("SUDO_USER"):
        return os.environ["SUDO_USER"]
    return getpass.getuser()


def _rendered_sudoers() -> str:
    raw = files("cove.resources.compose.files").joinpath("cove-sudoers").read_text()
    return raw.replace("YOUR_USERNAME", _operator_username())


def passwordless_sudo_ok() -> bool:
    """True when the operator can run sudo without a password.

    Asked functionally via `sudo -n -l` (never prompts, mutates nothing).
    The exit code alone is not enough: a recently cached sudo timestamp also
    lets `sudo -n` succeed for password-based grants, so the listing itself
    must name a NOPASSWD: ALL grant — the drop-in's exact shape.
    """
    result = subprocess.run(["sudo", "-n", "-l"], capture_output=True, text=True)
    if result.returncode != 0:
        return False
    return "NOPASSWD: ALL" in result.stdout


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
        if os.geteuid() == 0:
            # Already root (e.g. `sudo cove sudo enable`): sudo -S needs no
            # password, so don't prompt for one.
            sudo_password = ""
        else:
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
    if os.geteuid() == 0 and os.environ.get("SUDO_USER"):
        click.echo(f"Granted passwordless sudo to {os.environ['SUDO_USER']} (invoked under sudo).")
    click.echo(f"Passwordless sudo installed at {SUDOERS_PATH} (validated with visudo).")
    click.echo("`cove up` no longer prompts for the BECOME password.")


@click.group(name="sudo", help="Manage passwordless sudo for cove become tasks.")
def sudo() -> None:
    """Passwordless sudo is installed via /etc/sudoers.d/cove; see `cove sudo enable`."""


@sudo.command("enable")
def sudo_enable() -> None:
    """Enable passwordless sudo for `cove up` (installs /etc/sudoers.d/cove).

    One sudo prompt (none when already root). Validates the drop-in with
    visudo before and after the install, and stages it as a .tmp file that is
    only moved into place once it validates. Pairs with `cove sudo disable`.

    Examples:

        cove sudo enable
    """
    setup_sudoers()


@sudo.command("setup", hidden=True)
def sudo_setup() -> None:
    """Deprecated alias for `cove sudo enable` (renamed in 0.11.0)."""
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
        click.echo("Run `cove sudo enable` to install it.")


@sudo.command("disable")
def sudo_disable() -> None:
    """Remove /etc/sudoers.d/cove; `cove up` prompts for the BECOME password again.

    No prompt when passwordless sudo is already in place (or when running as
    root); otherwise one sudo password prompt. After removal the functional
    check runs again, so the reported state is the truth even if some other
    NOPASSWD: ALL grant exists outside the cove drop-in.

    Examples:

        cove sudo disable
    """
    if not SUDOERS_PATH.exists():
        click.echo("Passwordless sudo was not installed; nothing to do.")
        return
    result = subprocess.run(
        ["sudo", "-n", "rm", "-f", str(SUDOERS_PATH)], capture_output=True, text=True
    )
    if result.returncode != 0:
        if os.geteuid() == 0:
            # Already root (e.g. `sudo cove sudo disable`): sudo -S needs no
            # password, so don't prompt for one.
            sudo_password = ""
        else:
            sudo_password = getpass.getpass(f"sudo password for {getpass.getuser()}: ")
        result = subprocess.run(
            ["sudo", "-S", "-p", "", "rm", "-f", str(SUDOERS_PATH)],
            input=sudo_password + "\n",
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            raise click.ClickException(
                "sudoers removal failed:\n"
                f"{result.stdout}{result.stderr}".replace(sudo_password, "")
            )
    if passwordless_sudo_ok():
        click.echo(f"Removed {SUDOERS_PATH}, but passwordless sudo is still in place:")
        click.echo("another NOPASSWD: ALL grant exists outside the cove drop-in.")
        click.echo("Inspect it with `sudo -l` (your own password).")
    else:
        click.echo(f"Removed {SUDOERS_PATH}; `cove up` prompts for the BECOME password again.")
        click.echo("Re-enable any time with `cove sudo enable`.")