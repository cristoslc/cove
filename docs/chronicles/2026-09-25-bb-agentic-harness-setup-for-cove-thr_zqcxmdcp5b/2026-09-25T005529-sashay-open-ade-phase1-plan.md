---
type: decision
timestamp: 2026-09-25T005529
responding-to: operator instruction to proceed with Phase 1 of ADR-018
---

## Sashay open — ADE Phase 1 plan committed

**Responding to:** operator's "proceed" after the ADR-018 implementation certification.

ADR-018 is Accepted. Phase 1 is scoped deliberately non-destructive: stand up a second bb server as an `ade` profiled compose service reachable at `ade.cove`, with a `cove ade` CLI, and leave the operator's live bb instance untouched. Cutover and host re-enrollment are Phase 2 (intent-and-wait).

Recon established the pattern this follows: profiled compose service + `cove <service>` command module (`runner.py`/`litellm.py`) + nginx server block + bringup wiring + a per-service test module. Grounded bb facts: the server ships as the npm package `bb-app`; a headless server via `npx bb-app` is explicitly supported; default port 38886; data dir configurable.

Three spikes gate the design and run first: (1) non-loopback bind in a container, (2) WebSocket + auth behind nginx, (3) image build pin/entrypoint. If spike 1 fails (bb refuses non-loopback without Connect), the ingress shape changes and this sashay stops to report.

Plan: `docs/plans/ade-harness-phase1.md`.

**Commits in this unit:** none yet (intent post).
