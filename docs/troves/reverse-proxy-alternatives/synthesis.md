# Synthesis: Reverse Proxy Alternatives for Cove

**Trove:** `reverse-proxy-alternatives`
**Date:** 2026-06-11

## Key Findings

### 1. Performance is irrelevant at Cove's scale

All five proxies (HAProxy, Nginx, Caddy, Traefik, Envoy) handle homelab-scale traffic without perceptible differences. Performance only matters above ~10k req/s on a single node (hostim-showdown). Cove serves a single developer with <10 services — throughput is a non-factor.

### 2. Nginx CAN proxy TCP (including SSH)

A critical finding: nginx's `stream` module provides L4 TCP/UDP proxying. This means nginx can proxy SSH traffic — `git@git.cove` could route through nginx to forgejo's SSH port without needing HAProxy. The `stream` block works alongside `http` blocks in the same nginx config (homelab-comparison notes NPM's stream proxying for game servers; nginx docs confirm the module is in the open-source build).

### 3. Auto-HTTPS is not a differentiator for Cove

Caddy and Traefik's headline feature is automatic Let's Encrypt certificate management. Cove uses mkcert for locally-trusted certificates — no ACME challenge needed. This neutralizes the primary advantage of Caddy and Traefik over nginx for Cove's use case.

### 4. Dynamic service discovery is overkill

Traefik's Docker label-based auto-discovery shines when services come and go frequently (Kubernetes, CI/CD pipelines). Cove's service set is static — forgejo, vault, nginx, dnsmasq. Static nginx config rendered from a Jinja2 template is simpler and more debuggable.

### 5. Envoy is dramatically overkill

Envoy targets service mesh architectures with 50+ microservices, dynamic xDS configuration, and distributed tracing. Its resource footprint (~150MB idle) and operational complexity make it unsuitable for a single-machine developer platform (edgeservers-nginx-haproxy-envoy).

### 6. HAProxy's strengths don't align with Cove's needs

HAProxy excels at high-throughput L4/L7 load balancing with sophisticated health checks and sticky sessions. Cove doesn't load-balance across multiple backends — each service has a single instance. HAProxy's lack of static file serving and manual TLS setup add friction without benefit.

## Points of Agreement

All sources converge on:

- **Nginx is the safe default** for general-purpose reverse proxying. It has the largest ecosystem, most tutorials, and widest deployment (hostim-showdown, bigmike-comparison, edgeservers-nginx-haproxy-envoy, homelab-comparison).
- **HAProxy is the performance king** for pure load balancing, but not a web server (all sources).
- **Caddy wins on config simplicity**, especially for small static setups (hostim-showdown, homelab-comparison).
- **Traefik wins in container-native dynamic environments** (all sources).
- **Envoy is for service mesh**, not standalone reverse proxying (edgeservers-nginx-haproxy-envoy, onidel-benchmark).

## Points of Disagreement

- **Caddy vs Traefik for Docker Compose:** hostim-showdown says Caddy for 1-3 static services, Traefik for 10+. homelab-comparison says Traefik's label syntax is verbose and error-prone, Caddy's Caddyfile is simpler. Both agree Caddy is simpler for small setups.
- **HAProxy HTTP/3 readiness:** edgeservers-nginx-haproxy-envoy says it's still experimental in early 2026. onidel-benchmark says plans are in development. Nginx has the most mature HTTP/3 implementation.

## Gaps

- None of the sources cover mkcert-based local TLS (all assume Let's Encrypt or manual certbot).
- No source evaluates proxies specifically for offline-first local development platforms.
- TCP proxying capabilities are mentioned in passing but not deeply compared across all candidates.

## Recommendation for Cove

**Stay with nginx.** It is already deployed and working. The `stream` module provides a path to SSH proxying (`git@git.cove`) if needed — no migration to HAProxy required. Cove's static service set, mkcert TLS model, and offline-first constraints make nginx the right fit. The alternatives offer features Cove doesn't need (auto-HTTPS, dynamic discovery, service mesh) at the cost of complexity, resource usage, or ecosystem unfamiliarity.

If SSH proxying through nginx's `stream` module proves insufficient, HAProxy is the fallback — but only for the TCP layer, with nginx retained for HTTP.
