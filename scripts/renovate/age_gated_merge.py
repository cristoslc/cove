#!/usr/bin/env python3
"""Age-gated, threat-checked merge and republish for Renovate pull requests on Forgejo.

Renovate answers "is there a new version". This answers "is it safe, is it old
enough, is it green, and may it land" and then ships one coalesced release.

The split is deliberate:

* Renovate never automerges (``automerge: false`` in ``renovate.json``). The
  merge gate lives here, in one reviewable place, with the hold named.
* Every update takes the same 24-hour hold (operator decision, 2026-11-04; the
  tiered 48h/7d/14d/never windows are gone, majors included).
* Before the hold is evaluated, ``threat_eval`` reads the deterministic
  advisory, registry and release-notes feeds, researches the open-web gap with
  a light model, and asks a standard-tier model for a verdict. The release
  notes are the "changelog reviewed for security issues" half of the policy:
  the notes are an evidence row, and a version with no published notes is
  recorded as a coverage gap rather than silently skipped. The combined rule is
  "aged AND threat-checked proceed". A missing verdict, a hold, a block, an
  unreachable source, a model error, or a budget exhaustion holds. Only a
  recorded human override clears the threat half, and it clears nothing else.
* This script never pushes to ``main`` and never force-pushes. It merges only
  through the pull request API, so Forgejo branch protection (no direct push,
  required ``no-pii-gate`` context) stays in force for every merge it makes.
* Compose changes are never merged here. The stack-update runbook requires a
  staging E2E pass, an SBOM delta, and (``docs/musings/digest-pinning-plan.md``)
  the ``.env`` re-sync before an image pin can reach a host. Those are reported
  as held, never claimed as applied.

Exit code is 0 for a completed run (including "nothing eligible"), non-zero for
a hard failure (auth, API, check, merge, release, or a missing threat config on
a live run). A non-zero exit is the automation's visible failure; stdout
carries the report either way.

Usage (bb automation: script mode, ``--working-directory project``):

    COVE_RENOVATE_LIVE=1 python3 scripts/renovate/age_gated_merge.py

Without ``COVE_RENOVATE_LIVE=1`` the run is a dry run: it reports the same
decisions and changes nothing. It still evaluates threat evidence (read-only)
so the dry run shows the same verdicts, but it posts no comment, label, or
override record.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
import threat_eval  # noqa: E402  (operator script beside this one)

MARKER_VERSION = "cove-age-gate:v1"
MARKER_RE = re.compile(r"<!--\s*(cove-age-gate:\S+)\s*(.*?)-->", re.S)
FIELD_RE = re.compile(r"^[a-z_]+=\S*;$")

# Strongest first. Anything outside this set is a marker we do not understand
# and must not silently classify.
UPDATE_TYPE_RANK = ("major", "minor", "patch", "pinDigest", "digest")

# The operator turned the tiered windows off on 2026-11-04: patches, minors,
# digests and majors all take the same short hold. What replaces the tiering is
# the changelog review in ``threat_eval`` (release notes are an evidence row the
# judge must weigh) plus this minimum age, which exists so a compromised or
# rebuilt release is visible for a day before the automation can merge it.
# "In most cases" is deliberate: the automation always waits, and a shorter hold
# is an operator hand-merge, never something this script does.
MIN_AGE = timedelta(hours=24)

# Paths this automation may merge on its own. Everything else is reported.
MERGEABLE_PREFIXES = ("cli/", ".forgejo/workflows/")
WHEEL_PREFIXES = ("cli/", "compose/")

REQUIRED_CHECK_MARKERS = ("no-pii", "no-pii-gate")


class GateError(RuntimeError):
    """A hard failure: auth, API, merge, or release could not proceed."""


class MarkerError(ValueError):
    """The PR body carries a marker this script cannot read safely."""


@dataclass(frozen=True)
class Upgrade:
    datasource: str
    package: str
    version: str
    update_type: str
    released: datetime | None
    vulnerability: bool


@dataclass(frozen=True)
class Classification:
    update_type: str
    vulnerability: bool


@dataclass(frozen=True)
class Decision:
    merge: bool
    reason: str


@dataclass
class Report:
    rows: list[dict] = field(default_factory=list)
    merged: list[int] = field(default_factory=list)
    held: list[tuple[int, str]] = field(default_factory=list)
    release: str | None = None
    notes: list[str] = field(default_factory=list)


def _parse_ts(value: str) -> datetime | None:
    if not value or value.lower() in {"none", "null", "unknown"}:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MarkerError(f"unparseable timestamp {value!r} in age-gate marker") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_markers(body: str) -> list[Upgrade]:
    """Read the machine-readable marker Renovate renders into the PR body.

    Raises instead of guessing: a marker this script cannot read means the
    age of the update is unknown, and an unknown age is never eligible.
    """
    found = MARKER_RE.findall(body or "")
    if not found:
        return []
    upgrades: list[Upgrade] = []
    for version, payload in found:
        if version != MARKER_VERSION:
            raise MarkerError(f"unsupported age-gate marker version {version!r}")
        for chunk in payload.split(";"):
            chunk = chunk.strip()
            if not chunk:
                continue
            pairs: dict[str, str] = {}
            for token in chunk.split():
                if "=" not in token:
                    raise MarkerError(f"malformed age-gate field {token!r}")
                key, value = token.split("=", 1)
                pairs[key] = value
            missing = {"datasource", "package", "version", "type"} - pairs.keys()
            if missing:
                raise MarkerError(f"age-gate marker missing {sorted(missing)}")
            if pairs["type"] not in UPDATE_TYPE_RANK:
                raise MarkerError(f"unknown update type {pairs['type']!r}")
            upgrades.append(
                Upgrade(
                    datasource=pairs["datasource"],
                    package=pairs["package"],
                    version=pairs["version"],
                    update_type=pairs["type"],
                    released=_parse_ts(pairs.get("rel", "")),
                    vulnerability=pairs.get("vulnerability", "false").lower() == "true",
                )
            )
    if not upgrades:
        return []
    return upgrades


def strongest(update_types) -> Classification:
    for name in update_types:
        if name not in UPDATE_TYPE_RANK:
            raise MarkerError(f"unknown update type {name!r}")
    best = min(update_types, key=UPDATE_TYPE_RANK.index)
    return Classification(update_type=best, vulnerability=False)


def required_age(update_type: str, vulnerability: bool) -> timedelta | None:
    """One hold for every update type, majors included.

    The tiered windows were removed on 2026-11-04. Majors are no longer
    excluded outright; they carry the `major` label for human attention and
    still face the same 24-hour hold and the same changelog-aware threat
    verdict as everything else.
    """
    _ = (update_type, vulnerability)
    return MIN_AGE


def age_signal(upgrades: list[Upgrade], pr_created_at: datetime) -> tuple[datetime, str]:
    stamps = [u.released for u in upgrades if u.released is not None]
    if stamps:
        return max(stamps), "upstream release timestamp"
    return pr_created_at, "pull request age"


def _classify_paths(files: list[str]) -> tuple[bool, str]:
    if any(path.startswith("compose/") for path in files):
        return False, (
            "compose change: the runbook requires a staging E2E pass, an SBOM delta, "
            "and the .env pin re-sync (digest-pinning plan, Phase 0) before an image "
            "pin reaches a host; not auto-merged"
        )
    unknown = [p for p in files if not p.startswith(MERGEABLE_PREFIXES)]
    if unknown:
        return False, f"path outside the auto-merge allowlist: {', '.join(sorted(unknown)[:3])}"
    return True, "eligible"


def precheck(*, body: str, label_names: list[str], files: list[str]) -> Decision | None:
    """Everything that must hold before a threat check is worth paying for.

    This is the pure, no-network half of :func:`decide`: path
    policy. The age window is evaluated after the threat check, because "aged
    AND threat-checked proceed" is the combined rule.
    """
    try:
        upgrades = parse_markers(body)
    except MarkerError as exc:
        return Decision(False, f"unreadable age-gate marker: {exc}")

    if upgrades:
        update_type = strongest([u.update_type for u in upgrades]).update_type
    else:
        # Lock file maintenance has no per-dependency upgrades.
        update_type = "patch"

    paths_ok, path_reason = _classify_paths(files)
    if not paths_ok:
        return Decision(False, path_reason)
    return None


def decide(
    *,
    body: str,
    label_names: list[str],
    files: list[str],
    pr_created_at: datetime,
    now: datetime,
    branch: str = "",
    threat_verdict: str | None = None,
    threat_reason: str = "",
) -> Decision:
    """The whole gate, in one place, with no network access.

    ``threat_verdict`` is required. ``None`` means the threat check did not run,
    which is a hold: the gate never treats a missing verdict as permission.
    """
    try:
        upgrades = parse_markers(body)
    except MarkerError as exc:
        return Decision(False, f"unreadable age-gate marker: {exc}")

    security_label = "security" in label_names
    if upgrades:
        classification = strongest([u.update_type for u in upgrades])
        update_type = classification.update_type
        vulnerability = security_label or any(u.vulnerability for u in upgrades)
        signal, source = age_signal(upgrades, pr_created_at)
    else:
        # Lock file maintenance has no per-dependency upgrades. Treat it as a
        # patch-equivalent change measured from the PR's own age.
        update_type = "patch"
        vulnerability = security_label
        signal, source = pr_created_at, "pull request age"

    paths_ok, path_reason = _classify_paths(files)
    if not paths_ok:
        return Decision(False, path_reason)

    if threat_verdict is None:
        return Decision(False, "threat evaluation missing; holding (fail closed)")
    if threat_verdict not in threat_eval.VERDICTS:
        return Decision(
            False, f"unknown threat verdict {threat_verdict!r}; holding (fail closed)"
        )
    if threat_verdict != "proceed":
        return Decision(
            False,
            f"threat evaluation {threat_verdict}: "
            f"{threat_reason or 'see the threat comment on the pull request'}",
        )

    window = required_age(update_type, vulnerability)
    age = now - signal
    if age < window:
        remaining = window - age
        return Decision(
            False,
            f"age gate: {update_type}{' security' if vulnerability else ''} needs "
            f"{_human(window)} from {source}, has {_human(age)} (wait {_human(remaining)})",
        )
    return Decision(True, "eligible")


def _human(delta: timedelta) -> str:
    seconds = int(delta.total_seconds())
    if seconds < 0:
        seconds = 0
    days, rem = divmod(seconds, 86400)
    hours = rem // 3600
    if days:
        return f"{days}d{hours}h"
    return f"{hours}h"


# --------------------------------------------------------------------------
# Platform and process plumbing
# --------------------------------------------------------------------------


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _api_base() -> str:
    return _env("COVE_RENOVATE_API", "https://git.cove/api/v1").rstrip("/")


def _repo() -> str:
    return _env("COVE_RENOVATE_REPO", "cristos/cove")


def resolve_token() -> str:
    token = _env("FORGEJO_TOKEN")
    if token:
        return token
    try:
        token = subprocess.run(
            ["cove", "creds", "vault-get", "forgejo-token"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise GateError(
            "no Forgejo token: set FORGEJO_TOKEN or run "
            "`cove creds vault-put forgejo-token` (see docs/guides/renovate.md)"
        ) from exc
    if not token:
        raise GateError("FORGEJO_TOKEN and the Vault helper both returned nothing")
    return token


class Api:
    def __init__(self, base: str, token: str) -> None:
        self.base = base
        self._token = token

    def call(self, method: str, path: str, payload: dict | None = None) -> tuple[int, object]:
        url = f"{self.base}{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"token {self._token}")
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read().decode() or "{}"
                return response.status, json.loads(raw)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode() or "{}"
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                body = {"message": raw[:400]}
            return exc.code, body
        except urllib.error.URLError as exc:
            raise GateError(f"{method} {url} failed: {exc.reason}") from exc

    def get(self, path: str) -> object:
        status, body = self.call("GET", path)
        if status >= 400:
            raise GateError(f"GET {path} -> {status}: {_message(body)}")
        return body

    def post(self, path: str, payload: dict | None = None) -> tuple[int, object]:
        return self.call("POST", path, payload or {})


def _message(body: object) -> str:
    if isinstance(body, dict):
        return str(body.get("message") or body.get("error") or body)[:300]
    return str(body)[:300]


def _prs(api: Api) -> list[dict]:
    owner, name = _repo().split("/", 1)
    prs = api.get(f"/repos/{owner}/{name}/pulls?state=open&limit=50")
    assert isinstance(prs, list)
    return prs


def _pr_files(api: Api, number: int) -> list[str]:
    owner, name = _repo().split("/", 1)
    files = api.get(f"/repos/{owner}/{name}/pulls/{number}/files?limit=100")
    assert isinstance(files, list)
    return [item.get("filename", "") for item in files]


def _pr_comments(api: Api, number: int) -> list[dict]:
    owner, name = _repo().split("/", 1)
    comments = api.get(f"/repos/{owner}/{name}/issues/{number}/comments?limit=50")
    return comments if isinstance(comments, list) else []


def _cached_verdict(comments: list[dict], head_sha: str) -> threat_eval.Verdict | None:
    for comment in reversed(comments):
        try:
            verdict = threat_eval.parse_verdict_marker(str(comment.get("body") or ""))
        except threat_eval.MarkerError:
            continue
        if verdict is not None and verdict.head_sha == head_sha:
            return verdict
    return None


def _verdict_fresh(
    verdict: threat_eval.Verdict, limits: threat_eval.Limits, now: datetime
) -> bool:
    minutes = {
        "proceed": limits.reuse_minutes_proceed,
        "hold": limits.reuse_minutes_hold,
        "block": limits.reuse_minutes_block,
    }[verdict.verdict]
    age = now - verdict.checked_at
    return timedelta(0) <= age <= timedelta(minutes=minutes)


def _hold_for(request: threat_eval.CheckRequest, reason: str) -> threat_eval.Verdict:
    return threat_eval.Verdict(
        verdict="hold",
        confidence=0.0,
        evidence=[],
        model_used="none",
        cost_usd=0.0,
        tokens=0,
        rationale=reason,
        errors=[reason],
        checked_at=datetime.now(timezone.utc),
        head_sha=request.head_sha,
        packages=[pkg.label() for pkg in request.packages],
    )


def _threat_for_pr(
    api: Api,
    pr: dict,
    upgrades: list[Upgrade],
    comments: list[dict],
    *,
    config: threat_eval.Config | None,
    config_error: str,
    budget: threat_eval.Budget | None,
    feeds: threat_eval.Feeds | None,
    model: threat_eval.ProxyModel | None,
    live: bool,
    report: Report,
) -> threat_eval.Verdict:
    """Return the verdict for one PR, reusing a fresh marker when present.

    A missing configuration or a package list the marker cannot name is a
    synthetic hold. It is never permission.
    """
    number = int(pr["number"])
    head_sha = str(pr.get("head", {}).get("sha", ""))
    packages = [
        threat_eval.PackageRef(
            datasource=upgrade.datasource,
            package=upgrade.package,
            version=upgrade.version,
            ecosystem=threat_eval.ecosystem_for(upgrade.datasource),
        )
        for upgrade in upgrades
    ]
    request = threat_eval.CheckRequest(
        packages=packages,
        head_sha=head_sha,
        pr_number=number,
        pr_title=str(pr.get("title", "")),
    )
    if config is None:
        return _hold_for(request, config_error or "threat evaluation is not configured")
    if not packages:
        return _hold_for(
            request,
            "the pull request carries no per-package marker (lock file maintenance), "
            "so the threat check cannot name what changed; review or override",
        )
    cached = _cached_verdict(comments, head_sha)
    if cached is not None and _verdict_fresh(cached, config.limits, datetime.now(timezone.utc)):
        report.notes.append(
            f"#{number} threat {cached.verdict} reused from an earlier check "
            f"({_human(datetime.now(timezone.utc) - cached.checked_at)} old)."
        )
        return cached
    assert budget is not None and feeds is not None and model is not None
    verdict = threat_eval.Evaluator(
        config=config, feeds=feeds, model=model, budget=budget
    ).evaluate(request)
    report.notes.append(
        f"#{number} threat {verdict.verdict} "
        f"(${verdict.cost_usd:.4f}, {verdict.tokens} tokens, {verdict.model_used})."
    )
    if live:
        owner, name = _repo().split("/", 1)
        threat_eval.publish_verdict(api, f"{owner}/{name}", number, verdict, live=True)
    return verdict


def status_verdict(statuses: list[dict]) -> tuple[bool, str]:
    """Judge the required check from the statuses of one commit.

    Forgejo records every transition of a context as its own row (pending,
    pending, success), so "latest" has to mean the newest row, not the first
    one in the list. The combined endpoint returns one row per context; the
    list endpoint returns the history. Both are handled.
    """
    relevant = [
        s
        for s in statuses
        if all(marker in str(s.get("context", "")) for marker in REQUIRED_CHECK_MARKERS)
    ]
    if not relevant:
        return False, "required check no-pii-gate has not run on the head"
    latest = max(
        relevant,
        key=lambda s: (int(s.get("id") or 0), str(s.get("created_at", ""))),
    )
    state = str(latest.get("status") or latest.get("state") or "")
    if state == "success":
        return True, "no-pii-gate success"
    return False, f"required check is {state or 'unknown'} on the head"


def _check_success(api: Api, sha: str) -> tuple[bool, str]:
    owner, name = _repo().split("/", 1)
    combined = api.get(f"/repos/{owner}/{name}/commits/{sha}/status")
    if isinstance(combined, dict) and isinstance(combined.get("statuses"), list):
        return status_verdict(combined["statuses"])
    statuses = api.get(f"/repos/{owner}/{name}/commits/{sha}/statuses?limit=50")
    if not isinstance(statuses, list):
        raise GateError(f"unexpected statuses payload for {sha[:8]}")
    return status_verdict(statuses)


def _main_sha(api: Api) -> str:
    owner, name = _repo().split("/", 1)
    branch = api.get(f"/repos/{owner}/{name}/branches/main")
    assert isinstance(branch, dict)
    return str(branch["commit"]["id"])


def _is_renovate_pr(pr: dict) -> bool:
    if str(pr.get("head", {}).get("ref", "")).startswith("renovate/"):
        return True
    return MARKER_VERSION in str(pr.get("body") or "")


def _label_names(pr: dict) -> list[str]:
    return [str(label.get("name", "")) for label in pr.get("labels") or []]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise GateError(f"git {' '.join(args)} failed: {result.stderr.strip()[:400]}")
    return result.stdout.strip()


def _run(cmd: list[str], cwd: Path, what: str) -> str:
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if result.returncode != 0:
        raise GateError(f"{what} failed: {(result.stderr or result.stdout).strip()[:600]}")
    return result.stdout


def _preflight(repo: Path) -> None:
    if not (repo / "cli" / "pyproject.toml").exists():
        raise GateError(f"{repo} is not the cove checkout (no cli/pyproject.toml)")
    if _git(repo, "status", "--porcelain"):
        raise GateError(
            f"{repo} has uncommitted changes; the release flow will not run over them"
        )
    current = _git(repo, "branch", "--show-current")
    if current != "main":
        raise GateError(f"{repo} is on {current!r}, not main; the release flow needs main")


def _next_version(repo: Path) -> str:
    text = (repo / "cli" / "pyproject.toml").read_text()
    match = re.search(r'(?m)^version = "(\d+)\.(\d+)\.(\d+)"$', text)
    if not match:
        raise GateError("cannot read the version from cli/pyproject.toml")
    major, minor, patch = (int(part) for part in match.groups())
    return f"{major}.{minor}.{patch + 1}"


def _changelog(repo: Path, version: str, merged: list[dict]) -> None:
    path = repo / "CHANGELOG.md"
    text = path.read_text()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bullets = "\n".join(
        f"- **{item['title']}** ([#{item['number']}](../../pulls/{item['number']})) — merged by the Renovate age gate."
        for item in merged
    )
    section = f"## {version} ({stamp})\n\n### Changed\n{bullets}\n\n"
    # Release sections go below `## Unreleased`, above the previous release.
    anchor = re.search(r"(?m)^## (?!Unreleased)", text)
    if anchor is None:
        raise GateError("CHANGELOG.md has no released section to insert before")
    path.write_text(text[: anchor.start()] + section + text[anchor.start() :])


def _bump(repo: Path, version: str) -> None:
    pyproject = repo / "cli" / "pyproject.toml"
    text = pyproject.read_text()
    updated, count = re.subn(r'(?m)^version = "\d+\.\d+\.\d+"$', f'version = "{version}"', text, count=1)
    if count != 1:
        raise GateError("could not bump the version in cli/pyproject.toml")
    pyproject.write_text(updated)
    _run(["uv", "lock"], repo / "cli", "uv lock")
    diff = _git(repo, "diff", "--unified=0", "--", "cli/uv.lock")
    changed = [line for line in diff.splitlines() if line.startswith(("+version", "-version"))]
    if not changed or any(f'"{version}"' not in line for line in changed if line.startswith("+")):
        raise GateError(
            f"uv lock touched more than the project version; review cli/uv.lock before releasing:\n{diff[:800]}"
        )


def _notify(report: str, failed: bool) -> None:
    topic = _env("NTFY_TOPIC")
    if not topic:
        return
    server = _env("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    payload = {
        "topic": topic,
        "title": "Renovate age gate failed" if failed else "Renovate age gate",
        "message": report[:3500],
        "priority": 4 if failed else 3,
    }
    request = urllib.request.Request(
        server,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    token = _env("NTFY_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        urllib.request.urlopen(request, timeout=15).read()
    except Exception as exc:  # notification failure must never fail the run
        print(f"note: ntfy delivery failed: {exc}", file=sys.stderr)


def _render(report: Report, live: bool, failures: list[str]) -> str:
    lines = []
    head = "Renovate threat and age gate: " + datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )
    lines.append(f"## {head}{'' if live else ' (dry run)'}")
    lines.append("")
    if report.rows:
        lines.append("| PR | Title | Class | Age signal | Threat | Decision |")
        lines.append("|---|---|---|---|---|---|")
        for row in report.rows:
            lines.append(
                f"| #{row['number']} | {row['title'][:60]} | {row['class']} | "
                f"{row['age']} | {row.get('threat', 'not run')} | {row['decision']} |"
            )
        lines.append("")
    else:
        lines.append("No open Renovate pull requests.")
        lines.append("")
    if report.merged:
        lines.append(f"Merged this run: {', '.join('#' + str(n) for n in report.merged)}.")
    if report.held:
        lines.append("Held: " + "; ".join(f"#{n} ({why[:90]})" for n, why in report.held) + ".")
    if report.release:
        lines.append(f"Release: {report.release}.")
    for note in report.notes:
        lines.append(note)
    if failures:
        lines.append("")
        lines.append("**Failures**")
        lines.extend(f"- {item}" for item in failures)
    return "\n".join(lines).strip()


def main() -> int:
    repo = Path.cwd()
    live = _env("COVE_RENOVATE_LIVE").lower() in {"1", "true", "yes", "on"}
    report = Report()
    failures: list[str] = []
    token = ""
    try:
        token = resolve_token()
        api = Api(_api_base(), token)
        owner, name = _repo().split("/", 1)
        me = api.get("/user")
        report.notes.append(
            f"Token identity: {me.get('login', '?')} (the age gate acts as this account)."
        )
        if live:
            _preflight(repo)
            _git(repo, "fetch", "origin", "main", "--quiet")
            _git(repo, "merge", "--ff-only", "origin/main")
        main_sha = _main_sha(api)
        prs = [pr for pr in _prs(api) if _is_renovate_pr(pr)]

        threat_config: threat_eval.Config | None = None
        threat_error = ""
        try:
            threat_config = threat_eval.Config.load()
        except threat_eval.ConfigError as exc:
            threat_error = str(exc)
            report.notes.append(f"Threat evaluation: {exc}")
            if live:
                raise GateError(
                    f"{exc} The live gate refuses to merge without a threat check."
                ) from exc
        threat_budget = threat_eval.Budget(threat_config.limits) if threat_config else None
        threat_feeds = threat_eval.Feeds(threat_config) if threat_config else None
        threat_model = threat_eval.ProxyModel(threat_config) if threat_config else None

        eligible: list[dict] = []
        for pr in prs:
            number = int(pr["number"])
            title = str(pr.get("title", ""))
            labels = _label_names(pr)
            files = _pr_files(api, number)
            created = _parse_ts(str(pr.get("created_at", ""))) or datetime.now(timezone.utc)
            branch = str(pr.get("head", {}).get("ref", ""))
            body_text = str(pr.get("body") or "")
            try:
                marker_upgrades = (
                    parse_markers(body_text) if MARKER_VERSION in body_text else []
                )
            except MarkerError:
                marker_upgrades = []
            if marker_upgrades:
                classification = strongest([u.update_type for u in marker_upgrades])
                update_class = classification.update_type
                if "security" in labels or any(u.vulnerability for u in marker_upgrades):
                    update_class += " security"
                signal, source = age_signal(marker_upgrades, created)
            else:
                update_class = "maintenance"
                signal, source = created, "pull request age"

            pre = precheck(body=body_text, label_names=labels, files=files)
            draft = str(pr.get("title", "")).upper().startswith("WIP:") or bool(
                pr.get("draft")
            )
            threat_status = "not run"
            if pre is not None:
                decision = pre
            elif draft:
                decision = Decision(False, "draft PR")
            else:
                comments = _pr_comments(api, number)
                verdict = _threat_for_pr(
                    api,
                    pr,
                    marker_upgrades,
                    comments,
                    config=threat_config,
                    config_error=threat_error,
                    budget=threat_budget,
                    feeds=threat_feeds,
                    model=threat_model,
                    live=live,
                    report=report,
                )
                threat_status = verdict.verdict
                if verdict.verdict != "proceed":
                    override = threat_eval.parse_override(comments, labels)
                    if override is not None:
                        if live:
                            threat_eval.record_override(
                                api,
                                f"{owner}/{name}",
                                number,
                                verdict,
                                override,
                                live=True,
                            )
                        report.notes.append(
                            f"#{number} threat {verdict.verdict} overridden by "
                            f"{override.login}: {override.reason}"
                        )
                        verdict = replace(
                            verdict,
                            verdict="proceed",
                            rationale=(
                                f"human override by {override.login}: {override.reason}"
                            ),
                            model_used="human override",
                        )
                        threat_status = "override"
                decision = decide(
                    body=body_text,
                    label_names=labels,
                    files=files,
                    pr_created_at=created,
                    now=datetime.now(timezone.utc),
                    branch=branch,
                    threat_verdict=verdict.verdict,
                    threat_reason=verdict.rationale,
                )
            report.rows.append(
                {
                    "number": number,
                    "title": title,
                    "class": update_class,
                    "age": f"{_human(datetime.now(timezone.utc) - signal)} via {source}",
                    "threat": threat_status,
                    "decision": decision.reason if decision.merge else f"hold: {decision.reason}",
                }
            )
            if not decision.merge:
                report.held.append((number, decision.reason))
                continue

            base_sha = str(pr.get("base", {}).get("sha", ""))
            if base_sha != main_sha:
                if live:
                    status, body = api.post(f"/repos/{owner}/{name}/pulls/{number}/update")
                    if status >= 400:
                        report.held.append((number, f"behind main and rebase refused: {_message(body)}"))
                        continue
                report.notes.append(
                    f"#{number} was behind main; {'rebased' if live else 'would rebase'} and is re-checked next run."
                )
                report.held.append((number, "behind main, rebased; check re-runs"))
                continue

            ok, why = _check_success(api, str(pr["head"]["sha"]))
            if not ok:
                report.held.append((number, why))
                continue
            eligible.append(pr)

        eligible.sort(key=lambda pr: (0 if "security" in _label_names(pr) else 1, str(pr["created_at"])))

        for pr in eligible:
            number = int(pr["number"])
            if not live:
                report.notes.append(f"#{number}: would squash-merge with its PR title.")
                continue
            status, body = api.post(
                f"/repos/{owner}/{name}/pulls/{number}/merge",
                {
                    "Do": "squash",
                    "MergeTitleField": str(pr.get("title", "")),
                    "head_commit_id": str(pr["head"]["sha"]),
                },
            )
            if status >= 400:
                failures.append(f"merge #{number} refused: {_message(body)}")
                continue
            report.merged.append(number)
            _git(repo, "fetch", "origin", "main", "--quiet")
            _git(repo, "merge", "--ff-only", "origin/main")
            main_sha = _main_sha(api)

        if report.merged or (not live and eligible):
            merged_meta = [
                {
                    "number": int(pr["number"]),
                    "title": str(pr.get("title", "")),
                    "files": _pr_files(api, int(pr["number"])),
                }
                for pr in prs
                if int(pr["number"]) in (report.merged or [int(p["number"]) for p in eligible])
            ]
            wheel_paths = sorted(
                {
                    path
                    for item in merged_meta
                    for path in item["files"]
                    if path.startswith(WHEEL_PREFIXES)
                }
            )
            if not wheel_paths:
                report.notes.append(
                    "No merged change touched cli/ or compose/, so nothing a wheel carries "
                    "changed; no version was minted."
                )
            elif not live:
                report.notes.append(
                    "Would cut one coalesced patch release: bump cli/pyproject.toml + cli/uv.lock, "
                    "add a CHANGELOG section, open and merge the release PR, build the wheel, "
                    "then run scripts/release.sh to GitHub and Forgejo."
                )
            else:
                # The promote contract (AGENTS.md) is: post-merge to main, and
                # only once the unit gate is green. Gate first, then mint the
                # version, so a red gate never produces a release PR.
                _run(
                    ["uv", "run", "--directory", "cli", "pytest", "-x", "-q", "-m", "not e2e and not staging"],
                    repo,
                    "unit gate",
                )
                version = _next_version(repo)
                branch = f"release/{version}"
                if _git(repo, "ls-remote", "--heads", "origin", branch):
                    raise GateError(
                        f"release branch {branch} already exists; a previous release run did not finish. "
                        "Resolve or delete it before the next run."
                    )
                _git(repo, "checkout", "-b", branch)
                _bump(repo, version)
                _changelog(repo, version, merged_meta)
                _git(repo, "add", "cli/pyproject.toml", "cli/uv.lock", "CHANGELOG.md")
                _git(repo, "commit", "-m", f"chore(release): {version}")
                _git(repo, "push", "origin", branch)
                status, body = api.post(
                    f"/repos/{owner}/{name}/pulls",
                    {
                        "head": branch,
                        "base": "main",
                        "title": f"chore(release): {version}",
                        "body": "Coalesced release cut by the Renovate age-gate automation.",
                    },
                )
                if status >= 400:
                    raise GateError(f"release PR refused: {_message(body)}")
                release_pr = int(body["number"])  # type: ignore[index]
                _wait_for_release_check(api, release_pr)
                status, body = api.post(
                    f"/repos/{owner}/{name}/pulls/{release_pr}/merge",
                    {
                        "Do": "squash",
                        "MergeTitleField": f"chore(release): {version}",
                    },
                )
                if status >= 400:
                    raise GateError(f"release PR merge refused: {_message(body)}")
                _git(repo, "checkout", "main")
                _git(repo, "fetch", "origin", "main", "--quiet")
                _git(repo, "merge", "--ff-only", "origin/main")
                # `uv build` runs setup.py's build_py hook, which re-syncs
                # compose/ into the bundled resources, so the wheel carries the
                # merged tree without dirtying the checkout.
                _run(["uv", "build", "--wheel", "--out-dir", "dist"], repo / "cli", "wheel build")
                _git(repo, "tag", "-a", f"v{version}", "-m", f"cove-cli {version}")
                _run(["bash", "scripts/release.sh", version], repo, "release")
                report.release = f"{version} published to GitHub and Forgejo"
    except (GateError, MarkerError) as exc:
        failures.append(str(exc))
    finally:
        rendered = _render(report, live, failures)
        print(rendered)
        _notify(rendered, bool(failures))
    return 1 if failures else 0


def _wait_for_release_check(api: Api, number: int, timeout: int = 300) -> None:
    deadline = datetime.now(timezone.utc) + timedelta(seconds=timeout)
    while datetime.now(timezone.utc) < deadline:
        prs = _prs(api)
        pr = next((p for p in prs if int(p["number"]) == number), None)
        if pr is not None:
            ok, _why = _check_success(api, str(pr["head"]["sha"]))
            if ok:
                return
        time.sleep(10)
    raise GateError(f"release PR #{number} did not reach a green no-pii-gate within {timeout}s")


if __name__ == "__main__":
    sys.exit(main())
