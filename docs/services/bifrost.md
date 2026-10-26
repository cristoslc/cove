# Bifrost Gateway for Cove

**Status: additive replacement candidate.** Bifrost runs alongside the live
LiteLLM services on the `bifrost` compose profile. Nothing is removed, no
client is re-pointed, and the cutover is gated on four pending operator
decisions (see the Cutover checklist at the bottom). Design and evaluation:
[the LiteLLM exit musing](../musings/litellm-exit.md).

- **What it is**: [Bifrost](https://github.com/maximhq/bifrost) (Bifrost
  transports v2.3.2), an OpenAI-compatible LLM gateway with config-file
  governance, virtual keys, and ordered fallback routing. It carries the same
  model ladder LiteLLM serves today, re-expressed as Bifrost routing rules with
  fallback chains.
- **Where it lives**: https://bifrost.cove/ and https://bifrost.cove.local/
  through nginx (loopback port bind `127.0.0.1:4002`). The dashboard is
  protected by the shared Cove Admin identity (ADR-017).
- **Client traffic**: none. LiteLLM remains the agent traffic path during the
  additive phase; the workstation lane decides when clients re-point.

## Quick Start

```bash
cove bifrost up        # provisions credentials, seeds runtime files, starts
cove bifrost status    # health + credential wiring (names only)
cove bifrost logs -f   # tail logs
cove bifrost down      # stop (data preserved)
```

`cove up` never starts Bifrost as a side effect — it is deliberately absent
from `_start_optional_services()` until the cutover is decided.

## Configuration ownership

IaC-first, with the same split as LiteLLM:

- **`compose/bifrost/config.json`** (git-tracked): the governance source. It
  carries `source_of_truth: "config.json"`, the auth settings, the three
  custom provider instances, the single virtual key, and the nine tier
  routing rules. Seeded to `~/Documents/cove-data/bifrost/config.json`
  (first boot only; operator edits preserved, wedge-guarded).
- **`config.db`** (SQLite runtime store): **must pre-exist before the first
  container boot** — a file-only boot cannot carry governance. Bringup and
  `cove bifrost up` both seed it as an empty, valid SQLite file (`0600`,
  never recreated when present). Bifrost mounts it writable and manages its
  contents; with `source_of_truth: "config.json"`, file sections stay
  authoritative.
- **`dnsmasq.conf`** (git-tracked): the egress allowlist (see Security
  posture). Seeded first boot only.
- **`local.env`**: the Synthetic subscription key (`SYNTHETIC_API_KEY`), same
  pattern as LiteLLM's local.env. Created empty (`0600`), never overwritten.
- **The ollama-cloud key** is NOT Cove's to hold (workstation-lane ownership
  ruling, 2026-10-26): the workstation's SOPS role projects
  `OLLAMA_API_KEY` into the deployed compose `.env`, and the compose service
  passes it through — exactly as the LiteLLM services receive it today.

## The model ladder

The nine tier aliases re-express as CEL routing rules (`model == '<tier>'`)
with ordered fallback chains. Chain order is the spend-first order:
Synthetic subscription (1), ollama-cloud metered (2), the infinite
backstop (3). Wire ids are unchanged from the LiteLLM configuration.

| Tier id | Chain (in order) |
| --- | --- |
| `text:light` | syn-subscription `hf:zai-org/GLM-4.7-Flash` → ollama-cloud `gpt-oss:120b` → backstop `infinite:small:vision` |
| `text:standard` | syn-subscription `hf:deepseek-ai/DeepSeek-V4.1-Flash` → ollama-cloud `deepseek-v4.1-flash` → backstop |
| `text:ultra-heavy` | syn-subscription `hf:zai-org/GLM-5.3` → ollama-cloud `glm-5.3` → backstop |
| `vision:heavy` | syn-subscription `hf:zai-org/GLM-5.3-Flash` → ollama-cloud `glm-5.3-flash` → backstop |
| `vision:super-ultra-heavy` | syn-subscription `hf:moonshotai/Kimi-K3` → ollama-cloud `kimi-k3` → backstop |
| `nonstreaming:text:light` | syn-subscription → ollama-cloud (2 hops, no backstop) |
| `nonstreaming:text:standard` | syn-subscription → ollama-cloud (2 hops, no backstop) |
| `syn:large:text` | syn-subscription directly (1 hop) |
| `infinite:small:vision` | syn-infinite-backstop directly (1 hop) |

The infinite backstop is a **separate custom provider instance** pointing at
the same Synthetic endpoint, gated to `chat_completion_stream` only via
`allowed_requests`. That makes the streaming-only restriction structural: a
non-streaming request cannot reach the instance at all (verified in the live
smoke test — nothing reaches upstream). The non-streaming tiers simply omit
the backstop from their chains. This closes the LiteLLM gap where a
streaming-only backstop had to be trusted to configuration discipline.

## What's Hardened

