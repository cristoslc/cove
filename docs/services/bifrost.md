# Bifrost Gateway for Cove

**Status: additive replacement candidate; cutover plan approved.** Bifrost
runs alongside the live LiteLLM services on the `bifrost` compose profile.
Nothing is removed and no client is re-pointed yet; the four previously
pending cutover decisions were approved by the operator on 2026-10-26 and
the checklist at the bottom is now a resolved two-phase runbook. Design and
evaluation: [the LiteLLM exit musing](../musings/litellm-exit.md).

- **What it is**: [Bifrost](https://github.com/maximhq/bifrost) (Bifrost
  transports v2.3.2), an OpenAI-compatible LLM gateway with config-file
  governance, virtual keys, and ordered fallback routing. It carries the same
  model ladder LiteLLM serves today, re-expressed as Bifrost routing rules with
  fallback chains.
- **Where it lives**: https://bifrost.cove/ and https://bifrost.cove.local/
  through nginx (loopback port bind `127.0.0.1:4002`). The dashboard is
  protected by the shared Cove Admin identity (ADR-017).
- **Client traffic**: none yet. LiteLLM remains the agent traffic path;
  clients re-point to the product-neutral `llmproxy.cove` endpoint (see
  "Client endpoint" below) on cutover day, on a date the workstation lane
  sets.

## Quick Start

```bash
cove bifrost up        # provisions credentials, seeds runtime files, starts
cove bifrost status    # health + credential wiring (names only)
cove bifrost logs -f   # tail logs
cove bifrost down      # stop (data preserved)
```

`cove up` never starts Bifrost as a side effect — it is deliberately absent
from `_start_optional_services()` until the cutover is decided.

## Client endpoint: llmproxy.cove (product-neutral)

`llmproxy.cove` (+ `llmproxy.cove.local`) is THE canonical client-facing
OpenAI-compatible endpoint. The client contract is OpenAI-compatible HTTP,
so the hostname must outlive any single product: clients point at
`llmproxy.cove`, and a product swap changes the engine behind it without
touching a single client.

- **The product-swap line**: the alias vhost proxies to one IaC variable in
  `compose/nginx/default.conf.j2` — `set $llmproxy_upstream ...;`. That line
  names the ACTIVE proxy upstream: `http://litellm:4000` today (LiteLLM
  still serves agent traffic), flipped to `http://bifrost:8080` on cutover
  day. One line changes; nothing else does.
- **Edge authentication (clients hold ONE token)**: `llmproxy.cove` is the
  authentication edge, not a thin alias. Clients present a **client-scoped,
  cove-owned token** — never a backend credential — and nginx rejects anything
  else with `401` before an upstream sees the request. It then injects the
  ACTIVE backend credential toward the upstream (the LiteLLM master key
  today, the Bifrost virtual key after the flip). Backend credentials never
  reach clients, so a proxy swap cannot strand a client credential.

  | credential | who holds it | where it lives | where it is read |
  | --- | --- | --- | --- |
  | client token | machine clients (opencode, omp, pi) | 1Password item `Cove LLM Proxy Client Key` (URL-keyed `https://llmproxy.cove.local/`, field `client_key`; shared across machines) plus the Vault `op-cache` entry | `cove up` resolves it (env `COVE_LLM_PROXY_CLIENT_KEY` -> compose `.env` -> Vault cache -> provision the item) and renders it into `nginx/llmproxy-auth.conf` at mode 0600 |
  | LiteLLM master key | the edge and LiteLLM only | 1Password `LiteLLM Proxy` item -> compose `.env` `LITELLM_MASTER_KEY` | `cove up` reads `.env` and renders it into the same 0600 file; the client never sees it |
  | Bifrost virtual key | the edge and Bifrost only | gateway-generated, projected into compose `.env` as `BIFROST_CLIENT_VIRTUAL_KEY` | same render path; used only when the active upstream is `http://bifrost:8080` |

  The rendered credential file (`compose/nginx/llmproxy-auth.conf`, rendered
  at mode `0600` and gitignored) carries two `map`s: one exact-match map of
  `"Bearer <client token>"`, and one that pairs every switchable upstream with
  its backend key. The public `default.conf` (world-readable in the
  container) only references `$llmproxy_authorized` and
  `$llmproxy_upstream_key`, so it holds no secret. An upstream missing from
  the map gets an empty key and fails closed at the upstream rather than
  borrowing another product's credential. `cove up` refuses to render when
  the client token is missing (never an unauthenticated or wildcard edge).
- **Streaming-critical settings** are copied from the litellm vhost:
  `proxy_buffering off` and 3600s read/send timeouts, because the ladder
  serves 3600-second streams.
