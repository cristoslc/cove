"""Reject operator PII (user-specific config) in tracked files.

Incident 20261026-145212: the rendered 1Password seed (`compose/seeds/
vault-user.yaml`) — a `Vault <machine> <user>`-shaped item title with the
operator hostname, username and a live Vault UI credential value — shipped in
public repo tree AND history. The gate meant to catch it was blind: pytest ran
from `cli/`, so its repo-root-relative prefixes (`docs/`) never matched and it
only ever scanned the cli/ subtree; it excluded docs/ outright; and its own
pattern list embedded the real hostname.

Conventions the widened gate relies on:

- The scrub's synthetic placeholders (`<hostname>`, `/<hostname>.yml`,
  `operator@example.com`) are LEGITIMATE repo content — they are the documented
  template convention (resolver docstrings, bringup comments, host_vars
  examples, CHANGELOG prose). The `<hostname>` sentinel therefore moved out of
  the pattern list; patterns here only fire on operator-identifying values.
- cove ships no user-specific config. The username legitimately appears in
  Forgejo org/repo URLs (CHANGELOG, docs, README), so it is not a bare literal
  pattern — it is caught in its identifying contexts (Vault item titles) and
  via structural rules (only `*.example` seeds may be tracked).

Scope: every git-tracked file (repo-root relative — compose/, docs/,
CHANGELOG.md included), the bundled wheel resources under
`cli/cove/resources/compose/` when present (what the wheel actually ships),
plus structural rules for `compose/seeds/`.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
)

# Directory prefixes (repo-root relative) excluded from PII scanning.
# docs/ and compose/ are deliberately SCANNED (they carried the 2026-05-09
# leak); sbom/ embeds third-party upstream authors' emails in generated CycloneDX
# JSON (not operator PII); scripts/staging/ runs against a staging stack with
# synthetic credentials; .worktrees/ holds operator worktrees.
EXCLUDE_DIRS = (
    "sbom/",  # generated CycloneDX SBOMs embed third-party upstream authors' emails (not operator PII)
    ".git/", ".worktrees/", "scripts/staging/",
    "docs/troves/",  # cached third-party web snapshots (GitHub HTML with /users/<name> URLs) — not operator-authored
)

# Synthetic sentinel literals: strings whose only legitimate appearance is
# this gate's own pattern list. `<hostname>` is intentionally NOT a sentinel
# any more — it is the repo's placeholder convention.
PII_LITERALS = (
    "operator@example.com",
    "<tailscale-dns-name>",
)

# Context regexes: catch the identifying SHAPE without embedding any real
# operator value. All case-insensitive.
PII_REGEXES = (
    # Hostname family: machine-model prefix + 6-digit suffix. Deliberately
    # does NOT embed the actual leaked hostname; catches case variants and
    # future machine renames of the same family.
    ("hostname-family", r"(?i)\bmbpbk-?\d{6}\b"),
    # 1Password Vault item title carrying machine+user values. Template
    # placeholders never match (braces fall outside the segment class).
    ("vault-item-title", r"(?i)title:\s*\"?vault\s+[a-z0-9._-]+\s+[a-z0-9._-]+"),
    # macOS user home paths (>=2-char user segment; 1-char segments only appear
    # in test fixtures). Docs and configs must reference `~` instead.
    ("home-path", r"(?i)/users/[a-z0-9][a-z0-9._-]{1,}"),
    # Personal-mailbox domains (upstream SBOM emails live under sbom/, excluded).
    ("personal-email-domain", r"(?i)@(?:gmail|googlemail|icloud|outlook|hotmail|live|yahoo|protonmail|proton|fastmail|gmx|me|mac)\.(?:com|me|de|io|ch|net|org)\b"),
)

_PATTERN_NAMES = (
    [lit for lit in PII_LITERALS]
    + [name for name, _ in PII_REGEXES]
)

# Test files that legitimately reference PII patterns as test data (their own
# pattern lists). Excluded from the scan to avoid self-triggering.
_EXEMPT_FILES = {
    Path(__file__).resolve(),
    Path(__file__).parent.resolve() / "test_e2e_stateless.py",
}


def _pattern_hits(text: str) -> list[str]:
    """Return the pattern names that match `text` (pure matcher)."""
    hits = []
    for lit in PII_LITERALS:
        if lit in text:
            hits.append(lit)
    for name, rx in PII_REGEXES:
        if re.search(rx, text):
            hits.append(name)
    return hits


def _scan_targets() -> list[Path]:
    files = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    targets = []
    for rel in files:
        rel = rel.strip()
        if not rel or rel.startswith(EXCLUDE_DIRS):
            continue
        path = REPO_ROOT / rel
        if path.resolve() in _EXEMPT_FILES:
            continue
        targets.append(path)
    # Bundled wheel resources are a gitignored build artifact — but they are
    # what the wheel ships, so scan them on disk when the build ran.
    resources = REPO_ROOT / "cli" / "cove" / "resources" / "compose"
    if resources.is_dir():
        targets.extend(
            p for p in sorted(resources.rglob("*")) if p.is_file()
        )
    return targets


def test_no_pii_in_tracked_files():
    """No operator-identifying value in any tracked file or bundled resource."""
    hits = []
    for target in _scan_targets():
        try:
            text = target.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern in _pattern_hits(line):
                hits.append(f"{target.relative_to(REPO_ROOT)}:{lineno}: {pattern} :: {line.strip()}")
    assert not hits, (
        "operator-identifying patterns found in tracked files/bundled resources:\n"
        + "\n".join(hits)
    )


def test_no_rendered_seeds_tracked():
    """compose/seeds/ tracks ONLY *.example templates.

    A rendered seed re-entering the tree is exactly how the Vault UI
    credential value leaked into public history (incident 20261026-145212).
    """
    rels = subprocess.run(
        ["git", "ls-files", "compose/seeds"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    rels = [r.strip() for r in rels if r.strip()]
    assert rels, "compose/seeds must be tracked (example templates)"
    offenders = [r for r in rels if not r.endswith(".example")]
    assert not offenders, (
        "rendered (values-filled) seed files must never be tracked; ship "
        "*.example templates only. Offenders:\n" + "\n".join(offenders)
    )


def test_rendered_vault_user_seed_is_gitignored():
    """`compose/seeds/vault-user.yaml` must be ignored even after a gitignore
    regression in the */.yaml glob — it is the rendered seed path."""
    result = subprocess.run(
        ["git", "check-ignore", "-q", "compose/seeds/vault-user.yaml"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        "compose/seeds/vault-user.yaml must be gitignored (incident "
        "20261026-145212: a rendered copy of it leaked a credential value into "
        "public history)"
    )


class TestMatcherContract:
    """Failure-path: every pattern class fires on synthetic leak text and
    passes repo-safe content (placeholders, tilde paths, org/repo URLs)."""

    @pytest.mark.parametrize(
        "leak",
        [
            # Hostname family: synthetic model+number, either case.
            "machine: MBPBK-000000",
            ("machine: mbpbk000000"),
            # Vault item title with rendered machine+user values.
            ('title: "Vault mbpbk-000000 person"'),
            # Home path of a named user.
            "docs: /Users/someuser/proj",
            # Personal mailbox domain.
            "contact: a.smith@gmail.com",
            # Synthetic sentinels.
            "email: operator@example.com",
            "dns: <tailscale-dns-name>",
        ],
    )
    def test_matcher_catches_leak_text(self, leak):
        hits = _pattern_hits(leak)
        assert hits, f"leak text must be caught: {leak!r}"

    def test_leak_hits_pattern_name(self):
        assert "hostname-family" in _pattern_hits("MBPBK-000000")
        assert "vault-item-title" in _pattern_hits('title: "Vault mbpbk-000000 person"')
        assert "home-path" in _pattern_hits("docs: /Users/someuser/proj")
        assert "personal-email-domain" in _pattern_hits("contact: a.smith@gmail.com")
        assert "operator@example.com" in _pattern_hits("email: operator@example.com")
        assert "<tailscale-dns-name>" in _pattern_hits("dns: <tailscale-dns-name>")

    @pytest.mark.parametrize(
        "safe",
        [
            # Hostname placeholder convention (NOT a leak by design).
            "see /etc/resolver/cove.<hostname>",
            # Templated seed title keeps {{ }} placeholders.
            'title: "Vault {{ ansible_hostname }} {{ admin_username }}"',
            # Help-text example names (no `title:` context; not machine values).
            "cove creds vault-get 'op://Private/Vault MacBook user/password'",
            # Tilde paths, not /Users/<name>.
            "home: ~/.config/cove",
            # Org/repo URLs legitimately carry the username.
            "https://git.cove.local/<org>/<repo>/issues/51",
            # Local or synthetic mailboxes.
            "admin@cove.local",
            "editor: editor@example.com",
            # Model prefix without the numeric tail.
            "host=mbpbk",
            # 1-char fixture segment (only 2+ char segments are user-like).
            "Origin: /Users/x/compose/bringup.yml:439:7",
        ],
    )
    def test_matcher_passes_safe_text(self, safe):
        assert _pattern_hits(safe) == [], f"safe text must not match: {safe!r}"

    def test_gate_source_embeds_no_real_hostname(self):
        """Meta-guard: the gate's own source must not embed the real
        hostname digit-tail it hunts for (the 2026-05-09 regression class:
        the gate carried the PII it was pattern-matching). Synthesized
        fixture tails ("000000") are allowed; any other 6-digit tail is a
        real machine hostname."""
        source = Path(__file__).read_text(encoding="utf-8")
        tails = set(re.findall(r"(?i)mbpbk-?(\d{6})", source))
        assert tails <= {"000000", "999999"}, (
            f"real hostname digit-tail(s) embedded in the gate's own source: "
            f"{tails - {'000000', '999999'}}"
        )