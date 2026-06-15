# Sashay: opencode-as-cove-tier-2 musing — tier 1 harness catalog

## What

Convert `docs/musings/opencode-as-cove-tier-2.md` from a rough working draft into a focused musing on deploying AI coding harnesses as Cove tier-1 services, with a clear MVP → v1 → v2 roadmap.

## Why

The musing has evolved through several iterations and now contains:
- A redundant threat-model/hardening section (the user explicitly dropped hardened mode)
- An OpenCode-only MVP definition that was being confused with v1
- A tier-2 deployment section that conflates tier 2 with "other harnesses"
- A tier placement matrix that mixed v1/v2 scope without versioning
- A troves/harness-catalog with snapshot evidence (created 2026-06-15)
- Compose templates for OpenCode, Claude Code, Aider, ttyd-wrapped harnesses

The user wants:
- MVP = OpenCode only, tier 1 only (ship this first)
- v1 = multiple harnesses, still tier 1 only
- v2 = tier 2 deployments
- No hardened mode / Lima VM (Colima containers are fine)

## Goal

A musing that:
1. Leads with a clear MVP definition (OpenCode, tier 1, bind mounts including data)
2. Catalogs other harnesses as v1 candidates with deployment templates
3. Defers tier 2 to v2
4. References the harness-catalog trove for evidence
5. Treats swain-box as a reference pattern, not a Cove service

## Tasks

### 1. Consolidate the musing

Remove:
- The "Hardening: Should Cove Adopt the swain-box Pattern?" section (88 lines)
- The "What v1 explicitly is not" / "v2 will add" blocks that conflate versions
- Redundant OpenCode compose template (keep only in MVP section)

Restructure:
- Move MVP Definition to the top, right after "Why This Musing Exists"
- Four Patterns section becomes "Catalog of Harnesses" with clear v1/v2 markers
- Tier Placement Matrix gets a "Version" column
- Deployment Recommendations split into MVP / v1 / v2 sections
- Open Questions and Next Steps split by version

### 2. Add the harness-catalog trove

The trove at `docs/troves/harness-catalog/synthesis.md` already exists (created this session) with snapshot evidence for:
- Claude Code Remote Control (code.claude.com official docs)
- CloudCLI / claudecodeui (siteboon)
- ttyd (tsl0922)
- OpenClaw (openclaw/openclaw)
- swain-box (10 local files from ~/code/swain-box/)

The musing should reference the trove for the evidence trail, not duplicate the research.

### 3. Define the MVP compose service

The MVP section should have a complete, runnable compose service definition for OpenCode on tier 1, with:
- `ghcr.io/anomalyco/opencode:latest` image
- Bind mounts: code (rw), projects (rw), opencode data (rw, persistent), config (ro), skills (ro)
- Port 4096 → host 127.0.0.1
- Auth via `OPENCODE_SERVER_PASSWORD` from Vault
- Behind nginx at `opencode.cove`, accessible from phone via Tailscale

### 4. Add v1 harness templates

For each v1 candidate (Claude Code, Aider, Codex CLI, Gemini CLI, CloudCLI):
- Container image
- Command (entrypoint)
- Bind mounts
- Port or web surface
- Notes on web access from phone

### 5. Document the swain-box reference

- swain-box at ~/code/swain-box/ is a real working kernel-isolated deployment
- Reference pattern, not a Cove service
- Cove does not bundle Lima VM orchestration into `cove up`
- Operators who want kernel isolation follow swain-box's docs

## Acceptance criteria

- [ ] MVP section is at the top, has a complete compose service
- [ ] Tier placement matrix has Version column (MVP / v1 / v2)
- [ ] Deployment recommendations split by version
- [ ] Hardening section removed
- [ ] Four patterns renamed to "Catalog of Harnesses" or similar
- [ ] All compose templates for v1 harnesses present
- [ ] Musing references `docs/troves/harness-catalog/synthesis.md` for evidence
- [ ] Musing is under 250 lines
- [ ] No "v1 = MVP" confusion in any section
- [ ] swain-box is referenced as a reference pattern, not a service

## Out of scope

- Implementing the actual compose service
- Testing OpenCode in a container
- Building `cove up` integration
- Tier 2 deployment
- Hardened mode / Lima VM

## Next steps after PR merge

- Create GitHub issue for the open questions (XDG path verification, auth model, restart behavior)
- Add OpenCode service to Cove's compose stack
- Test: create session, restart container, verify persistence
- Document the MVP deployment in the Cove install docs
