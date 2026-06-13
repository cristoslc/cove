# ADR-014: Nginx as Sole Ingress Controller

**Status:** Accepted
**Date:** 2026-06-11
**Authored-by:** deepseek-v4-pro:cloud
**Supersedes:** ADR-013 (tailscale serve approach)
**Trove:** `reverse-proxy-alternatives@b1e3e2e`

## Context

Cove's service exposure model needs a single ingress controller. All services (forgejo, vault, pages) must be accessible through `*.cove` subdomains with TLS termination. No service should publish a host port directly — only the ingress controller binds to host ports.

We evaluated five alternatives: nginx, HAProxy, Caddy, Traefik, and Envoy. The trove `reverse-proxy-alternatives` collected five sources comparing these proxies across performance, configuration complexity, TLS automation, Docker integration, and protocol support.

## Decision

**Use nginx as the sole ingress controller.** No migration to HAProxy, Caddy, Traefik, or Envoy.

## Rationale

### 1. nginx is already deployed and working

Cove's compose stack already runs nginx with a Jinja2-rendered config. The existing template handles TLS termination, subdomain routing, and pages hosting. Replacing it would be a net-negative migration — new config format, new Docker image, new templates, new operational knowledge — for no functional gain.

### 2. nginx's `stream` module handles TCP/UDP proxying

A key finding from the trove: nginx's open-source build includes the `stream` module for L4 TCP/UDP proxying. This means nginx can proxy SSH traffic (`git@git.cove` → forgejo:2222) and future UDP services (TURN relays, QUIC) without needing HAProxy. The `stream` block coexists with `http` blocks in the same config file.

### 3. Auto-HTTPS is irrelevant for Cove

Caddy and Traefik's primary advantage over nginx is automatic Let's Encrypt certificate management. Cove uses mkcert for locally-trusted certificates — no ACME challenge, no public DNS validation, no internet dependency. This neutralizes the headline feature of both alternatives.

### 4. Dynamic service discovery is overkill

Traefik's Docker label-based auto-discovery targets environments where services are created and destroyed frequently (Kubernetes, CI/CD pipelines). Cove's service set is static — forgejo, vault, nginx, dnsmasq. A static nginx config rendered from a Jinja2 template is simpler, more debuggable, and version-controllable.

### 5. Envoy is dramatically overkill

Envoy targets service mesh architectures with 50+ microservices, dynamic xDS configuration, and distributed tracing. Its resource footprint (~150MB idle memory) and operational complexity make it unsuitable for a single-machine developer platform.

### 6. HAProxy's strengths don't align with Cove's needs

HAProxy excels at high-throughput L4/L7 load balancing with sophisticated health checks and sticky sessions. Cove doesn't load-balance across multiple backends — each service has a single instance. HAProxy's lack of static file serving, manual TLS setup, and separate config language add friction without benefit. It remains a fallback only if nginx's `stream` module proves insufficient for TCP proxying.

### 7. Performance is a non-factor

All five proxies handle homelab-scale traffic without perceptible differences. Performance only matters above ~10,000 req/s on a single node. Cove serves a single developer with fewer than 10 services.

## Consequences

### Positive

- No migration effort — nginx stays, config evolves incrementally.
- `stream` module provides a path to SSH proxying through the ingress controller, enabling `git@git.cove` without a separate SSH port mapping.
- Static Jinja2-rendered config is version-controllable and debuggable with `nginx -t`.
- Single binary handles TLS termination, HTTP routing, static pages, and TCP/UDP proxying.

### Negative

- nginx's `stream` module requires a separate port binding for TCP traffic (cannot multiplex HTTP and TCP on the same port via SNI). SSH proxying through nginx would need a dedicated port (e.g., port 22 on the host proxied to forgejo:22).
- No automatic service discovery — new services require template updates and a config reload. Acceptable given Cove's static service set.
- Observability is basic out of the box (stub_status module). Acceptable for a single-machine platform.

### Neutral

- HTTP/3 support is mature in nginx 1.25+ but not currently needed for Cove's local-only TLS model.
- nginx's config verbosity is higher than Caddy's but lower than Envoy's. The Jinja2 template abstracts most boilerplate.

## Alternatives Considered

| Alternative | Verdict | Reason |
|-------------|---------|--------|
| HAProxy | Fallback only | Overkill for single-instance services; no static file serving; manual TLS. Only considered if nginx `stream` proves insufficient. |
| Caddy | Rejected | Auto-HTTPS irrelevant (mkcert); smaller ecosystem; Docker integration requires plugin. |
| Traefik | Rejected | Dynamic discovery overkill for static services; verbose label syntax; Docker socket access concern. |
| Envoy | Rejected | Service mesh tooling; 150MB idle memory; dramatic overkill for single-machine platform. |
