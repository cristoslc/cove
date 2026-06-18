"""Resource resolution and extraction for stateless CLI."""

import os
import shutil
import subprocess
from importlib.resources import files
from pathlib import Path

import click

from cove import __version__


def _config_compose_dir() -> Path:
    return Path.home() / ".config" / "cove" / "compose"


def resolve_compose_dir() -> Path:
    env = os.environ.get("COVE_COMPOSE_DIR")
    if env:
        p = Path(env)
        if (p / "inventory.yml").exists():
            return p

    cwd = Path.cwd()
    for candidate in [cwd / "compose", cwd / ".worktrees" / cwd.name / "compose"]:
        if (candidate / "inventory.yml").exists():
            return candidate

    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, cwd=str(cwd),
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


def _bundled_compose_root():
    return files("cove.resources") / "compose"


def extract_resources(force: bool = False) -> Path:
    target = _config_compose_dir()
    src_root = _bundled_compose_root()
    if not src_root.is_dir():
        raise click.ClickException(
            "Bundled compose resources not found. Reinstall cove-cli."
        )

    version_file = target / ".version"
    if (
        not force
        and target.exists()
        and version_file.exists()
        and version_file.read_text().strip() == __version__
    ):
        return target

    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    for item in src_root.iterdir():
        _copy_resource(item, target)
    version_file.write_text(__version__)
    return target


def _copy_resource(src, dst: Path) -> None:
    src_path = Path(str(src))
    if src_path.is_dir():
        dst_dir = dst / src_path.name
        dst_dir.mkdir(parents=True, exist_ok=True)
        for child in src_path.rglob("*"):
            if child.is_file():
                rel = child.relative_to(src_path)
                target_file = dst_dir / rel
                target_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(child), str(target_file))
    else:
        shutil.copy2(str(src_path), str(dst / src_path.name))


def ensure_init() -> Path:
    target = _config_compose_dir()
    version_file = target / ".version"
    if target.exists() and version_file.exists():
        if version_file.read_text().strip() == __version__:
            return target
    return extract_resources()


def maybe_reextract() -> bool:
    target = _config_compose_dir()
    version_file = target / ".version"
    if not target.exists() or not version_file.exists():
        return False
    if version_file.read_text().strip() != __version__:
        extract_resources(force=True)
        return True
    return False