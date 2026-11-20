# Edge secrets check (observe-only)

**Status: observe-only. In front of Bifrost, measuring; nothing blocks.** This
is the build the operator ruling `dec_8trphpel0p3c` ordered after the spike:
four measured incidents were the same shape — an agent put tool output into a
prompt and a credential went to a model provider — so a secrets check goes in
front of the gateway, ahead of any semantic prompt-injection filter.

The measurement that justifies the shape is
[the spike](../musings/2026-11-19-edge-secrets-check-spike.md): the repository's
own rules caught 4 of 6 leaked shapes, two added rules reach 6 of 6 with no
false positive on six ordinary-prompt negatives, and a fresh `gitleaks` process
per scan costs a median 246 ms.

## Placement: a sidecar, not a Bifrost plugin

Bifrost v2.3.2 **does** have a request-body plugin surface. Its documented Go
plugin hooks (`PreLLMHook`, `HTTPTransportPreHook`) can read and even rewrite a
request body, which is the in-process placement the spike recommended.

It is not usable on this deployment. The official `maximhq/bifrost` image is
statically linked (`-extldflags '-static'`), so `plugin.Open` is unsupported and
a Go plugin cannot load — a finding recorded twice already
([Headroom decision](../musings/bifrost-headroom-decision.md),
[System One tier](../musings/2026-10-29-system-one-classifier-tier-and-zdr.md)).
Getting the plugin route would mean building and maintaining our own Bifrost
image, which breaks the digest pin and the vendor-update hold that are the
gateway's supply-chain anchors, and it would tie Cove-owned code to Bifrost's
internal core version. `compose/docker-compose.yml` pins Bifrost by digest and
this change does not touch that service definition.

So the check runs as a **long-lived sidecar**: a small reverse proxy in front of
the gateway that holds the rule engine warm in-process. Same property the plugin
would have given (no per-request process), without a custom gateway image.

- **Code**: `compose/secrets-guard/` (Go; the gitleaks rule engine as a library,
  pinned to the same release as the commit-hook gate).
- **Service**: the `secrets-guard` compose service, its own `secrets-guard`
  profile. `cove up` and `cove bifrost up` never start it.
- **Tests**: `cd compose/secrets-guard && go test ./...` for runtime behaviour;
  `cli/tests/test_secrets_guard.py` for the wiring and the single-source ruleset.

### Latency, measured

Warm engine, an M3 Pro, prompt-sized bodies. A fresh `gitleaks` process per scan
was 246 ms before reading a byte; this is what the request path actually pays:

| body | scan cost |
| --- | --- |
| one-line prompt with no credential keyword | ~0.02 ms |
| 100 KB prose, no keyword | ~0.35 ms |
| 1 MB prose, no keyword | ~3.7 ms |
| 100 KB of code-shaped text mentioning `api key`/`token` often | ~20 ms |
| 1 MB of the same | ~230 ms |

The expensive rows are gitleaks' default `generic-api-key` rule, which is
super-linear on a long single line, and a JSON body is one long line. That is
why `SECRETS_GUARD_MAX_BODY_BYTES` defaults to 4 MiB (above any real prompt this
ladder serves): a body over the cap is forwarded **unscanned** and logged as
`scan_skipped`, so the gap is visible in the measurement instead of looking like
a clean request.

## What it sees, and what it does not

It sees **model traffic only**: the raw bytes of every request body that reaches
the scanner, which for this gateway is the OpenAI-compatible JSON body —
`messages` content, tool output an agent pasted into a prompt, inline images.
That is where all four measured leaks travelled.

It does **not** see:

- a credential printed to an agent's transcript and never sent to a provider —
  the edge is not in that path, which is why the transcript-side control and the
  rotation habit stay;
- response bodies (it only reads requests; responses stream through untouched);
- traffic that does not reach it. Nothing routes client traffic through the
  scanner yet: the client path (`llmproxy.cove`) is deliberately untouched in
  this change. See "Turning it on" below.

Its rules are the repository's **one** `.gitleaks.toml` — the same file the
commit-hook gate reads — promoted with the two shapes the spike found missing
(a bare 40-hex Forgejo/Gitea token near a credential keyword, and `sk-proj-`
keys). The image carries no ruleset: the container mounts the wheel's generated
copy from `${COVE_DATA_ROOT}/secrets-guard/gitleaks.toml`, produced from
`.gitleaks.toml` at wheel build time and never hand-edited. One image works with
any ruleset, and an operator can read the exact rules in force instead of
trusting a layer.

## Observe-only, concretely

Every request is forwarded **byte-identical** to the backend. There is no code
path that alters, truncates, redacts, or rejects a request because of a hit. The
Go suite proves it: the sent body is compared with the body the backend received
for all twelve fixtures, and a stream is checked to reach the client while the
backend is still writing.

Hits are written as JSON lines on stdout, one object per line, and **never
carry the matched text**:

```json
{"ts":"2026-11-19T21:04:11.118Z","event":"request","method":"POST","path":"/v1/chat/completions","bytes":8421,"hits":1,"scan_ms":3.1}
{"ts":"2026-11-19T21:04:11.118Z","event":"secret_hit","method":"POST","path":"/v1/chat/completions","rule":"forgejo-token-context","fingerprint":"9f2c41ab07de","offset":5182}
```

