# Plan: `cove.local` Landing Page

## Motivation

Currently `cove.local` and `cove` are nginx aliases for Forgejo. Typing `cove.local` in the browser should show a landing page — a dashboard/portal with links to all Cove services, status, and documentation.

## Scope

- `cove.local` and `cove` get their own nginx server block serving a static landing page
- Remove them from the Forgejo server block's `server_name`
- Landing page is a simple HTML file served by nginx (no backend dependency)
- Page includes: service links (Forgejo, Vault, LiteLLM), status indicators, config page link, CA download

## Implementation

1. **Create landing page HTML** at `compose/nginx/landing.html` — a static page with service cards
2. **Add nginx server block** for `cove.local` and `cove` that serves the landing page
3. **Remove** `cove` and `cove.local` from the Forgejo server block's `server_name`
4. **Update tests** — assertions that check `cove`/`cove.local` in Forgejo server block
5. **Update cert validation** in `bringup.yml` — `cove` and `cove.local` are still valid SANs (used by the landing page server block)

## Key decisions

- Static HTML served by nginx — no backend, no rendering pipeline, zero dependencies
- Page is minimal but functional: service name, URL, status (up/down via JS fetch to hc.cove.local)
- Dark theme to match Cove's aesthetic
- Responsive for mobile config page access