- **Product hostnames stay admin/debug surfaces only**: `bifrost.cove` is
  the gateway console, `litellm.cove` is LiteLLM's UI while it drains. They
  are not client surfaces and are not removed.
- **Wiring**: cert SANs, the bringup TLS-validation loop, the `/etc/hosts`
  entry, the landing card, and the `cove bifrost status` health probe plus
  upstream report. The dnsmasq resolver is wildcard-based
  (`address=/cove/` and `address=/cove.local/`), so both neutral names
  resolve with no per-name entry.

### Migration and rollback (edge auth)

The edge gate turns on the moment this release's `cove up` renders nginx, so the
credential swap below is the lane's one coordinated change. Cove executes none
of it.

- **Migration**: replace each client's credential slot (today
  `~/.config/workstation/secrets/litellm-master-key`, sent straight to
  `litellm.cove`) with the edge token from
  `op://Private/Cove LLM Proxy Client Key/client_key`, and point its base URL
  at `https://llmproxy.cove/v1`. Clients then reach LiteLLM through the edge,
  which injects the master key server-side. The LiteLLM master key stops being
  a client credential entirely — it is an edge/backend credential from then on.
- **Rollback (before the drain window closes)**: flip `$llmproxy_upstream`
  back to `http://litellm:4000`, release, and re-render. Clients need no
  change: the client token and the server-side injection are independent of
  which backend is active.
- **Rolling back the edge itself** (a prior wheel): the old `default.conf` has
  no edge auth and forwards the client's own `Authorization` header, so a
  client already holding the edge token starts failing against the backend.
  Reverting the edge is therefore a coordinated change with the lane, exactly
  like a client re-point — not a quiet rollback.

## Configuration ownership

IaC-first, with the same split as LiteLLM:

- **`compose/bifrost/config.json`** (git-tracked): the governance source. It
  carries `source_of_truth: "config.json"`, the auth settings, the three
  custom OpenAI-base provider instances **plus the built-in `ollama` provider
  for the System One decision tier**, the single virtual key, the twelve tier
  routing rules (ten canonical aliases — including the decision tier — plus
  the two deprecated `text:standard` aliases), and the served-name key
  `aliases` that `/v1/models` advertises. Seeded to `~/Documents/cove-data/bifrost/config.json`
  (first boot only; operator edits preserved, wedge-guarded).
- **`config.db`** (SQLite runtime store): **must pre-exist before the first
  container boot** — a file-only boot cannot carry governance, and the store
  also carries the generated virtual key and the pricing cache. Bringup and
  `cove bifrost up` both seed it as an empty, valid SQLite file (`0600`,
  never recreated when present). Bifrost mounts it writable at
  `app/data/config.db` and manages its contents; `config.json` pins the
  store path ABSOLUTE (`/app/data/config.db`) because the documented
  default (`config.db`) resolves against the image WORKDIR (`/app`), not the
  APP_DIR (`/app/data`) — observed 2026-10-27: with the default, the store
  (and the generated virtual key inside it) reset on every container
  recreation. With `source_of_truth: "config.json"`, file sections stay
  authoritative; the generated token is preserved by hash-matched re-seeds.
- **The client virtual key** is **Bifrost-generated** (v2.3.x turns every
  seeded or API-passed value into its own `sk-bf-...` token; the seed value
  is ignored — observed 2026-10-27). The declaration in `config.json`
  carries policy only (no `value` field). `cove bifrost up` fetches the
  generated token from the gateway's admin API after boot and projects it
  into the deployed compose `.env` as `BIFROST_CLIENT_VIRTUAL_KEY` (in-process,
  never printed; rotation via the dashboard refreshes it on the next `up`).
  Clients authenticate OpenAI-style: `Authorization: Bearer <BIFROST_CLIENT_VIRTUAL_KEY>`
  (or `x-bf-vk:`); requests with no credential get 401 (`enforce_auth_on_inference`).
- **`dnsmasq.conf`** (git-tracked): the egress allowlist (see Security
  posture). Seeded first boot only.
- **`local.env`**: the provider key file (`0600`). `SYNTHETIC_API_KEY` is
  projected here by `cove bifrost up` from the LiteLLM local.env (the one
  deployed source of record the LiteLLM provider config already runs on —
  copied in-process, never printed; an existing entry is never overwritten;
  missing everywhere fails loudly with instructions). An ambient
  `SYNTHETIC_API_KEY` is not an input unless `COVE_ALLOW_AMBIENT_CREDENTIALS=1`
  is set deliberately; a divergence is reported with fingerprints, never
  values. `OLLAMA_API_KEY` is NOT written here: it
  arrives through the compose pass-through from the deployed `.env` where
  the workstation lane's SOPS projection lands it.
