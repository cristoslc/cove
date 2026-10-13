"""`cove update` — vendor-style updates for cove itself and its stack.

One command, one source of truth: the released cove CLI version specifies the
pins (compose files, images, migrations ship in the wheel); `cove update`
installs the latest tagged release and converges everything to it via the
normal bring-up flow. `cove update auto` schedules that daily — the opt-in is
the approval.

Never trunk: the only artifact `update` consumes is the wheel built from a
tagged release (the sashay rule stands). See
docs/musings/2026-09-26-cove-update-command.md (Decision).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path
from shutil import which

import click

from cove import __version__

REPO_URL_ENV = "COVE_REPO_GIT"
LAUNCHD_LABEL = "app.cove.update"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
LOG_PATH = Path.home() / "Library" / "Logs" / "cove-update.log"


def _repo_url() -> str:
    """The cove repo remote URL. env override wins; otherwise the dev
    checkout's origin remote is the canonical source (the operator machine
    is where scheduled updates run). No hardcoded repo owner: the repo URL
    is machine truth, not wheel-bundled truth."""
    url = os.environ.get(REPO_URL_ENV)
    if url:
        return url
    checkout = Path.home() / "Documents" / "code" / "cove"
    result = subprocess.run(
        ["git", "-C", str(checkout), "remote", "get-url", "origin"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    raise click.ClickException(
        f"Cannot determine the cove repo remote URL (no origin remote at "
        f"{checkout}). Set {REPO_URL_ENV}=<url> and retry."
    )


def _latest_tag() -> str | None:
    """Highest vX.Y.Z tag on the repo remote, or None if unreachable."""
    try:
        repo_url = _repo_url()
    except click.ClickException:
        return None
    result = subprocess.run(
        ["git", "ls-remote", "--tags", repo_url, "refs/tags/v*"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        return None
    tags = [
        m.group(1)
        for line in result.stdout.splitlines()
        if (m := re.match(r"refs/tags/v(\d+\.\d+\.\d+)$", line.split("\t", 1)[-1]))
    ]
    if not tags:
        return None

    def key(v: str):
        return tuple(int(p) for p in v.split("."))

    return max(tags, key=key)


def _version_tuple(v: str):
    try:
        return tuple(int(p) for p in v.split("."))
    except ValueError as exc:
        raise ValueError(f"not a semver: {v!r}") from exc


def _install_wheel(tag: str) -> str:
    """Build the wheel at `tag` in a throwaway worktree (mirrors the promote
    flow: sync compose resources -> build -> uv tool install --force), fail
    loud if the build does not produce one, and return the wheel path so the
    convergence gate can inspect the NEW wheel's bundled pins (the running
    process still holds the old code until restart)."""
    with tempfile.TemporaryDirectory(prefix="cove-update-") as tmp:
        worktree = Path(tmp) / "repo"
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree), f"v{tag}"],
            check=True, capture_output=True, text=True,
        )
        try:
            subprocess.run(
                ["uv", "build", "--directory", str(worktree / "cli"),
                 "--wheel", "--out-dir", str(worktree / "dist")],
                check=True, capture_output=True, text=True,
            )
            wheels = sorted((worktree / "dist").glob("cove_cli-*.whl"))
            if not wheels:
                raise click.ClickException(
                    f"wheel build produced nothing for v{tag} — cannot update."
                )
            subprocess.run(
                ["uv", "tool", "install", "--force", str(wheels[-1])],
                check=True, capture_output=True, text=True,
            )
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                capture_output=True, text=True, check=False,
            )
        return str(wheels[-1])


def _stack_running() -> bool:
    """True when at least one cove container is running. Update converges
    running services only — a downed stack (intentional `cove down`, or a
    mid-runbook `cove ade down`) must not be resurrected by an update."""
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise click.ClickException(
            f"docker ps failed ({result.stderr.strip() or 'no stderr'}) — "
            "cannot determine the running stack."
        )
    return any(name.startswith("cove-") for name in result.stdout.splitlines())


def _is_generated_compose_file(rel: str) -> bool:
    """Files bringup renders/generates locally and the wheel never ships:
    the rendered nginx config, the rendered dnsmasq config, and credential
    seed YAMLs (the bundle ships non-secret `*.example` seeds). Their
    presence in the deployed dir is runtime state, not a pin change."""
    return (
        rel == "nginx/default.conf"
        or rel == "dnsmasq/cove.conf"
        or (rel.startswith("seeds/") and rel.endswith(".yaml"))
    )


def _compose_files(root: Path) -> dict[str, str]:
    """relpath -> content for every file under a compose dir, excluding `.env`
    (the supported operator-override surface — its divergence is deliberate,
    never a reason to bring up) and the locally generated runtime files."""
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            if rel == ".env" or _is_generated_compose_file(rel):
                continue
            out[rel] = path.read_text(encoding="utf-8", errors="replace")
    return out


def _bundled_compose_files(wheel_path: str | None) -> dict[str, str] | None:
    """The compose tree the (possibly new, post-install) wheel bundles.
    `wheel_path` is what `_install_wheel` just installed; before any install,
    the current process's bundled resources are already the installed ones."""
    if wheel_path is None:
        from cove.stateless import _bundled_compose_root

        root = Path(str(_bundled_compose_root()))
        if not root.is_dir():
            return None
        return _compose_files(root)
    prefix = "cove/resources/compose/"
    with zipfile.ZipFile(wheel_path) as zf:
        files = {
            name[len(prefix):]: zf.read(name).decode("utf-8", errors="replace")
            for name in zf.namelist()
            if name.startswith(prefix) and not name.endswith("/")
        }
    files.pop(".env", None)
    for name in [n for n in files if _is_generated_compose_file(n)]:
        del files[name]
    return files


