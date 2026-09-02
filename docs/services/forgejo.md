# Forgejo for Cove

Forgejo is Cove's self-hosted git forge — the single source of truth for the operator's code, PRs, issues, and CI webhooks. It runs as a core (non-profiled) Cove service, provisioned entirely by `cove up` from the bundled compose files.

## Quick Start

```shell
cove up            # provisions Forgejo along with the rest of the stack
```

The forge is accessible at `https://git.cove.local/` through Cove's nginx ingress. Registration is disabled (`FORGEJO__service__DISABLE_REGISTRATION: "true"`), sign-in is required to view anything (`REQUIRE_SIGNIN_VIEW`), and the admin identity is seeded from 1Password on first boot — there is no default `admin@example.com` account.

## Webhook delivery (`webhook.ALLOWED_HOST_LIST`)

Forgejo ships with an SSRF guard on webhook delivery: `webhook.ALLOWED_HOST_LIST`, whose upstream default is `external`. Under `external`, Forgejo refuses to deliver webhooks to any loopback or private-network (RFC1918) target — including `host.docker.internal` and the Docker bridge gateway.

That default breaks legitimate local receivers. Live `git.cove` logs showed deliveries blocked exactly this way:

```
webhook can only call allowed HTTP servers (check your webhook.ALLOWED_HOST_LIST setting)
```

Issue [#44](https://git.cove.local/cristos/cove/issues/44) tracks the fix: Cove overrides the setting explicitly instead of relying on the upstream default (IaC bias — the setting is declared in code, never hand-edited into a running container).

### Cove's default: `loopback`

`compose/docker-compose.yml` sets:

```yaml
FORGEJO__webhook__ALLOWED_HOST_LIST: ${FORGEJO_WEBHOOK_ALLOWED_HOST_LIST:-loopback}
```

`loopback` allows delivery to `127.0.0.0/8` and `::1` **as seen from the forgejo container** — the narrowest useful allowlist. It is a deliberate relaxation of the SSRF guard, acceptable because:

- **Single-tenant platform** — no untrusted users can register webhooks (registration is disabled, sign-in required).
- **HMAC-signed webhooks** — every webhook payload is signed with a per-hook secret; a receiver can verify authenticity.
- **Wildcard avoided** — `*` (allow-all) is explicitly not used; the tests in `cli/tests/test_forgejo.py` assert the default is never `*` and never empty.

### Adding a receiver host

When a webhook receiver lives outside the forgejo container's loopback (e.g. a service on the Docker bridge or a tailnet IP), widen the allowlist via the `.env` / group_vars variable:

```shell
FORGEJO_WEBHOOK_ALLOWED_HOST_LIST=loopback,<host-or-cidr>
```

Examples: `loopback,172.18.0.11`, `loopback,host.docker.internal`, `loopback,100.64.0.0/10`. The value follows Forgejo's `ALLOWED_HOST_LIST` syntax (comma-separated hosts/CIDRs; see the upstream Forgejo config cheat sheet).

Set it in `compose/group_vars/all.yml` (`forgejo_webhook_allowed_host_list`) so it renders into the compose `.env` on bringup.

### First-boot-only .env caveat

The compose `.env` is rendered **on first boot only** (`compose/bringup.yml`, "Render compose .env (first boot only)"). Changing `forgejo_webhook_allowed_host_list` in group_vars on an existing machine does **not** rewrite the existing `.env`.

Options on an existing deployment:

- Set `FORGEJO_WEBHOOK_ALLOWED_HOST_LIST` directly in the deployed `.env`, **or**
- Recreate the container and let the compose default apply:

  ```shell
  docker compose up -d forgejo
  ```

The compose-level `:-loopback` default still applies whenever the variable is absent from `.env`.

### Promote path (wheel is the source of truth)

`compose/` in this repo is **dev-time source**. The setting reaches running stacks only via the post-merge promote: sync compose resources into the wheel, build, and reinstall `cove`. After a reinstall, recreate the forgejo container so it picks up the new env:

```shell
docker compose up -d forgejo
```

Never hand-edit the deployed compose directory (`~/.config/cove/compose/`) — it is a runtime copy regenerated from the wheel.