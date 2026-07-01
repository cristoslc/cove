# Jam Session: Tailscale serve conditional in bringup.yml

**Date:** 2026-06-30
**Branch:** `main` (trunk, no worktree)
**Status:** Fixed

## The bug

`cove up` failed on the "Configure tailscale serve for HTTPS on port 443" task with `Tailscale is stopped.` even though Tailscale was installed but not running.

## Root cause

`tailscale status --json` exits 0 even when Tailscale's `BackendState` is `"Stopped"`. The `when` condition on the serve task was:

```yaml
when: "ts_status.rc == 0 and not (cove_skip_tailscale_serve | default(false))"
```

This passed because `rc == 0` was true. But `tailscale serve status --json` then failed because the daemon wasn't actually running.

The JSON output still has `Self.TailscaleIPs` populated (persisted from last session), so checking IPs wasn't sufficient either.

## The fix

Use `Self.Online` (a boolean that's `false` when Tailscale is stopped):

```yaml
when: "ts_status.rc == 0 and (ts_status.stdout | default('{}') | from_json).Self.Online"
```

Also updated the IP fallback task to use `Self.Online` instead of `TailscaleIPs | length > 0` for consistency.

## Bonus bug: Vault addr resolution

After fixing the tailscale skip, `bootstrap_vault.yml` failed waiting for Vault. Root cause: `vault_addr` was `https://vault.cove` which resolves to `127.0.0.1:443` via `/etc/hosts`, but nginx is on `8443`. The pf 443→8443 forward needs sudo (not available with `--no-sudo`).

`bringup.yml` already used `127.0.0.1:8443` + `Host` header for its Vault health check, but `bootstrap_vault.yml`, `provision_vault_user.yml`, and `provision_forgejo.yml` all used `vault_addr` directly without the `Host` header.

### Fix

Changed `vault_addr` in `group_vars/all.yml` from `https://vault.cove` to `https://127.0.0.1:{{ nginx_https_port }}`, and added `Host: vault.cove` header to every `uri` call across all three playbooks.

## Bonus bug 2: Forgejo API calls via hostname

Same pattern — `provision_forgejo.yml` and `provision_pages.yml` used `forgejo_root_url` (`https://git.cove/`) for API calls, hitting `127.0.0.1:443` instead of `8443`.

### Fix

Added `forgejo_api_url: "https://127.0.0.1:{{ nginx_https_port }}/"` to `group_vars/all.yml`. Replaced `forgejo_root_url` with `forgejo_api_url` + `Host: git.cove` header on all API `uri` calls in `provision_forgejo.yml` (6 calls) and `provision_pages.yml` (6 calls). Kept `forgejo_root_url` for Forgejo's own `app_url` config and display-only summary lines.

## Files changed

- `compose/bringup.yml` — two `when` conditions updated
- `compose/group_vars/all.yml` — `vault_addr` changed to loopback + port; added `forgejo_api_url`
- `compose/bootstrap_vault.yml` — `Host` header on all 5 `uri` calls
- `compose/provision_vault_user.yml` — `Host` header on all 5 `uri` calls
- `compose/provision_forgejo.yml` — `Host` header on 7 `uri` calls, `forgejo_root_url` → `forgejo_api_url`
- `compose/provision_pages.yml` — `Host` header on 6 `uri` calls, `forgejo_root_url` → `forgejo_api_url`

## Verification

`cove up --no-sudo` completed end-to-end: bringup (34 ok, 2 skipped), vault bootstrap (13 ok, 11 skipped), vault user provision (12 ok, 4 skipped), forgejo provision (24 ok, 7 skipped). All services healthy.