- `rule` is the gitleaks rule id.
- `fingerprint` is the first 12 hex characters of SHA-256 over the matched
  value. Same credential, same fingerprint — so repeats can be counted across
  requests without storing the value.
- `offset` is the byte offset of the rule's match in the body. For a
  `secretGroup` rule that is the keyword, not the captured secret.
- `request` is the denominator: `hits` over requests is the false-positive rate
  the observation phase exists to measure.

Other lines: `scan_skipped` (`body_too_large`), `upstream_error` (transport
error text only), `body_read_error` (the request body could not be read, so it
could not be forwarded intact either), `startup` (rules path and count,
upstream, log mode, size cap).

Log modes (`SECRETS_GUARD_LOG`): `all` writes the request line and hit lines,
`hits` writes only hitting requests, `off` writes only skips and errors, so a
silent log is never mistaken for a clean one.

## Running it

```bash
cove secrets-guard up       # seed the ruleset, build, start (profile: secrets-guard)
cove secrets-guard status   # container state + posture
cove secrets-guard logs -f  # the JSON lines above
cove secrets-guard down     # stop; Bifrost is untouched
```

`up` publishes the scanner on `127.0.0.1:4003` (override with
`SECRETS_GUARD_PORT`) and forwards to `http://bifrost:8080`. The first `up`
builds the image locally, so the Go module download needs network once;
afterwards the build cache makes it a no-op.

`cove secrets-guard up` refuses loudly if the generated ruleset is missing from
the compose dir, which means the wheel was built before this change or a source
checkout has not run `python3 cli/scripts/sync_compose_resources.py`.

### Turning it on (observation, not blocking)

Nothing routes to the scanner until you point something at it. The least
invasive way to collect real evidence is to re-point **one** client or probe:

```bash
curl -sS http://127.0.0.1:4003/v1/chat/completions \
  -H "Authorization: Bearer $BIFROST_CLIENT_VIRTUAL_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"model":"text:light","messages":[{"role":"user","content":"hello"}]}'
```

That request is forwarded to Bifrost unchanged and logged. To measure the whole
gateway, point the client-facing endpoint at the scanner — the
`$llmproxy_upstream` line in `compose/nginx/default.conf.j2` — and re-render
nginx. That is a deliberate, separate change: it puts the scanner in the
production request path, so it is not part of this build, and this change leaves
`llmproxy.cove` and the Bifrost service definition alone.

## From observe-only to blocking

Blocking is a **later decision with its own evidence**, not a switch in this
build. The evidence it needs is the false-positive rate from this phase: how
often `secret_hit` fires on a request nobody would call a leak, and which rules
produce it. The `request` line is the denominator; `fingerprint` groups repeats
of one value without exposing it.

When that evidence says the rate is acceptable, the change is small and has a
known shape:

1. Add a policy mode to the scanner (`SECRETS_GUARD_MODE=observe|block`) whose
   only new act is answering the request with a policy status instead of
   forwarding it (a `4xx` that names the rule ids and never echoes the body).
   Redaction is the other option and a harder one: it rewrites the prompt, so it
   needs its own ruling about what the model is allowed to see.
2. Decide the failure posture: fail-open (a scanner error forwards) or
   fail-closed (a scanner error refuses). An observe-only proxy can fail open;
   a blocking one cannot decide that implicitly.
3. Point the client endpoint at the scanner first, in observe-only, and watch
   one clean week of `secret_hit` lines before flipping the mode.

Until then the layers that cover what the edge cannot see stay: the transcript
control and the rotation habit.

## Limits

- **Request bodies only.** A secret that only ever appears in a response, or in
  a local transcript, is out of scope by construction.
- **4 MiB scan cap** (`SECRETS_GUARD_MAX_BODY_BYTES`, overridable). Over-cap
  bodies are forwarded unscanned and logged.
- **Encoded payloads**: the raw body is scanned, so a credential inside
  base64 or a nested archive is not decoded. That is the same coverage the
  commit-hook gate has.
- **One process, one rule load.** gitleaks' config loader cannot extend its
  default rules twice in one process, so the scanner refuses a second, different
  ruleset loudly rather than serving a partial rule set.
- **No response inspection, no body retention.** Nothing but the values above is
  written anywhere.

## Troubleshooting

### The container exits at start

`cove secrets-guard logs` names the cause. The usual one is a missing ruleset:
the mount is `${COVE_DATA_ROOT}/secrets-guard/gitleaks.toml`, seeded by
`cove secrets-guard up` (and by `cove up`). If the file is absent from the
wheel, the source checkout needs `python3 cli/scripts/sync_compose_resources.py`.

### Every request is 502

The gateway is not reachable at `http://bifrost:8080`. The scanner has no
`depends_on` on Bifrost on purpose (they are in different profiles), so start
Bifrost first; each failed request logs an `upstream_error`.

### `scan_skipped` on long prompts

The body is over `SECRETS_GUARD_MAX_BODY_BYTES`. Raise it if those requests need
coverage, and read the latency table above first: the scan is synchronous and
keyword-dense code is the expensive case.
