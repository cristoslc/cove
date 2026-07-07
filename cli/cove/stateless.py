"""Resource resolution and extraction for stateless CLI."""

import hashlib
import os
import shutil
import subprocess
from importlib.resources import files
from pathlib import Path

import click

from cove import __version__


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
    version_file = target / ".version"
    if (
        not force
        and target.exists()
        and version_file.exists()
        and version_file.read_text().strip() == content_hash
    ):
        return target

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    for item in src_root.iterdir():
        _copy_resource(item, target)
    version_file.write_text(content_hash)
    return target


def _copy_resource(src, dst: Path) -> None:
    src_path = Path(str(src))
    if src_path.is_dir():
        shutil.copytree(src_path, dst / src_path.name, dirs_exist_ok=True)
    else:
        shutil.copy2(src_path, dst / src_path.name)


def ensure_init() -> Path:
    target = _config_compose_dir()
    version_file = target / ".version"
    if target.exists() and version_file.exists():
        if version_file.read_text().strip() == _bundled_content_hash():
            return target
    return extract_resources()


def maybe_reextract() -> bool:
    target = _config_compose_dir()
    version_file = target / ".version"
    if not target.exists() or not version_file.exists():
        return False
    if version_file.read_text().strip() != _bundled_content_hash():
        extract_resources(force=True)
        return True
    return False