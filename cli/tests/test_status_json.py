"""`cove status --json` contract.

The watchdog consumes this: one object per check, and a status code it can
trust. Before this, the command printed a table and always exited 0, so
nothing could act on it.
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from cove import status as status_module
from cove.cli import app


def _result(name: str, ok: bool, detail: str = "", optional: bool = False):
    return status_module.CheckResult(
        name=name, ok=ok, detail=detail, hints=["fix it"] if not ok else [], optional=optional
    )


def test_json_emits_one_object_per_check(monkeypatch):
    monkeypatch.setattr(
        status_module,
        "check_all",
        lambda: [_result("Forgejo", True, "running"), _result("Vault", True, "unsealed")],
    )
    outcome = CliRunner().invoke(app, ["status", "--json"])
    assert outcome.exit_code == 0, outcome.output
    payload = json.loads(outcome.output)
    assert payload == [
        {"name": "Forgejo", "ok": True, "detail": "running", "hints": [], "optional": False},
        {"name": "Vault", "ok": True, "detail": "unsealed", "hints": [], "optional": False},
    ]


def test_json_exits_non_zero_when_a_required_check_fails(monkeypatch):
    monkeypatch.setattr(
        status_module,
        "check_all",
        lambda: [_result("Forgejo", False, "healthz dead"), _result("Vault", True, "unsealed")],
    )
    outcome = CliRunner().invoke(app, ["status", "--json"])
    assert outcome.exit_code == 1
    payload = json.loads(outcome.output)
    failing = [item for item in payload if not item["ok"]]
    assert failing == [
        {
            "name": "Forgejo",
            "ok": False,
            "detail": "healthz dead",
            "hints": ["fix it"],
            "optional": False,
        }
    ]


def test_an_optional_service_down_does_not_fail_the_command(monkeypatch):
    """Optional services stay optional: `cove status` has always said so."""
    monkeypatch.setattr(
        status_module,
        "check_all",
        lambda: [_result("Bifrost", False, "not running", optional=True)],
    )
    outcome = CliRunner().invoke(app, ["status", "--json"])
    assert outcome.exit_code == 0
    assert json.loads(outcome.output)[0]["optional"] is True


def test_the_human_table_still_exits_non_zero_on_failure(monkeypatch):
    monkeypatch.setattr(
        status_module, "check_all", lambda: [_result("Forgejo", False, "healthz dead")]
    )
    outcome = CliRunner().invoke(app, ["status"])
    assert outcome.exit_code == 1
    assert "Forgejo" in outcome.output
