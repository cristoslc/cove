"""Tests for the Renovate threat evaluation layer.

The contract is deliberately fail-closed:

* a deterministic finding (OSV advisory for the target version, a yanked or
  deprecated release, a malicious-package advisory) blocks without asking a
  model;
* an unreachable source, a model error, an unparseable answer, or an exhausted
  token budget holds and says why;
* only ``proceed`` from the judge, with every deterministic source healthy, is
  eligible to merge;
* a human override needs a label *and* a reason, and is recorded.

The feeds and the model are injected so no test touches the network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts" / "renovate"
SCRIPT = SCRIPTS / "threat_eval.py"

sys.path.insert(0, str(SCRIPTS))


def _load_module():
    spec = importlib.util.spec_from_file_location("threat_eval", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def threat():
    return _load_module()


NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


def _pkg(threat, datasource="pypi", package="idna", version="3.16"):
    return threat.PackageRef(datasource=datasource, package=package, version=version)


class FakeFeeds:
    def __init__(self, error_cls, *, advisories=(), registry=(), issues=(), search=(), changelog=(), error=None):
        self.error_cls = error_cls
        self.advisories = list(advisories)
        self.registry = list(registry)
        self.repo_url = None
        self.issues = list(issues)
        self.changelog = list(changelog)
        self.search_hits = list(search)
        self.error = error
        self.calls: list[str] = []

    def advisories_for(self, pkg):
        self.calls.append("advisories")
        if self.error == "advisories":
            raise self.error_cls("OSV", "timed out")
        return list(self.advisories)

    def registry_for(self, pkg):
        self.calls.append("registry")
        if self.error == "registry":
            raise self.error_cls("PyPI", "503")
        return list(self.registry), self.repo_url

    def issues_for(self, pkg, repo_url):
        self.calls.append("issues")
        if self.error == "issues":
            raise self.error_cls("upstream issues", "403")
        return list(self.issues)

    def changelog_for(self, pkg, repo_url):
        self.calls.append("changelog")
        if self.error == "changelog":
            raise self.error_cls("GitHub releases", "503")
        return list(self.changelog)

    def search_for(self, pkg, queries):
        self.calls.append("search")
        if self.error == "search":
            raise self.error_cls("search", "provider unavailable")
        return list(self.search_hits)


def _request(threat):
    return threat.CheckRequest(
        packages=[_pkg(threat)],
        head_sha="abc",
        pr_number=7,
        pr_title="Update idna to 3.16",
    )


class FakeModel:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[tuple[str, int]] = []

    def complete(self, model, prompt, max_tokens):
        self.calls.append((model, max_tokens))
        if not self.answers:
            raise RuntimeError("model unavailable")
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer, {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}


def _decision(threat, verdict="proceed", confidence=0.9, findings=None, rationale="ok"):
    return json.dumps(
        {
            "verdict": verdict,
            "confidence": confidence,
            "findings": findings or [],
            "rationale": rationale,
        }
    )


def _queries(threat, *queries):
    return json.dumps({"queries": list(queries or ["idna supply chain attack"])})


# ---------------------------------------------------------------------------
# Configuration and the schema
# ---------------------------------------------------------------------------


def test_config_defaults_are_bounded_and_fail_closed(threat):
    config = threat.Config()
    assert config.enabled is True
    assert config.limits.per_check_tokens > 0
    assert config.limits.per_run_tokens >= config.limits.per_check_tokens
    assert config.limits.summarize_max_tokens > 0
    assert config.limits.judge_max_tokens > 0
    assert config.models.research
    assert config.models.judge


def test_config_rejects_zero_caps(threat, tmp_path):
    path = tmp_path / "threat.json"
    path.write_text(json.dumps({"limits": {"per_check_tokens": 0}}))
    with pytest.raises(threat.ConfigError):
        threat.Config.load(path)


def test_config_rejects_a_missing_file(threat, tmp_path):
    with pytest.raises(threat.ConfigError) as exc:
        threat.Config.load(tmp_path / "absent.json")
    assert "absent.json" in str(exc.value)


def test_verdict_marker_round_trips(threat):
    verdict = threat.Verdict(
        verdict="hold",
        confidence=0.55,
        evidence=[
            threat.Evidence(
                id="osv:GHSA-1",
                source="osv",
                url="https://osv.dev/vulnerability/GHSA-1",
                finding="target version is affected",
                relevance="direct",
            )
        ],
        model_used="vision:standard",
        cost_usd=0.0012,
        tokens=1234,
        rationale="One advisory covers the target.",
        errors=[],
        checked_at=NOW,
        head_sha="abc123",
        packages=["pypi/idna@3.16"],
    )
    marker = verdict.marker()
    assert marker.startswith("<!-- cove-threat-eval:v1 ")
    parsed = threat.parse_verdict_marker(marker)
    assert parsed is not None
    assert parsed.verdict == "hold"
    assert parsed.head_sha == "abc123"
    assert parsed.evidence[0].url == "https://osv.dev/vulnerability/GHSA-1"


def test_verdict_marker_rejects_an_unknown_version(threat):
    with pytest.raises(threat.MarkerError):
        threat.parse_verdict_marker("<!-- cove-threat-eval:v2 verdict=proceed head=x -->")


def test_marker_payload_never_contains_a_secret(threat):
    verdict = threat.Verdict(
        verdict="proceed",
        confidence=0.9,
        evidence=[],
        model_used="vision:standard",
        cost_usd=0.0,
        tokens=10,
        rationale="clean",
        errors=[],
        checked_at=NOW,
        head_sha="abc",
        packages=["pypi/idna@3.16"],
    )
    marker = verdict.marker()
    for forbidden in ("Authorization", "Bearer", "sk-", "client_key"):
        assert forbidden not in marker


# ---------------------------------------------------------------------------
# Version ranges and feed parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "version,spec,expected",
    [
        ("3.16", "< 3.15", False),
        ("3.14", "< 3.15", True),
        ("1.2.3", ">= 1.0.0, < 1.2.3", False),
        ("1.2.2", ">= 1.0.0, < 1.2.3", True),
        ("2.0.0", "<= 1.9.9", False),
        ("1.9.9", "<= 1.9.9", True),
        ("1.0.0", "= 1.0.0", True),
        ("1.0.1", "= 1.0.0", False),
        ("1.5.0", ">= 1.0.0 < 2.0.0 || >= 3.0.0", True),
    ],
)
def test_version_in_range(threat, version, spec, expected):
    assert threat.version_in_range(version, spec) is expected


def test_version_in_range_returns_none_when_it_cannot_tell(threat):
    assert threat.version_in_range("3.16", "a range with words") is None


def test_osv_result_blocks_the_target_version(threat):
    result = {
        "vulns": [
            {
                "id": "GHSA-mh6f-8j2x-4483",
                "summary": "Malicious package",
                "aliases": ["CVE-2018-1000001"],
                "database_specific": {"severity": "CRITICAL"},
            }
        ]
    }
    evidence = threat.osv_findings(result, _pkg(threat))
    assert evidence[0].source == "osv"
    assert evidence[0].relevance == "direct"
    assert "GHSA-mh6f-8j2x-4483" in evidence[0].url


def test_osv_empty_result_is_not_evidence(threat):
    assert threat.osv_findings({"vulns": []}, _pkg(threat)) == []


def test_github_advisory_outside_the_range_is_context(threat):
    advisories = [
        {
            "ghsa_id": "GHSA-65pc-fj4g-8rjx",
            "html_url": "https://github.com/advisories/GHSA-65pc-fj4g-8rjx",
            "summary": "IDNA denial of service",
            "vulnerabilities": [{"vulnerable_version_range": "< 3.15"}],
        }
    ]
    findings, unresolved = threat.github_advisory_findings(advisories, _pkg(threat))
    assert findings[0].relevance == "context"
    assert unresolved is False


def test_github_advisory_inside_the_range_forces_a_hold(threat):
    advisories = [
        {
            "ghsa_id": "GHSA-x",
            "html_url": "https://github.com/advisories/GHSA-x",
            "summary": "Bad release",
            "vulnerabilities": [{"vulnerable_version_range": "<= 3.16"}],
        }
    ]
    findings, unresolved = threat.github_advisory_findings(advisories, _pkg(threat))
    assert findings[0].relevance == "direct"
    assert unresolved is True


def test_an_unparseable_range_is_unresolved_and_holds(threat):
    advisories = [
        {
            "ghsa_id": "GHSA-y",
            "html_url": "https://github.com/advisories/GHSA-y",
            "summary": "Unknown range",
            "vulnerabilities": [{"vulnerable_version_range": "affected builds"}],
        }
    ]
    _findings, unresolved = threat.github_advisory_findings(advisories, _pkg(threat))
    assert unresolved is True


def test_registry_yanked_release_blocks(threat):
    payload = {"info": {"yanked": True, "yanked_reason": "broken"}, "urls": [{"yanked": True}]}
    findings, _repo = threat.registry_findings("pypi", payload, _pkg(threat))
    assert findings[0].relevance == "direct"
    assert "yanked" in findings[0].finding.lower()


def test_registry_deprecated_npm_version_blocks(threat):
    payload = {"deprecated": "do not use this version"}
    findings, _repo = threat.registry_findings(
        "npm", payload, _pkg(threat, datasource="npm", package="left-pad", version="1.0.0")
    )
    assert findings[0].relevance == "direct"
    assert "deprecated" in findings[0].finding.lower()


def test_clean_registry_payload_has_no_findings(threat):
    payload = {"info": {"yanked": False, "yanked_reason": None}, "urls": [{"yanked": False}]}
    findings, repo = threat.registry_findings("pypi", payload, _pkg(threat))
    assert findings == []
    assert repo is None


def test_repo_url_is_read_from_pypi_project_urls(threat):
    payload = {
        "info": {
            "project_urls": {
                "Source": "https://github.com/kjd/idna",
                "Issue tracker": "https://github.com/kjd/idna/issues",
            }
        }
    }
    assert threat.repo_url_from_metadata("pypi", payload) == "https://github.com/kjd/idna"


def test_repo_url_is_read_from_npm_repository(threat):
    payload = {"repository": {"url": "git+https://github.com/lodash/lodash.git"}}
    assert threat.repo_url_from_metadata("npm", payload) == "https://github.com/lodash/lodash"


def test_issue_findings_keep_the_version_in_the_finding(threat):
    items = [
        {
            "html_url": "https://github.com/kjd/idna/issues/99",
            "title": "3.16 regression in IDNA processing",
            "state": "open",
        }
    ]
    findings = threat.issue_findings(items, "https://github.com/kjd/idna", "3.16", "github")
    assert findings[0].source == "upstream-issues"
    assert "3.16" in findings[0].finding


# ---------------------------------------------------------------------------
# The evaluator: verdict classes and fail-closed paths
# ---------------------------------------------------------------------------


def _evaluator(threat, feeds, model, config=None, budget=None):
    config = config or threat.Config()
    return threat.Evaluator(
        config=config,
        feeds=feeds,
        model=model,
        budget=budget or threat.Budget(config.limits),
        now=lambda: NOW,
    )


def test_a_clean_check_proceeds(threat):
    feeds = FakeFeeds(threat.SourceError, )
    model = FakeModel(_queries(threat), _decision(threat, "proceed"), _decision(threat, "proceed"))
    verdict = _evaluator(threat, feeds, model).evaluate(_request(threat))
    assert verdict.verdict == "proceed"
    assert verdict.model_used == threat.Config().models.judge
    assert verdict.cost_usd > 0
    assert verdict.tokens > 0
    assert verdict.errors == []


def test_a_deterministic_advisory_blocks_even_when_the_model_says_proceed(threat):
    feeds = FakeFeeds(threat.SourceError, 
        advisories=[
            threat.Evidence(
                id="osv:GHSA-1",
                source="osv",
                url="https://osv.dev/vulnerability/GHSA-1",
                finding="target version is affected",
                relevance="direct",
            )
        ]
    )
    model = FakeModel(_queries(threat), _decision(threat, "proceed"), _decision(threat, "proceed"))
    verdict = _evaluator(threat, feeds, model).evaluate(_request(threat))
    assert verdict.verdict == "block"
    assert "deterministic" in verdict.rationale.lower()


def test_a_deterministic_block_survives_a_failing_corroborating_source(threat):
    feeds = FakeFeeds(
        threat.SourceError,
        advisories=[
            threat.Evidence(
                id="osv:GHSA-1",
                source="osv",
                url="https://osv.dev/vulnerability/GHSA-1",
                finding="target version is affected",
                relevance="direct",
            )
        ],
        error="registry",
    )
    model = FakeModel(_queries(threat), _decision(threat, "proceed"), _decision(threat, "proceed"))
    verdict = _evaluator(threat, feeds, model).evaluate(_request(threat))
    assert verdict.verdict == "block"
    assert any("pypi" in error.lower() for error in verdict.errors)


def test_an_unreachable_source_holds_without_calling_the_model(threat):
    feeds = FakeFeeds(threat.SourceError, error="advisories")
    model = FakeModel(_queries(threat), _decision(threat, "proceed"), _decision(threat, "proceed"))
    verdict = _evaluator(threat, feeds, model).evaluate(_request(threat))
    assert verdict.verdict == "hold"
    assert any("OSV" in error for error in verdict.errors)
    assert model.calls == []


def test_a_model_error_holds(threat):
    feeds = FakeFeeds(threat.SourceError, )
    model = FakeModel(_queries(threat), RuntimeError("timeout"), RuntimeError("timeout"))
    verdict = _evaluator(threat, feeds, model).evaluate(_request(threat))
    assert verdict.verdict == "hold"
    assert any("model" in error.lower() for error in verdict.errors)


def test_an_unparseable_model_answer_holds(threat):
    feeds = FakeFeeds(threat.SourceError, )
    model = FakeModel(_queries(threat), "not json at all", "not json at all")
    verdict = _evaluator(threat, feeds, model).evaluate(_request(threat))
    assert verdict.verdict == "hold"
    assert any("model" in error.lower() for error in verdict.errors)


def test_a_hallucinated_link_is_rejected(threat):
    feeds = FakeFeeds(threat.SourceError, )
    model = FakeModel(
        _queries(threat),
        _decision(
            threat,
            "proceed",
            findings=[
                {
                    "url": "https://example.invalid/made-up",
                    "finding": "invented",
                    "relevance": "direct",
                }
            ],
        ),
        _decision(threat, "proceed"),
    )
    verdict = _evaluator(threat, feeds, model).evaluate(_request(threat))
    assert verdict.verdict == "hold"
    assert any("model" in error.lower() for error in verdict.errors)


def test_a_model_hold_is_respected_when_the_floor_allows_it(threat):
    feeds = FakeFeeds(threat.SourceError, )
    model = FakeModel(
        _queries(threat),
        _decision(threat, "hold", 0.7, rationale="open regression report"),
        _decision(threat, "hold", 0.7, rationale="open regression report"),
    )
    verdict = _evaluator(threat, feeds, model).evaluate(_request(threat))
    assert verdict.verdict == "hold"
    assert "regression" in verdict.rationale


def test_an_empty_search_provider_holds_closed(threat):
    feeds = FakeFeeds(threat.SourceError, error="search")
    model = FakeModel(_queries(threat), _decision(threat, "proceed"), _decision(threat, "proceed"))
    verdict = _evaluator(threat, feeds, model).evaluate(_request(threat))
    assert verdict.verdict == "hold"
    assert any("search" in error.lower() for error in verdict.errors)


def test_the_per_check_token_budget_holds(threat):
    config = threat.Config(limits=threat.Limits(per_check_tokens=120, per_run_tokens=1000))
    feeds = FakeFeeds(threat.SourceError, )
    model = FakeModel(_queries(threat), _decision(threat, "proceed"), _decision(threat, "proceed"))
    verdict = _evaluator(threat, feeds, model, config=config).evaluate(_request(threat))
    assert verdict.verdict == "hold"
    assert any("budget" in error.lower() for error in verdict.errors)


def test_the_per_run_budget_is_shared_across_checks(threat):
    budget = threat.Budget(threat.Limits(per_check_tokens=10000, per_run_tokens=400))
    first = _evaluator(
        threat, FakeFeeds(threat.SourceError, ), FakeModel(_queries(threat), _decision(threat, "proceed")), budget=budget
    ).evaluate(_request(threat))
    second = _evaluator(
        threat, FakeFeeds(threat.SourceError, ), FakeModel(_queries(threat), _decision(threat, "proceed")), budget=budget
    ).evaluate(_request(threat))
    assert first.verdict == "proceed"
    assert second.verdict == "hold"
    assert any("budget" in error.lower() for error in second.errors)


def test_a_timeout_deadline_holds(threat):
    class SlowFeeds(FakeFeeds):
        def advisories_for(self, pkg):
            raise threat.SourceError("OSV", "timed out after 1s")

    verdict = _evaluator(threat, SlowFeeds(threat.SourceError), FakeModel()).evaluate(_request(threat))
    assert verdict.verdict == "hold"
    assert "OSV" in " ".join(verdict.errors)


def test_the_evidence_links_are_the_artifact(threat):
    feeds = FakeFeeds(threat.SourceError, 
        search=[
            threat.Evidence(
                id="search:1",
                source="search",
                url="https://example.org/report",
                finding="maintainer account takeover reported",
                relevance="indirect",
            )
        ]
    )
    model = FakeModel(_queries(threat), _decision(threat, "hold", 0.6, rationale="report"), _decision(threat, "hold"))
    verdict = _evaluator(threat, feeds, model).evaluate(_request(threat))
    comment = threat.render_comment(verdict)
    assert "https://example.org/report" in comment
    assert "hold" in comment.lower()


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


def _override_comments(*bodies):
    return [
        {"user": {"login": "operator"}, "body": body, "created_at": "2026-10-31T12:05:00Z"}
        for body in bodies
    ]


def test_override_needs_both_the_label_and_a_reason(threat):
    labels = ["threat-override"]
    assert threat.parse_override(_override_comments("cove-threat-override: reviewed the report"), labels)
    assert threat.parse_override(_override_comments("just a comment"), labels) is None
    assert threat.parse_override(_override_comments("cove-threat-override: reviewed"), []) is None


def test_override_rejects_a_too_short_reason(threat):
    assert threat.parse_override(_override_comments("cove-threat-override: ok"), ["threat-override"]) is None


def test_override_records_to_the_audit_log(threat, tmp_path, monkeypatch):
    log = tmp_path / "overrides.jsonl"
    monkeypatch.setenv("COVE_RENOVATE_AUDIT_LOG", str(log))
    api = FakeApi()
    verdict = threat.Verdict(
        verdict="hold",
        confidence=0.6,
        evidence=[],
        model_used="vision:standard",
        cost_usd=0.0,
        tokens=10,
        rationale="report",
        errors=[],
        checked_at=NOW,
        head_sha="abc",
        packages=["pypi/idna@3.16"],
    )
    override = threat.Override(
        login="operator",
        reason="the report is about a different release line",
        label="threat-override",
    )
    threat.record_override(api, "cristos/cove", 7, verdict, override, live=True)
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert rows[0]["login"] == "operator"
    assert rows[0]["verdict"] == "hold"
    assert rows[0]["head_sha"] == "abc"
    assert any(
        "cove-threat-override-ack:v1" in str(_body.get("body", ""))
        for _m, _p, _body in api.calls
    )


# ---------------------------------------------------------------------------
# Publishing to the pull request
# ---------------------------------------------------------------------------


class FakeApi:
    def __init__(self, labels=None, comments=None):
        self.calls: list[tuple[str, str, dict]] = []
        self.labels = list(labels or [])
        self.issue_labels = [
            {"id": i + 1, "name": name}
            for i, name in enumerate(self.labels)
            if name.startswith("threat:")
        ]
        self.comments = list(comments or [])

    def call(self, method, path, payload=None):
        self.calls.append((method, path, payload or {}))
        base = path.split("?")[0]
        if method == "GET" and "/issues/" in base and base.endswith("/labels"):
            return 200, list(self.issue_labels)
        if method == "GET" and base.endswith("/labels"):
            return 200, [{"id": i + 1, "name": name} for i, name in enumerate(self.labels)]
        if method == "POST" and base.endswith("/labels"):
            name = (payload or {}).get("name", "")
            self.labels.append(name)
            return 201, {"id": len(self.labels), "name": name}
        if method == "GET" and "/comments" in base:
            return 200, self.comments
        if method == "DELETE" and "/labels/" in base:
            self.issue_labels = [
                label for label in self.issue_labels if not base.endswith(str(label["id"]))
            ]
        return 200, {}


def _proceed_verdict(threat):
    return threat.Verdict(
        verdict="proceed",
        confidence=0.9,
        evidence=[],
        model_used="vision:standard",
        cost_usd=0.001,
        tokens=100,
        rationale="clean",
        errors=[],
        checked_at=NOW,
        head_sha="abc",
        packages=["pypi/idna@3.16"],
    )


def test_publish_adds_the_verdict_label_and_a_marker_comment(threat):
    api = FakeApi(labels=["dependencies", "security"])
    threat.publish_verdict(api, "cristos/cove", 7, _proceed_verdict(threat), live=True)
    posted = [p for m, p, body in api.calls if m == "POST" and "/comments" in p]
    assert posted
    comment = next(body["body"] for m, p, body in api.calls if m == "POST" and "/comments" in p)
    assert "cove-threat-eval:v1" in comment
    assert "threat:proceed" in api.labels
    assert any(
        m == "POST" and p.endswith("/issues/7/labels") and body.get("labels")
        for m, p, body in api.calls
    )


def test_publish_removes_the_other_threat_labels(threat):
    api = FakeApi(labels=["threat:hold", "dependencies"])
    threat.publish_verdict(api, "cristos/cove", 7, _proceed_verdict(threat), live=True)
    deleted = [p for m, p, _b in api.calls if m == "DELETE" and "/labels/" in p]
    assert any(p.endswith("/1") for p in deleted)


def test_publish_in_dry_run_changes_nothing(threat):
    api = FakeApi(labels=["threat:hold"])
    threat.publish_verdict(api, "cristos/cove", 7, _proceed_verdict(threat), live=False)
    assert api.calls == []


# ---------------------------------------------------------------------------
# Config and documentation invariants
# ---------------------------------------------------------------------------


def test_the_shipped_config_matches_the_schema(threat):
    config = threat.Config.load(SCRIPTS / "threat_eval.config.json")
    assert config.models.research != config.models.judge
    assert config.limits.per_check_tokens <= config.limits.per_run_tokens
    assert config.search_providers
    assert config.sources["osv"].startswith("https://")


def test_the_guide_states_the_limits_and_the_escape_hatch():
    text = (REPO_ROOT / "docs" / "guides" / "renovate-threat-eval.md").read_text()
    lowered = text.lower()
    assert "fail closed" in lowered
    assert "threat-override" in lowered
    assert "cannot see" in lowered or "cannot" in lowered
    assert "osv" in lowered
    assert "budget" in lowered


def test_an_unreachable_changelog_source_holds_without_calling_the_model(threat):
    """The changelog review is a gate, not a nice-to-have.

    If the release notes cannot be read, the update is unknown, and unknown
    holds: the operator's policy makes the changelog the security review.
    """
    feeds = FakeFeeds(threat.SourceError, error="changelog")
    feeds.repo_url = "https://github.com/psf/requests"
    model = FakeModel(_queries(threat), _decision(threat, "proceed"), _decision(threat, "proceed"))
    verdict = _evaluator(threat, feeds, model).evaluate(_request(threat))
    assert verdict.verdict == "hold"
    assert any("GitHub releases" in error for error in verdict.errors)
    assert model.calls == []
