#!/usr/bin/env python3
"""Evidence-backed threat evaluation for Renovate pull requests.

The age gate answers "has this release been out long enough". It cannot answer
"is this release safe". This module gathers the evidence that can be checked
without trusting the wait, asks a cheap model to research the open-web gap, and
asks a decision model for a verdict. The merge gate consumes the verdict.

The rules that matter:

* **Deterministic evidence wins.** An OSV advisory that matches the exact target
  version, a malicious-package advisory, or a yanked/deprecated release blocks
  without asking a model.
* **Fail closed.** A missing configuration, an unreachable required source, a
  model error, an unparseable answer, or an exhausted token budget produces
  ``hold``. Only ``proceed`` with healthy sources is mergeable.
* **The evidence links are the artifact.** Every verdict carries the URLs it
  read so a human can audit it in seconds. Model output that cites a URL the
  tool did not supply is rejected.
* **The override is explicit and recorded.** The ``threat-override`` label plus
  a ``cove-threat-override: <reason>`` comment lets a human proceed; the tool
  posts an acknowledgement and appends a JSONL audit row.

Model calls go through the Cove LLM proxy (``llmproxy.cove``) with the shared
edge client token. No provider credential is ever read or printed here.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

MARKER_VERSION = "cove-threat-eval:v1"
MARKER_RE = re.compile(r"<!--\s*cove-threat-eval:(\S+)\s+(.*?)\s*-->", re.S)
VERDICTS = ("proceed", "hold", "block")
VERDICT_RANK = {"proceed": 0, "hold": 1, "block": 2}
OVERRIDE_LABEL = "threat-override"
OVERRIDE_PREFIX = "cove-threat-override:"
VERDICT_LABELS = {
    "proceed": "threat:proceed",
    "hold": "threat:hold",
    "block": "threat:block",
}
LABEL_COLORS = {"proceed": "0e8a16", "hold": "fbca04", "block": "b60205"}
DEFAULT_AUDIT_LOG = "~/.local/state/cove/renovate-threat-overrides.jsonl"
MIN_OVERRIDE_REASON = 10


class ThreatError(RuntimeError):
    """Base class for this module's failures."""


class ConfigError(ThreatError):
    """The configuration is missing or unusable."""


class SourceError(ThreatError):
    """An evidence source could not be read. The verdict is hold."""

    def __init__(self, source: str, detail: str) -> None:
        self.source = source
        self.detail = detail
        super().__init__(f"{source}: {detail}")


class ModelError(ThreatError):
    """The research or decision model failed or answered outside the schema."""


class BudgetError(ThreatError):
    """The configured token budget is exhausted. The verdict is hold."""


