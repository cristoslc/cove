# Registry Consolidation: Forgejo OCI Registry Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the planned standalone `registry:2` container with Forgejo's built-in OCI registry as the sole container image registry within Cove's scope.

**Architecture:** Forgejo ships an OCI-compatible container registry at `/v2/` on its domain. Woodpecker pipelines push images via `GITHUB_TOKEN`. Remote deploy targets (Hetzner, etc.) authenticate with Forgejo PATs. No separate `registry:2` container, no containerd mirror config, no `registry.cove.local` DNS entry within Cove. Consumer projects (e.g., Homelab) handle their own registry needs outside Cove's scope.

**Tech Stack:** Forgejo (OCI registry), Woodpecker/Forgejo Actions (CI auth), Ansible (provisioning)

---

## Chunk 1: Documentation Updates

### Task 1: Update `docs/abstractions.md` — Registry Context

**File:** `docs/abstractions.md:32-36`

Remove the phrase "in the local registry" which implies a separate service. Reference Forgejo's registry as the implementation vehicle. Update the Image definition to point at OCI artifacts stored in Forgejo.

- [ ] **Step 1: Read the file**

- [ ] **Step 2: Edit Registry Context section**

Current:
```
## Registry Context

### Image

A built container, stored as an OCI artifact in the local registry. Images are what pipelines produce when the build target is a Dockerfile. They are identified by `<name>:<tag>` and serve as the input to container deployments. The registry caches both locally built and externally pulled images, making them available offline.
```

New:
```
## Registry Context

### Image

A built container, stored as an OCI artifact in Forgejo's container registry. Images are what pipelines produce when the build target is a Dockerfile. They are identified by `<owner>/<name>:<tag>` and pushed to `forgejo.cove.local/v2/`. They serve as the input to container deployments. Forgejo's registry stores both locally built and externally pulled images, making them available to authenticated consumers.
```

- [ ] **Step 3: Verify edit applied**

---

### Task 2: Update `docs/architecture.md` — Registry Context + Future Section

**File:** `docs/architecture.md`

Three changes:

- [x] **Step 1: Read the file** (already read)

- [ ] **Step 2: Update Registry Context table** (lines 100-109)

Old:
```
| Aspect | Detail |
|--------|--------|
| Language | image, tag, layer, pull, push, cache |
| Storage | Docker Registry (on-disk, `~/Documents/cove-data/registry/`) |
| Entry point | `registry.cove.local` |
| Implementation | Docker Registry Deployment (future) |
```

New:
```
| Aspect | Detail |
|--------|--------|
| Language | image, tag, layer, pull, push, cache |
| Storage | Forgejo data directory (`~/Documents/cove-data/forgejo/`) |
| Entry point | `forgejo.cove.local/v2/` |
| Implementation | Forgejo built-in OCI registry |
```

- [ ] **Step 3: Update Container Registry (future) section** (lines 179-181)

Old:
```
### Container Registry (future)

A local Docker Registry deployment caching pulled images and Kaniko build outputs, configured as a containerd mirror for fully offline operation.
```

New:
```
### Container Registry (future)

The Registry context is implemented by Forgejo's built-in OCI-compatible container registry at the `/v2/` path. Woodpecker pipelines push images using `GITHUB_TOKEN` scoped to the project. Remote deploy targets authenticate with Forgejo PATs. A standalone `registry:2` container is not needed within Cove's scope — consumer projects (e.g., Homelab) deploy their own registries if required.
```

- [ ] **Step 4a: Update Forgejo annotation in topology diagram** (line 303)

Old:
```
│       │   ├── forgejo (StatefulSet)
```

New:
```
│       │   ├── forgejo (StatefulSet)          # Git + CI + OCI registry
```

- [ ] **Step 4b: Remove registry line from topology diagram** (line 306)

Old:
```
│       │   ├── registry (Deployment)
```

New: (delete the line)

---

### Task 3: Update `docs/epic/Proposed/(EPIC-001)-Cove-Platform-Core/(EPIC-001)-Cove-Platform-Core.md`

**File:** `docs/epic/Proposed/(EPIC-001)-Cove-Platform-Core/(EPIC-001)-Cove-Platform-Core.md`

- [ ] **Step 1: Read the file** around line 39

- [ ] **Step 2: Update the scope bullet**

Old:
```
- Local image registry (Harbor-like via Docker Registry)
```

New:
```
- Local image registry (Forgejo built-in OCI registry)
```

