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


class TestLlmProxyEdgeCheck:
    """The row that replaced the retired LiteLLM row: the client endpoint.

    A 401 proves the vhost routes and the 0600 auth map rendered, without a
    credential; a 200 would mean the edge stopped enforcing client auth.
    """

    def _stub(self, monkeypatch, status_code):
        import types

        calls = []

        def fake_get(url, **kwargs):
            calls.append((url, kwargs))
            return types.SimpleNamespace(status_code=status_code, text="")

        monkeypatch.setattr(status_module.requests, "get", fake_get)
        return calls

    def test_401_is_healthy_and_names_the_host(self, monkeypatch):
        calls = self._stub(monkeypatch, 401)
        result = status_module._check_llmproxy()
        assert result.ok is True
        assert result.name == "LLM proxy edge"
        assert "auth enforced" in result.detail
        assert calls[0][1]["headers"]["Host"] == "llmproxy.cove.local"
        assert calls[0][0].endswith("/v1/models")

    def test_200_without_a_token_is_a_failure(self, monkeypatch):
        self._stub(monkeypatch, 200)
        result = status_module._check_llmproxy()
        assert result.ok is False
        assert "without a client token" in result.detail
        assert result.hints

    def test_other_statuses_report_the_code_not_connection_refused(self, monkeypatch):
        self._stub(monkeypatch, 502)
        result = status_module._check_llmproxy()
        assert result.ok is False
        assert "HTTP 502" in result.detail

    def test_connection_refused_is_unreachable(self, monkeypatch):
        import requests as requests_module

        def fake_get(url, **kwargs):
            raise requests_module.exceptions.ConnectionError()

        monkeypatch.setattr(status_module.requests, "get", fake_get)
        result = status_module._check_llmproxy()
        assert result.ok is False
        assert result.detail == "Connection refused"
