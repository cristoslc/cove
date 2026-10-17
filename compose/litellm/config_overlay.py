"""Build LiteLLM's runtime config from Cove defaults and local operator state."""

from __future__ import annotations

import argparse
import os
import re
import secrets
import stat
from pathlib import Path
from typing import Any

import yaml

_SECRET_FIELDS = {"key", "password", "secret", "token", "credential", "credentials"}
_SECRET_SUFFIXES = ("_key", "_password", "_secret", "_token", "_credential", "_credentials")
_SEALED_SETTINGS = {"disable_mcp", "disable_jwt_auth"}


def _open_trusted_child_directory(
    path: Path, trusted_root: Path, *, create: bool
) -> tuple[int, str]:
    """Open a real direct child of a configured root without following it.

    The configured root itself may be a symlink (for operator-managed mounts).
    The Cove-owned child directory may not be a symlink.
    """
    root = Path(os.path.abspath(trusted_root))
    child = Path(os.path.abspath(path))
    if child.parent != root or child.name in {"", ".", ".."}:
        raise ValueError(f"LiteLLM path must be a direct child of trusted root: {path}")

    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise OSError("safe LiteLLM path setup requires O_NOFOLLOW support")
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    if not directory_flag:
        raise OSError("safe LiteLLM path setup requires O_DIRECTORY support")
    common_flags = os.O_RDONLY | directory_flag | getattr(os, "O_CLOEXEC", 0)
    nofollow_flags = common_flags | nofollow
    root.mkdir(parents=True, exist_ok=True)
    root_fd = os.open(root, common_flags)
    try:
        try:
            child_fd = os.open(child.name, nofollow_flags, dir_fd=root_fd)
            created = False
        except FileNotFoundError:
            if not create:
                raise
            try:
                os.mkdir(child.name, 0o700, dir_fd=root_fd)
                created = True
            except FileExistsError:
                # A concurrent creator won; open only a real directory.
                created = False
            child_fd = os.open(child.name, nofollow_flags, dir_fd=root_fd)
    finally:
        os.close(root_fd)

    try:
        if not stat.S_ISDIR(os.fstat(child_fd).st_mode):
            raise ValueError(f"LiteLLM directory must be a real directory: {path}")
        previous_mode = stat.S_IMODE(os.fstat(child_fd).st_mode)
        os.fchmod(child_fd, 0o700)
    except BaseException:
        os.close(child_fd)
        raise
    if created:
        return child_fd, "created"
    return child_fd, "permissions-updated" if previous_mode != 0o700 else "unchanged"


def ensure_private_directory(path: Path, trusted_root: Path) -> str:
    """Create or secure Cove's private directory under a configured root."""
    directory_fd, status = _open_trusted_child_directory(path, trusted_root, create=True)
    os.close(directory_fd)
    return status


def ensure_private_env_file(path: Path, trusted_root: Path) -> str:
    """Create or secure a regular env file beneath a real directory child."""
    child = Path(os.path.abspath(path))
    root = Path(os.path.abspath(trusted_root))
    if child.parent.parent != root or child.parent.name in {"", ".", ".."}:
        raise ValueError(f"LiteLLM env file must be below the trusted root: {path}")
    directory_fd, directory_status = _open_trusted_child_directory(
        child.parent, root, create=True
    )
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise OSError("safe local.env setup requires O_NOFOLLOW support")
        common_flags = nofollow | getattr(os, "O_CLOEXEC", 0)
        read_flags = os.O_RDONLY | common_flags | getattr(os, "O_NONBLOCK", 0)
        try:
            fd = os.open(child.name, read_flags, dir_fd=directory_fd)
            created = False
        except FileNotFoundError:
            try:
                fd = os.open(
                    child.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | common_flags,
                    0o600,
                    dir_fd=directory_fd,
                )
                created = True
            except FileExistsError:
                # A concurrent creator won; reopen with O_NOFOLLOW before use.
                fd = os.open(child.name, read_flags, dir_fd=directory_fd)
                created = False
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError(f"LiteLLM env file must be a regular file: {path}")
            previous_mode = stat.S_IMODE(os.fstat(fd).st_mode)
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
    finally:
        os.close(directory_fd)
    if created:
        return "created"
    if directory_status != "unchanged" or previous_mode != 0o600:
        return "permissions-updated"
    return "unchanged"