---

### Task 4: Update `docs/spec/Proposed/(SPEC-001)-Cove-Binary-CLI/(SPEC-001)-Cove-Binary-CLI.md`

**File:** `docs/spec/Proposed/(SPEC-001)-Cove-Binary-CLI/(SPEC-001)-Cove-Binary-CLI.md`

- [ ] **Step 1: Read around line 58**

- [ ] **Step 2: Update the push target**

Old:
```
- Pushes image to local registry (`localhost:5000/<name>:<tag>`).
```

New:
```
- Pushes image to Forgejo's OCI registry (`forgejo.cove.local/v2/<owner>/<name>:<tag>`).
```

Also update line 96 if the acceptance criteria mention `localhost:5000`:

Old:
```
| Build via Kaniko | `cove build .` produces image in local registry | Pass |
```

New:
```
| Build via Kaniko | `cove build .` produces image in Forgejo registry | Pass |
```

- [ ] **Step 3: Update `cove up` description** (line 43)

Old:
```
- Deploy platform services: Forgejo, Vault, CI runners, local image registry.
```

New:
```
- Deploy platform services: Forgejo (including OCI registry), Vault, CI runners.
```

- [ ] **Step 4: Update acceptance criterion #2** (line 82)

Old:
```
2. `cove up` on a fresh machine provisions a Lima VM (macOS) or starts k3s (Linux), deploys Forgejo, Vault, CI, and local registry, and reports healthy within 10 minutes.
```

New:
```
2. `cove up` on a fresh machine provisions a Lima VM (macOS) or starts k3s (Linux), deploys Forgejo (including OCI registry), Vault, and CI, and reports healthy within 10 minutes.
```

- [ ] **Step 5: Update acceptance criterion #4** (line 84)

Old:
```
4. `cove build .` builds a Dockerfile in the current directory via Kaniko and pushes to the local registry.
```

New:
```
4. `cove build .` builds a Dockerfile in the current directory via Kaniko and pushes to Forgejo's OCI registry.
```

- [ ] **Step 6: Update remaining SPEC-001 references** — verify lines 43, 82, 84, 96 no longer say "local registry" (covered by steps 3-5 above)

- [ ] **Step 7: Update the verification table** (line 96)

Old:
```
| Build via Kaniko | `cove build .` produces image in local registry | Pass |
```

New:
```
| Build via Kaniko | `cove build .` produces image in Forgejo registry | Pass |
```

---

### Task 5: Update `docs/superpowers/specs/2026-05-02-cove-design.md`

**File:** `docs/superpowers/specs/2026-05-02-cove-design.md`

Multiple changes:

- [ ] **Step 1: Read the full file** (already partially read)

- [ ] **Step 2: Update topology diagram** (line 41)

Old:
```
│       ├── registry (Deployment)          # Image cache (offline)
```

Remove this line, update forgejo line:

```
│       ├── forgejo (StatefulSet)          # Git + CI + OCI registry
```

- [ ] **Step 3: Update principle table** (line 55)

Old:
```
| **Fully offline** | All images pre-cached in local registry. Builder images cached. No external pulls during normal use. |
```

Remove "pre-cached in local registry" — if we're not doing the containerd mirror, this principle changes. Update to:

```
| **Fully offline** | All images stored in Forgejo's OCI registry. Builder images cached. No external pulls during normal use. |
```

- [ ] **Step 4: Remove the `### Registry (Deployment + hostPath)` section** (lines 84-89)

Delete lines 84-89 entirely:

```
### Registry (Deployment + hostPath)

- Stores pulled images and Kaniko build outputs
- `hostPath` at `~/Documents/cove/registry/`
- Used by Kaniko to push build outputs
- Used by k3s to pull images when offline (configured as `mirror` in containerd)
```

- [ ] **Step 5: Update Registry UI reference** (line 96)

