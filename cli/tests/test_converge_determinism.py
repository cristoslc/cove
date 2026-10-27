"""A converge that changes nothing must change nothing (contract).

2026-10-26: every `cove up` recreated `cove-litellm` and restarted `cove-nginx`,
opening a 1-2 minute 502 window for every LLM-proxy client (two agent threads
aborted mid-turn). After the churn was traced to the live project converging
from alternating compose dirs (guarded in `test_compose_source_guards.py`), two
playbook-level non-determinisms remained, and they are pinned here:

  1. The iOS `.mobileconfig` identifiers were three fresh `uuid4()` values per
     run, so the rendered iOS DNS installer script rewrote itself on every
     converge.
  2. The compose `.env` carried `NGINX_CONF_DIR` / `DNSMASQ_CONF_DIR` from
     whichever dir converged first (first-boot-only render). Compose folds both
     into the nginx/dnsmasq config hash, so a stale value recreates nginx on a
     converge that changed nothing.

Both are checked structurally against `compose/bringup.yml`, plus one executed
check of the UUID snippet: the task's own inline Python is run twice and the
outputs must be byte-identical. No Ansible run, no Docker, no live stack.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
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

IOS_UUID_TASK = "Derive stable UUIDs for the iOS profile"
ENV_PATH_TASK = "Ensure compose-dir path env matches the Ansible vars (nginx / dnsmasq)"


def _bringup_text() -> str:
    return BRINGUP.read_text()


def _tasks() -> list[dict]:
    data = yaml.safe_load(_bringup_text())
    if isinstance(data, list):
        return data[0]["tasks"]
    return data["tasks"]


def _find_task(name: str) -> dict:
    for task in _tasks():
        if task.get("name") == name:
            return task
    raise AssertionError(f"bringup.yml has no task named {name!r}")


def _module_args(task: dict) -> dict:
    """The module payload of a task (the key that is not an Ansible keyword)."""
    keywords = {
        "name", "when", "loop", "register", "changed_when", "failed_when",
        "become", "vars", "notify", "tags", "loop_control", "environment",
        "args", "ignore_errors", "no_log", "delegate_to", "run_once",
    }
    for key, value in task.items():
        if key not in keywords:
            return value
    raise AssertionError(f"task {task.get('name')!r} has no module")


class TestIOSProfileUUIDsAreDeterministic:
    def test_bringup_generates_no_random_uuids(self):
        """uuid4 is the exact non-determinism that rewrote the iOS script."""
        text = _bringup_text()
        assert "uuid.uuid4" not in text, (
            "bringup.yml must not generate per-run random UUIDs: a no-op "
            "converge would rewrite the iOS DNS installer script"
        )
        assert "uuid4()" not in text

    def test_uuid_task_is_registered_and_not_a_change(self):
        task = _find_task(IOS_UUID_TASK)
        assert task["register"] == "uuids"
        assert task["changed_when"] is False, (
            "deriving stable UUIDs is not a change; converge output must say so"
        )

    def test_uuid_snippet_is_byte_identical_across_runs(self):
        """Execute the playbook's own inline Python twice; outputs must match."""
        argv = _module_args(_find_task(IOS_UUID_TASK))["argv"]
        assert argv[0].startswith("{{"), "expected the Ansible python interpreter"
        assert argv[1] == "-c"
        snippet = argv[2]

        def run(seed: str, identity: str) -> str:
            result = subprocess.run(
                [sys.executable, "-c", snippet, seed, identity],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout

        first = run("test-ca-b64", "testhost")
        second = run("test-ca-b64", "testhost")
        assert first == second, "iOS profile UUIDs must not change between converges"

        values = first.split()
        assert len(values) == 3, f"expected ca/dns/profile UUIDs, got {values!r}"
        assert len(set(values)) == 3, "the three identifiers must differ"
        for value in values:
            assert uuid.UUID(value).version == 5, (
                f"expected a name-based (v5) UUID, got {value!r}"
            )

    def test_uuid_snippet_varies_per_machine_and_ca(self):
        """Stable per converge, distinct across machines/CA generations."""
        argv = _module_args(_find_task(IOS_UUID_TASK))["argv"]
        snippet = argv[2]

        def run(seed: str, identity: str) -> str:
            return subprocess.run(
                [sys.executable, "-c", snippet, seed, identity],
                capture_output=True,
                text=True,
                check=True,
            ).stdout

        base = run("test-ca-b64", "testhost")
        assert run("test-ca-b64", "otherhost") != base
        assert run("other-ca-b64", "testhost") != base


class TestComposeDirPathEnvIsResynced:
    def test_env_path_task_runs_on_every_up(self):
        task = _find_task(ENV_PATH_TASK)
        assert "when" not in task, (
            "the NGINX_CONF_DIR/DNSMASQ_CONF_DIR sync must run on every up, "
            "not first-boot only"
        )
        assert "creates" not in _module_args(task), "lineinfile is not creates-guarded"

    def test_env_path_task_derives_both_paths_from_the_ansible_vars(self):
        task = _find_task(ENV_PATH_TASK)
        loop = task["loop"]
        by_key = {entry["key"]: entry["value"] for entry in loop}
        assert set(by_key) == {"NGINX_CONF_DIR", "DNSMASQ_CONF_DIR"}, (
            "every compose-dir-derived .env path must be re-synced"
        )
        assert by_key["NGINX_CONF_DIR"] == "{{ nginx_conf_dir }}"
        assert by_key["DNSMASQ_CONF_DIR"] == "{{ dnsmasq_conf_dir }}"

    def test_first_boot_env_render_still_goes_through_the_same_vars(self):
        """The first-boot render must not disagree with the per-up sync."""
        text = _bringup_text()
        assert "NGINX_CONF_DIR={{ nginx_conf_dir }}" in text
        assert "DNSMASQ_CONF_DIR={{ dnsmasq_conf_dir }}" in text


class TestNginxTemplateHasNoPerRunInputs:
    @pytest.mark.parametrize("template", ["default.conf.j2", "config.html.j2"])
    def test_template_uses_no_clock_or_random_values(self, template):
        source = (COMPOSE_DIR / "nginx" / template).read_text()
        for token in ("ansible_date_time", "uuid4", "now()", "lookup('pipe'"):
            assert token not in source, (
                f"{template} must not depend on {token}: it would make a no-op "
                "converge rewrite the config and restart nginx"
            )

    def test_nginx_template_task_is_not_creates_guarded(self):
        """A drift-aware render must run every up (v0.7.0 regression guard)."""
        task = _find_task("Render nginx config from template")
        assert "creates" not in _module_args(task)
        assert task.get("notify") == "Reload nginx"
