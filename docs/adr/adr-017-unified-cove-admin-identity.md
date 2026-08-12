# ADR-017: Unified Cove Admin Identity

**Status:** Proposed
**Date:** 2026-08-12
**Authored-by:** deepseek-v4-flash:0731-cloud

## Context

Cove is a single-operator platform: "one owner, one identity, one admin" (PURPOSE.md). Each service that ships its own admin login has historically been provisioned with its own per-service credentials — a random username, a random password, or a per-hostname 1Password item. This fragments the operator's mental model: to log into a service they must recall which username and which password belong to which service, and on a second machine the credentials may not even match.

Speedtest Tracker surfaced the problem concretely. Its admin login requires an **email address**, not a username. The initial implementation generated a random friendly word+number username (`river31` style) per host, which (a) was not an email and would not satisfy Speedtest Tracker's login form, and (b) reintroduced the per-hostname fragmentation the shared-credential work had just removed.

Cove already has a canonical operator identity: `admin@cove.local`, the shared Cove admin email used across the platform. The operator's direction is that service admin credentials should be **friendly and shared**, not random and per-host. This ADR codifies a single unified admin identity for Cove services.

## Decision

**All Cove services that expose an admin login use a single unified admin identity:**

- **Email / username:** `admin@cove.local` — the shared Cove admin email, identical on every machine.
- **Password:** a word-based passphrase (hyphen-separated words from a small portable wordlist), generated once and shared across machines.
- **Storage:** the credentials live in a single shared 1Password item, keyed to the service's `https://<service>.cove.local/` URL (not per-hostname), so the same credentials work on all the operator's machines. The first machine seeds the item; the rest inherit it.

For Speedtest Tracker specifically, the admin email, admin password, and `SPEEDTEST_APP_KEY` are stored together in the shared 1Password item titled `Speedtest Tracker`, keyed to `https://speedtest.cove.local/`, and cached in Vault for offline use.

## Rationale

### Why a single email, not per-service usernames

Cove has one operator. A single `admin@cove.local` identity means the operator never has to remember which username belongs to which service — it is always the same. It also matches the platform's existing canonical admin email, so the identity is consistent with the rest of Cove rather than introducing a new one.

### Why a word-based passphrase, not random alphanumeric

The operator's direction is that admin credentials should be **friendly** — readable and typable — not random alphanumeric strings. A word-based passphrase (4 hyphenated words from a 23-word list ≈ 18 bits of entropy) is memorable enough to type at a login screen while still providing a meaningful entropy floor. It is generated once and shared, so the operator types it rarely.

### Why shared and URL-keyed, not per-hostname

The operator runs Cove on multiple machines. Per-hostname credentials would force a different login on each machine and require re-seeding per host. A single shared item keyed to the service URL means the first machine seeds it and every other machine inherits the same credentials — one identity, everywhere.

## Consequences

- **Speedtest Tracker admin login is `admin@cove.local`** with a word-based passphrase, stored in the shared 1Password item `Speedtest Tracker` keyed to `https://speedtest.cove.local/`, reused across machines.
- **Future Cove services with admin logins should follow the same pattern** — the unified `admin@cove.local` identity and a shared, URL-keyed 1Password item — rather than inventing per-service usernames.
- **The random friendly-username generator is removed** from the Speedtest Tracker flow; the admin identity is the fixed Cove email.
- **No per-hostname credential drift:** because the item is shared and URL-keyed, all machines present the same admin identity.

## See also

- ADR-016 — Two-Tier Service Adoption Rubric (Speedtest Tracker is a Tier 2 extended service)
- `docs/speedtest.md` — Speedtest Tracker admin identity and credential flow
- PURPOSE.md — "one owner, one identity, one admin"