Old:
```
- Registry UI: `https://registry.cove.local`
```

Remove or replace — Forgejo's registry has no standalone UI, it's managed through the Forgejo package registry interface at `git.cove.local`.

- [ ] **Step 6: Update Kaniko push target** (line 102)

Old:
```
- Pushes output to `registry.cove.local`
```

New:
```
- Pushes output to Forgejo's OCI registry (`git.cove.local/v2/` with GITHUB_TOKEN auth)
```

- [ ] **Step 7: Update NetworkPolicy reference** (line 81)

Old:
```
- `NetworkPolicy`: egress allowed only to Forgejo, Vault, and registry. No general internet access.
```

New:
```
- `NetworkPolicy`: egress allowed only to Forgejo, Vault, and Forgejo's OCI registry. No general internet access.
```

- [ ] **Step 8: Remove registry from Runner egress NetworkPolicy** (line 290)

Old:
```
| Runner egress | — | No | No | NetworkPolicy: only to Forgejo, Vault, registry |
```

New:
```
| Runner egress | — | No | No | NetworkPolicy: only to Forgejo, Vault |
```

- [ ] **Step 9: Remove registry from Kata/RuntimeClass table** (line 269)

Old:
```
| Registry | runc | Trusted code. Image cache. |
```

Remove this line entirely.

- [ ] **Step 10: Remove registry from Network Segmentation table** (line 288)

Old:
```
| Registry | Traefik (optional) | Yes | Yes | For pulling images from other machines |
```

Remove this line entirely.

- [ ] **Step 11: Update "What Must Be Built" table** (line 319)

Old:
```
| **Registry Deployment** | Build new | No equivalent. Needed for offline image caching. |
```
Replace with: (remove the row, or strike through and note "Superseded by Forgejo's built-in OCI registry — no standalone registry needed.")

- [ ] **Step 12: Update kata/runc RuntimeClass comment** (line 137)

Old:
```
Platform pods (Forgejo, Vault, registry, Traefik) use the default `runc` runtime for performance.
```

New:
```
Platform pods (Forgejo, Vault, Traefik) use the default `runc` runtime for performance.
```

- [ ] **Step 13: Remove registry from data dir** (line 168)

Old:
```
├── registry/
```

Remove this line.

- [ ] **Step 14: Update offline image caching item** (line 344)

Old:
```
| **Offline image caching** | First run needs internet to pull base images. | Pre-pull script during setup. Registry caches everything. Builder images (kaniko, distroless, Kata guest kernel) pre-cached. |
```

New:
```
| **Offline image caching** | First run needs internet to pull base images. | Pre-pull script during setup. Forgejo registry stores everything. Builder images (kaniko, distroless, Kata guest kernel) pre-cached. |
```

---

## Chunk 2: Ansible Role Cleanup

### Task 6: Remove registry from `deploy-platform.yml`

**File:** `roles/cove/tasks/deploy-platform.yml:11`

- [ ] **Step 1: Read the file** (already read)

- [ ] **Step 2: Remove `registry-deployment.yml.j2` from the loop**

Old:
```yaml
  loop:
    - forgejo-statefulset.yml.j2
    - vault-statefulset.yml.j2
    - runner-deployment.yml.j2
    - registry-deployment.yml.j2
    - traefik-values.yml.j2
    - network-policies.yml.j2
```

New:
```yaml
  loop:
    - forgejo-statefulset.yml.j2
    - vault-statefulset.yml.j2
    - runner-deployment.yml.j2
    - traefik-values.yml.j2
    - network-policies.yml.j2
```

---

### Task 7: Remove registry data dir from `main.yml`

**File:** `roles/cove/tasks/main.yml:12`

- [ ] **Step 1: Read the file** (already read)

- [ ] **Step 2: Remove the `registry/data` directory creation**

Remove line 12:
```yaml
    - "{{ cove_data_dir }}/registry/data"
```

---

### Task 8: Update the musing to finalize

**File:** `docs/musings/container-registry-comparison.md`

- [ ] **Step 1: Read the musing** (already read)

- [ ] **Step 2: Update the Landscape table** — replace the "Cove Registry" row to point at Forgejo:

Old:
```
| **Cove Registry** (planned) | Local disk only | None | mTLS / internal network | Yes | Docker Registry v2 (`registry:2`), port 5000, subdomain `registry.cove.local`. Storage at `~/cove-data/registry/`. |
```

New:
```
| **Forgejo OCI Registry** | Local disk only | None | Forgejo PAT / GITHUB_TOKEN | Partial | Forgejo's built-in `/v2/` registry. No separate `registry:2` container. Storage in Forgejo data dir. |
```

- [ ] **Step 3: Update the "Recommendation for Cove" table** — change build artifacts / CI pipeline push targets from `localhost:5000` to `forgejo.cove.local/v2/`

- [ ] **Step 4: Simplify the "Simplified Recommendation" section** to state the decision as made (Forgejo is the default, no separate registry within Cove)