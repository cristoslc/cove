"""Resource resolution and extraction for stateless CLI."""

import hashlib
import os
import platform
import secrets
import shutil
import stat
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

import click
import yaml

from cove import __version__

# Files bringup generates at runtime that extraction must never prune or
# overwrite. `certs/rootCA.pem` is copied from the machine's CA by bringup (the
# bundle may ship no `certs/` at all — `compose/certs/` is gitignored, so a
# wheel built from a clean checkout, e.g. the `cove update` git-worktree path,
# has none). Pruning it left the file missing; Docker then auto-created it as a
# directory and `docker restart cove-nginx` refused to start (2026-10-19 sev-2).
# `nginx/llmproxy-auth.conf` is the rendered 0600 edge credential file: the
# wheel ships only its template, so pruned-then-recreated would hand the running
# nginx a fresh inode it never sees (same stale-inode class).
RUNTIME_PRESERVED_FILES = (
    ".env",
    "nginx/default.conf",
    "nginx/llmproxy-auth.conf",
    "certs/rootCA.pem",
)

# The live compose project name, hardcoded in compose/docker-compose.yml. Docker
# Compose keys a project by (name, working directory), so a second compose dir
# declaring the same name is what lets an unrelated checkout recreate the live
# stack (incident 20261018-015539).
LIVE_COMPOSE_PROJECT_NAME = "cove"

# Explicit operator escape hatch for running a live-named compose source from a
# directory that points at a different data root (see
# require_live_project_from_canonical_dir).
NONCANONICAL_OVERRIDE_ENV = "COVE_ALLOW_FOREIGN_DATA_ROOT"

# Explicit operator escape hatch for converging the live project from a
# NON-canonical compose dir that shares the canonical data root. Without it,
# the live stack only converges from ~/.config/cove/compose, so a no-op
# converge cannot flip absolute config-hash inputs (bind sources, build
# contexts, NGINX_CONF_DIR) and recreate litellm/nginx.
LIVE_SOURCE_OVERRIDE_ENV = "COVE_ALLOW_NONCANONICAL_LIVE_SOURCE"

# Compose top-level project-name files, checked in Compose's own precedence.
_COMPOSE_FILE_NAMES = (
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
)


