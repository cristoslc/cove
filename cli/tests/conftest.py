"""Shared fixtures for Cove CLI e2e tests.

Builds the wheel once per session, installs it into an isolated venv, and
yields a handle that invokes the *built* `cove` binary against a temp HOME.
This exercises the branch's packaged resources (cove.resources/compose/)
end-to-end without relying on whatever stack happens to be on 127.0.0.1:443.

Per `~/.agents/agents-md-detail/test-driven-design.md` E2E Protocol:
  - single command: `pytest tests/` runs these by default (no -m flag needed)
  - shared build helper: session-scoped `_cove_artifact` builds wheel once
  - complete flow: init -> ops -> cleanup/idempotency covered in test_e2e_stateless.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _copy_cli_tree(repo: Path, dst: Path) -> None:
    """Copy `cli/` and `compose/` into an isolated build tree.

    Skips the local venv, build/dist outputs, bytecode caches, and the
    gitignored in-tree `cove/resources/compose/` artifact so a build here never
    reads or mutates the working tree's copy.
    """
    skip_dirs = {".venv", "venv", "build", "dist", "__pycache__", ".pytest_cache"}
    artifact = Path("cove") / "resources" / "compose"

    def _ignore(dirpath, names):
        here = Path(dirpath)
        rel = here.relative_to(repo)
        ignored = []
        for name in names:
            if name in skip_dirs:
                ignored.append(name)
            elif name.endswith(".egg-info"):
                ignored.append(name)
            elif (rel / name).as_posix() == artifact.as_posix():
                ignored.append(name)
        return ignored

    for sub in ("cli", "compose"):
        shutil.copytree(
            repo / sub, dst / sub, ignore=_ignore, symlinks=True
        )


def _build_wheel(cli_dir: Path, out_dir: Path) -> Path:
    """Build the wheel for `cli_dir` into `out_dir`; fail loudly on error."""
    out_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out_dir)],
        cwd=str(cli_dir),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.fail(f"`uv build` failed:\n{proc.stderr}\n{proc.stdout}")
    wheels = sorted(out_dir.glob("cove_cli-*.whl"))
    assert wheels, f"no wheel produced in {out_dir}"
    return wheels[-1]


def _wheel_compose_files(wheel: Path) -> dict[str, bytes]:
    """Map relpath -> bytes for `cove/resources/compose/` inside the wheel."""
    prefix = "cove/resources/compose/"
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(wheel) as zf:
        for name in zf.namelist():
            if name.startswith(prefix) and not name.endswith("/"):
                files[name[len(prefix):]] = zf.read(name)
    return files


@pytest.fixture(scope="session")
def bundled_compose(tmp_path_factory) -> dict[str, bytes]:
    """The checked-in `compose/` tree as packaged into a freshly built wheel.

    The wheel is the deploy artifact (`cove up` / `cove update` extract
    `~/.config/cove/compose/` from it), so this is the authoritative view of
    what actually ships. Built in an isolated copy of the repo: the gitignored
    in-tree artifact (`cli/cove/resources/compose/`) is neither read nor
    mutated, so a stale local copy cannot fail the drift guards and a real
    packaging gap still can.
    """
    repo = _repo_root()
    if not (repo / "cli" / "pyproject.toml").exists():
        pytest.skip(f"cli/ not found under {repo}")

    work = tmp_path_factory.mktemp("cove-bundle")
    tree = work / "src"
    tree.mkdir()
    _copy_cli_tree(repo, tree)
    wheel = _build_wheel(tree / "cli", work / "wheels")
    return _wheel_compose_files(wheel)


@pytest.fixture(scope="session")
def _cove_artifact(tmp_path_factory):
    """Build the wheel once per session and install into an isolated venv.

    Yields a dict with:
      - bin:   Path to the installed `cove` executable
      - wheel: Path to the built wheel
      - venv:  Path to the temp venv
    """
    repo = _repo_root()
    cli_dir = repo / "cli"
    if not (cli_dir / "pyproject.toml").exists():
        pytest.skip(f"cli/ not found at {cli_dir}")

    work = tmp_path_factory.mktemp("cove-artifact")
    wheel_dir = work / "wheels"
    wheel_dir.mkdir()

    build = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(wheel_dir)],
        cwd=str(cli_dir),
        capture_output=True,
        text=True,
    )
    if build.returncode != 0:
        pytest.fail(f"`uv build` failed:\n{build.stderr}\n{build.stdout}")

    wheels = list(wheel_dir.glob("cove_cli-*.whl"))
    assert wheels, f"no wheel produced in {wheel_dir}"
    wheel = wheels[0]

    venv = work / "venv"
    vcreate = subprocess.run(
        [sys.executable, "-m", "venv", str(venv)],
        capture_output=True,
        text=True,
    )
    if vcreate.returncode != 0:
        pytest.fail(f"venv creation failed:\n{vcreate.stderr}")

    pip = venv / "bin" / "pip"
    inst = subprocess.run(
        [str(pip), "install", "--no-deps", str(wheel)],
        capture_output=True,
        text=True,
    )
    if inst.returncode != 0:
        pytest.fail(f"pip install failed:\n{inst.stderr}")
    deps = subprocess.run(
        [str(pip), "install", "click", "cryptography>=42.0.0", "jinja2>=3.1", "pyyaml>=6.0.3", "requests>=2.33.0"],
        capture_output=True,
        text=True,
    )
    if deps.returncode != 0:
        pytest.fail(f"dep install failed:\n{deps.stderr}")

    bin_path = venv / "bin" / "cove"
    assert bin_path.exists(), f"cove binary not at {bin_path}"

    yield {"bin": bin_path, "wheel": wheel, "venv": venv, "work": work}


@pytest.fixture()
def cove_home(tmp_path, monkeypatch):
    """Isolated HOME so cove writes nothing outside the test sandbox."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("COVE_COMPOSE_DIR", raising=False)
    monkeypatch.delenv("COVE_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("COVE_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("COVE_OP_VAULT", raising=False)
    monkeypatch.delenv("COVE_TS_DNS_NAME", raising=False)
    return home


@pytest.fixture()
def cove_run(_cove_artifact, cove_home, monkeypatch):
    """Callable that invokes the installed `cove` binary in the sandbox.

    Returns a wrapper around subprocess.run with HOME/COVE_* pre-set.
    Pass args as a list; returns the CompletedProcess.
    """
    bin_path = _cove_artifact["bin"]

    def _run(args, **kw):
        env = dict(os.environ)
        env["HOME"] = str(cove_home)
        env.pop("COVE_COMPOSE_DIR", None)
        kw.setdefault("capture_output", True)
        kw.setdefault("text", True)
        kw.setdefault("timeout", 180)
        return subprocess.run([str(bin_path), *args], env=env, **kw)

    return _run


@pytest.fixture()
def cove_python(_cove_artifact):
    """Path to the Python interpreter inside the artifact venv."""
    return _cove_artifact["venv"] / "bin" / "python"