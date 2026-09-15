**Responding to:** PR-level code review (step 8), four specialist lenses (security, logic, style, docs)

Review verdict: **needs_changes** — 0 critical, 5 high, 9 medium, 13 low.

**High findings (must fix):**
1. provision_forgejo.yml register task missing `no_log: true` — registration token leaks to logs/ps
2. `FORGEJO_RUNNER_DATA_ROOT` first-boot-only .env gap → re-registration every `cove up` on existing installs (compose fallback `/data` is a VM path). Fix: `${COVE_DATA_ROOT}/forgejo-runner:/data`
3. Dead copy-pasted helpers `_compose_dir/_compose_env_path/_upsert_env` in runner.py (never called)
4. Doc admin runners URL has bogus `/-/` prefix (GitLab-ism)
5. Mermaid edge reversed (Forgejo does not poll the runner)

**Medium (address):** docker-socket blast radius undocumented (no hardened/NOT table), hardcoded container name ignores override, pages mount inert without `valid_volumes` config, `cove runner status/logs` never target the service (empty output), user-level vs admin registration-token endpoint mislabeled, Quick Start two-step flow under-specified, missing README/AGENTS/CHANGELOG index entries, trailing newlines, conftest timeout change flagged as unrelated (rationale documented in chronicle 0002; kept deliberately).

Low findings recorded in review; will fix the quick wins (undefined var, changed_when, duplicate test) alongside highs.