def _read_regular_at(directory_fd: int, name: str) -> tuple[bytes, int]:
    """Read a regular file without following a symlink relative to a directory fd."""
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise OSError("safe LiteLLM config access requires O_NOFOLLOW support")
    fd = os.open(
        name,
        os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0),
        dir_fd=directory_fd,
    )
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"LiteLLM config must be a regular file: {name}")
        chunks = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks), metadata.st_mode
    finally:
        os.close(fd)


def _read_regular_path(path: Path, *, trusted_root: Path | None = None) -> tuple[bytes, int] | None:
    """Read an optional regular config file through a directory descriptor."""
    parent = Path(os.path.abspath(path.parent))
    if trusted_root is not None:
        directory_fd, _ = _open_trusted_child_directory(parent, trusted_root, create=False)
    else:
        directory_fd = os.open(
            parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
        )
    try:
        try:
            return _read_regular_at(directory_fd, path.name)
        except FileNotFoundError:
            return None
    finally:
        os.close(directory_fd)


def _write_regular_at(directory_fd: int, name: str, content: bytes, mode: int) -> None:
    """Atomically replace a file relative to a validated directory descriptor."""
    temporary = f".{name}.{os.getpid()}.{secrets.token_hex(8)}"
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        mode,
        dir_fd=directory_fd,
    )
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(fd)
    os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)


def _open_config_directory(local: Path, trusted_root: Path | None) -> int:
    parent = Path(os.path.abspath(local.parent))
    if trusted_root is not None:
        return _open_trusted_child_directory(parent, trusted_root, create=False)[0]
    return os.open(
        parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    )


def _mapping_from_bytes(content: bytes, label: str) -> dict[str, Any]:
    value = yaml.safe_load(content)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"LiteLLM config must be a YAML mapping: {label}")
    return value


def merge_config(base: dict[str, Any], local: dict[str, Any]) -> dict[str, Any]:
    """Merge local values over base; append model deployments and replace other lists."""
    merged = dict(base)
    for key, value in local.items():
        if key == "model_list" and isinstance(value, list):
            base_models = merged.get(key, [])
            if not isinstance(base_models, list):
                raise ValueError("base model_list must be a list")
            merged[key] = [*base_models, *value]
        elif isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = merge_config(merged[key], value)
        else:
            merged[key] = value
    return merged


