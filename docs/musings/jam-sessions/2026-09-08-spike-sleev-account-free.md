---
title: "Spike: Sleev Account-Free Pilot (Guest Mode)"
created: 2026-09-08
status: Draft
---

# Spike: Sleev Account-Free Pilot (Guest Mode)

Follow-up to the [metered-economics decision note](./2026-09-08-custom-compressor-metered-economics.md), which recommended a Sleev pilot. Operator constraint: **no account sign-up**. Result: the pilot runs in guest mode, but the optimization itself could not be triggered on our traffic — root cause documented below.

## What worked

- `npm install sleev` (v1.8.1), `sleev setup --yes` — guest legal terms accepted non-interactively, gateway installed to `~/.local/share/sleev/`, registered as launchd service `ai.sleev.gateway`, listening on `127.0.0.1:17321`. No sign-in required.
- Guest mode confirmed: `sleev usage --json` → `mode: guest, plan: guest, 500 premium requests remaining`. Config shows `auth.signedIn: false`.
- Requests route fine in guest mode: OpenAI-compatible POST to the gateway with `sleev-harness: opencode` + `sleev-base-url: https://ollama.com/v1` headers forwarded to Ollama Cloud with the operator's bearer key, 200s, correct GLM-5.3-flash responses. Account-free works as advertised.

## What didn't: zero optimization on replay traffic

Replayed the same five tool-heavy real-session windows (~176K prompt tokens total) through the gateway: **0.0% reduction on every window**, five repeated sends of the largest window included. The gateway debug log (`~/.local/state/sleev/debug-logs/server/gateway.err.log`) shows every request as:

```
routing=passthrough format=- converter=- plan=non_stream_passthrough
incoming=44344 outgoing=44344   # bytes unchanged, messages=-->- (never parsed)
```

**Root cause: custom providers are opaque passthrough by design.** The docs' own routing rules confirm the split:

- **Named providers** (`sleev-provider: anthropic|openai|zai-coding-plan|...`) — Sleev knows the wire format, parses messages, tracks sessions, applies its optimization ("deep optimization" of tool responses, redundant reads, bash output).
- **Custom providers** (`sleev-base-url: https://...` header or URL-routing form) — forwarded byte-for-byte, never parsed, never optimized. Ollama Cloud is not in the named-provider list; the `sleev-provider`-route test with a dummy Z.AI key confirms named-provider routing engages the parser (401 from upstream — expected with a dummy key — but `provider=zai-coding-plan` was at least recognized and parsed the body: `incoming=38746`).

A live harness sending through a **named** provider would accumulate session state across turns and trigger optimization. Our replay (one-shot sends of historical windows, custom-provider route) structurally cannot trigger it — this is a harness-fidelity limitation of the replay method, not necessarily a product failure. The marketing claim (30-80% per session, 65% average) is scoped to live harness sessions through named providers.

## Telemetry posture (account-free)

- Gateway contacts `api.sleev.ai` (`control_url` in `~/.config/sleev/gateway.json`) at setup and presumably periodically — an installation credential is generated (`slv_inst_...`, guest installation ID).
- At the time of inspection the gateway process had no established external sockets; telemetry cadence unknown. Offline licensing (zero telemetry) remains enterprise-only. Unverified beyond this: cadence, payload contents, and whether "no conversation content" holds in practice.
- Guest install left 25 MB in `~/.local/share/sleev/` + launchd service; stopped via `sleev gateway stop`.

## Verdict for the build decision

The pilot's original questions get partial answers:

1. **Does DCP-class reduction hold at the proxy layer?** Unverifiable account-free — custom providers don't optimize, and Ollama Cloud is not a named provider. Validating the 65% claim requires either a named-provider key (Z.AI coding plan serves GLM directly — would also need an account there) or a live harness session (the agent-cooperative toolkit means a one-shot replay can't exercise it).
2. **What the pilot *did* prove:** guest mode works with no sign-in; telemetry exists (control URL registered, no external sockets observed during the test window but enterprise-only opt-out confirmed earlier); the closed binary runs a launchd service on the host.

**Certified:** Sleev's account-free pilot yields a governance datapoint (guest mode works, telemetry exists at `api.sleev.ai`, custom providers passthrough-only) but **not** the reduction measurement the build decision wanted. The build-vs-license question stays open with a fork: (a) create a throwaway account + named-provider key to do the measurement properly, or (b) proceed to port DCP-core using our own replay harness as the eval baseline — the 6.3%/95% spread from the previous spikes is the target band. Neither path requires the operator's identity on a Sleev account.

Artifacts: `/var/folders/.../opencode/spike-sleev/` (node_modules, sleev-replay-totals.json), guest config at `~/.config/sleev/`, gateway binary + db at `~/.local/share/sleev/` (25 MB, removable).