class MarkerError(ThreatError):
    """A verdict marker cannot be read safely."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Limits:
    per_check_tokens: int = 12000
    per_run_tokens: int = 60000
    summarize_max_tokens: int = 1800
    judge_max_tokens: int = 1600
    http_timeout_s: float = 20.0
    check_deadline_s: float = 120.0
    search_results: int = 5
    search_window_days: int = 90
    reuse_minutes_proceed: int = 1440
    reuse_minutes_hold: int = 60
    reuse_minutes_block: int = 1440


@dataclass(frozen=True)
class Models:
    research: str = "text:light"
    judge: str = "vision:standard"


@dataclass(frozen=True)
class Price:
    input: float = 0.0
    output: float = 0.0


@dataclass(frozen=True)
class Prices:
    research: Price = Price(input=0.10, output=0.30)
    judge: Price = Price(input=0.30, output=1.20)


DEFAULT_SOURCES = {
    "proxy": "https://llmproxy.cove/v1",
    "osv": "https://api.osv.dev/v1/query",
    "github_advisories": "https://api.github.com/advisories",
    "github_issues": "https://api.github.com/search/issues",
    "github_releases": "https://api.github.com/repos",
    "nvd": "https://services.nvd.nist.gov/rest/json/cves/2.0",
    "pypi": "https://pypi.org/pypi",
    "npm": "https://registry.npmjs.org",
    "codeberg": "https://codeberg.org/api/v1",
    "hn_algolia": "https://hn.algolia.com/api/v1/search_by_date",
    "brave": "https://api.search.brave.com/res/v1/web/search",
}


@dataclass(frozen=True)
class Config:
    enabled: bool = True
    proxy_url: str = DEFAULT_SOURCES["proxy"]
    token_env: str = "COVE_LLM_PROXY_CLIENT_KEY"
    token_op_ref: str = "op://Private/Cove LLM Proxy Client Key/client_key"
    models: Models = field(default_factory=Models)
    limits: Limits = field(default_factory=Limits)
    prices: Prices = field(default_factory=Prices)
    search_providers: tuple[str, ...] = ("github_issues", "hn_algolia")
    sources: dict = field(default_factory=lambda: dict(DEFAULT_SOURCES))
    github_token_env: str = "GITHUB_TOKEN"
    brave_key_env: str = "COVE_THREAT_SEARCH_KEY"

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        if path is None:
            path = os.environ.get("COVE_THREAT_EVAL_CONFIG") or Path(__file__).with_name(
                "threat_eval.config.json"
            )
        path = Path(path)
        if not path.exists():
            raise ConfigError(
                f"threat evaluation config not found at {path}; the gate refuses to "
                "merge without one (fail closed). Copy the shipped file or set "
                "COVE_THREAT_EVAL_CONFIG."
            )
        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
        if raw.get("version") != 1:
            raise ConfigError(f"{path} has unsupported version {raw.get('version')!r}")
        limits_raw = dict(raw.get("limits") or {})
        limits = Limits(**{k: v for k, v in limits_raw.items() if hasattr(Limits, k)})
        models_raw = dict(raw.get("models") or {})
        models = Models(**{k: v for k, v in models_raw.items() if hasattr(Models, k)})
        prices_raw = dict(raw.get("prices_usd_per_mtok") or {})
        prices = Prices(
            research=Price(**dict(prices_raw.get("research") or {})),
            judge=Price(**dict(prices_raw.get("judge") or {})),
        )
        sources = dict(DEFAULT_SOURCES)
        sources.update(dict(raw.get("sources") or {}))
        missing = set(DEFAULT_SOURCES) - sources.keys()
        if missing:
            raise ConfigError(f"{path} is missing sources: {sorted(missing)}")
        config = cls(
            enabled=bool(raw.get("enabled", True)),
            proxy_url=str(raw.get("proxy_url") or DEFAULT_SOURCES["proxy"]),
            token_env=str(raw.get("token_env") or "COVE_LLM_PROXY_CLIENT_KEY"),
            token_op_ref=str(
                raw.get("token_op_ref") or "op://Private/Cove LLM Proxy Client Key/client_key"
            ),
            models=models,
            limits=limits,
            prices=prices,
            search_providers=tuple(raw.get("search_providers") or ()),
            sources=sources,
            github_token_env=str(raw.get("github_token_env") or "GITHUB_TOKEN"),
            brave_key_env=str(raw.get("brave_key_env") or "COVE_THREAT_SEARCH_KEY"),
        )
        _validate(config, path)
        return config


def _validate(config: Config, path: Path) -> None:
    limits = config.limits
    for name in ("per_check_tokens", "per_run_tokens", "summarize_max_tokens", "judge_max_tokens"):
        if int(getattr(limits, name)) <= 0:
            raise ConfigError(f"{path}: limits.{name} must be greater than zero")
    if limits.per_run_tokens < limits.per_check_tokens:
        raise ConfigError(f"{path}: limits.per_run_tokens must be >= limits.per_check_tokens")
    if limits.http_timeout_s <= 0 or limits.check_deadline_s <= 0:
        raise ConfigError(f"{path}: timeouts must be greater than zero")
    if not config.models.research or not config.models.judge:
        raise ConfigError(f"{path}: models.research and models.judge must be set")
    if not config.proxy_url.startswith(("https://", "http://")):
        raise ConfigError(f"{path}: proxy_url must be an HTTP(S) URL")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PackageRef:
    datasource: str
    package: str
    version: str
    ecosystem: str | None = None

    def label(self) -> str:
        return f"{self.datasource}/{self.package}@{self.version}"


@dataclass(frozen=True)
class Evidence:
    id: str
    source: str
    url: str
    finding: str
    relevance: str = "context"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "url": self.url,
            "finding": self.finding,
            "relevance": self.relevance,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Evidence":
        return cls(
            id=str(data["id"]),
            source=str(data["source"]),
            url=str(data["url"]),
            finding=str(data["finding"]),
            relevance=str(data.get("relevance") or "context"),
        )


@dataclass
class Verdict:
    verdict: str
    confidence: float
    evidence: list[Evidence]
    model_used: str
    cost_usd: float
    tokens: int
    rationale: str
    errors: list[str]
    checked_at: datetime
    head_sha: str = ""
    packages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "confidence": round(self.confidence, 3),
            "evidence": [item.to_dict() for item in self.evidence],
            "model_used": self.model_used,
            "cost": {"usd": round(self.cost_usd, 6), "tokens": self.tokens},
            "rationale": self.rationale,
            "errors": list(self.errors),
            "checked_at": self.checked_at.astimezone(timezone.utc).isoformat(),
            "head_sha": self.head_sha,
            "packages": list(self.packages),
        }

    def marker(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        encoded = base64.b64encode(payload.encode()).decode()
        return f"<!-- {MARKER_VERSION} {encoded} -->"


def parse_verdict_marker(text: str) -> Verdict | None:
    if not text:
        return None
    matches = MARKER_RE.findall(text)
    if not matches:
        return None
    version, encoded = matches[-1]
    if f"cove-threat-eval:{version}" != MARKER_VERSION:
        raise MarkerError(f"unsupported threat marker version {version!r}")
    try:
        data = json.loads(base64.b64decode(encoded).decode())
    except (ValueError, json.JSONDecodeError) as exc:
        raise MarkerError(f"unreadable threat marker payload: {exc}") from exc
    if data.get("verdict") not in VERDICTS:
        raise MarkerError(f"unknown verdict {data.get('verdict')!r} in threat marker")
    try:
        checked_at = datetime.fromisoformat(str(data["checked_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError) as exc:
        raise MarkerError(f"unreadable checked_at in threat marker: {exc}") from exc
    cost = data.get("cost") or {}
    return Verdict(
        verdict=str(data["verdict"]),
        confidence=float(data.get("confidence") or 0.0),
        evidence=[Evidence.from_dict(item) for item in data.get("evidence") or []],
        model_used=str(data.get("model_used") or ""),
        cost_usd=float(cost.get("usd") or 0.0),
        tokens=int(cost.get("tokens") or 0),
        rationale=str(data.get("rationale") or ""),
        errors=[str(item) for item in data.get("errors") or []],
        checked_at=checked_at,
        head_sha=str(data.get("head_sha") or ""),
        packages=[str(item) for item in data.get("packages") or []],
    )


@dataclass
class CheckRequest:
    packages: list[PackageRef]
    head_sha: str
    pr_number: int = 0
    pr_title: str = ""


# ---------------------------------------------------------------------------
# Deterministic evidence
# ---------------------------------------------------------------------------

OSV_ECOSYSTEMS = {
    "pypi": "PyPI",
    "npm": "npm",
    "cargo": "crates.io",
    "go": "Go",
    "maven": "Maven",
    "nuget": "NuGet",
    "packagist": "Packagist",
    "rubygems": "RubyGems",
    "github-actions": "GitHub Actions",
    "hex": "Hex",
    "pub": "Pub",
    "swift": "SwiftURL",
}

GITHUB_ADVISORY_ECOSYSTEMS = {
    "PyPI": "pip",
    "npm": "npm",
    "crates.io": "rust",
    "Go": "go",
    "Maven": "maven",
    "NuGet": "nuget",
    "Packagist": "composer",
    "RubyGems": "rubygems",
    "GitHub Actions": "actions",
    "Hex": "erlang",
    "Pub": "pub",
    "SwiftURL": "swift",
}


def ecosystem_for(datasource: str) -> str | None:
    return OSV_ECOSYSTEMS.get(datasource)


def _version_tuple(text: str) -> tuple[int, ...] | None:
    cleaned = text.strip().lstrip("vV")
    match = re.match(r"^(\d+(?:\.\d+)*)", cleaned)
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def _compare(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    width = max(len(left), len(right))
    a = left + (0,) * (width - len(left))
    b = right + (0,) * (width - len(right))
    return (a > b) - (a < b)


def version_in_range(version: str, spec: str) -> bool | None:
    """True/False for a common semver range, None when it cannot be parsed.

    GitHub advisories use ranges such as ``< 3.15`` or
    ``>= 1.0.0, < 1.2.3``. An unparseable range is *unresolved*, which the
    caller turns into a hold; it is never silently treated as "not affected".
    """
    current = _version_tuple(version)
    if current is None or not spec or not spec.strip():
        return None
    for segment in spec.split("||"):
        segment = re.sub(r"(<=|>=|<|>|=)\s+", r"\1", segment.strip())
        if not segment:
            continue
        tokens = [token for token in re.split(r"[,\s]+", segment) if token]
        if not tokens:
            continue
        matched = True
        for token in tokens:
            match = re.match(r"^(<=|>=|<|>|=)?\s*(.+)$", token)
            if not match:
                return None
            operator = match.group(1) or "="
            bound = _version_tuple(match.group(2))
            if bound is None:
                return None
            comparison = _compare(current, bound)
            if operator == "<" and not comparison < 0:
                matched = False
            elif operator == "<=" and not comparison <= 0:
                matched = False
            elif operator == ">" and not comparison > 0:
                matched = False
            elif operator == ">=" and not comparison >= 0:
                matched = False
            elif operator == "=" and comparison != 0:
                matched = False
        if matched:
            return True
    return False


def osv_findings(result: dict, pkg: PackageRef) -> list[Evidence]:
    findings: list[Evidence] = []
    for vuln in result.get("vulns") or []:
        vuln_id = str(vuln.get("id") or "")
        if not vuln_id:
            continue
        aliases = [str(item) for item in vuln.get("aliases") or []]
        summary = str(vuln.get("summary") or "advisory")
        severity = str((vuln.get("database_specific") or {}).get("severity") or "")
        detail = f"{vuln_id} affects {pkg.package} {pkg.version}: {summary[:160]}"
        if severity:
            detail = f"{detail} ({severity})"
        if aliases:
            detail = f"{detail}; aliases {', '.join(aliases[:3])}"
        findings.append(
            Evidence(
                id=f"osv:{vuln_id}",
                source="osv",
                url=f"https://osv.dev/vulnerability/{vuln_id}",
                finding=detail,
                relevance="direct",
            )
        )
    return findings


def github_advisory_findings(
    advisories: list[dict], pkg: PackageRef
) -> tuple[list[Evidence], bool]:
    findings: list[Evidence] = []
    forces_hold = False
    for advisory in advisories:
        ghsa = str(advisory.get("ghsa_id") or "")
        if not ghsa:
            continue
        url = str(advisory.get("html_url") or f"https://github.com/advisories/{ghsa}")
        summary = str(advisory.get("summary") or "advisory")
        direct = False
        unresolved = False
        for vuln in advisory.get("vulnerabilities") or []:
            spec = str(vuln.get("vulnerable_version_range") or "")
            inside = version_in_range(pkg.version, spec)
            if inside is True:
                direct = True
            elif inside is None:
                unresolved = True
        if direct:
            forces_hold = True
            relevance = "direct"
            finding = f"{ghsa} lists a range that covers {pkg.version}: {summary[:160]}"
        elif unresolved:
            forces_hold = True
            relevance = "context"
            finding = (
                f"{ghsa} has a version range the tool could not parse for "
                f"{pkg.package} {pkg.version}: {summary[:140]} (unresolved)"
            )
        else:
            relevance = "context"
            finding = f"{ghsa} does not cover {pkg.version}: {summary[:160]}"
        identifier = f"github-advisories:{ghsa}" + (":unresolved" if unresolved else "")
        findings.append(
            Evidence(
                id=identifier,
                source="github-advisories",
                url=url,
                finding=finding,
                relevance=relevance,
            )
        )
    return findings, forces_hold


def _first_github_url(values) -> str | None:
    for value in values:
        if not isinstance(value, str):
            continue
        match = re.search(r"https?://github\.com/([^/\s]+)/([^/\s#?]+)", value)
        if match:
            return f"https://github.com/{match.group(1)}/{match.group(2).removesuffix('.git')}"
    return None


def repo_url_from_metadata(datasource: str, payload: dict) -> str | None:
    if datasource == "pypi":
        info = payload.get("info") or {}
        urls = info.get("project_urls") or {}
        ordered = [
            urls.get("Source"),
            urls.get("Repository"),
            urls.get("Issue tracker"),
            urls.get("Homepage"),
            *urls.values(),
            info.get("home_page"),
        ]
        return _first_github_url(ordered)
    if datasource == "npm":
        repository = payload.get("repository")
        if isinstance(repository, dict):
            return _first_github_url([repository.get("url")])
        return _first_github_url([repository])
    if datasource == "github-actions":
        return f"https://github.com/{payload.get('full_name', '')}".rstrip("/")
    return None


def registry_findings(
    datasource: str, payload: dict, pkg: PackageRef
) -> tuple[list[Evidence], str | None]:
    findings: list[Evidence] = []
    if datasource == "pypi":
        info = payload.get("info") or {}
        yanked = bool(info.get("yanked")) or any(
            item.get("yanked") for item in payload.get("urls") or []
        )
        if yanked:
            reason = str(info.get("yanked_reason") or "no reason published")
            findings.append(
                Evidence(
                    id=f"registry:yanked:{pkg.package}@{pkg.version}",
                    source="registry",
                    url=f"https://pypi.org/project/{pkg.package}/{pkg.version}/",
                    finding=f"the PyPI release is yanked ({reason})",
                    relevance="direct",
                )
            )
    elif datasource == "npm":
        deprecated = payload.get("deprecated")
        if deprecated:
            findings.append(
                Evidence(
                    id=f"registry:deprecated:{pkg.package}@{pkg.version}",
                    source="registry",
                    url=f"https://www.npmjs.com/package/{pkg.package}/v/{pkg.version}",
                    finding=f"the npm version is deprecated: {str(deprecated)[:160]}",
                    relevance="direct",
                )
            )
    return findings, repo_url_from_metadata(datasource, payload)


def issue_findings(
    items: list[dict], repo_url: str, version: str, host: str
) -> list[Evidence]:
    findings: list[Evidence] = []
    for item in items:
        title = str(item.get("title") or "")
        body = str(item.get("body") or "")
        if version not in f"{title}\n{body}":
            continue
        url = str(item.get("html_url") or item.get("url") or "")
        if not url:
            continue
        findings.append(
            Evidence(
                id=f"upstream-issues:{host}:{item.get('number', len(findings))}",
                source="upstream-issues",
                url=url,
                finding=f"open upstream issue mentions {version}: {title[:160]}",
                relevance="indirect",
            )
        )
    return findings


def deterministic_floor(evidence: list[Evidence], errors: list[str]) -> str:
    # A deterministic block is stronger than a hold, so it survives a failing
    # corroborating source. A source failure can never turn a block into a
    # weaker outcome.
    for item in evidence:
        if item.source == "osv" and item.relevance == "direct":
            return "block"
        if item.source == "registry" and item.relevance == "direct":
            return "block"
    if errors:
        return "hold"
    floor = "proceed"
    for item in evidence:
        if item.id.endswith(":unresolved"):
            floor = "hold"
        elif item.source == "github-advisories" and item.relevance == "direct":
            floor = "hold"
    return floor


# ---------------------------------------------------------------------------
# HTTP and feeds
# ---------------------------------------------------------------------------


class UrllibHttp:
    """A tiny JSON client that raises SourceError instead of guessing."""

    def json(
        self,
        method: str,
        url: str,
        *,
        payload: dict | None = None,
        headers: dict | None = None,
        timeout: float = 20.0,
        source: str = "source",
    ) -> object:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", "cove-threat-eval/1")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:300].decode(errors="replace")
            raise SourceError(source, f"HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SourceError(source, str(getattr(exc, "reason", exc))) from exc
        try:
            return json.loads(raw.decode() or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceError(source, f"non-JSON response: {exc}") from exc


class Feeds:
    """The deterministic sources, keyed by URL in the configuration."""

    def __init__(self, config: Config, http: UrllibHttp | None = None) -> None:
        self.config = config
        self.http = http or UrllibHttp()
        self._timeout = config.limits.http_timeout_s

    def _github_headers(self) -> dict:
        token = os.environ.get(self.config.github_token_env, "").strip()
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def advisories_for(self, pkg: PackageRef) -> list[Evidence]:
        findings: list[Evidence] = []
        ecosystem = pkg.ecosystem or ecosystem_for(pkg.datasource)
        if ecosystem is None:
            findings.append(
                Evidence(
                    id=f"coverage:no-osv:{pkg.datasource}",
                    source="coverage",
                    url="https://osv.dev/",
                    finding=(
                        f"OSV has no ecosystem mapping for datasource "
                        f"{pkg.datasource}; no structured advisory check ran for "
                        f"{pkg.package} {pkg.version}"
                    ),
                    relevance="context",
                )
            )
            return findings
        result = self.http.json(
            "POST",
            self.config.sources["osv"],
            payload={
                "package": {"name": pkg.package, "ecosystem": ecosystem},
                "version": pkg.version,
            },
            timeout=self._timeout,
            source="OSV",
        )
        if not isinstance(result, dict):
            raise SourceError("OSV", "unexpected payload")
        osv = osv_findings(result, pkg)
        findings.extend(osv)
        if any(item.relevance == "direct" for item in osv):
            # A deterministic block already exists; skip corroboration cost.
            return findings

        advisory_ecosystem = GITHUB_ADVISORY_ECOSYSTEMS.get(ecosystem)
        if advisory_ecosystem:
            query = urllib.parse.urlencode(
                {"ecosystem": advisory_ecosystem, "affects": pkg.package, "per_page": 20}
            )
            advisories = self.http.json(
                "GET",
                f"{self.config.sources['github_advisories']}?{query}",
                headers=self._github_headers(),
                timeout=self._timeout,
                source="GitHub advisories",
            )
            if not isinstance(advisories, list):
                raise SourceError("GitHub advisories", "unexpected payload")
            gh_findings, _force = github_advisory_findings(advisories, pkg)
            findings.extend(gh_findings)
            if _force:
                return findings

        cve_ids = sorted(
            {
                alias
                for vuln in result.get("vulns") or []
                for alias in vuln.get("aliases") or []
                if str(alias).startswith("CVE-")
            }
        )[:3]
        for cve in cve_ids:
            payload = self.http.json(
                "GET",
                f"{self.config.sources['nvd']}?cveId={urllib.parse.quote(cve)}",
                timeout=self._timeout,
                source="NVD",
            )
            vulns = (payload or {}).get("vulnerabilities") if isinstance(payload, dict) else []
            if vulns:
                description = (
                    vulns[0].get("cve", {}).get("descriptions", [{}])[0].get("value", "")
                )
                findings.append(
                    Evidence(
                        id=f"nvd:{cve}",
                        source="nvd",
                        url=f"https://nvd.nist.gov/vuln/detail/{cve}",
                        finding=f"{cve}: {str(description)[:180]}",
                        relevance="context",
                    )
                )
        return findings

    def registry_for(self, pkg: PackageRef) -> tuple[list[Evidence], str | None]:
        if pkg.datasource == "pypi":
            url = f"{self.config.sources['pypi']}/{pkg.package}/{pkg.version}/json"
        elif pkg.datasource == "npm":
            url = f"{self.config.sources['npm']}/{pkg.package}/{pkg.version}"
        elif pkg.datasource == "github-actions":
            payload = self.http.json(
                "GET",
                f"https://api.github.com/repos/{pkg.package}",
                headers=self._github_headers(),
                timeout=self._timeout,
                source="GitHub repository",
            )
            return [], repo_url_from_metadata("github-actions", payload if isinstance(payload, dict) else {})
        else:
            return (
                [
                    Evidence(
                        id=f"coverage:no-registry:{pkg.datasource}",
                        source="coverage",
                        url="",
                        finding=(
                            f"no registry metadata feed is wired for datasource "
                            f"{pkg.datasource}; yanked/deprecated state was not checked"
                        ),
                        relevance="context",
                    )
                ],
                None,
            )
        payload = self.http.json(
            "GET",
            url,
            timeout=self._timeout,
            source=f"{pkg.datasource} registry",
        )
        if not isinstance(payload, dict):
            raise SourceError(f"{pkg.datasource} registry", "unexpected payload")
        return registry_findings(pkg.datasource, payload, pkg)

    def changelog_for(self, pkg: PackageRef, repo_url: str) -> list[Evidence]:
        """Release notes for the target version, as judged evidence.

        The update policy gates on the changelog being read for security-relevant
        changes, so the notes go to the judge as an evidence row. A version with
        no published notes is recorded as a coverage gap instead of being
        silently skipped: "nobody read the changelog" must stay visible.
        """
        if not repo_url or not repo_url.startswith("https://github.com/"):
            return []
        owner_repo = repo_url.removeprefix("https://github.com/").strip("/")
        payload = self.http.json(
            "GET",
            f"{self.config.sources['github_releases']}/{owner_repo}/releases?per_page=30",
            headers=self._github_headers(),
            timeout=self._timeout,
            source="GitHub releases",
        )
        if not isinstance(payload, list):
            raise SourceError("GitHub releases", "unexpected payload")
        target = pkg.version.lstrip("v")
        for release in payload:
            tag = str(release.get("tag_name") or "").lstrip("v")
            if tag != target:
                continue
            notes = (release.get("body") or "").strip()
            url = release.get("html_url") or repo_url
            if not notes:
                return [
                    Evidence(
                        id=f"changelog:{owner_repo}@{target}",
                        source="coverage",
                        url=url,
                        finding="release published with empty notes; read the changelog by hand",
                        relevance="gap",
                    )
                ]
            return [
                Evidence(
                    id=f"changelog:{owner_repo}@{target}",
                    source="changelog",
                    url=url,
                    finding=notes[:1200],
                    relevance="context",
                )
            ]
        return [
            Evidence(
                id=f"changelog:{owner_repo}@{target}",
                source="coverage",
                url=repo_url,
                finding="no release notes published for the target version; read the changelog by hand",
                relevance="gap",
            )
        ]

    def issues_for(self, pkg: PackageRef, repo_url: str) -> list[Evidence]:
        if not repo_url:
            return []
        if repo_url.startswith("https://github.com/"):
            owner_repo = repo_url.removeprefix("https://github.com/").strip("/")
            query = urllib.parse.urlencode(
                {
                    "q": f"repo:{owner_repo} is:issue is:open {pkg.version} (regression OR bug OR broken)",
                    "per_page": 10,
                    "sort": "created",
                    "order": "desc",
                }
            )
            payload = self.http.json(
                "GET",
                f"{self.config.sources['github_issues']}?{query}",
                headers=self._github_headers(),
                timeout=self._timeout,
                source="GitHub issues",
            )
            items = (payload or {}).get("items") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                raise SourceError("GitHub issues", "unexpected payload")
            return issue_findings(items, repo_url, pkg.version, "github")
        if repo_url.startswith("https://codeberg.org/"):
            owner_repo = repo_url.removeprefix("https://codeberg.org/").strip("/")
            payload = self.http.json(
                "GET",
                f"{self.config.sources['codeberg']}/repos/{owner_repo}/issues?state=open&limit=20&type=issues",
                timeout=self._timeout,
                source="Codeberg issues",
            )
            if not isinstance(payload, list):
                raise SourceError("Codeberg issues", "unexpected payload")
            return issue_findings(payload, repo_url, pkg.version, "codeberg")
        return []

    def search_for(self, pkg: PackageRef, queries: list[str]) -> list[Evidence]:
        if not self.config.search_providers:
            raise SourceError(
                "search",
                "no search provider is configured; set search_providers in the threat "
                "evaluation config (github_issues, hn_algolia, or brave)",
            )
        findings: list[Evidence] = []
        seen: set[str] = set()
        since = datetime.now(timezone.utc) - timedelta(days=self.config.limits.search_window_days)
        for provider in self.config.search_providers:
            if provider == "github_issues":
                findings.extend(self._github_issue_search(pkg, queries, since, seen))
            elif provider == "hn_algolia":
                findings.extend(self._hn_search(pkg, queries, since, seen))
            elif provider == "brave":
                findings.extend(self._brave_search(pkg, queries, seen))
            else:
                raise SourceError("search", f"unknown search provider {provider!r}")
        return findings

    def _github_issue_search(self, pkg, queries, since, seen) -> list[Evidence]:
        findings: list[Evidence] = []
        for query in queries[:3]:
            q = f'"{pkg.package}" ({query}) created:>={since.date().isoformat()}'
            payload = self.http.json(
                "GET",
                f"{self.config.sources['github_issues']}?"
                + urllib.parse.urlencode(
                    {"q": q, "per_page": self.config.limits.search_results, "sort": "created", "order": "desc"}
                ),
                headers=self._github_headers(),
                timeout=self._timeout,
                source="GitHub issue search",
            )
            items = (payload or {}).get("items") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                raise SourceError("GitHub issue search", "unexpected payload")
            for item in items:
                url = str(item.get("html_url") or "")
                if not url or url in seen:
                    continue
                seen.add(url)
                findings.append(
                    Evidence(
                        id=f"search:github:{url}",
                        source="search",
                        url=url,
                        finding=f"{item.get('title', '')[:160]} ({item.get('state', '?')}, {item.get('created_at', '?')})",
                        relevance="context",
                    )
                )
        return findings

    def _hn_search(self, pkg, queries, since, seen) -> list[Evidence]:
        findings: list[Evidence] = []
        for query in queries[:3]:
            payload = self.http.json(
                "GET",
                f"{self.config.sources['hn_algolia']}?"
                + urllib.parse.urlencode(
                    {
                        "query": f"{pkg.package} {query}",
                        "tags": "story",
                        "hitsPerPage": self.config.limits.search_results,
                        "numericFilters": f"created_at_i>{int(since.timestamp())}",
                    }
                ),
                timeout=self._timeout,
                source="HN Algolia",
            )
            hits = (payload or {}).get("hits") if isinstance(payload, dict) else None
            if not isinstance(hits, list):
                raise SourceError("HN Algolia", "unexpected payload")
            for hit in hits:
                url = str(hit.get("url") or "")
                if not url or url in seen:
                    continue
                seen.add(url)
                findings.append(
                    Evidence(
                        id=f"search:hn:{hit.get('objectID', url)}",
                        source="search",
                        url=url,
                        finding=f"{str(hit.get('title') or '')[:160]} (HN, {hit.get('created_at', '?')})",
                        relevance="context",
                    )
                )
        return findings

    def _brave_search(self, pkg, queries, seen) -> list[Evidence]:
        key = os.environ.get(self.config.brave_key_env, "").strip()
        if not key:
            raise SourceError(
                "search",
                f"the brave provider needs {self.config.brave_key_env}; set it or "
                "drop brave from search_providers",
            )
        findings: list[Evidence] = []
        for query in queries[:3]:
            payload = self.http.json(
                "GET",
                f"{self.config.sources['brave']}?"
                + urllib.parse.urlencode(
                    {"q": f"{pkg.package} {query}", "count": self.config.limits.search_results}
                ),
                headers={"X-Subscription-Token": key},
                timeout=self._timeout,
                source="Brave search",
            )
            results = (
                (payload or {}).get("web", {}).get("results") if isinstance(payload, dict) else None
            )
            if not isinstance(results, list):
                raise SourceError("Brave search", "unexpected payload")
            for result in results:
                url = str(result.get("url") or "")
                if not url or url in seen:
                    continue
                seen.add(url)
                findings.append(
                    Evidence(
                        id=f"search:brave:{url}",
                        source="search",
                        url=url,
                        finding=f"{str(result.get('title') or '')[:160]}",
                        relevance="context",
                    )
                )
        return findings


# ---------------------------------------------------------------------------
# Models and budget
# ---------------------------------------------------------------------------


class ProxyModel:
    """OpenAI-compatible chat calls through llmproxy.cove."""

    def __init__(self, config: Config, http: UrllibHttp | None = None) -> None:
        self.config = config
        self.http = http or UrllibHttp()

    def _token(self) -> str:
        explicit = os.environ.get(self.config.token_env, "").strip()
        if explicit:
            return explicit
        try:
            result = subprocess.run(
                ["cove", "creds", "vault-get", self.config.token_op_ref],
                check=True,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ModelError(
                "no llmproxy client token: set "
                f"{self.config.token_env} or cache {self.config.token_op_ref}"
            ) from exc
        token = result.stdout.strip()
        if not token:
            raise ModelError(f"{self.config.token_op_ref} resolved to an empty token")
        return token

    def complete(self, model: str, prompt: str, max_tokens: int) -> tuple[str, dict]:
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        try:
            payload = self.http.json(
                "POST",
                f"{self.config.proxy_url.rstrip('/')}/chat/completions",
                payload=body,
                headers={"Authorization": f"Bearer {self._token()}"},
                timeout=self.config.limits.http_timeout_s,
                source="LLM proxy",
            )
        except SourceError as exc:
            raise ModelError(str(exc)) from exc
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelError("LLM proxy returned no choice") from exc
        content = str(message.get("content") or "").strip()
        usage = payload.get("usage") or {}
        return content, usage


class Budget:
    def __init__(self, limits: Limits) -> None:
        self.limits = limits
        self.used_run_tokens = 0

    def new_check(self) -> "CheckBudget":
        return CheckBudget(self)


class CheckBudget:
    def __init__(self, parent: Budget) -> None:
        self.parent = parent
        self.used_tokens = 0

    def reserve(self, requested: int) -> int:
        remaining_check = self.parent.limits.per_check_tokens - self.used_tokens
        remaining_run = self.parent.limits.per_run_tokens - self.parent.used_run_tokens
        allowed = min(int(requested), remaining_check, remaining_run)
        if allowed < 32:
            raise BudgetError(
                f"token budget exhausted (check {self.used_tokens}/"
                f"{self.parent.limits.per_check_tokens}, run "
                f"{self.parent.used_run_tokens}/{self.parent.limits.per_run_tokens})"
            )
        return allowed

    def charge(self, usage: dict) -> int:
        tokens = int(
            usage.get("total_tokens")
            or (int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0))
        )
        self.used_tokens += tokens
        self.parent.used_run_tokens += tokens
        if self.used_tokens > self.parent.limits.per_check_tokens:
            raise BudgetError(
                f"per-check token budget exceeded ({self.used_tokens} > "
                f"{self.parent.limits.per_check_tokens})"
            )
        if self.parent.used_run_tokens > self.parent.limits.per_run_tokens:
            raise BudgetError(
                f"per-run token budget exceeded ({self.parent.used_run_tokens} > "
                f"{self.parent.limits.per_run_tokens})"
            )
        return tokens


def _extract_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ModelError(f"model did not return JSON: {cleaned[:160]!r}") from exc
    if not isinstance(data, dict):
        raise ModelError("model returned JSON that is not an object")
    return data


def _sanitize_queries(queries) -> list[str]:
    if not isinstance(queries, list):
        raise ModelError("research model did not return a query list")
    cleaned: list[str] = []
    for item in queries:
        if not isinstance(item, str):
            continue
        query = re.sub(r"\bsite:\S+", "", item)
        query = re.sub(r"\s+", " ", query).strip(" .;,")
        if not query or len(query) > 120:
            continue
        if query not in cleaned:
            cleaned.append(query)
    if not cleaned:
        raise ModelError("research model returned no usable queries")
    return cleaned[:3]


def parse_model_decision(
    text: str, allowed_urls: set[str]
) -> tuple[str, float, list[Evidence], str]:
    data = _extract_json(text)
    verdict = str(data.get("verdict") or "")
    if verdict not in VERDICTS:
        raise ModelError(f"model returned unknown verdict {verdict!r}")
    try:
        confidence = float(data.get("confidence"))
    except (TypeError, ValueError) as exc:
        raise ModelError("model did not return a numeric confidence") from exc
    if not 0.0 <= confidence <= 1.0:
        raise ModelError(f"model confidence {confidence} is outside [0, 1]")
    findings: list[Evidence] = []
    for index, item in enumerate(data.get("findings") or []):
        if not isinstance(item, dict):
            raise ModelError("model findings are not objects")
        url = str(item.get("url") or "")
        if url not in allowed_urls:
            raise ModelError(
                f"model cited a URL the tool did not supply: {url[:120]!r}"
            )
        findings.append(
            Evidence(
                id=f"model:{index}",
                source="model",
                url=url,
                finding=str(item.get("finding") or "")[:240],
                relevance=str(item.get("relevance") or "context"),
            )
        )
    rationale = str(data.get("rationale") or "").strip()
    if not rationale:
        raise ModelError("model returned no rationale")
    return verdict, confidence, findings, rationale[:600]


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


SEARCH_TERMS = (
    "supply chain attack",
    "compromised malicious release",
    "maintainer account takeover",
)


class Evaluator:
    def __init__(
        self,
        *,
        config: Config,
        feeds: Feeds,
        model: ProxyModel,
        budget: Budget,
        now=None,
    ) -> None:
        self.config = config
        self.feeds = feeds
        self.model = model
        self.budget = budget
        self.now = now or (lambda: datetime.now(timezone.utc))

    def evaluate(self, request: CheckRequest) -> Verdict:
        started = self.now()
        check = self.budget.new_check()
        evidence: list[Evidence] = []
        errors: list[str] = []
        spend: list[tuple[str, int, int]] = []
        model_used = self.config.models.judge

        def call(role: str, model: str, prompt: str, requested: int) -> str:
            allowed = check.reserve(requested)
            try:
                text, usage = self.model.complete(model, prompt, allowed)
            except (ModelError, BudgetError):
                raise
            except Exception as exc:  # a provider or transport failure is a hold
                raise ModelError(str(exc)) from exc
            tokens = check.charge(usage)
            spend.append(
                (
                    role,
                    int(usage.get("prompt_tokens") or 0),
                    int(usage.get("completion_tokens") or 0),
                )
            )
            _ = tokens
            return text

        if not self.config.enabled:
            return self._hold(
                request, check, "threat evaluation is disabled in the configuration"
            )

        for pkg in request.packages:
            try:
                evidence.extend(self.feeds.advisories_for(pkg))
            except SourceError as exc:
                errors.append(str(exc))
            try:
                registry, repo_url = self.feeds.registry_for(pkg)
                evidence.extend(registry)
            except SourceError as exc:
                repo_url = None
                errors.append(str(exc))
            if repo_url:
                try:
                    evidence.extend(self.feeds.issues_for(pkg, repo_url))
                except SourceError as exc:
                    errors.append(str(exc))
                try:
                    evidence.extend(self.feeds.changelog_for(pkg, repo_url))
                except SourceError as exc:
                    errors.append(str(exc))

            if errors:
                continue

            try:
                queries_prompt = self._queries_prompt(pkg, request)
                raw = call(
                    "research",
                    self.config.models.research,
                    queries_prompt,
                    self.config.limits.summarize_max_tokens,
                )
                queries = _sanitize_queries(_extract_json(raw).get("queries"))
            except (ModelError, BudgetError) as exc:
                errors.append(f"research model: {exc}")
                continue
            try:
                hits = self.feeds.search_for(pkg, queries)
            except SourceError as exc:
                errors.append(str(exc))
                continue
            evidence.extend(hits)
            if hits:
                try:
                    raw = call(
                        "research",
                        self.config.models.research,
                        self._summary_prompt(pkg, hits),
                        self.config.limits.summarize_max_tokens,
                    )
                    evidence.extend(self._parse_summary(raw, hits))
                except (ModelError, BudgetError) as exc:
                    errors.append(f"research model: {exc}")

        floor = deterministic_floor(evidence, errors)
        cost = self._cost(spend)
        if floor == "block":
            rationale = "deterministic evidence: " + "; ".join(
                item.finding
                for item in evidence
                if (item.source, item.relevance) in {("osv", "direct"), ("registry", "direct")}
            )[:400]
            return Verdict(
                verdict="block",
                confidence=0.95,
                evidence=evidence,
                model_used="none (deterministic)",
                cost_usd=cost,
                tokens=check.used_tokens,
                rationale=rationale,
                errors=errors,
                checked_at=self.now(),
                head_sha=request.head_sha,
                packages=[pkg.label() for pkg in request.packages],
            )
        if errors:
            return Verdict(
                verdict="hold",
                confidence=0.0,
                evidence=evidence,
                model_used="none (source failure)",
                cost_usd=cost,
                tokens=check.used_tokens,
                rationale="a required evidence source was unavailable or the budget was exhausted; "
                "holding because the check never reached a verdict",
                errors=errors,
                checked_at=self.now(),
                head_sha=request.head_sha,
                packages=[pkg.label() for pkg in request.packages],
            )
        if (self.now() - started).total_seconds() > self.config.limits.check_deadline_s:
            return Verdict(
                verdict="hold",
                confidence=0.0,
                evidence=evidence,
                model_used="none (deadline)",
                cost_usd=cost,
                tokens=check.used_tokens,
                rationale="the check exceeded its deadline; holding",
                errors=["deadline: threat evaluation exceeded its configured budget"],
                checked_at=self.now(),
                head_sha=request.head_sha,
                packages=[pkg.label() for pkg in request.packages],
            )

        try:
            raw = call(
                "judge",
                self.config.models.judge,
                self._judge_prompt(request, evidence, floor),
                self.config.limits.judge_max_tokens,
            )
            verdict, confidence, findings, rationale = parse_model_decision(
                raw, {item.url for item in evidence}
            )
            evidence.extend(findings)
        except (ModelError, BudgetError) as exc:
            errors.append(f"judge model: {exc}")
            return Verdict(
                verdict="hold",
                confidence=0.0,
                evidence=evidence,
                model_used=self.config.models.judge,
                cost_usd=self._cost(spend),
                tokens=check.used_tokens,
                rationale="the decision model failed or answered outside the schema; holding",
                errors=errors,
                checked_at=self.now(),
                head_sha=request.head_sha,
                packages=[pkg.label() for pkg in request.packages],
            )

        if VERDICT_RANK[verdict] < VERDICT_RANK[floor]:
            rationale = f"{rationale} (raised to {floor} by deterministic evidence)"
            verdict = floor
        if verdict != "proceed" and not rationale:
            rationale = "no rationale returned; holding"

        return Verdict(
            verdict=verdict,
            confidence=confidence,
            evidence=evidence,
            model_used=self.config.models.judge,
            cost_usd=self._cost(spend),
            tokens=check.used_tokens,
            rationale=rationale,
            errors=errors,
            checked_at=self.now(),
            head_sha=request.head_sha,
            packages=[pkg.label() for pkg in request.packages],
        )

    def _hold(self, request: CheckRequest, check: CheckBudget, reason: str) -> Verdict:
        return Verdict(
            verdict="hold",
            confidence=0.0,
            evidence=[],
            model_used="none",
            cost_usd=0.0,
            tokens=check.used_tokens,
            rationale=reason,
            errors=[reason],
            checked_at=self.now(),
            head_sha=request.head_sha,
            packages=[pkg.label() for pkg in request.packages],
        )

    def _cost(self, spend: list[tuple[str, int, int]]) -> float:
        total = 0.0
        for role, prompt, completion in spend:
            price = self.config.prices.research if role == "research" else self.config.prices.judge
            total += (prompt * price.input + completion * price.output) / 1_000_000
        return total

    def _queries_prompt(self, pkg: PackageRef, request: CheckRequest) -> str:
        window = self.config.limits.search_window_days
        return (
            "You generate web-search queries for a security check. Return JSON only: "
            '{"queries":["...","..."]}. '
            f"Package: {pkg.package}, version {pkg.version}, ecosystem {pkg.datasource}. "
            f"Pull request: {request.pr_title[:120]}. "
            f"Find reports from the last {window} days of a supply-chain compromise: "
            "malicious publish, typosquat, maintainer account takeover, compromised CI. "
            "Return two or three short keyword queries. No site: operators, no prose."
        )

    def _summary_prompt(self, pkg: PackageRef, hits: list[Evidence]) -> str:
        rows = "\n".join(f"- {item.finding} | {item.url}" for item in hits[:12])
        return (
            "Summarize search hits for a security check. Return JSON only: "
            '{"findings":[{"url":"...","finding":"one line","relevance":"direct|indirect|context"}]}. '
            "Use only the URLs below. Do not speculate. If a hit does not show a "
            "compromise, omit it. "
            f"Package {pkg.package} {pkg.version}.\nHits:\n{rows}"
        )

    def _parse_summary(self, text: str, hits: list[Evidence]) -> list[Evidence]:
        data = _extract_json(text)
        allowed = {item.url for item in hits}
        findings: list[Evidence] = []
        for index, item in enumerate(data.get("findings") or []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            if url not in allowed:
                continue
            findings.append(
                Evidence(
                    id=f"search-summary:{index}",
                    source="search",
                    url=url,
                    finding=str(item.get("finding") or "")[:200],
                    relevance=str(item.get("relevance") or "context"),
                )
            )
        return findings

    def _judge_prompt(self, request: CheckRequest, evidence: list[Evidence], floor: str) -> str:
        rows = "\n".join(
            f"- [{item.source}/{item.relevance}] {item.finding} | {item.url}"
            for item in evidence[:40]
        ) or "- (no adverse evidence was found)"
        packages = ", ".join(pkg.label() for pkg in request.packages)
        return (
            "You are a conservative software supply-chain reviewer. Decide whether this "
            "dependency update is safe to merge. Return JSON only: "
            '{"verdict":"proceed|hold|block","confidence":0.0,"findings":'
            '[{"url":"...","finding":"one line","relevance":"direct|indirect|context"}],'
            '"rationale":"one or two sentences"}. '
            f"Update: {packages}. Pull request: {request.pr_title[:140]}. "
            f"The deterministic floor is {floor}; you may raise it but not lower it. "
            "Use only the URLs supplied below; cite the ones that drove your decision. "
            "Prefer hold when the evidence is thin or ambiguous. "
            "A known advisory for the target version is a block. An open regression "
            "report or an unverified compromise report is a hold. "
            f"Evidence:\n{rows}"
        )


# ---------------------------------------------------------------------------
# Overrides
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Override:
    login: str
    reason: str
    label: str = OVERRIDE_LABEL


def parse_override(comments: list[dict], labels: list[str]) -> Override | None:
    if OVERRIDE_LABEL not in labels:
        return None
    for comment in reversed(comments):
        body = str(comment.get("body") or "")
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped.lower().startswith(OVERRIDE_PREFIX):
                continue
            reason = stripped[len(OVERRIDE_PREFIX) :].strip()
            if len(reason) < MIN_OVERRIDE_REASON:
                continue
            login = str((comment.get("user") or {}).get("login") or "unknown")
            return Override(login=login, reason=reason)
    return None


def record_override(
    api,
    repo: str,
    number: int,
    verdict: Verdict,
    override: Override,
    *,
    live: bool,
) -> None:
    if not live:
        return
    path = Path(
        os.environ.get("COVE_RENOVATE_AUDIT_LOG", DEFAULT_AUDIT_LOG)
    ).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "at": datetime.now(timezone.utc).isoformat(),
        "repo": repo,
        "pr": number,
        "login": override.login,
        "reason": override.reason,
        "verdict": verdict.verdict,
        "head_sha": verdict.head_sha,
        "packages": verdict.packages,
        "evidence": [item.url for item in verdict.evidence],
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    os.chmod(path, 0o600)
    encoded = base64.b64encode(override.reason.encode()).decode()
    body = (
        f"Threat override recorded for `{override.login}` at head "
        f"`{verdict.head_sha[:12]}`. The verdict was **{verdict.verdict}**.\n\n"
        f"Reason: {override.reason}\n\n"
        f"<!-- cove-threat-override-ack:v1 by={override.login} head={verdict.head_sha} "
        f"verdict={verdict.verdict} reason_b64={encoded} -->"
    )
    api.call("POST", f"/repos/{repo}/issues/{number}/comments", {"body": body})


# ---------------------------------------------------------------------------
# Pull request publishing
# ---------------------------------------------------------------------------


def render_comment(verdict: Verdict) -> str:
    lines = [f"## Threat evaluation: {verdict.verdict}", ""]
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Verdict | **{verdict.verdict}** |")
    lines.append(f"| Confidence | {verdict.confidence:.2f} |")
    lines.append(f"| Model | `{verdict.model_used}` |")
    lines.append(
        f"| Cost | ${verdict.cost_usd:.4f} ({verdict.tokens:,} tokens) |"
    )
    lines.append(
        f"| Checked | {verdict.checked_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} |"
    )
    lines.append(f"| Head | `{verdict.head_sha[:12]}` |")
    lines.append("")
    lines.append(f"**Rationale.** {verdict.rationale}")
    lines.append("")
    if verdict.evidence:
        lines.append("### Evidence")
        for item in verdict.evidence:
            link = f"[{item.source}]({item.url})" if item.url else item.source
            lines.append(f"- {link} ({item.relevance}): {item.finding}")
    else:
        lines.append("No adverse evidence was found in the configured sources.")
    if verdict.errors:
        lines.append("")
        lines.append("### Gaps")
        lines.extend(f"- {item}" for item in verdict.errors)
    lines.append("")
    lines.append(
        "This is a heuristic. Audit the links above; the verdict is not a guarantee. "
        "A human override needs the `threat-override` label and a "
        "`cove-threat-override: <reason>` comment."
    )
    lines.append("")
    lines.append(verdict.marker())
    return "\n".join(lines)


def _ensure_label(api, repo: str, name: str, color: str) -> int:
    status, labels = api.call("GET", f"/repos/{repo}/labels?limit=100")
    if status < 400 and isinstance(labels, list):
        for label in labels:
            if str(label.get("name")) == name:
                return int(label.get("id") or 0)
    status, created = api.call(
        "POST",
        f"/repos/{repo}/labels",
        {"name": name, "color": color, "description": "Cove threat evaluation"},
    )
    if status >= 400 or not isinstance(created, dict):
        raise ThreatError(f"could not create label {name}: {created}")
    return int(created.get("id") or 0)


def publish_verdict(api, repo: str, number: int, verdict: Verdict, *, live: bool) -> None:
    if not live:
        return
    target_name = VERDICT_LABELS[verdict.verdict]
    target_id = _ensure_label(api, repo, target_name, LABEL_COLORS[verdict.verdict])
    for other in VERDICT_LABELS.values():
        if other != target_name:
            _ensure_label(api, repo, other, "ededed")

    status, current = api.call("GET", f"/repos/{repo}/issues/{number}/labels")
    if status < 400 and isinstance(current, list):
        for label in current:
            if str(label.get("name")) in VERDICT_LABELS.values() and str(
                label.get("name")
            ) != target_name:
                api.call(
                    "DELETE",
                    f"/repos/{repo}/issues/{number}/labels/{int(label.get('id') or 0)}",
                )
        present = {str(label.get("name")) for label in current}
    else:
        present = set()
    if target_name not in present:
        api.call(
            "POST",
            f"/repos/{repo}/issues/{number}/labels",
            {"labels": [target_id]},
        )
    api.call(
        "POST",
        f"/repos/{repo}/issues/{number}/comments",
        {"body": render_comment(verdict)},
    )


# ---------------------------------------------------------------------------
# Reachability probe
# ---------------------------------------------------------------------------


def probe(config: Config, http: UrllibHttp | None = None) -> list[tuple[str, bool, str]]:
    http = http or UrllibHttp()
    rows: list[tuple[str, bool, str]] = []
    checks = [
        (
            "OSV",
            lambda: http.json(
                "POST",
                config.sources["osv"],
                payload={"package": {"name": "idna", "ecosystem": "PyPI"}, "version": "3.16"},
                timeout=config.limits.http_timeout_s,
                source="OSV",
            ),
        ),
        (
            "GitHub advisories",
            lambda: http.json(
                "GET",
                f"{config.sources['github_advisories']}?ecosystem=pip&affects=idna&per_page=1",
                timeout=config.limits.http_timeout_s,
                source="GitHub advisories",
            ),
        ),
        (
            "NVD",
            lambda: http.json(
                "GET",
                f"{config.sources['nvd']}?cveId=CVE-2020-14343",
                timeout=config.limits.http_timeout_s,
                source="NVD",
            ),
        ),
        (
            "PyPI",
            lambda: http.json(
                "GET",
                f"{config.sources['pypi']}/idna/3.16/json",
                timeout=config.limits.http_timeout_s,
                source="PyPI",
            ),
        ),
        (
            "npm",
            lambda: http.json(
                "GET",
                f"{config.sources['npm']}/lodash/4.17.21",
                timeout=config.limits.http_timeout_s,
                source="npm",
            ),
        ),
        (
            "GitHub issue search",
            lambda: http.json(
                "GET",
                f"{config.sources['github_issues']}?q=repo%3Akjd%2Fidna+is%3Aissue+is%3Aopen+3.16&per_page=1",
                timeout=config.limits.http_timeout_s,
                source="GitHub issue search",
            ),
        ),
        (
            "Codeberg",
            lambda: http.json(
                "GET",
                f"{config.sources['codeberg']}/repos/forgejo/forgejo/issues?state=open&limit=1",
                timeout=config.limits.http_timeout_s,
                source="Codeberg",
            ),
        ),
        (
            "HN Algolia",
            lambda: http.json(
                "GET",
                f"{config.sources['hn_algolia']}?query=supply%20chain&tags=story&hitsPerPage=1",
                timeout=config.limits.http_timeout_s,
                source="HN Algolia",
            ),
        ),
    ]
    for name, call in checks:
        try:
            call()
            rows.append((name, True, "ok"))
        except SourceError as exc:
            rows.append((name, False, str(exc)[:200]))
    try:
        model = ProxyModel(config, http)
        model.complete(config.models.research, "Reply with JSON only: {\"ok\":true}", 8)
        rows.append(("LLM proxy", True, f"model {config.models.research} answered"))
    except (ModelError, SourceError) as exc:
        rows.append(("LLM proxy", False, str(exc)[:200]))
    return rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print(msg: str) -> None:
    print(msg)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    config_path = os.environ.get("COVE_THREAT_EVAL_CONFIG") or None
    try:
        config = Config.load(config_path)
    except ConfigError as exc:
        _print(f"error: {exc}")
        return 2
    if not argv or argv[0] in {"-h", "--help"}:
        _print(__doc__ or "")
        _print("usage: threat_eval.py probe | check --datasource D --package P --version V --head-sha S")
        return 0
    if argv[0] == "probe":
        rows = probe(config)
        _print("| Source | Reachable | Detail |")
        _print("|---|---|---|")
        for name, ok, detail in rows:
            _print(f"| {name} | {'yes' if ok else 'NO'} | {detail.replace('|', '/')} |")
        return 0 if all(ok for _name, ok, _detail in rows) else 1
    if argv[0] == "check":
        args = {argv[i].removeprefix("--"): argv[i + 1] for i in range(1, len(argv) - 1, 2)}
        missing = {"datasource", "package", "version", "head-sha"} - args.keys()
        if missing:
            _print(f"error: missing {sorted(missing)}")
            return 2
        pkg = PackageRef(
            datasource=args["datasource"],
            package=args["package"],
            version=args["version"],
            ecosystem=ecosystem_for(args["datasource"]),
        )
        evaluator = Evaluator(
            config=config,
            feeds=Feeds(config),
            model=ProxyModel(config),
            budget=Budget(config.limits),
        )
        verdict = evaluator.evaluate(
            CheckRequest(packages=[pkg], head_sha=args["head-sha"], pr_title="cli check")
        )
        _print(render_comment(verdict))
        return 0 if verdict.verdict == "proceed" else 1
    _print(f"error: unknown command {argv[0]!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
