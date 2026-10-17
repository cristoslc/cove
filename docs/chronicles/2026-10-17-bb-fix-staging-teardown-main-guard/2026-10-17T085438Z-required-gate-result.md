# Required gate result — 2026-10-17 08:54:38 UTC

Per operator request: the required Cove gate passed in the isolated follow-up worktree: `uv run --directory cli pytest -x -q -m "not e2e and not staging"` → 777 passed, 31 deselected, 5 warnings, in 46.91s. No E2E or staging run was performed. The branch remains a test-only correction with explicit coverage that the overlap guard runs from a controlled non-main branch and the production-branch refusal still works.