def detect_hostname() -> str:
    """Return a stable machine hostname for state/credential keying.

    On macOS, prefers the kernel's LocalHostName (the name shown in
    System Settings > General > About), which is stable across networks.
    The kernel hostname (platform.node()) silently drifts to the
    DHCP-assigned hostname whenever HostName is unset, breaking any
    per-hostname lookup (host_vars file, 1Password op refs). Falls back
    to platform.node() on other platforms or if scutil is unavailable.
    """
    if sys.platform == "darwin":
        try:
            res = subprocess.run(
                ["scutil", "--get", "LocalHostName"],
                capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        else:
            if res.returncode == 0:
                name = res.stdout.strip().split(".")[0]
                if name:
                    return name
    return platform.node().split(".")[0]


def _config_compose_dir() -> Path:
    return Path.home() / ".config" / "cove" / "compose"


def canonical_data_root() -> Path:
    """The canonical operator data root (compose/group_vars/all.yml cove_data_root)."""
    return Path.home() / "Documents" / "cove-data"


def _bundled_compose_root():
    return files("cove.resources") / "compose"


def _bundled_content_hash() -> str:
    """SHA-256 of all bundled resource file contents (sorted by path)."""
    h = hashlib.sha256()
    root = Path(str(_bundled_compose_root()))
    if not root.is_dir():
        return ""
    paths = sorted(
        p for p in root.rglob("*") if p.is_file() and p.name != ".version"
    )
    for p in paths:
        h.update(p.read_bytes())
    return h.hexdigest()


def _directory_fd(root_fd: int, parts: tuple[str, ...], relative_path: str,
                  *, create: bool = False) -> int | None:
    """Open a directory path relative to root without following any symlink."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    current_fd = os.dup(root_fd)
    try:
        for part in parts:
            try:
                next_fd = os.open(part, flags, dir_fd=current_fd)
            except FileNotFoundError:
                if not create:
                    os.close(current_fd)
                    return None
                try:
                    os.mkdir(part, mode=0o755, dir_fd=current_fd)
                except FileExistsError:
                    pass
                try:
                    next_fd = os.open(part, flags, dir_fd=current_fd)
                except OSError as exc:
                    raise click.ClickException(
                        f"Refusing to preserve {relative_path}: parent path is not "
                        "a real directory."
                    ) from exc
            except OSError as exc:
                raise click.ClickException(
                    f"Refusing to preserve {relative_path}: parent path is not "
                    "a real directory."
                ) from exc
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        try:
            os.close(current_fd)
        except OSError:
            pass
        raise


def _open_compose_directory(target: Path, *, create: bool = False) -> int | None:
    """Open the installed Compose directory beneath the trusted home without links."""
    home = Path.home()
    try:
        parts = target.relative_to(home).parts
    except ValueError as exc:
        raise click.ClickException(
            f"Refusing to access Compose resources outside the home directory: {target}"
        ) from exc

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    home_fd = os.open(home.resolve(strict=True), flags)
    try:
        return _directory_fd(home_fd, parts, str(target), create=create)
    finally:
        os.close(home_fd)


def _read_runtime_file(target: Path, relative_path: str) -> tuple[bytes, int] | None:
    """Read one runtime file without following links or blocking on special files."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise click.ClickException(
            "This platform cannot safely preserve runtime Compose files."
        )
    root_fd = _open_compose_directory(target)
    if root_fd is None:
        return None

    parts = tuple(Path(relative_path).parts)
    parent_fd = None
    try:
        parent_fd = _directory_fd(root_fd, parts[:-1], relative_path)
        if parent_fd is None:
            return None
        try:
            fd = os.open(
                parts[-1],
                os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0),
                dir_fd=parent_fd,
            )
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise click.ClickException(
                f"Refusing to preserve {relative_path}: expected a regular file "
                "without symlinks."
            ) from exc

        try:
            file_stat = os.fstat(fd)
            if not stat.S_ISREG(file_stat.st_mode):
                raise click.ClickException(
                    f"Refusing to preserve {relative_path}: expected a regular file."
                )
            mode = stat.S_IMODE(file_stat.st_mode)
            if relative_path == ".env" and mode & 0o077:
                # Keep the persistent environment file private without replacing
                # its inode, which may be observed through a bind mount.
                mode &= 0o600
                os.fchmod(fd, mode)
            with os.fdopen(fd, "rb") as stream:
                content = stream.read()
            return content, mode
        except BaseException:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
    finally:
        if parent_fd is not None:
            os.close(parent_fd)
        os.close(root_fd)


def _remove_tree_entry(parent_fd: int, name: str) -> None:
    """Remove an entry relative to an open directory without following links."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
    try:
        child_fd = os.open(name, directory_flags, dir_fd=parent_fd)
    except (NotADirectoryError, FileNotFoundError):
        try:
            os.unlink(name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        return
    except OSError:
        # A symlink or another non-directory entry is unlinked, never followed.
        try:
            os.unlink(name, dir_fd=parent_fd)
        except FileNotFoundError:
            pass
        return
    try:
        for child_name in os.listdir(child_fd):
            _remove_tree_entry(child_fd, child_name)
    finally:
        os.close(child_fd)
    os.rmdir(name, dir_fd=parent_fd)


def _file_matches_bundle(
    directory_fd: int, name: str, relative: str, src_root: Path
) -> bool:
    """True when the deployed entry is a regular file byte-identical (and
    mode-identical) to the bundle's copy at the same relative path.

    Used to skip pruning entries extraction would otherwise delete and re-copy:
    deletion is what forces a new inode, and a new inode under a running
    container's file bind is a stale (unlinked) mount. Never follows a symlink
    and never blocks on a special file — any such entry reports False and takes
    the normal remove-and-recopy path."""
    source = src_root / relative
    try:
        source_stat = source.lstat()
    except OSError:
        return False
    if not stat.S_ISREG(source_stat.st_mode):
        return False

    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        return False
    try:
        fd = os.open(
            name,
            os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0),
            dir_fd=directory_fd,
        )
    except OSError:
        return False
    try:
        deployed_stat = os.fstat(fd)
        if not stat.S_ISREG(deployed_stat.st_mode):
            return False
        if stat.S_IMODE(deployed_stat.st_mode) != stat.S_IMODE(source_stat.st_mode):
            return False
        if deployed_stat.st_size != source_stat.st_size:
            return False
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            deployed = stream.read()
    finally:
        if fd != -1:
            os.close(fd)
    try:
        return deployed == source.read_bytes()
    except OSError:
        return False


def _prune_for_extraction(target: Path, src_root: Path) -> None:
    """Remove stale resources while retaining runtime files and their inodes.

    An entry whose content already matches the bundle is *not* stale: it is left
    in place so `_copy_resource` overwrites it in place (same inode). Deleting it
    would give it a fresh inode, which a running container's file bind would not
    see (2026-10-19 stale-inode/sealed-vault class)."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
    root_fd = _open_compose_directory(target)
    if root_fd is None:
        return
    preserved = set(RUNTIME_PRESERVED_FILES)
    source_root = Path(str(src_root))

    def prune(directory_fd: int, prefix: str = "") -> None:
        for name in os.listdir(directory_fd):
            relative = f"{prefix}/{name}" if prefix else name
            if relative in preserved:
                continue
            if any(path.startswith(relative + "/") for path in preserved):
                child_fd = os.open(name, flags, dir_fd=directory_fd)
                try:
                    prune(child_fd, relative)
                finally:
                    os.close(child_fd)
                continue
            # Recurse into real directories instead of removing them wholesale:
            # their unchanged files must keep their inodes. The directory is
            # removed only if nothing was kept.
            try:
                child_fd = os.open(name, flags, dir_fd=directory_fd)
            except OSError:
                child_fd = None
            if child_fd is not None:
                try:
                    prune(child_fd, relative)
                    remaining = os.listdir(child_fd)
                finally:
                    os.close(child_fd)
                if not remaining:
                    os.rmdir(name, dir_fd=directory_fd)
                continue
            if _file_matches_bundle(directory_fd, name, relative, source_root):
                continue
            _remove_tree_entry(directory_fd, name)

    try:
        prune(root_fd)
    finally:
        os.close(root_fd)