def _validate_config(config: dict[str, Any]) -> None:
    def visit(value: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = (*path, str(key))
                field_name = str(key).lower()
                if field_name in _SECRET_FIELDS or field_name.endswith(_SECRET_SUFFIXES):
                    if not isinstance(child, str) or not re.fullmatch(
                        r"os\.environ/[A-Za-z_][A-Za-z0-9_]*", child
                    ):
                        raise ValueError(
                            f"credential at {'.'.join(child_path)} must use an os.environ/NAME reference"
                        )
                visit(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, (*path, str(index)))

    visit(config)
    general = config.get("general_settings", {})
    if not isinstance(general, dict):
        raise ValueError("general_settings must be a mapping")
    for setting in _SEALED_SETTINGS:
        if general.get(setting) is not True:
            raise ValueError(f"general_settings.{setting} must remain true")


def generate_runtime_config(
    base: Path,
    local: Path,
    runtime: Path,
    *,
    legacy: Path | None = None,
    trusted_root: Path | None = None,
) -> dict[str, Any]:
    """Migrate existing runtime config once, then atomically render current defaults."""
    base_content = _read_regular_path(base)
    if base_content is None:
        raise FileNotFoundError(base)
    base_config = _mapping_from_bytes(base_content[0], str(base))

    config_parent = Path(os.path.abspath(local.parent))
    for owned_path in (runtime, legacy):
        if owned_path is not None and Path(os.path.abspath(owned_path.parent)) != config_parent:
            raise ValueError("local, runtime, and legacy LiteLLM configs must share one directory")
    directory_fd = _open_config_directory(local, trusted_root)
    try:
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise OSError("safe LiteLLM config access requires O_NOFOLLOW support")

        # Validate existing runtime output before it can be read or replaced. In
        # the migration layout this is also the legacy source file.
        runtime_before = None
        try:
            runtime_before = _read_regular_at(directory_fd, runtime.name)
        except FileNotFoundError:
            pass

        try:
            local_fd = os.open(
                local.name,
                os.O_RDONLY
                | nofollow
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NONBLOCK", 0),
                dir_fd=directory_fd,
            )
        except FileNotFoundError:
            local_bytes = b"{}\n"
            if legacy is not None:
                try:
                    local_bytes = _read_regular_at(directory_fd, legacy.name)[0]
                except FileNotFoundError:
                    pass
            try:
                local_fd = os.open(
                    local.name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow | getattr(os, "O_CLOEXEC", 0),
                    0o600,
                    dir_fd=directory_fd,
                )
                with os.fdopen(local_fd, "wb") as stream:
                    stream.write(local_bytes)
                    stream.flush()
                    os.fsync(stream.fileno())
                local_fd = None
            except FileExistsError:
                local_fd = os.open(
                    local.name,
                    os.O_RDONLY
                    | nofollow
                    | getattr(os, "O_CLOEXEC", 0)
                    | getattr(os, "O_NONBLOCK", 0),
                    dir_fd=directory_fd,
                )
        if local_fd is not None:
            try:
                metadata = os.fstat(local_fd)
                if not stat.S_ISREG(metadata.st_mode):
                    raise ValueError(f"LiteLLM config must be a regular file: {local}")
                os.fchmod(local_fd, 0o600)
                chunks = []
                while True:
                    chunk = os.read(local_fd, 65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                local_bytes = b"".join(chunks)
            finally:
                os.close(local_fd)
        local_config = _mapping_from_bytes(local_bytes, str(local))
    finally:
        os.close(directory_fd)

    runtime_config = merge_config(base_config, local_config)
    _validate_config(runtime_config)
    rendered = yaml.safe_dump(runtime_config, sort_keys=False, allow_unicode=True).encode("utf-8")
    runtime_mode = runtime_before[1] & 0o777 if runtime_before is not None else None
    needs_write = runtime_before is None or runtime_before[0] != rendered or runtime_mode != 0o644
    if needs_write:
        # The pinned image runs as UID 1000. Credential fields are validated
        # as environment references above, so the mounted YAML can be readable
        # by that container user while its 0700 host directory stays private.
        directory_fd = _open_config_directory(local, trusted_root)
        try:
            # Recheck at the point of replacement so a newly introduced link is
            # rejected instead of silently replacing or reading through it.
            try:
                _read_regular_at(directory_fd, runtime.name)
            except FileNotFoundError:
                pass
            _write_regular_at(directory_fd, runtime.name, rendered, 0o644)
        finally:
            os.close(directory_fd)
    return runtime_config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ensure-private-dir", type=Path)
    parser.add_argument("--ensure-env-file", type=Path)
    parser.add_argument("--trusted-root", type=Path)
    parser.add_argument("--base", type=Path)
    parser.add_argument("--local", type=Path)
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--legacy", type=Path)
    args = parser.parse_args()
    setup_statuses = []
    if args.ensure_private_dir is not None:
        if args.trusted_root is None:
            parser.error("--trusted-root is required with --ensure-private-dir")
        setup_statuses.append(
            ensure_private_directory(args.ensure_private_dir, args.trusted_root)
        )
    if args.ensure_env_file is not None:
        if args.trusted_root is None:
            parser.error("--trusted-root is required with --ensure-env-file")
        setup_statuses.append(
            ensure_private_env_file(args.ensure_env_file, args.trusted_root)
        )
    if any(value is None for value in (args.base, args.local, args.runtime, args.legacy)):
        if args.base is None and setup_statuses:
            print(
                "updated"
                if any(status != "unchanged" for status in setup_statuses)
                else "unchanged"
            )
            return
        parser.error("--base, --local, --runtime, and --legacy are required for config generation")
    local_existed = _read_regular_path(args.local, trusted_root=args.trusted_root) is not None
    old_runtime = _read_regular_path(args.runtime, trusted_root=args.trusted_root)
    generate_runtime_config(
        args.base, args.local, args.runtime, legacy=args.legacy, trusted_root=args.trusted_root
    )
    new_runtime = _read_regular_path(args.runtime, trusted_root=args.trusted_root)
    changed = not local_existed or old_runtime != new_runtime
    changed = changed or any(status != "unchanged" for status in setup_statuses)
    print("updated" if changed else "unchanged")


if __name__ == "__main__":
    main()