def _convergence_pending(wheel_path: str | None) -> bool:
    """True only when bring-up could change something: the release's bundled
    compose differs from what is deployed. Anything the wheel cannot change,
    it must not bring the stack up for."""
    from cove.stateless import resolve_compose_dir

    deployed = _compose_files(resolve_compose_dir())
    bundled = _bundled_compose_files(wheel_path)
    if bundled is None:
        return True  # cannot prove no-impact → converge (fail loud)
    return deployed != bundled


def _converge(check: bool, quiet: bool, wheel_path: str | None) -> None:
    """Bring up, but only when it has impact: pending pin changes AND a stack
    that is already running."""
    pending = _convergence_pending(wheel_path)
    if check:
        click.echo(f"  converge:          {'pending' if pending else 'no-op (pins converged)'}")
        click.echo(f"  stack:             {'running' if _stack_running() else 'not running'}")
        return
    if not pending:
        if not quiet:
            click.echo("  stack already converged — nothing to bring up.")
        return
    if not _stack_running():
        # Logged even in quiet mode: the scheduled run's log should say why
        # it did nothing.
        click.echo(
            "  stack is not running — skipped bring-up. Update converges "
            "running services only; `cove up` when you want the stack."
        )
        return
    if quiet:
        env = dict(os.environ, COVE_PULL_POLICY="always")
        subprocess.run(
            [which("cove") or "cove", "up", "--no-provision", "--non-interactive"],
            stdin=subprocess.DEVNULL, env=env, check=False,
        )
    else:
        subprocess.run([_cove_bin(), "up"], check=False)


def _check_container_pins() -> None:
    """Best-effort visibility: what the running containers actually are."""
    try:
        from cove.ade import _running_image

        image = _running_image()
    except Exception:
        image = None
    if image:
        click.echo(f"  ade container:      {image}")


def _do_update(check: bool, quiet: bool) -> None:
    installed = __version__
    latest = _latest_tag()

    if check:
        click.echo(f"  cove cli installed: {installed}")
        click.echo(f"  cove cli latest:    {latest or '(unreachable)'}")
        _check_container_pins()
        _converge(check=True, quiet=quiet, wheel_path=None)
        return

    if latest is None:
        raise click.ClickException(
            "Could not determine the latest cove release (the repo remote "
            f"is unreachable or unknown). Set {REPO_URL_ENV}=<url> or run "
            "from a machine with repo access."
        )

    wheel_path: str | None = None
    if _version_tuple(latest) > _version_tuple(installed):
        click.echo(f"Updating cove: {installed} -> {latest}...")
        wheel_path = _install_wheel(latest)
        click.echo(f"Installed cove {latest}.")
    elif not quiet:
        click.echo(f"cove cli is up to date ({installed}).")

    # Converge the stack to the (possibly new) wheel's pins — but only when
    # it changes something AND the stack is running (operator decision
    # 2026-10-13): updates never resurrect stopped services and never run
    # bring-up on a converged stack. Quiet mode is the scheduled path: no
    # TTY, no 1Password, no provisioning; floating tags are force-re-pulled
    # so they actually receive upstream patches.
    _converge(check=False, quiet=quiet, wheel_path=wheel_path)


def _cove_bin() -> str:
    return which("cove") or "cove"


def _bootout() -> None:
    subprocess.run(
        ["launchctl", "bootout", f"gui/{os.getuid()}", LAUNCHD_LABEL],
        capture_output=True, text=True, check=False,
    )


def _render_plist(hour: int, minute: int) -> str:
    cove_bin = _cove_bin()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{cove_bin}</string>
        <string>update</string>
        <string>--quiet</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key><integer>{hour}</integer>
        <key>Minute</key><integer>{minute}</integer>
    </dict>
    <key>StandardOutPath</key><string>{LOG_PATH}</string>
    <key>StandardErrorPath</key><string>{LOG_PATH}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>HOME</key><string>{Path.home()}</string>
    </dict>
</dict>
</plist>
"""


@click.group("update", invoke_without_command=True)
@click.option("--check", is_flag=True, help="Report staleness only; change nothing.")
@click.option("--quiet", is_flag=True, help="Non-interactive (scheduled runs).")
@click.pass_context
def update(ctx: click.Context, check: bool, quiet: bool):
    """Update cove: latest CLI release, then the stack to its pins.

    One command, one source of truth — the released cove version specifies
    the pins; `cove update` installs it and converges everything to it.
    Forgejo data migrations and Vault upgrades run inside the normal
    bring-up flow.
    """
    if ctx.invoked_subcommand is None:
        _do_update(check, quiet)


@update.command("auto")
@click.option("--off", "off_", is_flag=True, help="Remove the daily schedule.")
@click.option("--at", default="09:17", help="Daily time, HH:MM (default 09:17).")
def auto(off_: bool, at: str):
    """Schedule `cove update --quiet` daily. The opt-in IS the approval.

    Failures and rollbacks surface in the log; routine successes are silent.
    """
    if off_:
        _bootout()
        if PLIST_PATH.exists():
            PLIST_PATH.unlink()
        click.echo("Daily cove update removed.")
        return

    try:
        hour_s, minute_s = at.split(":")
        hour, minute = int(hour_s), int(minute_s)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except ValueError:
        raise click.ClickException(f"Invalid --at {at!r} (expected HH:MM).")

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(_render_plist(hour, minute))
    _bootout()
    subprocess.run(
        ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST_PATH)],
        check=True, capture_output=True, text=True,
    )
    click.echo(f"Daily cove update scheduled at {hour:02d}:{minute:02d} ({PLIST_PATH}).")
