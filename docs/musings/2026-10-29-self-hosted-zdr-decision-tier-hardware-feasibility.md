---
title: "Self-hosted ZDR decision tier: hardware feasibility"
date: 2026-10-29
status: Proposal
thread: thr_3jk4rbhc8u
related:
  - docs/musings/2026-10-29-system-one-classifier-tier-and-zdr.md
  - docs/services/bifrost.md
  - compose/bifrost/config.json
  - compose/bifrost/dnsmasq.conf
---

# Self-hosted ZDR decision tier: hardware feasibility

## The question

The hosted ZDR decision tier is settled on paper: Cloudflare Workers AI serving
Clef is the one provider that is both contractually no-retention on consumer
terms and carryable by Bifrost's built-in Decisions path. The operator chose to
keep that as a written proposal rather than build it. This note answers the other
half: self-hosting is the strongest retention position of all, because no third
party ever sees the prompt. What hardware does the fleet actually have, and can
any of it host a decision model continuously?

The bar is deliberately low. The tier serves short decision calls, roughly 300
input tokens each, a few hundred a day at present. The Cloudflare option costs
about $0.0114 per 1,000 calls and is free up to roughly 9,650 calls a day. So a
self-hosted tier only has to beat "free to a few cents", not a datacentre bill.

## Verdict in one paragraph

No single target can host the model the companion note names. Clef-Flash is a 9B
multimodal model, about 18.2 GB in BF16 and an 11 GB build under Ollama that
Cloudflare sizes for a 16 GB card, and the fleet's only usable GPU is a 12 GB RTX
3060 that already carries image generation. The answer is therefore a qualified
no for Clef-Flash and a qualified yes for a much smaller decision model (Laya at
421M, `tev1:0.8b`, or a 3 to 4B checkpoint), which fits in 1 to 3 GB. The
smallest realistic self-hosted tier puts one of those small models on the T14's
CPU, or on the 3060 behind a hard VRAM reservation that evicts the imagegen
model. Both are workload calls, not hardware impossibilities. Building it buys
the retention position, not money: at this volume the Cloudflare tier is free.

## 1. The hardware we actually have

The HomeLab orchestrator thread (`thr_r282wvvnkf`) was asked directly and
answered with live, read-only probes. Its numbers are the spine of this table;
repo records fill the rest and disagree in two places, noted below. The record
does not use the phrase "hardware target". It organises by hosts and VMs, so
those are the targets here.

| Target | CPU | RAM | GPU / VRAM | On anyway? | Host a small model continuously? |
| --- | --- | --- | --- | --- | --- |
| **Thor** (Proxmox bare metal, `192.168.0.101`) | i7-9700K, 8C/8T | ~77 GB (record) | RTX 3060 12 GB, **passed through to VM 102**, so none on the host | yes | CPU-only only; technically yes, but it is the hypervisor |
| **docker01** (VM 102, `192.168.0.23`) | 4 vCPU (i7-9700K) | 39 GiB visible, 28 available; 15 GiB swap with 7 GiB in use | RTX 3060 12 GB, **~6.2 GiB already resident** (ComfyUI) | yes | No, on the probe reading: swap pressure plus a 4-thread CPU carrying transcodes |
| **bulkstorage01** (VM 100, `192.168.0.18`) | unknown | 20 GB max (4 GB floor) | none | yes | No; storage role, no GPU |
| **Hetzner bastion** (`178.105.167.223`) | 2 vCPU ARM Neoverse-N1 (CAX11) | 3 GiB | none | yes | No; it is the ingress path and has no GPU |
| **T14** (`TBR-T14G5-202609`, `100.83.212.103`) | Ryzen 7 PRO 8840U, 16 threads | 30 GiB total, 22 available | Radeon 780M iGPU (shared memory, ~15 GiB GTT) | yes | **Yes, with care**: CPU inference has trivial headroom, the iGPU is shared with the chat models |
| **Mac workstation** (`<hostname>`, the Cove host) | Apple M3 Pro, 11-core CPU | 36 GB unified | 14-core Apple GPU | no, it sleeps | Technically the most capable; it is the daily driver and not a service host |

