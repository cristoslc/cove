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

from cove import __version__

# Files bringup generates at runtime that extraction must never prune or
# overwrite. `certs/rootCA.pem` is copied from the machine's CA by bringup (the
# bundle may ship no `certs/` at all — `compose/certs/` is gitignored, so a
# wheel built from a clean checkout, e.g. the `cove update` git-worktree path,
# has none). Pruning it left the file missing; Docker then auto-created it as a
# directory and `docker restart cove-nginx` refused to start (2026-10-19 sev-2).
RUNTIME_PRESERVED_FILES = (".env", "nginx/default.conf", "certs/rootCA.pem")


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


def _prune_for_extraction(target: Path) -> None:
    """Remove stale resources while retaining runtime files and their inodes."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
    root_fd = _open_compose_directory(target)
    if root_fd is None:
        return
    preserved = set(RUNTIME_PRESERVED_FILES)

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
        _prune_for_extraction(target)
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
    """Bundle-relative paths of every file extraction would (re)write.

    Extraction prunes then re-copies each of these, giving it a NEW inode even
    when its bytes are unchanged. Any running container binding one of them
    ends up holding a stale (deleted) inode, so `cove up` restarts exactly the
    containers whose bind sources appear here. Mirrors `_copy_resource`'s
    exclusions (runtime-preserved files and `.version`)."""
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


def compose_resource_dir() -> Path:
    """The deployed compose dir that extraction writes (~/.config/cove/compose).

    Distinct from `resolve_compose_dir()`, which may return a dev checkout's
    `./compose`. Bind sources of the running stack are intersected against THIS
    dir, because it is the one extraction rewrites."""
    return _config_compose_dir()


def bundle_is_current() -> bool:
    """True when there is nothing to re-extract: the deployed compose dir is
    absent (fresh install, no running stack to reconcile), or its `.version`
    marker matches the bundled bundle hash.

    A missing `.version` is treated as "nothing to do" — the stack was never
    extracted from this dir, so no container can hold a stale inode from it.
    This keeps `cove up` from probing Docker when there is nothing to restart."""
    version = _read_runtime_file(_config_compose_dir(), ".version")
    if version is None:
        return True
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
