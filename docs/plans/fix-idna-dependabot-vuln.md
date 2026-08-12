# Plan: Fix idna Dependabot vulnerability

> **Source:** `docs/musings/idna-dependabot-vuln.md`
>
> **Status:** Plan — ready for sashay (not yet started).

## Context

Cove 0.4.0's GitHub release surfaced a Dependabot alert: **idna** (`< 3.15`, moderate, CVSS 5.3, GHSA-65pc-fj4g-8rjx) in `cli/uv.lock`. `idna` is a transitive dependency via `requests`. The fix is a bump to `3.15`+.

## Scope

Bump `idna` to `>=3.15` in the lock, verify tests, rebuild + reinstall the `cove` wheel (the CLI is the single source of truth — a dependency change requires reinstall to propagate), and re-release 0.4.1 (or 0.4.0 patch) to GitHub.

## Behavior Contracts (BDD — drive test design)

### FC-1: idna resolved to a patched version
```
Feature: idna is patched
  Scenario: lock resolves idna >= 3.15
    Given the cove CLI project
    Then cli/uv.lock resolves idna to a version >= 3.15

  Scenario: Dependabot alert can be dismissed as fixed
    When the fix is pushed to GitHub main
    Then the idna alert on cli/uv.lock is resolved (auto-closed by Dependabot)
```

### FC-2: regression guard
```
Feature: idna cannot regress below the patched floor
  Scenario: idna has an explicit minimum
    Then cli/pyproject.toml pins idna >= 3.15 (or an equivalent direct constraint)
```

## Test Plan

- **T0-1** — assert `cli/uv.lock` resolves `idna` to `>=3.15` (parse lock).
- **T0-2** — assert `cli/pyproject.toml` has an explicit `idna>=3.15` constraint (or equivalent), so Dependabot/uv can't regress below the floor.
- Full tier-0 suite must pass: `uv run --directory cli pytest -x -q -m "not e2e and not staging"`.

## Implementation

1. **Bump idna** — add `idna>=3.15` to `cli/pyproject.toml` dependencies (direct, explicit floor) and run `uv lock` so `cli/uv.lock` resolves `idna` to `3.15`+ (likely `3.18` latest).
2. **Verify** — confirm `cli/uv.lock` has `idna >= 3.15`; run the test gate.
3. **Release** — bump version to `0.4.1` (patch), add CHANGELOG entry, build wheel, reinstall local `cove`, tag `v0.4.1`, push to `fjl` + `github`, create GitHub release + upload wheel.
4. **Dependabot** — confirm the alert auto-closes on push (or dismiss as fixed if not).

## Compliance

- Test command: `uv run --directory cli pytest -x -q -m "not e2e and not staging"`.
- Release flow: per AGENTS.md (cove CLI is the single source of truth; reinstall to propagate).

## Acceptance criteria

1. `cli/uv.lock` resolves `idna` to `>=3.15`.
2. `cli/pyproject.toml` has an explicit `idna>=3.15` (or equivalent) constraint.
3. Full tier-0 suite passes.
4. Wheel rebuilt + `cove` reinstalled; installed tool reports the patched version.
5. GitHub `v0.4.1` (or patch) release created with wheel; Dependabot idna alert resolved.