- **The ollama-cloud key** is NOT Cove's to hold (workstation-lane ownership
  ruling, 2026-10-26): the workstation's SOPS role projects
  `OLLAMA_API_KEY` into the deployed compose `.env`, and the compose service
  passes it through — exactly as the LiteLLM services receive it today.

## The model ladder

Twelve tier aliases re-express as CEL routing rules (`model == '<tier>'`)
with ordered fallback chains. Eleven are chat tiers whose chain order is the
spend-first order: Synthetic subscription (1), ollama-cloud metered (2), the
infinite backstop (3). Wire ids are unchanged from the LiteLLM configuration.
The twelfth, `vision:system1-classifier`, is a **decision tier** and is not
part of that ladder (see "The System One decision tier" below).

The standard tier serves **DeepSeek V4.1 Flash, which accepts image input**,
so per ADR-008 ("aliases lead with the modality") its canonical alias is
`vision:standard`. The former `text:standard` name stays resolvable as a
**deprecated alias pointing at the identical chain** while clients migrate
(see "Alias migration" below).

| Tier id | Chain (in order) |
| --- | --- |
| `text:light` | syn-subscription `hf:zai-org/GLM-4.7-Flash` → ollama-cloud `gpt-oss:120b` → backstop `infinite:small:vision` |
| `vision:standard` | syn-subscription `hf:deepseek-ai/DeepSeek-V4.1-Flash` (image input) → ollama-cloud `deepseek-v4.1-flash` → backstop |
| `text:ultra-heavy` | syn-subscription `hf:zai-org/GLM-5.3` → ollama-cloud `glm-5.3` → backstop |
| `vision:heavy` | syn-subscription `hf:zai-org/GLM-5.3-Flash` → ollama-cloud `glm-5.3-flash` → backstop |
| `vision:super-ultra-heavy` | syn-subscription `hf:moonshotai/Kimi-K3` → ollama-cloud `kimi-k3` → backstop |
| `nonstreaming:text:light` | syn-subscription → ollama-cloud (2 hops, no backstop) |
| `nonstreaming:vision:standard` | syn-subscription `hf:deepseek-ai/DeepSeek-V4.1-Flash` (image input) → ollama-cloud `deepseek-v4.1-flash` (2 hops, no backstop) |
| `syn:large:text` | syn-subscription directly (1 hop) |
| `infinite:small:vision` | syn-infinite-backstop directly (1 hop) |
| `text:standard` | **deprecated alias** — same chain as `vision:standard` |
| `nonstreaming:text:standard` | **deprecated alias** — same chain as `nonstreaming:vision:standard` |
| `vision:system1-classifier` | **decision tier, not a chat tier** — built-in `ollama` provider `clef` on Ollama Cloud (1 hop, no fallback; served on `POST /v1/decisions`) |

### The System One decision tier

`vision:system1-classifier` is a **decision** tier: it answers typed questions
on Bifrost's `POST /v1/decisions` (and the native `/typesafe/v1/systemone`
route), never a chat completion. It is named for the capability and leads with
the modality, per ADR-008 — Clef is a 27B multimodal decision model that reads
text, JSON, and images.

Why it needs the **built-in `ollama` provider** rather than a fourth custom
instance: Bifrost's `SupportedBaseProviders` (the custom-provider base list)
excludes `ollama`, and an `openai`-base custom provider would POST OpenAI's
`/v1/decisions` request shape at Ollama's `/v1/systemone` endpoint and
mis-parse the TypeSafe-shaped reply. The built-in provider speaks Ollama's
protocol: it converts the normalized decision request to the System One body
and calls `<base_url>/v1/systemone`. It **requires** a per-key
`ollama_key_config.url` — Bifrost's key validation refuses an ollama key without
it (`core/utils.go`: `ollama_key_config is required`), and live-verified
2026-10-29 the gateway skips such a key at startup and every request 400s with
`no_key_supports_model` (`network_config.base_url` is only a runtime fallback,
so both are set).

The tier is additive and reaches only the `ollama` provider — that is, it never
fans out to a chat deployment. It has **no fallback**: no second System One
provider is configured, and falling back to a chat tier would silently hand a
decision request to a model that cannot answer it, so the tier fails loudly
instead. `ollama.com` was already on the DNS allowlist (it is `ollama-cloud`'s
configured upstream), so no egress change was needed.