Where each fact comes from:

- The orchestrator's probe (`bb thread output thr_r282wvvnkf`, 2026-10-29):
  docker01 at 39 GiB visible with 28 available and 7 GiB of 15 GiB swap in
  residence; the bastion confirmed as ARM CAX11; the T14's Ryzen 7 PRO 8840U and
  30 GiB; the Mac's existence as a target it flagged rather than volunteered.
- The Homelab repo: `docs/ARCHITECTURE.md` (Thor as Proxmox host, 77 GB RAM,
  RTX 3060 12 GB passthrough, VM memory/balloon table, 28 containers),
  `infrastructure/thor/README.md` (VM 102 disk and memory history),
  `docs/musings/jam-sessions/2026-08-16-docker-ps-blocks-jam.md` (the host CPU is
  `i7-9700K`, exposed to the VM with `qm set 102 -cpu host`), and
  `docs/adr/Accepted/(ADR-009)-Imagegen-Upscale-Lane-Local-First-Cloud-Fallback.md`
  (the card is 12,288 MiB, RTX 3060 12.49 GB, 170 W TDP).
- This Mac: `system_profiler`, read locally.

Two disagreements worth keeping honest. The probe corrected the RAM figure for
docker01: the record's "48 GB" is the VM's configured maximum, and about 39 GiB
is what the guest actually sees. And the probe flagged Thor's 77 GB as
record-based and unverified, because it had no non-invasive path to the
hypervisor from its session. It did not run anything on any host and touched no
config.

## 2. What a decision model actually needs

### 2.1 Clef-Flash is 9B, and that is the problem

Clef is Cloudflare's decision model family, released as open weights on
2026-10-01 under Apache 2.0. Both variants are post-trained from a frozen Qwen
backbone plus a rank-256 LoRA and a small joint schema head that scores every
option of every question in one forward pass.

