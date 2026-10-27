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
import sys
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


_wheel_tmpdir: tempfile.TemporaryDirectory | None = None


def _release_wheel_tmpdir() -> None:
    """Delete the temp tree holding the wheel the update flow last installed
    and compared. Issue #80: that wheel must outlive `_install_wheel` (the
    post-install pin-compare reads it), so its temp dir is released by the
    flow — `_do_update`'s finally — not by the function that built it."""
    global _wheel_tmpdir
    if _wheel_tmpdir is not None:
        _wheel_tmpdir.cleanup()
        _wheel_tmpdir = None


def _install_wheel(tag: str) -> str:
    """Build the wheel at `tag` in a throwaway git worktree (mirrors the
    promote flow: sync compose resources -> build -> uv tool install --force),
    fail loud if the build does not produce one, install it, and return the
    wheel path so the convergence gate can inspect the NEW wheel's bundled
    pins (the running process still holds the old code until restart).

    The returned path is the exact file `uv tool install` consumed, and it
    stays readable until `_release_wheel_tmpdir()` (called by `_do_update`
    after the pin-compare). Issue #80: the path used to live inside a
    TemporaryDirectory that was deleted the moment this function returned,
    so the post-install pin-compare crashed with FileNotFoundError on a
    dangling path. The built wheel lands OUTSIDE the git worktree so
    worktree cleanup cannot take it with it."""
    global _wheel_tmpdir
    _release_wheel_tmpdir()  # a previous run's wheel is dead weight now
    tmp = tempfile.TemporaryDirectory(prefix="cove-update-")
    _wheel_tmpdir = tmp
    worktree = Path(tmp.name) / "repo"
    dist = Path(tmp.name) / "dist"
    try:
        subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree), f"v{tag}"],
            check=True, capture_output=True, text=True,
        )
        try:
            # Promote parity: the wheel must bundle this tag's compose pins.
            # `cli/cove/resources/compose/` is a gitignored build artifact,
            # so a fresh worktree has to run the tag's own sync script
            # before building — same as scripts/release.sh does.
            subprocess.run(
                [sys.executable,
                 str(worktree / "cli" / "scripts" / "sync_compose_resources.py")],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(
                ["uv", "build", "--directory", str(worktree / "cli"),
                 "--wheel", "--out-dir", str(dist)],
                check=True, capture_output=True, text=True,
            )
            wheels = sorted(dist.glob("cove_cli-*.whl"))
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
    except BaseException:
        _release_wheel_tmpdir()
        raise


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
    presence in the deployed dir is runtime state, not a pin change.
    Also `.env*` at the compose root: the override surface and the example
    documenting it (.env.example can be missing from wheels' dotfile
    packaging without affecting any pin)."""
    return (
        rel == "nginx/default.conf"
        or rel == "dnsmasq/cove.conf"
        or (rel.startswith("seeds/") and rel.endswith(".yaml"))
        or rel == ".env"
        or rel == ".env.example"
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
    if not Path(wheel_path).is_file():
        # Issue #80: never a raw FileNotFoundError traceback — name the
        # wheel that is missing so the operator can re-run `cove update`.
        raise click.ClickException(
            f"the installed update wheel is missing ({wheel_path}) — cannot "
            "compare bundled pins. Re-run `cove update`."
        )
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
            [_cove_bin(), "up", "--no-provision", "--non-interactive"],
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
    try:
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
    finally:
        # The pin-compare has read the installed wheel (issue #80): the temp
        # tree holding it can go. Never released mid-flow — the convergence
        # gate needs the file until `_convergence_pending` has decided.
        _release_wheel_tmpdir()


def _cove_bin() -> str:
    """Absolute path to the installed `cove` executable.

    `which` resolves through the invoking PATH. Under launchd the process was
    started from the plist's absolute ProgramArguments path, so `sys.argv[0]`
    is that same binary and is the fallback when the agent's PATH is bare.
    Never returns a bare name: the literal "cove" fallback is exactly what
    produced `FileNotFoundError: 'cove'` in the daily job (2026-10-27), where
    the plist PATH omitted `~/.local/bin`.
    """
    found = which("cove")
    if found:
        return str(Path(found))
    argv0 = Path(sys.argv[0] or "")
    if argv0.is_absolute() and argv0.is_file() and os.access(argv0, os.X_OK):
        return str(argv0)
    raise click.ClickException(
        "Cannot resolve the installed `cove` executable: it is not on PATH "
        "and sys.argv[0] is not an absolute file. Re-run `cove update auto` "
        "from a shell where `cove` is on PATH."
    )


# launchd starts an agent with a bare PATH. The update flow shells out to
# `cove` (the converge re-exec), `uv` (wheel build and tool install), `git`
# (the release worktree), `docker` (stack state), and `ansible-playbook` (the
# converge). On macOS `cove`, `uv`, and `ansible-playbook` live in
# `~/.local/bin`, which launchd's default PATH omits, so the generated plist
# pins a PATH that contains them.
_FALLBACK_PATH_DIRS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
)


def _plist_path(cove_bin: str) -> str:
    """PATH for the scheduled run.

    The resolved cove bin dir comes first, then the PATH the scheduling shell
    ran under (where `cove update auto` was typed, so it names every tool the
    operator actually has), then the standard macOS/Host dirs. Deduped with
    order preserved; the first match wins, as in a shell.
    """
    candidates: list[str] = []
    binary = Path(cove_bin)
    if binary.is_absolute():
        candidates.append(str(binary.parent))
    candidates.extend(os.environ.get("PATH", "").split(os.pathsep))
    candidates.extend(_FALLBACK_PATH_DIRS)
    dirs: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in dirs:
            dirs.append(candidate)
    return os.pathsep.join(dirs)


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
        <key>PATH</key><string>{_plist_path(cove_bin)}</string>
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

    The plist pins the `cove` this command resolves, so run it from the
    installed tool, not a checkout's virtualenv: otherwise the daily job runs
    that venv's binary, which disappears when the venv is rebuilt.

    Routine success is silent. Every run writes to the log the agent points at
    (`~/Library/Logs/cove-update.log` on macOS); that file is the only place a
    failed scheduled run surfaces, and nothing pushes it to you.
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