def _invalidate_version_file(target: Path) -> None:
    """Remove the bundle marker without following a symlink before pruning."""
    root_fd = _open_compose_directory(target)
    if root_fd is None:
        return
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        try:
            fd = os.open(
                ".version",
                os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0),
                dir_fd=root_fd,
            )
        except FileNotFoundError:
            return
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise click.ClickException(
                    "Refusing to invalidate .version: expected a regular file."
                )
        finally:
            os.close(fd)
        os.unlink(".version", dir_fd=root_fd)
    finally:
        os.close(root_fd)


def _write_version_file(target: Path, content_hash: str) -> None:
    """Atomically replace the bundle marker without following a target link."""
    root_fd = _open_compose_directory(target)
    if root_fd is None:
        raise click.ClickException(f"Compose resource directory disappeared: {target}")
    temp_name = f".version.cove-{secrets.token_hex(8)}"
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=root_fd,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(content_hash)
                stream.flush()
            os.replace(
                temp_name,
                ".version",
                src_dir_fd=root_fd,
                dst_dir_fd=root_fd,
            )
        except BaseException:
            try:
                os.unlink(temp_name, dir_fd=root_fd)
            except FileNotFoundError:
                pass
            raise
    finally:
        os.close(root_fd)


def resolve_compose_dir() -> Path:
    env = os.environ.get("COVE_COMPOSE_DIR")
    if env:
        p = Path(env)
        if (p / "inventory.yml").exists():
            return p
        raise click.ClickException(
            f"COVE_COMPOSE_DIR={env} does not contain inventory.yml."
        )

    cwd = Path.cwd()
    for candidate in [cwd / "compose", cwd / ".worktrees" / cwd.name / "compose"]:
        if (candidate / "inventory.yml").exists():
            return candidate

    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, cwd=cwd,
    )
    if result.returncode == 0:
        git_root = Path(result.stdout.strip())
        if (git_root / "compose" / "inventory.yml").exists():
            return git_root / "compose"

    installed = _config_compose_dir()
    if (installed / "inventory.yml").exists():
        return installed

    raise click.ClickException(
        "Could not find compose/inventory.yml. Run `cove init` first."
    )


def read_env_file_value(compose_dir: Path, key: str) -> str | None:
    """Return KEY's non-empty value from compose_dir/.env, or None.

    Deliberately parses only literal `KEY=VALUE` lines (first match wins) and
    never expands `~` or variables: Compose itself does not expand `~`, so a
    value like the `.env.example` placeholder must be treated as-is rather than
    silently resolved.
    """
    env_path = compose_dir / ".env"
    try:
        lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return None
    for line in lines:
        if line.startswith(f"{key}="):
            value = line.split("=", 1)[1].strip().strip("\"'")
            if value:
                return value
    return None