Capability is verified live, not assumed (2026-10-29, through this gateway):
a `predicate` question returned `0.9941`, and a `choice` question on a 16×16
solid-red PNG returned `colour = red` (`0.9903`) with
`routing_info = {"provider": "ollama", "model": "clef", "requested_model":
"vision:system1-classifier"}`.

### How a caller discovers the tiers

`GET /v1/models` advertises the served tier names. Bifrost builds the listing
from provider model catalogues; the tier names ride in as **static key
`aliases`** (a schema-defined map on a provider key), which the gateway
backfills into the listing even though they are not provider models. Every tier
is declared exactly once, on the key of its routing rule's primary provider,
carrying the rule's primary wire model as the value, so the discoverable list
cannot drift from what serves.

Two things had to change for the listing to be non-empty. First, `list_models`
was `false` on all three custom providers, and Bifrost's list-all fan-out
**skips** any provider whose `allowed_requests` forbids it — so with it off the
listing was `{"data":[]}`. It is now enabled on all three. Second, nothing
declared the tier names; the `aliases` map does now. Each key's `models`
allowlist is also narrowed from `["*"]` to the exact wire models the routing
rules send that key, so the listing carries only the models this gateway serves
(no upstream-catalogue noise) and the key is least-privilege.

Entries are provider-scoped: `syn-subscription/vision:standard`,
`syn-infinite-backstop/infinite:small:vision`, and the wire ids
(`syn-subscription/hf:deepseek-ai/DeepSeek-V4.1-Flash`). A client that sends the
provider-scoped tier name routes through the same routing rule as the bare
name, because Bifrost strips the provider prefix before evaluating the rule. A
live `GET /v1/models` against the pinned gateway returns 22 such entries and no
foreign models. The built-in `ollama` provider's decision tier surfaces the
same way (its key's `aliases` backfills `ollama/vision:system1-classifier`,
beside the allowlist entry `ollama/clef`).

Bifrost's schema still defines **no capability or modality field** for a model
or a routing rule, so `/v1/models` carries no vision flag and none is invented
for it. The capability is told by the alias name (`vision:standard`) and by the
routing rule's `description` (a real, schema-defined field the dashboard's
Routing Rules list renders), which the machine-readable API
`GET /api/governance/routing-rules` returns.

The capability is verified, not assumed: a 1×1 red PNG sent inline to the
standard tier (as `text:standard`, the name it carried at probe time) through
the running gateway returned HTTP 200 with the model answering `Red`, routed at
order 1 to `syn-subscription` `hf:deepseek-ai/DeepSeek-V4.1-Flash`
(`requested_model: "text:standard"`). The same wire evidence is recorded in the
workstation repo (2026-10-22, plus Synthetic's catalogue declaring
`input_modalities: ["text", "image"]`).

### Alias migration

`vision:standard` / `nonstreaming:vision:standard` are the canonical names;
`text:standard` / `nonstreaming:text:standard` are deprecated aliases to the
same chains, kept so the 34 bb project defaults and the client configs pinned
to the old ids keep working on merge night. Removing the deprecated rules is a
**later step**, and it requires all of the following first:

1. Every client surface moved off `text:standard` / `nonstreaming:text:standard`
   (the workstation-lane opencode provider config, the `omp` models template,
   `scripts/synthetic_catalog.py`, `tests/python/test_cove_alias_modality.py`).
2. The 34 remembered bb project defaults re-pointed to `vision:standard`.
3. The LiteLLM overlay in `~/Documents/cove-data/` re-pointed (only while
   LiteLLM still drains; Bifrost is the target path).
4. The cove Bifrost cutover complete, so `vision:standard` is the live name
   through `llmproxy.cove`.

Until then the deprecated rules must stay; a hard rename would 404 every
remembered default.

The infinite backstop is a **separate custom provider instance** pointing at
the same Synthetic endpoint, gated to `chat_completion_stream` only via
`allowed_requests`. That makes the streaming-only restriction structural: a
non-streaming request cannot reach the instance at all (verified in the live
smoke test — nothing reaches upstream). The non-streaming tiers simply omit
the backstop from their chains. This closes the LiteLLM gap where a
streaming-only backstop had to be trusted to configuration discipline.

## Stalled-stream escalation (TTFT cutoff)

A throttled Synthetic request does not fail: it accepts the stream and then
produces no first token, so nothing in the retry or fallback path fires until the
provider's 120-second request timeout expires. The tier rule carries a
**time-to-first-token cutoff** on its target (`ttft_timeout_ms`), which closes an
attempt that has produced no first token in time and moves to the next fallback.
The client never sees the slow attempt, because Bifrost streams nothing until an
attempt yields a first token.

