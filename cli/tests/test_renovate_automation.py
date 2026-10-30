"""Tests for the Renovate age-gate automation and its Renovate configuration.

Two contracts are pinned here:

1. The pure policy in ``scripts/renovate/age_gated_merge.py`` (marker parsing,
   update classification, age windows, path policy). The script is loaded by
   path because it is an operator automation, not part of the wheel.
2. The configuration invariants that keep the split honest: Renovate never
   automerges, the merge decision lives in the automation, and the workflow
   targets Forgejo over the in-network endpoint.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "renovate" / "age_gated_merge.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("age_gated_merge", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec: dataclasses resolves string annotations through
    # sys.modules, which is empty for a file loaded by path otherwise.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate():
    return _load_module()


NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def _marker(*upgrades: str) -> str:
    body = "Some Renovate prose.\n\n<!-- cove-age-gate:v1 "
    body += " ".join(upgrades)
    return body + "-->"


def test_parse_markers_reads_every_upgrade_in_a_group(gate):
    body = _marker(
        "datasource=docker package=postgres version=16.5 rel=2026-10-01T00:00:00.000Z type=patch vulnerability=false;",
        "datasource=docker package=nginx version=1.27.5 rel=2026-10-20T00:00:00.000Z type=patch vulnerability=false;",
    )
    ups = gate.parse_markers(body)
    assert [u.package for u in ups] == ["postgres", "nginx"]
    assert ups[1].released == datetime(2026, 10, 20, tzinfo=timezone.utc)


def test_parse_markers_accepts_an_empty_group(gate):
    assert gate.parse_markers(_marker()) == []


def test_parse_markers_rejects_an_unknown_marker_version(gate):
    with pytest.raises(gate.MarkerError):
        gate.parse_markers("<!-- cove-age-gate:v2 datasource=docker package=x version=1; -->")


def test_parse_markers_rejects_a_malformed_field(gate):
    with pytest.raises(gate.MarkerError):
        gate.parse_markers(_marker("datasource=docker package=x broken;"))


def test_strongest_update_type_wins_for_a_group(gate):
    assert gate.strongest(["patch", "minor"]).update_type == "minor"
    assert gate.strongest(["pinDigest", "patch"]).update_type == "patch"
    assert gate.strongest(["digest"]).update_type == "digest"


def test_strongest_update_type_rejects_unknown_types(gate):
    with pytest.raises(gate.MarkerError):
        gate.strongest(["rollback"])


def test_major_updates_have_no_age_window(gate):
    assert gate.required_age("major", vulnerability=False) is None


def test_known_age_windows(gate):
    assert gate.required_age("patch", vulnerability=False) == timedelta(days=7)
    assert gate.required_age("minor", vulnerability=False) == timedelta(days=14)
    assert gate.required_age("digest", vulnerability=False) == timedelta(days=7)
    assert gate.required_age("patch", vulnerability=True) == timedelta(hours=48)


def test_age_signal_uses_the_newest_release_in_a_group(gate):
    ups = gate.parse_markers(
        _marker(
            "datasource=docker package=a version=1 rel=2026-09-01T00:00:00.000Z type=patch vulnerability=false;",
            "datasource=docker package=b version=2 rel=2026-10-29T00:00:00.000Z type=patch vulnerability=false;",
        )
    )
    signal, source = gate.age_signal(ups, pr_created_at=NOW)
    assert signal == datetime(2026, 10, 29, tzinfo=timezone.utc)
    assert source == "upstream release timestamp"


def test_age_signal_falls_back_to_pr_age_without_timestamps(gate):
    ups = gate.parse_markers(
        _marker("datasource=docker package=a version=1 rel=None type=patch vulnerability=false;")
    )
    signal, source = gate.age_signal(ups, pr_created_at=NOW - timedelta(days=3))
    assert signal == NOW - timedelta(days=3)
    assert source == "pull request age"


def test_decision_merges_a_week_old_patch(gate):
    decision = gate.decide(
        body=_marker("datasource=pypi package=idna version=3.16 rel=2026-10-01T00:00:00.000Z type=patch vulnerability=false;"),
        label_names=[],
        files=["cli/uv.lock"],
        pr_created_at=NOW - timedelta(days=1),
        now=NOW,
    )
    assert decision.merge is True
    assert decision.reason == "eligible"


def test_decision_holds_a_fresh_patch(gate):
    decision = gate.decide(
        body=_marker("datasource=pypi package=idna version=3.16 rel=2026-10-28T00:00:00.000Z type=patch vulnerability=false;"),
        label_names=[],
        files=["cli/uv.lock"],
        pr_created_at=NOW - timedelta(days=1),
        now=NOW,
    )
    assert decision.merge is False
    assert "age" in decision.reason


def test_decision_never_merges_a_major(gate):
    decision = gate.decide(
        body=_marker("datasource=docker package=postgres version=18 rel=2026-01-01T00:00:00.000Z type=major vulnerability=false;"),
        label_names=["major"],
        files=["compose/docker-compose.yml"],
        pr_created_at=NOW - timedelta(days=90),
        now=NOW,
    )
    assert decision.merge is False
    assert decision.reason.startswith("major")


def test_decision_holds_a_compose_change_even_when_old(gate):
    decision = gate.decide(
        body=_marker("datasource=docker package=nginx version=1.31 rel=2026-01-01T00:00:00.000Z type=minor vulnerability=false;"),
        label_names=[],
        files=["compose/docker-compose.yml"],
        pr_created_at=NOW - timedelta(days=30),
        now=NOW,
    )
    assert decision.merge is False
    assert "staging" in decision.reason


def test_decision_takes_the_security_window_from_a_label(gate):
    decision = gate.decide(
        body=_marker("datasource=docker package=nginx version=1.31 rel=2026-10-29T00:00:00.000Z type=patch vulnerability=false;"),
        label_names=["security"],
        files=["compose/docker-compose.yml"],
        pr_created_at=NOW - timedelta(days=1),
        now=NOW,
    )
    # The label shortens the wait but does not bypass the compose hold.
    assert decision.merge is False
    assert decision.reason.startswith("compose")


def test_decision_merges_an_osv_update_after_48_hours(gate):
    decision = gate.decide(
        body=_marker("datasource=pypi package=idna version=3.16 rel=2026-10-27T00:00:00.000Z type=patch vulnerability=true;"),
        label_names=["dependencies"],
        files=["cli/uv.lock"],
        pr_created_at=NOW - timedelta(days=3),
        now=NOW,
    )
    assert decision.merge is True


def test_decision_holds_a_lockfile_maintenance_pr_until_it_is_a_week_old(gate):
    decision = gate.decide(
        body="No marker for lock file maintenance.",
        label_names=["dependencies"],
        files=["cli/uv.lock"],
        pr_created_at=NOW - timedelta(days=2),
        now=NOW,
        branch="renovate/lock-file-maintenance",
    )
    assert decision.merge is False
    assert "age" in decision.reason


def test_status_verdict_prefers_the_newest_transition(gate):
    statuses = [
        {"id": 3, "context": "no-pii / no-pii-gate (pull_request)", "status": "success"},
        {"id": 1, "context": "no-pii / no-pii-gate (pull_request)", "status": "pending"},
        {"id": 2, "context": "no-pii / no-pii-gate (pull_request)", "status": "pending"},
    ]
    assert gate.status_verdict(statuses) == (True, "no-pii-gate success")


def test_status_verdict_reports_a_failure_after_a_success(gate):
    statuses = [
        {"id": 1, "context": "no-pii / no-pii-gate (pull_request)", "status": "success"},
        {"id": 2, "context": "no-pii / no-pii-gate (pull_request)", "status": "failure"},
    ]
    ok, why = gate.status_verdict(statuses)
    assert ok is False
    assert "failure" in why


def test_status_verdict_requires_the_check_to_have_run(gate):
    ok, why = gate.status_verdict([{"id": 1, "context": "some-other-check", "status": "success"}])
    assert ok is False
    assert "has not run" in why


def test_renovate_config_never_automeres():
    config = json.loads((REPO_ROOT / "renovate.json").read_text())
    assert config["automerge"] is False
    assert config["platformAutomerge"] is False
    for rule in config.get("packageRules", []):
        assert rule.get("automerge") is not True


def test_renovate_config_pins_osv_and_digests():
    config = json.loads((REPO_ROOT / "renovate.json").read_text())
    assert config["osvVulnerabilityAlerts"] is True
    assert config["pinDigests"] is True
    assert config["vulnerabilityAlerts"]["addLabels"] == ["security"]


def test_renovate_config_uses_timestamp_optional_for_registries_without_times():
    config = json.loads((REPO_ROOT / "renovate.json").read_text())
    assert config["minimumReleaseAgeBehaviour"] == "timestamp-optional"


def test_renovate_config_covers_tunnel_and_group_vars():
    config = json.loads((REPO_ROOT / "renovate.json").read_text())
    compose_patterns = config["docker-compose"]["managerFilePatterns"]
    assert any("tunnel" in pattern for pattern in compose_patterns)
    managers = config["customManagers"]
    assert any("group_vars" in str(manager["managerFilePatterns"]) for manager in managers)


def test_renovate_workflow_targets_forgejo_and_stays_dry_by_default():
    workflow = yaml.safe_load((REPO_ROOT / ".forgejo" / "workflows" / "renovate.yml").read_text())
    job = workflow["jobs"]["renovate"]
    env = job["env"]
    assert env["RENOVATE_PLATFORM"] == "forgejo"
    assert env["RENOVATE_ENDPOINT"].endswith("/api/v1")
    assert env["RENOVATE_GIT_URL"] == "endpoint"
    assert env["COVE_RENOVATE_MODE"] == "dry-run"


def test_renovate_workflow_refuses_the_actions_token():
    text = (REPO_ROOT / ".forgejo" / "workflows" / "renovate.yml").read_text()
    assert "forgejo-actions" in text