def effective_env_value(compose_dir: Path, key: str) -> str | None:
    """The value Compose would interpolate for KEY: process env, then `.env`.

    Process env wins only when non-empty (Compose merges the shell environment
    over `.env`).
    """
    from_process = os.environ.get(key)
    if from_process:
        return from_process
    return read_env_file_value(compose_dir, key)


def effective_data_root(compose_dir: Path) -> str | None:
    """The COVE_DATA_ROOT Compose would interpolate for this compose dir.

    Returns None when neither the process environment nor `.env` provides a
    non-empty value — the state in which `${COVE_DATA_ROOT}/x` collapses to a
    container-absolute `/x`.
    """
    return effective_env_value(compose_dir, "COVE_DATA_ROOT")


REQUIRED_DATA_ROOT_KEYS = ("COVE_DATA_ROOT", "FORGEJO_DATA_ROOT")


def declared_compose_project_name(compose_dir: Path) -> str | None:
    """The top-level `name:` from the compose dir's compose file, or None.

    Only the top-level key counts: a nested `name:` under a service is not the
    project name. PyYAML's SafeLoader returns the first of duplicate top-level
    keys, matching Compose's own first-wins behavior closely enough for a guard.
    """
    for filename in _COMPOSE_FILE_NAMES:
        compose_file = compose_dir / filename
        if not compose_file.is_file():
            continue
        try:
            data = yaml.safe_load(compose_file.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise click.ClickException(
                f"Cannot parse {compose_file} to check the compose project "
                f"name: {exc}"
            ) from exc
        if not isinstance(data, dict):
            return None
        name = data.get("name")
        return str(name) if name else None
    return None


def require_usable_data_root(compose_dir: Path, *, allow_missing_env: bool) -> None:
    """Abort when this compose dir has no usable data-root values.

    A compose invocation with an empty data root collapses every
    `${COVE_DATA_ROOT}/x` (and `${FORGEJO_DATA_ROOT}/x`) bind to a
    container-absolute `/x` (incident 20261018-015539). Fail loud instead,
    naming the resolved directory and every missing key.

    `allow_missing_env` covers first boot into the canonical dir, where
    `cove up` legitimately starts with no `.env` (bringup.yml renders a complete
    one before `docker compose up`). An `.env` that EXISTS but lacks a usable
    data root is always an error — that is the partial-file shape left by a
    service `up` writing one key into a dir that never had a rendered `.env`.
    """
    env_path = compose_dir / ".env"
    if not env_path.exists() and allow_missing_env:
        return
    missing = [
        key
        for key in REQUIRED_DATA_ROOT_KEYS
        if effective_env_value(compose_dir, key) is None
    ]
    if not missing:
        return
    if not env_path.exists():
        cause = "the .env is missing"
    else:
        cause = (
            "the .env (and process environment) have no non-empty value for "
            + " / ".join(missing)
        )
    raise click.ClickException(
        f"Compose dir {compose_dir} has no usable {' / '.join(missing)} "
        f"({cause}). Refusing to run: an empty data root collapses every "
        "${COVE_DATA_ROOT}/x bind mount to container-absolute /x and would "
        "recreate containers against the wrong data. Fix it by running from "
        "the canonical compose dir (~/.config/cove/compose), setting the key "
        "in the environment, or deleting "
        f"{env_path} so the next `cove up` re-renders a complete .env."
    )


def require_live_project_from_canonical_dir(compose_dir: Path) -> None:
    """Abort unless the live project converges from its canonical source dir.

    `docker-compose.yml` pins `name: cove`, and Compose keys a project by
    (name, working directory). Two hazards follow.

    Hijack: a compose dir with the live name and a *different* data root
    recreates the live containers against foreign storage (incident
    20261018-015539). Refused unless NONCANONICAL_OVERRIDE_ENV is set.

    Churn: a compose dir with the live name and the *canonical* data root is
    not harmless, because every service's config hash embeds absolute paths
    resolved from the compose directory: relative bind sources
    (`./vault/vault.hcl`, `./certs/rootCA.pem`), `build.context: ./litellm`,
    and the `NGINX_CONF_DIR` / `DNSMASQ_CONF_DIR` values in `.env`. Converging
    the live stack from two different dirs (the install dir and a checkout, or
    two checkouts) therefore changes the hash of litellm, nginx, vault, and ade
    on every flip and recreates them even when nothing changed. Each recreate
    drops the LLM proxy for one to two minutes (2026-10-26 incident). Refused
    unless LIVE_SOURCE_OVERRIDE_ENV is set.

    Only the canonical install dir passes with no opt-in.
    """
    if declared_compose_project_name(compose_dir) != LIVE_COMPOSE_PROJECT_NAME:
        return
    try:
        same_dir = compose_dir.resolve() == _config_compose_dir().resolve()
    except OSError:
        same_dir = False
    if same_dir:
        return

    root = effective_data_root(compose_dir)
    same_root = False
    if root is not None:
        try:
            same_root = (
                Path(root).expanduser().resolve() == canonical_data_root().resolve()
            )
        except OSError:
            same_root = False

    if not same_root:
        if os.environ.get(NONCANONICAL_OVERRIDE_ENV):
            return
        raise click.ClickException(
            f"Compose dir {compose_dir} declares the live project name "
            f"'{LIVE_COMPOSE_PROJECT_NAME}' but its COVE_DATA_ROOT "
            f"({root or 'unset'}) is not the canonical one "
            "(~/Documents/cove-data). Compose keys a project by (name, working "
            "directory), so this would recreate the live stack against foreign "
            "data. Run from the canonical dir (~/.config/cove/compose), point "
            "COVE_DATA_ROOT at the canonical root, or set "
            f"{NONCANONICAL_OVERRIDE_ENV}=1 to override deliberately."
        )

    if os.environ.get(LIVE_SOURCE_OVERRIDE_ENV):
        return
    raise click.ClickException(
        f"Compose dir {compose_dir} declares the live project name "
        f"'{LIVE_COMPOSE_PROJECT_NAME}' but is not the canonical compose dir "
        "(~/.config/cove/compose). Compose keys a project by (name, working "
        "directory) and every service's config hash embeds absolute paths "
        "resolved from that directory (relative bind sources such as "
        "./vault/vault.hcl and ./certs/rootCA.pem, build contexts such as "
        "./litellm, and the NGINX_CONF_DIR / DNSMASQ_CONF_DIR values in .env). "
        "Converging the live stack from two different dirs recreates litellm, "
        "nginx, vault, and ade on every flip even when nothing changed, and "
        "each recreate drops the LLM proxy for one to two minutes. Run the "
        "live stack from the canonical dir, or set "
        f"{LIVE_SOURCE_OVERRIDE_ENV}=1 to converge from this source "
        "deliberately (the recreate is expected)."
    )


def ensure_compose_source_ready(compose_dir: Path) -> None:
    """Refuse a compose source that would collapse binds or hijack the live stack.

    Called by every compose entry point (`cove up`, `cove down`, and the service
    `up` commands) before anything reaches Ansible or Docker. The canonical
    install dir may be missing its `.env` (fresh install); any other dir must
    carry a usable COVE_DATA_ROOT.
    """
    canonical = _config_compose_dir()
    try:
        allow_missing_env = compose_dir.resolve() == canonical.resolve()
    except OSError:
        allow_missing_env = False
    require_usable_data_root(compose_dir, allow_missing_env=allow_missing_env)
    require_live_project_from_canonical_dir(compose_dir)


def require_compose_source_ready() -> Path:
    """Resolve the compose dir and refuse an unsafe source; return the dir.

    Convenience entry point for container-mutating commands so each call site
    reads as one guard call rather than a resolve + check pair.
    """
    compose_dir = resolve_compose_dir()
    ensure_compose_source_ready(compose_dir)
    return compose_dir


def extract_resources(force: bool = False) -> Path:
    target = _config_compose_dir()
    src_root = _bundled_compose_root()
    if not src_root.is_dir():
        raise click.ClickException(
            "Bundled compose resources not found. Reinstall cove-cli."
        )

    content_hash = _bundled_content_hash()
    target_fd = _open_compose_directory(target)
    if target_fd is not None:
        os.close(target_fd)
        version = _read_runtime_file(target, ".version")
        if not force and version is not None and version[0].decode().strip() == content_hash:
            return target
        # Validate every allowlisted path before pruning anything.
        for relative_path in RUNTIME_PRESERVED_FILES:
            _read_runtime_file(target, relative_path)
        _invalidate_version_file(target)
        _prune_for_extraction(target, Path(str(src_root)))
    else:
        target_fd = _open_compose_directory(target, create=True)
        assert target_fd is not None
        os.close(target_fd)

    for item in src_root.iterdir():
        _copy_resource(item, target, Path(item.name))

    _write_version_file(target, content_hash)
    return target


def _copy_resource(src, dst: Path, relative: Path | None = None) -> None:
    relative = relative or Path(Path(str(src)).name)
    if relative.as_posix() in RUNTIME_PRESERVED_FILES or relative.as_posix() == ".version":
        return
    src_path = Path(str(src))
    if src_path.is_dir():
        destination = dst / src_path.name
        destination.mkdir(exist_ok=True)
        for child in src_path.iterdir():
            if child.name in {"__pycache__"} or child.suffix == ".pyc":
                continue
            _copy_resource(child, destination, relative / child.name)
    else:
        shutil.copy2(src_path, dst / src_path.name)


def bundled_resource_files() -> frozenset[str]:
    """Bundle-relative paths of every file extraction may write.

    Mirrors `_copy_resource`'s exclusions (runtime-preserved files and
    `.version`). This is the *universe* of bindable bundle files; use
    `changed_resource_files()` to learn which ones extraction will actually
    replace (only those change an inode)."""
    root = _bundled_compose_root()
    root_path = Path(str(root))
    if not root_path.is_dir():
        return frozenset()
    files: set[str] = set()
    for p in root_path.rglob("*"):
        if not p.is_file():
            continue
        relative = p.relative_to(root_path).as_posix()
        if relative in RUNTIME_PRESERVED_FILES or relative == ".version":
            continue
        files.add(relative)
    return frozenset(files)


def changed_resource_files() -> frozenset[str]:
    """Bundle files whose deployed copy extraction would actually replace.

    A file is "changed" when it is missing, differs in content, or differs in
    mode. Content-identical files are left in place by
    `_prune_for_extraction`, keeping their inode, so they cannot invalidate a
    running container's bind. Only this set may trigger a container restart.

    Returns empty when the compose dir was never extracted (no `.version`):
    nothing can be attributed to it, and a fresh install has no running
    containers holding its inodes."""
    target = _config_compose_dir()
    src_root = Path(str(_bundled_compose_root()))
    if not src_root.is_dir():
        return frozenset()
    if _read_runtime_file(target, ".version") is None:
        return frozenset()
    root_fd = _open_compose_directory(target)
    if root_fd is None:
        return frozenset()

    changed: set[str] = set()
    try:
        for relative in bundled_resource_files():
            parts = tuple(Path(relative).parts)
            parent_fd = _directory_fd(root_fd, parts[:-1], relative)
            if parent_fd is None:
                changed.add(relative)
                continue
            try:
                if not _file_matches_bundle(parent_fd, parts[-1], relative, src_root):
                    changed.add(relative)
            finally:
                os.close(parent_fd)
    finally:
        os.close(root_fd)
    return frozenset(changed)


def compose_resource_dir() -> Path:
    """The deployed compose dir that extraction writes (~/.config/cove/compose).

    Distinct from `resolve_compose_dir()`, which may return a dev checkout's
    `./compose`. Bind sources of the running stack are intersected against THIS
    dir, because it is the one extraction rewrites."""
    return _config_compose_dir()


def bundle_is_current() -> bool:
    """True when the deployed compose dir carries the current bundle marker, so
    extraction would early-return without touching any file."""
    version = _read_runtime_file(_config_compose_dir(), ".version")
    if version is None:
        return False
    return version[0].decode().strip() == _bundled_content_hash()


def ensure_init() -> Path:
    target = _config_compose_dir()
    version = _read_runtime_file(target, ".version")
    if version is not None and version[0].decode().strip() == _bundled_content_hash():
        return target
    return extract_resources()


def maybe_reextract() -> bool:
    target = _config_compose_dir()
    version = _read_runtime_file(target, ".version")
    if version is None:
        return False
    if version[0].decode().strip() != _bundled_content_hash():
        extract_resources(force=True)
        return True
    return False
