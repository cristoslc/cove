# Spike: a Gitleaks-shaped secrets check at the LLM edge

Operator ruling `dec_8trphpel0p3c`: put a secrets check in front of Bifrost before any semantic prompt-injection filter, because four token-in-transcript incidents are the measured problem and the repository already maintains a ruleset.

This is the spike the ruling's own brief asked for: detection rate, false positives, and latency, measured rather than assumed. Run it with `scripts/spikes/edge-secrets/run.py`.

## What was measured

Twelve fixtures in real secret shapes with fake values, run through `gitleaks stdin` twice each, best time reported:

- six `pos-*` fixtures: Forgejo 40-hex token, GitHub PAT, OpenAI project key, AWS key pair, OpenSSH private key block, JWT;
- six `neg-*` fixtures: a 40-hex commit SHA in prose, a code snippet reading an env var, an `op://` reference, the `<redacted-forgejo-token>` placeholder, a 64-hex SHA-256 digest, an ordinary prompt.

### The repository's own rules are not enough

| Config | True positives | False negatives | False positives |
|-|-|-|-|
| `.gitleaks.toml` as shipped | 4 / 6 | 2 | 0 / 6 |
| plus two spike rules | 6 / 6 | 0 | 0 / 6 |

The two misses are the ones that matter here:

- **The Forgejo token shape.** Gitea and Forgejo tokens are bare 40-hex strings with no prefix. The default `generic-api-key` rule needs context and entropy it does not get from prose, so our own token shape passed through untouched.
- **`sk-proj-` keys.** The default rule covers the legacy `sk-` form, not the project-key form providers now issue.

### Why a shape-only rule cannot fix the first one

A 40-hex token is indistinguishable from a git commit SHA. A bare `\b[0-9a-f]{40}\b` rule would fire on every prompt that quotes a commit, and agent traffic quotes commits constantly. That is why the spike rule is context-aware: it matches 40 hex only near `token`, `bearer`, `password`, `secret`, or `api_key`, which catches the Forgejo fixture and leaves the commit-SHA fixture silent.

### Latency decides the placement

Every scan was a fresh process: **median 246 ms**, range 240 to 277 ms. That is fine inside a long-lived Go plugin, where the rule engine loads once, and far too slow per request as an nginx subrequest or a spawned check.

## What this implies

- **Reuse the rules, add two.** The check should extend `.gitleaks.toml` with a context-aware token rule and an `sk-proj-` rule; the shipped set leaves the two shapes we actually leak undetected.
- **Implement it in-process, not per request.** A Bifrost custom Go plugin, or a check inside the agent's tool-output path, is the only placement where 246 ms of process startup is not on the request path.
- **The edge only sees model traffic.** These leaks happened because an agent put tool output into a prompt, so a request-body check would have caught them before they reached the provider. It would not catch a token printed only to the transcript without ever being sent, which is why the transcript-side control and the rotation habit stay.

## What the spike did not cover

- Real traffic. No request bodies are retained, by design, so the corpus is synthetic plus the shapes from incident records.
- Long documents. A 100 KB prompt is a different latency profile from a one-line fixture.
- Redaction behaviour. The spike measures detection; whether a hit should block the request or redact the span is a separate decision, and blocking is the safer default for credentials.

## Recommendation

Build the check as an in-process plugin with the two extra rules, run it in observe-only mode first so the false-positive rate on real prompts is measured before anything blocks, and keep the transcript-side and rotation controls as the layers that cover what the edge cannot see.

## Follow-through

The build landed as [PR #185 — feat(secrets-guard): observe-only secrets check in front of Bifrost](https://git.cove.local/cristos/cove/pulls/185). Two findings changed the recommended placement, and the PR body carries the evidence: Bifrost does have the request-body plugin hooks, but the pinned official image is statically linked and cannot load a Go plugin, so a plugin would mean a custom gateway image and a broken digest pin. The check therefore runs as a long-lived sidecar in `compose/secrets-guard/`, linking gitleaks v8.30.0 as a Go library and reading this repository's one `.gitleaks.toml`. The two rules measured here are promoted into that file (the spike's `spike.toml` is deleted, so there is no second copy to drift) and are shared with the commit-hook gate. Placement, measured warm-scan cost, what the scanner does not see, and the shape of turning it into blocking are in [the service page](../services/secrets-guard.md).
