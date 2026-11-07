"""The expected-state file: what Cove last asked the stack to be.

The watchdog compares live state against this file rather than inferring
intent, so the file's integrity matters more than its content: an atomic,
0600 write, a partial converge that is visibly incomplete, and a per-service
update that never invents expectations for containers it did not touch.
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from cove import expected_state


@pytest.fixture()
def state_file(tmp_path):
    return tmp_path / "state" / "expected.json"


def test_missing_file_reads_as_none(tmp_path):
    assert expected_state.read_expected(tmp_path / "nope.json") is None


def test_write_is_atomic_and_0600(state_file):
    payload = expected_state.record_down(state_file)
    assert state_file.is_file()
    mode = stat.S_IMODE(state_file.stat().st_mode)
    assert mode == 0o600, oct(mode)
    assert json.loads(state_file.read_text())["reason"] == "down"
    # no temp files left behind
    assert sorted(p.name for p in state_file.parent.iterdir()) == ["expected.json"]


def test_failed_replace_leaves_the_previous_file_intact(state_file, monkeypatch):
    expected_state.record_down(state_file)
    before = state_file.read_text()

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        expected_state.record_up(state_file)
    assert state_file.read_text() == before, "a failed write must not replace the file"
    leftovers = [p.name for p in state_file.parent.iterdir() if p.name != "expected.json"]
    assert leftovers == [], f"temp file left behind: {leftovers}"


def test_up_marks_core_running_and_optional_as_observed(state_file, monkeypatch):
    monkeypatch.setattr(
        expected_state, "_running_containers", lambda: {"cove-bifrost", "cove-forgejo"}
    )
    payload = expected_state.record_up(state_file)
    services = payload["services"]
    for core in expected_state.CORE_CONTAINERS:
        assert services[core]["expected"] == "running"
    assert services["cove-bifrost"]["expected"] == "running"
    assert services["cove-litellm"]["expected"] == "stopped"
    assert payload["converge_incomplete"] is False


def test_up_preserves_an_explicit_expectation_when_docker_is_unreachable(
    state_file, monkeypatch
):
    monkeypatch.setattr(expected_state, "_running_containers", lambda: {"cove-litellm"})
    expected_state.record_up(state_file)
    monkeypatch.setattr(expected_state, "_running_containers", lambda: None)
    payload = expected_state.record_up(state_file)
    assert payload["services"]["cove-litellm"]["expected"] == "running"


def test_down_marks_everything_stopped(state_file):
    payload = expected_state.record_down(state_file)
    assert all(entry["expected"] == "stopped" for entry in payload["services"].values())
    assert payload["reason"] == "down"


def test_service_up_touches_only_its_own_containers(state_file):
    expected_state.record_service("bifrost", "running", state_file)
    payload = expected_state.read_expected(state_file)
    assert payload["services"]["cove-bifrost"]["expected"] == "running"
    assert payload["services"]["cove-bifrost-dns"]["expected"] == "running"
    assert "cove-forgejo" not in payload["services"]


def test_service_down_marks_only_that_service(state_file):
    expected_state.record_service("bifrost", "running", state_file)
    payload = expected_state.record_service("bifrost", "stopped", state_file)
    assert payload["services"]["cove-bifrost"]["expected"] == "stopped"
    assert payload["services"]["cove-bifrost-dns"]["expected"] == "stopped"
    assert payload["reason"] == "service-stopped"


def test_unknown_service_is_rejected(state_file):
    with pytest.raises(KeyError):
        expected_state.record_service("nginx", "running", state_file)


def test_incomplete_converge_keeps_the_prior_map_and_sets_the_flag(state_file):
    expected_state.record_up(state_file)
    before = json.loads(state_file.read_text())["services"]
    payload = expected_state.record_incomplete("up", state_file)
    assert payload["converge_incomplete"] is True
    assert payload["services"] == before, "a partial converge must not invent expectations"
    assert json.loads(state_file.read_text()) == payload


def test_since_only_moves_when_the_expectation_changes(state_file, monkeypatch):
    monkeypatch.setattr(expected_state, "_running_containers", lambda: set())
    first = expected_state.record_up(state_file)["services"]["cove-forgejo"]["since"]
    second = expected_state.record_up(state_file)["services"]["cove-forgejo"]["since"]
    assert first == second
    third = expected_state.record_down(state_file)["services"]["cove-forgejo"]["since"]
    assert third != first


def test_compose_forgejo_healthcheck_probes_healthz():
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parent.parent.parent
    compose = yaml.safe_load((root / "compose" / "docker-compose.yml").read_text())
    healthcheck = compose["services"]["forgejo"]["healthcheck"]
    assert "/api/healthz" in " ".join(healthcheck["test"]), (
        "the healthcheck must hit /api/healthz; `/` answered 200 during the "
        "2026-11-06 wedge while the API was dead"
    )
