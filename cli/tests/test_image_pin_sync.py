"""Wheel image pins reach an existing host on every converge (digest plan Phase 0).

The digest-pinning plan (docs/musings/digest-pinning-plan.md, #142) found the
delivery defect: `compose/bringup.yml` wrote the image variables into the
deployed compose `.env` on first boot only, and the later re-sync covered four
non-image keys. A pin bump in the wheel's `group_vars` therefore changed the
compose default, not the value Compose interpolates from `.env`; `cove update`
reported success while applying nothing. `--pull always` hid it while tags
floated.

The contract pinned here:

  1. Every image key the compose set interpolates from the environment is
     authoritative from the wheel and is re-synced into the deployed `.env` on
     every converge.
  2. Only keys named in `cove_image_env_operator_overrides` (group_vars,
     overridable in host_vars) may diverge. ADE is the built-in exception
     because `cove ade update` writes its pin at runtime.
  3. An operator edit to an authoritative key is overwritten, not silently
     preserved. The allowlist is the only way to keep one.

These tests load the same `compose/scripts/sync_env.py` that bringup runs and
drive it against a temp `.env`. No Ansible run, no Docker, no live stack.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def _project_root() -> Path:
    start = Path(__file__).resolve().parent
    for _ in range(6):
        if (start / "compose" / "inventory.yml").exists():
            return start
        start = start.parent
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
COMPOSE_DIR = PROJECT_ROOT / "compose"
BRINGUP = COMPOSE_DIR / "bringup.yml"
GROUP_VARS = COMPOSE_DIR / "group_vars" / "all.yml"
SYNC_SCRIPT = COMPOSE_DIR / "scripts" / "sync_env.py"

SYNC_TASK = "Sync image pins into the compose .env (wheel authoritative)"

# `${VAR:-default}` and `${VAR}` forms, the two Compose interpolation shapes
# the compose set uses for image references and build args.
_INTERP_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)(?::-[^}]*)?\}")


def _load_sync_module():
    spec = importlib.util.spec_from_file_location("cove_sync_env", SYNC_SCRIPT)
    assert spec is not None and spec.loader is not None, f"cannot load {SYNC_SCRIPT}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bringup() -> dict:
    data = yaml.safe_load(BRINGUP.read_text())
    return data[0] if isinstance(data, list) else data


def _tasks() -> list[dict]:
    return _bringup()["tasks"]


def _task(name: str) -> dict:
    for task in _tasks():
        if task.get("name") == name:
            return task
    raise AssertionError(f"bringup.yml has no task named {name!r}")


def _compose_image_env_keys() -> set[str]:
    """Every env key the compose set interpolates into an image or build tag."""
    keys: set[str] = set()
    for path in COMPOSE_DIR.rglob("*.yml"):
        for match in _INTERP_RE.finditer(path.read_text()):
            key = match.group(1)
            if key.endswith("_IMAGE") or key == "ADE_BB_APP_VERSION":
                keys.add(key)
    return keys


def _pins() -> dict[str, str]:
    return _bringup()["vars"]["cove_image_env_pins"]


def _overrides() -> list[str]:
    return yaml.safe_load(GROUP_VARS.read_text())["cove_image_env_operator_overrides"]


class TestContract:
    def test_pins_cover_every_image_env_key_the_compose_set_consumes(self):
        assert set(_pins()) == _compose_image_env_keys(), (
            "the authoritative pin map must name every ${*_IMAGE} / tag key the "
            "compose set interpolates; a missing key keeps the first-boot .env "
            "value forever"
        )

    def test_default_allowlist_is_exactly_the_ade_runtime_override(self):
        assert _overrides() == ["ADE_IMAGE", "ADE_BB_APP_VERSION"], (
            "ADE is the one documented runtime override (cove ade update); "
            "every other image key must be wheel-authoritative"
        )
        assert set(_overrides()) <= set(_pins())

    def test_sync_task_runs_on_every_converge_not_first_boot_only(self):
        task = _task(SYNC_TASK)
        assert "when" not in task, (
            "the image pin sync must run on every up; a first-boot guard is the "
            "delivery defect this task closes"
        )
        module = task["ansible.builtin.command"]
        assert "creates" not in module, "a creates guard skips existing .env files"
        argv = module["argv"]
        assert argv[0].startswith("{{") and argv[0].endswith("}}")
        assert argv[1].endswith("scripts/sync_env.py")
        assert "cove_image_env_pins" in argv[3]
        assert "cove_image_env_operator_overrides" in argv[4]

    def test_first_boot_render_keeps_every_pin_for_a_complete_env(self):
        text = BRINGUP.read_text()
        for key in _pins():
            assert f"{key}=" in text, (
                f"first boot must still render {key}; the per-up sync is a "
                "repair path, not the only writer"
            )


class TestPinSync:
    def test_pin_change_in_the_wheel_reaches_the_deployed_env(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "COVE_DATA_ROOT=/srv/cove-data\n"
            "FORGEJO_IMAGE=codeberg.org/forgejo/forgejo:15\n"
            "NGINX_IMAGE=nginx:1.27-alpine\n"
        )
        module = _load_sync_module()

        changed = module.sync_pins(
            env,
            {
                "FORGEJO_IMAGE": "codeberg.org/forgejo/forgejo:16",
                "NGINX_IMAGE": "nginx:1.27-alpine",
            },
        )

        assert changed is True
        text = env.read_text()
        assert "FORGEJO_IMAGE=codeberg.org/forgejo/forgejo:16" in text
        assert "codeberg.org/forgejo/forgejo:15" not in text
        assert "NGINX_IMAGE=nginx:1.27-alpine" in text
        assert "COVE_DATA_ROOT=/srv/cove-data" in text

    def test_allowlisted_operator_override_survives_a_converge(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("ADE_IMAGE=cove-ade:0.45.0\nADE_BB_APP_VERSION=0.45.0\n")
        module = _load_sync_module()

        changed = module.sync_pins(
            env,
            {
                "ADE_IMAGE": "cove-ade:0.44.0",
                "ADE_BB_APP_VERSION": "0.44.0",
            },
            overrides={"ADE_IMAGE", "ADE_BB_APP_VERSION"},
        )

        assert changed is False
        text = env.read_text()
        assert "ADE_IMAGE=cove-ade:0.45.0" in text
        assert "ADE_BB_APP_VERSION=0.45.0" in text

    def test_non_allowlisted_operator_edit_is_overwritten(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("NGINX_IMAGE=private.example/nginx:pinned\n")
        module = _load_sync_module()

        changed = module.sync_pins(
            env,
            {"NGINX_IMAGE": "nginx:1.27-alpine"},
            overrides=(),
        )

        assert changed is True
        assert env.read_text().strip() == "NGINX_IMAGE=nginx:1.27-alpine"

    def test_first_boot_creates_a_private_env_with_every_pin(self, tmp_path):
        env = tmp_path / ".env"
        module = _load_sync_module()
        pins = {"FORGEJO_IMAGE": "forgejo:15", "NGINX_IMAGE": "nginx:1.27-alpine"}

        changed = module.sync_pins(env, pins)

        assert changed is True
        assert env.read_text() == "FORGEJO_IMAGE=forgejo:15\nNGINX_IMAGE=nginx:1.27-alpine\n"
        assert (env.stat().st_mode & 0o777) == 0o600

    def test_partial_env_gains_missing_pins_and_keeps_other_lines(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("# operator note\nCOVE_DATA_ROOT=/srv/cove-data\n")
        module = _load_sync_module()

        module.sync_pins(env, {"NGINX_IMAGE": "nginx:1.27-alpine"})

        text = env.read_text()
        assert text.startswith("# operator note\nCOVE_DATA_ROOT=/srv/cove-data\n")
        assert "NGINX_IMAGE=nginx:1.27-alpine" in text

    def test_repeat_sync_is_a_no_op(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("NGINX_IMAGE=nginx:1.27-alpine\n")
        module = _load_sync_module()

        assert module.sync_pins(env, {"NGINX_IMAGE": "nginx:1.27-alpine"}) is False

    def test_duplicate_pin_lines_collapse_to_one(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "NGINX_IMAGE=nginx:1.27-alpine\n"
            "COVE_DATA_ROOT=/srv/cove-data\n"
            "NGINX_IMAGE=nginx:old\n"
        )
        module = _load_sync_module()

        module.sync_pins(env, {"NGINX_IMAGE": "nginx:1.27-alpine"})

        lines = env.read_text().splitlines()
        assert lines.count("NGINX_IMAGE=nginx:1.27-alpine") == 1
        assert not any("nginx:old" in line for line in lines)

    def test_unknown_allowlist_key_fails_loudly(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("")
        module = _load_sync_module()

        with pytest.raises(ValueError, match="NGNIX_IMAGE"):
            module.sync_pins(env, {"NGINX_IMAGE": "nginx:1.27-alpine"}, overrides={"NGNIX_IMAGE"})

    def test_cli_reports_changed_and_unchanged(self, tmp_path):
        env = tmp_path / ".env"
        pins = json.dumps({"NGINX_IMAGE": "nginx:1.27-alpine"})

        first = subprocess.run(
            [sys.executable, str(SYNC_SCRIPT), str(env), pins],
            capture_output=True,
            text=True,
            check=False,
        )
        second = subprocess.run(
            [sys.executable, str(SYNC_SCRIPT), str(env), pins],
            capture_output=True,
            text=True,
            check=False,
        )

        assert first.returncode == 0, first.stderr
        assert first.stdout.strip() == "changed"
        assert second.returncode == 0, second.stderr
        assert second.stdout.strip() == "unchanged"