- **Digest-pinned image**: `maximhq/bifrost:v2.3.2` pinned to its multi-arch
  manifest digest (overridable via `BIFROST_IMAGE` only with the full
  tag+digest pair; the compose default carries both).
- **Inference auth enforced by default**: `client.enforce_auth_on_inference`
  is `true`, dashboard auth enabled, `disable_auth_on_inference` false. A
  missing virtual key gets 401 (live-smoke verified). The single virtual key
  (`env.BIFROST_VIRTUAL_KEY`) is allowed on all three instances.
- **Request-body logging OFF** (adoption gate): `client.enable_logging:
  false`, `disable_content_logging: true`,
  `allow_per_request_content_storage_override: false`, and `logs_store`
  disabled entirely. Declared in IaC, pinned by tests.
- **Egress allowlist (DNS choke)**: the gateway's `dns:` is pinned to
  `cove-bifrost-dns` (172.43.0.10), a minimal dnsmasq sink on the dedicated
  `bifrost-egress` network (172.43.0.0/24, outside Docker's default pools).
  The sink is read-only, caps-dropped except `NET_BIND_SERVICE`, publishes
  no ports, and NXDOMAINs every name except `api.synthetic.new` and
  `ollama.com` (`compose/bifrost/dnsmasq.conf`). **Caveat**: DNS enforcement
  does not stop direct-IP egress; the digest pin and the vendor-update hold
  are the anchors there.
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

## Virtual key auth re-check (file-seeded VK)

The spike found a file-seeded virtual key failing to authenticate while an
API-created one worked. **Outcome at implementation (v2.3.2): the file-seeded
virtual key authenticates correctly.** The live smoke proves both halves:
a request without a virtual key gets 401 (auth enforced), and a request
bearing the `env.BIFROST_VIRTUAL_KEY` value passes governance and reaches the
routed provider. No workaround is needed; `source_of_truth: "config.json"`
plus the pre-seeded store is sufficient.

## Commands

`cove bifrost up` — provision credentials (1Password `Bifrost Gateway` item:
config-store encryption key, dashboard admin password, client virtual key;
the admin username comes from the shared Cove Admin item, ADR-017), seed the
runtime files, and start the profile (`up -d --build`, the sink image is
built locally).

`cove bifrost status` — compose ps, credential-wiring booleans (SET/missing,
names never values), and the nginx health probe.

`cove bifrost down` / `cove bifrost logs [-n N] [-f]` as for other optional
services.

## Architecture

```
clients (later phase) ──https──> nginx :443
                     bifrost.cove ─> bifrost :8080 (127.0.0.1:4002)
                                       │  config.json (ro) + config.db (rw)
                                       │  env_file local.env + compose .env
                                       ▼
                            DNS: cove-bifrost-dns (allowlist sink) ──> only api.synthetic.new, ollama.com
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

## Cutover checklist (NOT executed in the additive phase)

The following steps exist only when the operator decides to cut over. Four
decisions are **pending** and owned by the operator — annotated here, not
made:

1. [Pending decision 2 of the musing] **pgdata disposal** — secure-delete the
   LiteLLM pgdata volume vs. age-encrypted archive + retention period.
2. [Pending decision 3 of the musing] **Key-rotation timing** — rotate the
   Synthetic and ollama keys at cutover vs. after the rollback window closes.
3. [Pending decision 4 of the musing] **1Password `LiteLLM Proxy` item** —
   delete at teardown vs. keep one release for the rollback window.
4. [Pending decision 5 of the musing] **Drain window length** — one week
   proposed in the musing; length still to be confirmed.

After the four decisions: re-point clients (workstation lane controls this),
stop and disable the `litellm` profile, teardown the pgdata per decision 2,
and remove the `LiteLLM Proxy` 1Password item per decision 4.

## Troubleshooting

### Gateway won't start

`docker logs cove-bifrost` — most commonly a missing credential: every
`env.*` reference in `config.json` must resolve (`BIFROST_ENCRYPTION_KEY`,
`BIFROST_ADMIN_USERNAME`, `BIFROST_ADMIN_PASSWORD`, `BIFROST_VIRTUAL_KEY`,
`SYNTHETIC_API_KEY` in `local.env`, `OLLAMA_API_KEY` from the workstation
projection). `cove bifrost status` names what is missing.

### Allowlisted provider is unreachable

The provider host must appear in `compose/bifrost/dnsmasq.conf`'s
`server=/host/resolver` lines AND in the config's provider `base_url`s under
the same hostname. Everything else NXDOMAINs by design — that is the
fail-closed posture, not a fault.

### Sink container restarts

`docker logs cove-bifrost-dns` and validate
`~/Documents/cove-data/bifrost/dnsmasq.conf` with
`docker compose --profile bifrost run --rm bifrost-dns dnsmasq --test -C
/etc/dnsmasq.d/bifrost.conf` (read-only mount: fix the data-root copy, not
the container).