# secrets-guard — observe-only secrets check for the Bifrost edge

A transparent reverse proxy that scans request bodies against the repository's
one `.gitleaks.toml`, logs what it finds without the matched text, and forwards
every request to the backend unchanged.

The image ships no ruleset: the rules are mounted read-only from
`${COVE_DATA_ROOT}/secrets-guard/gitleaks.toml`, seeded from the wheel by
`cove secrets-guard up` and by `cove up`. It never blocks and never rewrites.

It exists because four measured incidents were the same shape: an agent put tool
output into a prompt and a credential went to a model provider. The spike that
measured detection, false positives, and latency is
[`docs/musings/2026-11-19-edge-secrets-check-spike.md`](../../docs/musings/2026-11-19-edge-secrets-check-spike.md);
the operator-facing page is
[`docs/services/secrets-guard.md`](../../docs/services/secrets-guard.md).

## Why a sidecar and not a Bifrost plugin

Bifrost v2.3.2 does have a request-body plugin surface (`PreLLMHook`,
`HTTPTransportPreHook`), but the official `maximhq/bifrost` image is statically
linked (`-extldflags '-static'`), so `plugin.Open` is unsupported and a Go plugin
cannot load. Using it would mean building and maintaining our own Bifrost image,
which breaks the digest pin that is the deployment's supply-chain anchor. A
long-lived sidecar keeps the same in-process engine (no per-request process) and
leaves the pinned gateway untouched. The full argument is in the service docs.

## Run the tests

```bash
cd compose/secrets-guard
go test ./...            # correctness
go test -bench . -benchtime 200x ./...   # latency evidence
```

`go test` needs the repository tree: the fixtures live in
`scripts/spikes/edge-secrets/corpus/` and the ruleset is the repo's
`.gitleaks.toml`. Both are host-only, which is why `*_test.go` is excluded from
the image build context.

## What the measured scan costs

`go test -bench` on an M3 Pro, warm engine, prompt-sized bodies wrapped the way
real traffic wraps them:

| body | cost |
| --- | --- |
| one-line prompt, no credential keyword | ~0.02 ms |
| 100 KB prose, no keyword | ~0.35 ms |
| 1 MB prose, no keyword | ~3.7 ms |
| 100 KB code-shaped text mentioning `api key`/`token` often | ~20 ms |
| 1 MB of the same | ~230 ms |

The last rows are the default `generic-api-key` rule, which is quadratic-ish on
a long single line. That is why `SECRETS_GUARD_MAX_BODY_BYTES` defaults to 4 MiB:
a body over the cap is forwarded unscanned and logged as `scan_skipped`. A fresh
`gitleaks` process per scan, by contrast, cost a median 246 ms before reading a
byte.

## Environment

| variable | default | meaning |
| --- | --- | --- |
| `SECRETS_GUARD_UPSTREAM` | — (required) | backend base URL, e.g. `http://bifrost:8080` |
| `SECRETS_GUARD_LISTEN` | `:8080` | listen address inside the container |
| `SECRETS_GUARD_RULES` | `/etc/secrets-guard/gitleaks.toml` | ruleset path |
| `SECRETS_GUARD_MAX_BODY_BYTES` | `4194304` | scan cap; larger bodies are forwarded unscanned and logged |
| `SECRETS_GUARD_LOG` | `all` | `all` (request + hit lines), `hits`, or `off` |

## Log lines

One JSON object per line on stdout. No field can hold matched text, a body, or a
header:

- `secret_hit`: `rule`, `fingerprint` (first 12 hex of SHA-256 over the matched
  value), `offset` (byte offset of the rule match in the body), `method`, `path`.
- `request`: `bytes`, `hits`, `scan_ms`, `method`, `path` — the denominator for
  a false-positive rate.
- `scan_skipped`: `reason` (`body_too_large`), `bytes`.
- `upstream_error`: `error` (the transport error, never the body).
- `startup`: `rules`, `rules_count`, `upstream`, `mode`, `max_bytes`.

## Subcommands

- *(none)* — serve.
- `healthcheck` — GET the local `/healthz`; used as the container healthcheck.
- `scan --config PATH` — scan stdin once and print hit JSON. Useful for proving
  a ruleset on demand; never used on the request path.
