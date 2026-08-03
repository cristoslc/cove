# Fix `cove litellm up` for Docker Compose v5

## Context

Docker Compose v5.3.1 (Docker 29.6.2) removed the singular `--profile` flag
from `docker compose up`. `cli/cove/litellm.py:32` still calls
`up -d --profile litellm`, so `cove litellm up` fails with
`unknown flag: --profile`.

Compose v5 activates profiles via the `COMPOSE_PROFILES` environment variable:

```
COMPOSE_PROFILES=litellm docker compose up -d
```

## Change

1. In `cli/cove/litellm.py`, replace `--profile litellm` with the
   `COMPOSE_PROFILES` env var approach for the `up` command. Prefer passing
   the env var through `subprocess.run(..., env=...)` so it applies to the
   compose invocation without leaking into the parent shell.
2. Update `cli/tests/test_litellm.py::TestLitellmCommands::test_litellm_up_uses_profile_flag`
   to assert the new mechanism (e.g., `COMPOSE_PROFILES` in the source, or
   that `up` no longer passes `--profile` while still gating to the litellm
   profile). The test must fail against the current code (red) and pass after
   the fix (green).
3. Verify `cove litellm down` still uses `stop` (unchanged) and that no core
   Cove services are started by `cove litellm up` — only litellm, litellm-db,
   and headroom (the `litellm` profile).

## Acceptance criteria

- `cove litellm up` starts litellm, litellm-db, and headroom without starting
  core services.
- `cove litellm down` stops litellm and headroom (via `stop`).
- Unit tests pass: `uv run --directory cli pytest -x -q -m "not e2e and not staging"`.
- Existing coverage matrix in `docs/test-coverage-matrix.yaml` updated for any
  changed paths.

## Non-goals

- Not changing LiteLLM's memory footprint or config (separate topic, see
  `docs/tech-debt/cove-litellm-compose-profile-flag.md`).
- Not touching compose service definitions or the `profiles: ["litellm"]`
  keys themselves.