### What the pinned version supports (v2.3.2)

- **Granularity is the routing target.** The store column is
  `routing_targets.ttft_timeout_ms`, and the file loader reads it from each
  `targets[]` entry. A rule-level `ttft_timeout_ms` is **silently ignored** by
  v2.3.2 (verified against the pinned image 2026-11-03: rule-level waited out an
  8-second stall; target-level escalated at 1.5 seconds). Current upstream docs
  and the dashboard present the field per rule; each rule here has exactly one
  target, so the two placements describe the same hop.
- **Streaming only.** Non-streaming requests ignore it and keep the provider
  request timeout.
- **The last attempt is never cut off.** The cutoff applies to each attempt that
  still has a fallback behind it.
- **No same-provider retry.** A TTFT miss goes straight to the next fallback and
  does not spend `max_retries`. A provider *request* timeout is also not retried
  (verified on the pinned image: `max_retries: 1` produced one attempt, then the
  fallback), so a stalled hop costs its timeout once, not twice.

### Measured distribution and the chosen threshold

Source: the live traffic path's spend logs (LiteLLM `LiteLLM_SpendLogs`), because
Bifrost's own `logs_store` is disabled by the adoption gate. Window: the seven
days to 2026-11-03. `completionStartTime - startTime` is time to first token;
`request_duration_ms` is the whole request.

| Tier | n | p50 | p95 | p99 | p99.9 | max TTFT | max total |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `vision:standard` | 11,645 | 2.7s | 8.2s | 15.0s | 21.5s | 33.6s | 471.5s |
| `text:standard` (alias) | 5,192 | 2.7s | 6.2s | 9.7s | 25.4s | 37.8s | 214.7s |
| `text:light` | 7 | 7.5s | 17.4s | 19.1s | — | 19.5s | 19.5s |
| pooled light/standard | 16,859 | 2.7s | ~8s | 13.4s | 23.2s | 37.8s | — |
| heavy tiers (pooled) | 5,471 | — | — | ~25s | 103.4s | 127.9s | 553.4s |

**Threshold: 25,000 ms on `text:light`, `vision:standard`, and the deprecated
`text:standard` alias.** It sits just above the pooled p99.9 (23.2s), so it
escalates only the extreme tail: **7 of 16,859 requests (0.04%) exceeded 25s** in
the window. Twenty-nine exceeded 22s and three exceeded 30s.

The heavy tiers keep their 120s ceiling: **62 of 5,471 heavy requests (1.1%)
exceeded 25s**, and `vision:heavy` has a p99 of 25.0s. A cutoff there would
escalate healthy long generations, which is the failure mode a global timeout
reduction would produce. The non-streaming and single-hop tiers are untouched:
non-streaming ignores the field, and a rule without fallbacks is never cut.

Worst case per hop is now bounded at 25s for the two metered hops, with the
last (streaming-only) backstop still running under its 120s provider timeout.

### Where the change lands, and what reaches an existing host

