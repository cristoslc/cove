---
type: checkpoint
timestamp: 2026-09-25T010326
responding-to: plan spike 2 — WebSocket + auth behavior behind nginx for the bb web client
---

## Spike 2 — web client uses WebSockets; direct-URL mode carries NO auth

**Responding to:** the plan's Spike 2, which asks whether the bb web client survives a reverse proxy and what auth direct-URL mode carries.

**WebSocket: confirmed, standard upgrade headers required.** The bb web app opens a browser `WebSocket` for its realtime channel (the app bundle constructs `new WebSocket(...)` for the realtime connection). Probing the server, `/internal/ws` is the internal websocket endpoint and returns `HTTP/1.1 401 Unauthorized` without a token (the host-daemon credential), while the browser-facing realtime path is part of the public API. nginx therefore needs `proxy_http_version 1.1`, `proxy_set_header Upgrade $http_upgrade`, `Connection $connection_upgrade` (a `map`), and no response buffering — the same shape any websocket reverse proxy uses. No special cookie or subprotocol negotiation is required.

**Auth: direct-URL mode is fully unauthenticated.** The authoritative bb doc (`docs/multiple-devices.md`) states it plainly:

> For compatibility only, `npx bb-app --server-bind-host 0.0.0.0` restores direct IPv4 network access. The public API is unauthenticated and permits command execution and file reads, so use wildcard binding only behind a trusted network boundary and never through Funnel or the public internet.

Verified live: an unauthenticated `GET /api/v1/plugins` returned real JSON data with no credentials or cookies. Requests to unknown paths return the SPA HTML shell. So `ade.cove` gives anyone who can reach the Cove ingress full command-execution and file-read access to the ADE — equivalent to the trust boundary Cove already places on its own network (nginx ingress, Forgejo, Vault). The plan's contingency ("if it carries none, ade.cove needs an auth decision before it is exposed beyond loopback") is answered: it carries none. ADR-018 already accepts Direct URL mode over `ade.cove`; the network boundary is the Cove host itself. This is recorded, not improvised.

**Commits in this unit:** <pending — committed together with Spike 1 entry>.
