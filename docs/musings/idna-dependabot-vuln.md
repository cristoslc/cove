# Musing: Fix idna Dependabot vulnerability

> **Status:** Musing — captured from the 0.4.0 release. Not yet started.

## The issue

When Cove 0.4.0 was released to GitHub (`cristoslc/cove`), Dependabot flagged **one moderate vulnerability**:

- **Alert #1** — `idna` (pip, in `cli/uv.lock`)
- **GHSA-65pc-fj4g-8rjx** — IDNA: specially crafted inputs to `idna.encode()` can bypass the CVE-2024-3651 fix
- **CVSS 5.3** (moderate)
- **Vulnerable range:** `< 3.15`
- **Patched:** `3.15`

`idna` is a **transitive** dependency — pulled in via `requests` (which is a direct dependency of the `cove` CLI). It is not pinned in `cli/pyproject.toml`.

## Version state (a wrinkle)

- `cli/uv.lock` resolves `idna` to **3.13** (still vulnerable; `< 3.15`).
- `pip index versions idna` reports **3.15, 3.16, 3.17, 3.18** available, so the fix is `3.15`+.
- The venv reported `3.11` in one probe but `3.13` in another — the lock is authoritative at `3.13`. Worth confirming the exact resolved version during the fix.

## Why it matters

`idna.encode()` is used for Internationalized Domain Name handling. The CLI is `localhost`-first and reaches `*.cove` domains, but the vulnerability is in the **dependency** `requests` uses for domain encoding — a crafted IDN could trigger it. Low practical exposure for a local tool, but a released wheel on a public GitHub repo should not carry a known moderate CVE in a dependency. Fixing it is cheap (bump the lock).

## Proposed fix

Bump `idna` to `>=3.15` in the lock. Since it's transitive, the cleanest path:

1. Update `cli/uv.lock` so `idna` resolves to `3.15`+ (e.g. `uv lock` / `uv add idna` as a direct dep, or bump the lock resolution).
2. Run the test gate (`uv run --directory cli pytest -x -q -m "not e2e and not staging"`).
3. Rebuild the wheel + reinstall `cove` (the CLI is the single source of truth — a dependency bump requires a reinstall to propagate).
4. Optionally add an explicit `idna` minimum constraint so Dependabot can't regress it.

## Notes / deferred

- Decide whether to pin `idna>=3.15` explicitly in `cli/pyproject.toml` (guards against regression) or rely on lock resolution alone.
- The other Dependabot state: only the one moderate alert exists; no others.