The authoritative artefact is `compose/bifrost/config.json` (git-tracked, and the
source of the wheel's bundled copy). The deployed
`~/Documents/cove-data/bifrost/config.json` is seeded from it **first boot only**
(`force: false`), so a converge neither reverts the value nor delivers it: a fresh
install gets it, and an existing host keeps its current file until the operator
copies the new config and restarts the gateway (a gateway restart is a live
session interruption, so it is scheduled, never implicit).

### Reproduction

`TestBifrostLiveSmoke::test_ttft_cutoff_escalates_a_stalled_stream` runs the
pinned image against a mock that accepts the stream and stalls 6 seconds on the
primary. A test-only probe rule carries a 1.5-second target-level cutoff and the
same ordered fallback; the test asserts the fallback serves at roughly 1.5
seconds, that `x-bifrost-routing-info-is-fallback` and `x-bifrost-fallback-index:
1` are set, and that the primary was attempted exactly once. Opt in with:

```bash
COVE_ALLOW_LIVE_TESTS=1 uv run --directory cli pytest -m live \
  cli/tests/test_bifrost.py::TestBifrostLiveSmoke::test_ttft_cutoff_escalates_a_stalled_stream
```

The 25,000 ms shipped value itself is pinned by
`TestBifrostConfigValidation::test_latency_sensitive_tiers_carry_a_ttft_cutoff`,
which also holds the heavy, non-streaming, and single-hop tiers clear of the
field.

## Regime governor (windowed escalation)

The per-request cutoff above bounds one stalled stream. It does not notice a
*regime*: a stretch of minutes in which most requests on a tier are slow. The
measured regimes had median first-token times of 8.4 to 19.2 seconds against a
baseline of 1.3 to 4.3 seconds, and they were load-shaped (all 200s, no 429s,
three of four windows below the median request rate).

Bifrost v2.3.2 has no windowed latency primitive: routing rules are static CEL
matches and `ttft_timeout_ms` is per request. The windowed rule therefore runs
as a small controller outside the gateway, `cove bifrost governor`, one pass per
invocation (dry-run by default, `--apply` to act). A systemd timer, launchd job,
or cron entry runs it every minute.

- **Signal**: Bifrost's `bifrost_stream_first_token_latency_seconds` histogram,
  scraped from `/metrics` with the dashboard Basic credentials. The histogram is
  cumulative, so each pass keeps a bucket snapshot and a 15-minute ring of
  deltas; the median is read from the deltas covering at least 20 samples.
- **Threshold**: the pooled median across `rr-vision-standard` and
  `rr-text-standard` at or above **6,000 ms** escalates. The highest ordinary
  prompt-band median is 4,300 ms (250k+ tokens outside a regime) and the lowest
  regime median is 8,400 ms, so 6 seconds sits between the two populations. A
  median of 20 over 8 seconds requires 11 slow requests out of 20, which does
  not occur outside a regime (4.4% of requests exceed 8 seconds; inside a
  regime 58% to 100% do).
- **Action**: both standard rules swap their target to
  `ollama-cloud/deepseek-v4.1-flash` and their fallbacks to the streaming-only
  backstop. Restore at a pooled median of **4,000 ms** or below, or at the
  dwell limit.
- **Caps**: at most 3 episodes per hour, 8 per week, 15 minutes per episode,
  and a 10-minute cooldown after an episode. Worst case is 2 hours per week
  (about 12% of the week) fully escalated. In the measured week the 8-second
  signal produced 5 episodes covering 288 standard-tier requests (1.7% of tier
  traffic); 123 of those (43%) had answered within 8 seconds and would be
  routed to the fallback anyway. The caps are what bound that waste, since the
  legacy Ollama weekly ceiling is unquantified.
- **Net underneath**: the merged 25,000 ms per-request `ttft_timeout_ms` stays
  on the escalated target too, so a single stalled stream still cuts even during
  an episode.
- **Fail-safe**: the governor mutates the gateway's rule store transiently and
  writes its original targets to a 0600 state file. A gateway restart re-syncs
  `config.json` and reverts to Synthetic. A metrics counter reset (restart)
  rebaselines instead of firing. No samples, no action.

The governor only sees Bifrost traffic, so it is inert until the client path is
re-pointed to `llmproxy.cove` and Bifrost serves the tiers. It is not started by
any converge.

## What's Hardened

- **Digest-pinned image**: `maximhq/bifrost:v2.3.2` pinned to its multi-arch
  manifest digest (overridable via `BIFROST_IMAGE` only with the full
  tag+digest pair; the compose default carries both).
- **Inference auth enforced by default**: `client.enforce_auth_on_inference`
  is `true`; a request with no (valid) virtual key gets 401 on every tier
  (live-verified 2026-10-27). Dashboard auth is disabled ON INFERENCE
  (`disable_auth_on_inference: true`) so the OpenAI-compatible contract
  holds: `Authorization: Bearer <token>` carries the virtual key; the
  dashboard/API surface itself stays username/password protected.
  Dashboard auth is enabled, and the generated virtual key is allowed on
  all three instances.
- **Request-body logging OFF** (adoption gate): `client.enable_logging:
  false`, `disable_content_logging: true`,
  `allow_per_request_content_storage_override: false`, and `logs_store`
  disabled entirely. Declared in IaC, pinned by tests.
- **Egress allowlist (DNS choke)**: the gateway's `dns:` is pinned to
  `cove-bifrost-dns` (172.43.0.10), a minimal dnsmasq sink on the dedicated
  `bifrost-egress` network (172.43.0.0/24, outside Docker's default pools).
  The sink runs on a read-only rootfs with no pidfile written at all
  (`--pid-file=`, dnsmasq's no-pidfile form), publishes no ports, and
  NXDOMAINs every name except exactly three documented vendor contacts:
  `api.synthetic.new` and `ollama.com` (the inference providers), plus
  `getbifrost.ai` — Bifrost loads its pricing catalog from there at
  STARTUP and exits (crash-looped the container behind the sink, 2026-10-26
  converge). The allowlist's purpose is preventing QUIET egress growth, not
  forbidding every vendor contact: a startup fetch of a public pricing
  catalog is not telemetry and carries no prompt data. Vendoring a pricing
  snapshot was rejected — it goes stale, and wrong cost numbers are worse
  than a known contact. `compose/bifrost/dnsmasq.conf` carries the rationale
  in-file and the tests pin the exact three-name list.
  Caps: `cap_drop: ALL` plus
  `NET_BIND_SERVICE` (bind :53), `SETUID`, and `SETGID` (dnsmasq's
  startup privilege drop to the unprivileged `dnsmasq` user). The kernel
  clears those caps at the drop, so the long-running daemon holds none.
  **Caveat**: DNS enforcement does not stop direct-IP egress; the digest
  pin and the vendor-update hold are the anchors there.
- **Loopback-only**: the raw port binds 127.0.0.1; nginx is the ingress.

## Supply-chain finding (2026-10-26)

Upstream publishes **no image signatures, SBOM attestations, or SLSA
provenance** for the Bifrost images: `release-pipeline.yml` has no cosign and
no provenance step. Its hardening is real but different — fully SHA-pinned
GitHub Actions, step-security egress blocking, phone-gated release approval —
none of which is verifiable from a pulled digest. The verified anchors are:

1. the pinned multi-arch manifest digest (updated only via a deliberate pin
   bump), and
2. the vendor-update hold period (48-72h) between upstream release and pin
   adoption.

Nothing signature-based could be wired into bringup verification; the finding
is recorded here instead.

## Virtual key resolution (the spike's file-seeded VK finding, resolved)

The spike found a file-seeded virtual key failing to authenticate while an
API-created one worked. **Mechanism (established 2026-10-27 on v2.3.2,
live gateway):** Bifrost generates every virtual-key TOKEN itself
(`sk-bf-...`). A value provided at seed time — a literal or an `env.*`
reference in `config.json` — is ignored, and an admin-API-created key with a
provided value is regenerated too. The seeded ROW (id, policy, provider
configs) is honored; only the token is generated. A request bearing the
seed-provided value gets 401 `access not found`.

**Resolution:** the config's VK declaration carries policy only (no `value`
field); the store is durable (absolute path on the mounted bind), so the
generated token is created once and preserved by hash-matched re-seeds;
`cove bifrost up` fetches the token from the admin API after boot and
projects it into the compose `.env` as `BIFROST_CLIENT_VIRTUAL_KEY`. The
1Password item's short-lived `virtual_key` field from the first additive
build is superseded: the rotating, authoritative token lives in the gateway
(rotatable via the dashboard/API) and its fetched copy in the `.env`.

## Commands

`cove bifrost up` — provision credentials (1Password `Bifrost Gateway` item:
config-store encryption key and dashboard admin password; the admin username
comes from the shared Cove Admin item, ADR-017), seed the runtime files,
project the provider keys, and start the profile (`up -d --build`, the sink
image is built locally); after boot it fetches the gateway-GENERATED client
virtual key from the admin API and projects it into the compose `.env`.

`cove bifrost status` — compose ps, credential-wiring booleans (SET/missing,
names never values), and the nginx health probe (an auth answer like
LiteLLM's master-key 401 counts REACHABLE; only a dead probe or an
unhealthy HTTP answer is UNREACHABLE).

`cove bifrost down` / `cove bifrost logs [-n N] [-f]` as for other optional
services.

## Architecture

```
clients ──https──> nginx :443
         llmproxy.cove ── auth edge: client token only (401 otherwise)
                        ├─ injects $llmproxy_upstream_key (backend key, server-side)
                        └─> $llmproxy_upstream (the ACTIVE proxy; one IaC line)
                        ├─ today: litellm :4000 — from cutover: bifrost :8080 (127.0.0.1:4002)
         bifrost.cove (admin console) ─> bifrost :8080
                                           │  config.json (ro) + config.db (rw)
                                           │  env_file local.env + compose .env
                                           ▼
                                DNS: cove-bifrost-dns (allowlist sink) ──> only api.synthetic.new, ollama.com, getbifrost.ai
                                           │
                                           ▼
                          syn-subscription / ollama-cloud / syn-infinite-backstop
```

## Test coverage

`cli/tests/test_bifrost.py` holds the config, compose, nginx, bringup, and
CLI suites (tier 1, default gate) plus the `live`-marked container smoke
(opt-in `COVE_ALLOW_LIVE_TESTS=1`): a self-managed `docker run` of the pinned
image against a local model-keyed mock upstream, verifying the 401 posture,
the file-seeded VK, ordered fallback (stream and non-stream), the single-hop
tiers, and the structural streaming-only gate. Rows live in
`docs/test-coverage-matrix.yaml`.

## Cutover checklist (decisions approved 2026-10-26; NOT yet executed)

The operator approved all four previously-pending decisions on 2026-10-26,
so this is a resolved plan, not a set of options. Execution is two phases:
cutover day, then teardown one week later.

**Resolved decisions**

- **pgdata disposal**: secure-delete the `litellm-db` postgres volume at
  teardown — it can hold prompt-bearing request logs.
- **Key-rotation timing**: at cutover. The Synthetic and ollama-cloud keys
  rotate on cutover day; the ollama half is scheduled by the workstation
  lane against the date cove sends.
- **1Password `LiteLLM Proxy` item**: retained until the drain window
  closes (so a prior-wheel rollback still authenticates), then deleted.
- **Drain window**: one week between client re-point and LiteLLM removal.
- **Client re-point target**: `llmproxy.cove` (see "Client endpoint"
  above). The workstation lane controls the re-point timing; cove sends the
  cutover date once the neutral endpoint is merged and verified.

### Phase 1 — cutover day

1. Flip the product-swap line to `http://bifrost:8080` in
   `compose/nginx/default.conf.j2`, release, reinstall, and `cove up` so
   nginx re-renders with the new upstream.
2. Start the bifrost profile: `cove bifrost up` (skip if already running).
3. Smoke the neutral endpoint with a real streaming request through the
   ladder: a `stream: true` chat completion against
   `https://llmproxy.cove/v1/chat/completions` with the CLIENT TOKEN (the
   edge injects the Bifrost virtual key server-side; the virtual key is no
   longer a client credential).
4. Rotate the Synthetic key (provider side, then into both env copies —
   Bifrost's `local.env` and LiteLLM's, which still drains for a week).
5. Notify the workstation lane with the cutover date; the lane has already
   replaced the clients' credential slot with the edge client token (see
   "Migration and rollback" above) and schedules the ollama-cloud key
   rotation for the same day.
6. Watch the old `litellm.cove` vhost drain over the week.

### Phase 2 — teardown day (T+7)

1. Stop LiteLLM and disable the `litellm` compose profile.
2. Secure-delete the `litellm-db` postgres pgdata volume (prompt-bearing
   request logs; irreversible, operator sign-off).
3. Drop the `OLLAMA_API_KEY` pass-through line from the deployed compose
   `.env` (workstation-lane property; the lane provisioned the key into
   Bifrost directly at cutover).
4. Delete the 1Password `LiteLLM Proxy` item and its Vault cache entries —
   the drain window closed today, so the retention rule is satisfied.
5. Prune the litellm image.

Rollback shape: before teardown day, the prior release's wheel restores the
whole surface and the product-swap line flips back to
`http://litellm:4000` with no client re-re-point. After teardown, the
secure-delete is the point of no return (which is why it is gated to T+7
with explicit sign-off). The full removal order (compose services, CLI
group, tests, docs, SBOM) remains in
[the exit musing](../musings/litellm-exit.md#exit-plan-removal-order-once-the-replacement-is-chosen).

## Troubleshooting

### Gateway won't start

`docker logs cove-bifrost` — most commonly a missing credential: every
`env.*` reference in `config.json` must resolve (`BIFROST_ENCRYPTION_KEY`,
`BIFROST_ADMIN_USERNAME`, `BIFROST_ADMIN_PASSWORD`,
`SYNTHETIC_API_KEY` in `local.env`, `OLLAMA_API_KEY` from the workstation
projection). `cove bifrost status` names what is missing.

### Allowlisted provider is unreachable

The provider host must appear in `compose/bifrost/dnsmasq.conf`'s
`server=/host/resolver` lines AND in the config's provider `base_url`s under
the same hostname. Everything else NXDOMAINs by design — that is the
fail-closed posture, not a fault. The third contact, `getbifrost.ai`, is the
startup pricing-catalog fetch; removing it crash-loops the gateway (it
exits instead of starting degraded).

### Gateway crash-loops at startup

`docker logs cove-bifrost` — the classic shape is the pricing manager:
`failed to initialize pricing manager ... lookup getbifrost.ai ... no such
host`. The sink's allowlist copy under the data root may be stale after a
pin bump; re-seed `~/Documents/cove-data/bifrost/dnsmasq.conf` from
`compose/bifrost/dnsmasq.conf` and `docker restart cove-bifrost-dns`.

### Sink container restarts

`docker logs cove-bifrost-dns` and validate
`~/Documents/cove-data/bifrost/dnsmasq.conf` with
`docker compose --profile bifrost run --rm bifrost-dns dnsmasq --test -C
/etc/dnsmasq.d/bifrost.conf` (read-only mount: fix the data-root copy, not
the container).