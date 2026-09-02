# Plan: Forgejo webhook ALLOWED_HOST_LIST — explicit loopback allowlist

**Status:** Ready for sashay
**Source issue:** [cove#44](https://git.cove.local/cristos/cove/issues/44) — `forgejo: webhook.ALLOWED_HOST_LIST blocks internal/loopback webhook delivery`
**Related:** `docs/plans/forge-steward.md` (tidesman P4 — the webhook consumer this unblocks)

## Problem

Forgejo's default `webhook.ALLOWED_HOST_LIST = external` (SSRF guard) denies webhook delivery to all RFC1918 private IPs and loopback. Cove's forgejo container sets no override, so the default applies. Live `git.cove` logs confirm blocked deliveries to `host.docker.internal:9999`, `172.18.0.1:9999`, and `172.18.0.11:8799`:

```
webhook can only call allowed HTTP servers (check your webhook.ALLOWED_HOST_LIST setting)
```

Impact: tidesman (forge-steward) webhook registration would silently fail to deliver. Manual fixes to a running container are a smell — the setting must be declared in code (IaC bias).

## Change

Add an explicit, configurable allowlist to the forgejo compose env, defaulting to `loopback`:

1. **`compose/docker-compose.yml`** — forgejo service environment:
   ```yaml
   FORGEJO__webhook__ALLOWED_HOST_LIST: ${FORGEJO_WEBHOOK_ALLOWED_HOST_LIST:-loopback}
   ```
2. **`compose/group_vars/all.yml`** — new var: `forgejo_webhook_allowed_host_list: "loopback"` (near the other forgejo vars).
3. **`compose/bringup.yml`** — .env render block gains:
   `FORGEJO_WEBHOOK_ALLOWED_HOST_LIST={{ forgejo_webhook_allowed_host_list | default('loopback') }}`
   (Existing deployments have first-boot-only .env; the compose `:-loopback` default still applies on recreate — note this in docs.)
4. **`docs/services/forgejo.md`** (new) — Forgejo service doc with a **Webhook delivery** section: what the setting does, the `external` default and why we override it, how to add a receiver host/CIDR (`loopback,<host-or-cidr>`), security posture (HMAC-signed webhooks, single-tenant, loopback-scoped), and the first-boot-only .env caveat (`docker compose up -d forgejo` recreates with the new value).
5. **`cli/tests/test_forgejo.py`** (new, mirrors `test_litellm.py` style):
   - compose: forgejo service env has `FORGEJO__webhook__ALLOWED_HOST_LIST` with default `loopback` (and never `*`)
   - bringup: .env render includes `FORGEJO_WEBHOOK_ALLOWED_HOST_LIST=`
   - group_vars: `forgejo_webhook_allowed_host_list` defaults to `loopback`
   - adversarial: wildcard `*` and empty value rejected/absent by construction
6. **`docs/test-coverage-matrix.yaml`** — rows:
   - `forgejo webhook ALLOWED_HOST_LIST compose default (loopback)` — blast medium, happy/sad executable
   - `bringup .env includes FORGEJO_WEBHOOK_ALLOWED_HOST_LIST` — blast medium, happy/sad executable
7. **`CHANGELOG.md`** — entry under Unreleased/Added.

## Non-goals

- No tidesman wiring (that's forge-steward P4; its receiver host/CIDR is configured then).
- No change to Forgejo image/version.
- No live webhook delivery E2E (no receiver exists yet; unit-level compose assertions + docs only — delivery itself is covered when tidesman lands).

## Security notes

- `loopback` is a deliberate relaxation of the SSRF guard scoped to 127.0.0.0/8 + ::1 as seen *from the forgejo container* (its own loopback). Acceptable: single-tenant local platform, webhooks are HMAC-secret-signed, no untrusted users can register webhooks (registration disabled).
- Wildcard `*` is explicitly avoided; the default is the narrowest useful allowlist. Operators widen per-receiver via the documented env var.

## Acceptance

- `uv run --directory cli pytest -x -q -m "not e2e and not staging"` green.
- Compose config renders with the new env var (`docker compose config` or YAML parse in tests).
- Coverage matrix + docs + CHANGELOG updated.