| | Clef | Clef-Flash |
| --- | --- | --- |
| Backbone | Qwen3.8-27B | Qwen3.5-9B |
| Weights, BF16 | ~54 to 55 GB | 18.2 GB |
| Ollama library build | n/a | 11 GB on disk, sized for a 16 GB card |
| Context at full window | 85 GB VRAM (Cloudflare's figure, 64k) | 41 GB VRAM (64k); the shipped code defaults to 16,384 |
| Community quantisation | 4-bit ~14 GB weights | FP8 12 GB, but needs SM 8.9+ |

The RTX 3060 is Ampere, compute capability 8.6. It cannot run the FP8 build
(that needs Ada, Hopper, or Blackwell), its 12,288 MiB cannot hold the 18.2 GB
BF16 weights, and the 11 GB Ollama build leaves almost nothing for KV cache or
vision on a card that is also holding a ~6 GiB imagegen model. So Clef-Flash
does not fit this hardware today at any quantisation, and that is the load-bearing
fact of this note.

### 2.2 Smaller decision models do fit

Bifrost's Decisions capability also carries genuinely small decision models, and
these are the ones the hardware could serve:

| Model | Size | Notes |
| --- | --- | --- |
| Laya | 421M (ModernBERT-large); 322M multilingual | Text and JSON only, 512 to 8,192 tokens context, runs on CPU or GPU, served by `laya-serve` |
| `tev1:0.8b` | 0.8B | Listed by Bifrost as an Ollama decision model |
| `vllm-sr/d3`, `d1-3b` | 3B class | Decision 3.0; supports up to 255 options |
| `kev-4b` | 4B | SGLang decision checkpoints |

At Q4 or Q8 these occupy roughly 0.5 to 3 GB. That is the range the fleet can
actually hold, and it is two orders of magnitude smaller than Clef-Flash. None
of them is Clef-Flash, and none has been benchmarked here against the Cloudflare
Decision Index.

### 2.3 Which Bifrost provider would serve it

The companion note's taxonomy is confirmed against Bifrost's own docs:

- **Built-in `ollama` provider** serves decisions on `POST /v1/systemone`, and
  Ollama is already installed on docker01 at `192.168.0.23:11434`. This is the
  lowest-effort path because Ollama needs no new service. Its key requires
  `ollama_key_config.url`.
- **Built-in `vllm` provider** serves decisions on `/v1/systemone` from vLLM
  v0.32.0, and needs a CUDA 13 build of the image plus `vllm_key_config.url`.
- **Built-in `sgl` (SGLang) provider** serves decisions on `/v1/systemone` from
  v0.5.21; images require v0.5.22 or later.
- **Custom provider on the `typesafe` base** is the shape for a server that is
  none of the above, such as `laya-serve` or Nimble's own SGLang app. This is the
  one that reaches Laya and the smallest models.

Whichever provider is chosen, the tier must carry **no fallback**. A ZDR tier
that falls back to a third party on failure is not ZDR, which is the failure the
tier exists to prevent.

### 2.4 Do the small decision models take images?

A modality is the model's input side, read from its own card or serving docs, not inferred from the family it belongs to. Per model:

| Model | Input | Evidence |
| --- | --- | --- |
| Laya (421M) | **Text only** | A ModernBERT-large encoder plus a decision head, with no vision tower; Bifrost's self-hosted-decision-models page lists its Input as "Text only" and states images are rejected with a `400` before the call |
| `tev1:0.8b` | **Text only** | Ollama's `tev1` library page lists Input "Text" for every tag including `tev1:0.8b`; `state` is a string or JSON, and the 0.8B is a Qwen3.5-0.8B fine-tune |
| `vllm-sr/d3` | **Text, JSON, images, videos** | Hugging Face card `vllm-sr/d3`: "multimodal foundation decision model … input (text or JSON, optionally with images and videos)", with documented `images`/`videos` fields |
| `d1-3b` (Liquid d1-3B) | **Text, JSON, images** | Liquid AI's release lists `d1-3B` as "text + vision" on LFM2.5-VL-3B; the Ollama `d1` page lists Input "vision" and a state of "text, JSON, images" |
| `kev-4b` | **Text only** | OpenRouter's decisions catalogue lists `jaredpalmer/kev-4b` as `input_modalities: ["text"]`; a LoRA and pointer head on Qwen3.5-4B-Base, no vision tower |

One correction falls out of the table: **`vllm-sr/d3` is 27B, not a 3B model**, so it does not fit this hardware. The Decision 3.0 checkpoints that do fit are the smaller siblings — `d3-mini` (4B), `d3-nano` (2B), `d3-lite` (0.8B), and `d3-edge` (0.6B) — and all four accept images and video like the rest of the family.

**Other small decision models that accept images.** Under about 4B, the image-capable set includes `d1-3b` (3.12B, text+vision), the four small Decision 3.0 siblings, Baseten's `baseten/joey-1` (2B, `text+image->decisions`), and Perplexity's `pplx-decider-flash-v1.2` (4B, `text+image`). Text-only peers are just as common: Laya, `tev1:0.8b`, `kev-4b`, Nace.AI's `drex-v1.5`/`v2.0`, and Upstage's `solar-decide`.

**Alias prefix per ADR-008.** An alias leads with its modality, so an image-reading checkpoint takes `vision:` and a text-only one takes `text:`. For the models in §2.2 that fit this hardware, the honest prefix is `vision:` for `d1-3b` and the small Decision 3.0 checkpoints, and `text:` for Laya, `tev1:0.8b`, and `kev-4b`.

The vision capability does not change the hardware verdict — the image-capable small checkpoints fit the same 1 to 3 GB budget as the text-only ones — it only changes the honest alias: name the tier `vision:` if it must answer image decisions the way the shipped Clef tier does, and `text:` if it only ever answers text.

## 3. Target by target

**Thor, the Proxmox host.** The GPU is passed through to VM 102, so a model here
is CPU-only. The i7-9700K with 8 threads and tens of GB of reclaimable RAM can
run a small classifier, and there is no GPU contention. The honest objection is
architectural, not physical: this is the hypervisor, kept to roughly 3.4 GB of
host demand so the VMs get the rest, and adding a resident inference workload
there inverts the design the homelab is built on. The probe called it the "best
candidate" on CPU and RAM grounds alone; read against the architecture, it is the
wrong place to put a service.

**docker01 (VM 102) and the RTX 3060.** This is the only GPU target and the one
that matters. The card can hold a 1 to 3 GB classifier at idle: about 6 GiB is
free while ComfyUI's model idles at 0% utilisation. The problem is residency under
load. ComfyUI's working set peaks near 9 GiB, Plex and Jellyfin throw NVENC and
NVDEC transcode bursts on demand, and Ollama's local models share the same card.
Add a resident classifier and simultaneous load reaches the 12 GB ceiling. The
probe rejected docker01 outright for a different reason: the VM's swap is 7 GiB
of 15 GiB in use, its CPU is 4 threads already carrying transcodes and two
servers, and adding a resident is the wrong pressure. Verdict: **no for a
guaranteed resident; a best-effort or reserved-slice yes if the imagegen model is
capped or evicted first.**

**bulkstorage01.** No GPU, 20 GB max with a 4 GB floor, and a storage role.
**No.**

**Hetzner bastion.** 2 ARM vCPU, 3 GiB, no GPU, and it is the single ingress
path for every Cloudflare-fronted service. Even a CPU-only classifier would
compete with HAProxy on the critical path, and the box is remote from the data.
**No.**

**T14.** The best continuous home in the fleet for a small model. It is always
on, hosting production chat, with 16 threads and 22 GiB available, and a
few hundred 300-token decisions a day is trivial work for its CPU. The iGPU
(Radeon 780M, GTT shared pool) could serve it too, but the GTT holds one model at
a time through llama-swap and the T14 already runs two uncensored local models
(gemma4-12b and gpt-oss-20b) one at a time. A resident classifier is a third
resident, which is a workload-collision call rather than a hardware limit.
Verdict: **yes, with modest care, CPU first.**

**Mac workstation.** An M3 Pro with 36 GB unified memory is the most capable
model host in the fleet and could run Clef-Flash itself. It is also the operator's
daily driver, it sleeps, and it is where Cove and Bifrost already run. A sleeping
host cannot answer a decision call, so it is unsuitable as a service target
without an always-on posture. Verdict: **capable, not suitable.**

## 4. Against the two hosted options

| | Cloudflare Workers AI (Clef) | Shipped Ollama tier (Clef) | Self-hosted small model |
| --- | --- | --- | --- |
| Retention | Contractual no-retention on consumer terms | Transient processing, no fixed window, no consumer opt-out | No third party sees the prompt, by construction |
| Cost at 300-token calls | $0.0114 per 1,000; free to ~9,650/day | ~$0.0114 per 1,000 class | Sunk capex, marginal power near zero |
| Model | `clef` / `clef-flash` (open weights) | `clef` | Laya, `tev1:0.8b`, 3B to 4B checkpoints |
| Capability | Clef-Flash quality, 9B | Clef quality, 27B | Unbenchmarked here, materially weaker than Clef |
| Effort | A token and two config keys | Shipped | A new service, VRAM reservation, model updates, contention |
| ZDR strength | Strong, gateway-gated | Weak | Strongest |

Two changes since the companion note are worth recording. First, Clef and
Clef-Flash are Apache-2.0 open weights, so Cloudflare is serving open models, not
a closed black box; the retention question is about who sees the prompt, not about
model opacity. Second, at a few hundred calls a day the Cloudflare free
allocation covers the traffic outright, so a self-hosted tier at this volume saves
no money. It buys exactly one thing: the guarantee that no third party is in the
path. Whether that is worth a resident service is an operator call, not a
hardware one.

## 5. Recommendation

**Do not try to self-host Clef-Flash on this hardware.** It does not fit the only
GPU in the fleet at any usable quantisation, and a homelab that is already
oversubscribed on that card is the wrong place to force it.

**If a self-hosted ZDR tier is wanted, the smallest viable build is a small
decision model, not Clef-Flash.** The recommended shape:

1. Pick a small open decision checkpoint: Laya (421M), `tev1:0.8b`, or a 3B to 4B
   checkpoint, and record its licence and provenance before serving it.
2. Serve it as a digest-pinned container on the T14, CPU first, so it shares
   nothing with the 3060's imagegen and transcode workload. If the 3060 is
   preferred, cap or evict ComfyUI and reserve a fixed VRAM slice; do not run it
   best-effort on a contended card.
3. Expose it to Bifrost as one new provider with **no fallback**: the built-in
   `ollama` provider if the checkpoint is Ollama-servable, the built-in `vllm` or
   `sgl` provider for a vLLM or SGLang server, or a custom `typesafe`-base
   provider for `laya-serve`.
4. Add the routing rule and the virtual-key grant, and pin the no-fallback
   decision in `cli/tests/test_bifrost.py`, in the same shape the shipped tier
   already uses.

**The lower-effort answer remains the hosted one.** The Cloudflare tier is free
at this volume, contractually no-retention, and a config change rather than a
service. Self-hosting is worth building only if excluding every third party from
the prompt is a hard requirement, which is a decision the retention question
should force explicitly rather than by default.

**If the answer must be Clef-Flash quality self-hosted, the smallest thing that
changes it is a 16 GB or larger GPU in the fleet**, or relaxed expectations from
"resident" to "loaded on demand". Nothing else in the inventory moves that line.

## 6. Unknowns

1. **Thor's RAM** (~77 to 80 GB) is record-based, not live-verified; the probe had
   no non-invasive path to the hypervisor.
2. **Clef-Flash's real footprint at short context on Ampere is untested.** The
   Ollama build is 11 GB and Cloudflare sizes it for a 16 GB card; whether it
   fits 12,288 MiB at a few hundred tokens with KV cache is unknown, and
   Cloudflare's 41 GB figure is measured at 64k context.
3. **Whether stock vLLM serves `Cloudflare/clef-flash` out of the box is
   disputed.** Bifrost's docs say yes from vLLM v0.32.0; a third-party tutorial
   says vLLM does not wire the joint schema head and a community plugin is
   required. Unresolved here; it matters only if Clef-Flash is attempted.
4. **No 4-bit Clef-Flash build has been evaluated.** FP8 needs SM 8.9+, which the
   3060 lacks, and BF16 exceeds 12 GB; whether a usable 4-bit build exists and
   what quality it loses are unverified.
5. **Latency of a small model on the T14 CPU** at 300-token inputs is unmeasured,
   and its iGPU shares a GTT pool with the resident chat models.
6. **Whether Bifrost can reach a LAN model host.** Bifrost runs on the Mac behind
   the dnsmasq DNS choke; whether a plain `192.168.0.x` upstream is permitted or
   needs an allowlist entry is unverified.
7. **Power draw is approximate.** The 3060's 170 W is its TDP, not a measurement,
   and Thor's idle and loaded draw are unknown. The 26¢/kWh all-in figure comes
   from the mining musing, not a bill.
8. **The T14 as a production chat host** already runs 23 containers and two
   resident local models; a third resident is a workload decision, not a hardware
   question, and the operator should own it.
9. **Whether the volume ever exceeds Cloudflare's free allocation** (about 9,650
   calls a day). Below that line, self-hosting saves nothing.
