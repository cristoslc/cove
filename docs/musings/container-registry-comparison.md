# Container Registry: GHCR vs. Cove-Hosted vs. Public Infra

## Landscape

| Registry | Storage Cost | Pull Limits | Auth Model | Offline-Capable | Notes |
|----------|-------------|-------------|------------|-----------------|-------|
| **GHCR** | Free (for now) | None | GitHub PAT / GITHUB_TOKEN | No | 30-day notice before billing starts. Unclear pricing when it does — likely $0.25/GB storage, $0.50/GB egress. |
| **Docker Hub** | Free tier: 1 private repo | 100 pulls/hr (anon), 200/6hr (free auth) | Docker ID + PAT | No | Pro $9/mo removes rate limits. Team $15/user/mo. Business $24/user/mo. |
| **AWS ECR** | $0.10/GB-mo | None (regional) | IAM | No | In-region egress free (EC2/ECS/EKS). Cross-region at internet data-transfer rates. NAT Gateway adds $0.045/GB. 500MB free-tier private, 50GB free public. |
| **Forgejo OCI Registry** | Local disk only | None | Forgejo PAT / GITHUB_TOKEN | Partial | Forgejo's built-in `/v2/` registry. No separate `registry:2` container. Storage in Forgejo data dir. |

## Key Insights

1. **GHCR is a ticking clock.** It's free only because GitHub hasn't flipped the billing switch. When it does, any serious image volume becomes expensive fast (10TB = ~$2,400+/mo at standard Packages rates). Cove's constraint of no internet dependencies during builds/CI makes GHCR unusable as a primary registry for pipeline artifacts anyway.

2. **The cove registry's primary value isn't cost — it's offline autonomy.** Cove's design constraint (no internet during builds/CI) means Woodpecker runners (Kaniko, buildx) must push to a local registry, and k3s must pull from a local mirror. Public registries are useful only for seed images at `cove up` time.

3. **Seed images get cached in Forgejo.** `cove up` pulls Forgejo from `codeberg.org` and Vault from Docker Hub. These can be pushed into Forgejo's OCI registry after first pull for offline availability.

4. **ECR is the closest analogue to what cove wants locally.** In-region pulls are free, storage is cheap. But it's still a cloud dependency, requires AWS creds, and crosses the "no internet" boundary. The cove registry replicates ECR's local-pull efficiency without the cloud tax.

5. **Multi-architecture and layer deduplication matter.** ECR added cross-repo blob mounting in Jan 2026. Docker Registry v2 supports it natively. GHCR deduplicates within namespaces. Cove's registry gets this for free via upstream `distribution/distribution`.

6. **The real risk with GHCR is lock-in.** If Woodpecker pipelines push to GHCR, and GHCR starts billing or has an outage, all CI/CD is blocked. Cove's design pushes to `forgejo.cove.local/v2/` instead — zero external dependency for the build-deploy loop.

## Recommendation for Cove

| Function | Target | Rationale |
|----------|--------|-----------|
| Build artifacts (Kaniko output) | `forgejo.cove.local/v2/<owner>/<name>:<tag>` | Forgejo's built-in registry; no extra service |
| Seed images (Forgejo, Vault, etc.) | External registry → Forgejo | Pull once at setup, push to Forgejo |
| CI pipeline pushes | `forgejo.cove.local/v2/` (via GITHUB_TOKEN) | Same auth model as GHCR, tied to project |
| Remote deploy pull | `forgejo.cove.local/v2/` (via Forgejo PAT) | Hetzner boxes authenticate with Forgejo credentials |
| Public distribution | GHCR or Docker Hub | Only if sharing outside Cove's private network |

## Can Forgejo Replace a Separate Registry Container?

Forgejo ships a built-in OCI-compatible container registry at `/v2/` on the Forgejo domain. A standalone `registry:2` is not needed within Cove's scope. Forgejo handles: build pushes (Woodpecker via `GITHUB_TOKEN`), authenticated pulls from remote deploy targets (Hetzner via Forgejo PAT), and project-scoped permissions.

The only use case Forgejo's registry doesn't cover is **containerd mirror functionality** — transparently caching upstream images (`alpine`, `node`, etc.) on first pull. Forgejo doesn't speak the pull-through proxy protocol. If this becomes necessary, a standalone `registry:2` can be added alongside Forgejo.

**Decision: Forgejo's built-in OCI registry is the default.** Consumer projects (e.g., Homelab) deploy their own registries if required.

## Simplified Recommendation for Cove (Private Network)

| Function | Target | Auth |
|----------|--------|------|
| Woodpecker CI push | `forgejo.cove.local/v2/<owner>/<image>` | GITHUB_TOKEN |
| Remote deploy pull (Hetzner, etc.) | `forgejo.cove.local/v2/<owner>/<image>` | Forgejo PAT / deploy key |
| Upstream cache | Forgejo (push pulled images explicitly) | Forgejo auth |
| Public distribution | GHCR or Docker Hub | Standard auth |

**Decision: Forgejo's built-in OCI registry is the sole container registry within Cove's scope.** No separate `registry:2` container. Consumer projects (e.g., Homelab) deploy their own registries if needed. Forgejo replaces GHCR for all Cove-internal image distribution.