10. **Whether an always-on box is in scope** at all. The Mac sleeps, and the
    standing decision is "bb lives with Cove on this Mac"; a separate always-on
    host would change the picture and is not part of this assessment.

## Evidence table

| # | Claim | Source |
| --- | --- | --- |
| 1 | Verified inventory for Thor, docker01, the bastion, the T14, the Mac, and the NFS VM, with live read-only probe numbers | `bb thread output thr_r282wvvnkf`, 2026-10-29 |
| 2 | Thor is a Proxmox host, 77 GB RAM, RTX 3060 12 GB passed through to VM 102; VM 100 and 102 memory and balloon table; 28 containers | Homelab `docs/ARCHITECTURE.md`; `infrastructure/thor/README.md` |
| 3 | Host CPU is `i7-9700K`, exposed to VM 102 with `qm set 102 -cpu host` | Homelab `docs/musings/jam-sessions/2026-08-16-docker-ps-blocks-jam.md` |
| 4 | Card is 12,288 MiB (RTX 3060 12.49 GB), 170 W TDP | Homelab `docs/adr/Accepted/(ADR-009)-...md` |
| 5 | Clef is 27B, Clef-Flash is 9B (Qwen3.5-9B plus a joint schema head), Apache-2.0, released 2026-10-01 | Hugging Face `Cloudflare/clef-flash`; Cloudflare blog "Introducing Clef" |
| 6 | Clef-Flash Ollama build is 11 GB and sized for a 16 GB card; BF16 weights are 18.2 GB; FP8 quant is 12 GB and needs SM 8.9+ | LumaDock "How to self-host Cloudflare Clef-flash"; `kurcontko/clef-flash-FP8-Dynamic` model card |
| 7 | Bifrost Decisions providers: `ollama`, `vllm` (from v0.32.0), `sgl` (from v0.5.21), plus `typesafe`-base custom providers for `laya-serve` and Nimble | `docs.getbifrost.ai/quickstart/gateway/decisions`, `/providers/supported-providers/vllm`, `/providers/supported-providers/sgl`, `/providers/self-hosted-decision-models` |
| 8 | Small decision models: Laya 421M and 322M, `tev1:0.8b`, `vllm-sr/d3` (3B, up to 255 options), `kev-4b` | Bifrost Decisions and self-hosted-provider docs; LumaDock comparison table |
| 9 | `ollama_key_config.url` and `vllm_key_config.url` are required per key; Ollama already runs on docker01 at `192.168.0.23:11434` | Homelab `docs/ARCHITECTURE.md`; Bifrost vLLM provider docs; companion musing §1.4 |
| 10 | Cloudflare pricing: `clef-flash` $0.038 per M input tokens; 10,000 free neurons per day; ~$0.0114 per 1,000 calls at 300 tokens | Companion musing Part 4; Cloudflare Workers AI model page |
| 11 | Maine electricity is ~26¢/kWh all-in | Homelab `docs/musings/anonymous-infrastructure/beyond-the-hydra-autonomous-model.md` |
| 12 | The T14 runs 23 containers and two resident local models behind llama-swap on a shared GTT pool | Homelab `docs/ARCHITECTURE.md`; `docs/musings/2026-09-13-ai-chatbot-t14-in-house-migration.md` |
| 13 | This Mac is an Apple M3 Pro, 11-core CPU, 36 GB unified memory | `system_profiler` on the workstation |
| 14 | Laya (421M) is a ModernBERT-large encoder plus a decision head with text/JSON input only; Bifrost rejects images with a `400` | Bifrost docs `/providers/self-hosted-decision-models`; Laya model card `convaiinnovations/laya` (Hugging Face) |
| 15 | `tev1:0.8b` is text-only; the `tev1` family lists Input "Text" for every tag and is a Qwen3.5 fine-tune in 4B and 0.8B sizes | Ollama library `/library/tev1`; OpenRouter decisions catalogue `togethercomputer/tev1-4b-experimental` (`input_modalities: ["text"]`) |
| 16 | `vllm-sr/d3` is a 27B multimodal decision model (text, JSON, images, videos); the fitting Decision 3.0 members are `d3-mini` (4B), `d3-nano` (2B), `d3-lite` (0.8B), `d3-edge` (0.6B), all image-capable | Hugging Face card `vllm-sr/d3`; vLLM recipes `/vllm-sr/d3` and `/vllm-sr/d3-edge`; MarkTechPost "What is Decision 3.0" |
| 17 | Liquid `d1-3B` is a 3.12B text+vision decision model on LFM2.5-VL-3B; `kev-4b` is text-only | Liquid AI d1 release; Ollama library `/library/d1`; OpenRouter decisions catalogue `jaredpalmer/kev-4b` (`input_modalities: ["text"]`) |
| 18 | Small image-capable decision models under ~4B include `baseten/joey-1` (2B) and `perplexity/pplx-decider-flash-v1.2` (4B), both `text+image->decisions` | OpenRouter models API `?output_modalities=decisions` (fetched 2026-10-29) |
