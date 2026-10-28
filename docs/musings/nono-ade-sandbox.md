# Muse: nono as a sandbox layer in Cove's ADE stack

**Date:** 2026-10-28
**Trigger:** review of SPIKE-017 (`bb/nono agent sandbox`, draft PR #143 in the workstation repo) — does a kernel-enforced process sandbox belong in Cove's ADE?
**Spike:** `docs/research/Active/(SPIKE-017)-nono-agent-sandbox-for-bb/` (branch `bb/nono-agent-sandbox-spike-thr_ces8x6i2qm`, Forgejo PR #143, draft)
**Rubric:** ADR-016 (Two-Tier Service Adoption Rubric), ADR-018 (ADE and its execution modes), PURPOSE.md (Low-Isolation, Low-Friction; Self-Contained)
**Method:** read the spike note and its profile/launcher; read the bundled Modal Sandbox skill (bb `0.47.1`), ADR-016/018, `docs/services/ade.md`, the Forgejo runner compose entry; then measured the spike's profile with nono `0.80.0` on macOS/Seatbelt, read-only, no stack touched.

## Recommendation in one paragraph

**Adopt later, and not as a default.** The spike's seam is real and cheap — a launcher behind an ACP provider entry, no bb change — but the *policy* it ships is not safe to adopt: measured, the drafted grant list lets a sandboxed agent read every Cove service credential, the local CA private key, and the decrypted SOPS secrets sitting in the checkout. A narrowed profile that keeps the agent working and closes those reads is straightforward and is drafted in §3. Even then, nono bounds what the agent's own syscalls touch, not what the agent can get its harness to do: from inside the sandbox, the bb daemon answered an unauthenticated API call, so the work the agent cannot do itself it can still ask for. The sandbox is worth having eventually as the on-host capability layer under the container step-up that ADR-018 already plans; it is not worth shipping before Phase 2 enrollment is live-verified and the grant list is rewritten from "what broke first" to "what is minimal".

If the operator does adopt it, the first seam is the **ACP agent launch on the machine that runs threads**, one opt-in provider id, default off — never a `cove ade` flag, never a compose change.

---

## 1. Two different questions: *where* a thread runs vs *what* it may touch

`environment-modal-sandbox` is an official bb environment provider: it allocates a Modal Sandbox (gVisor or a VM runtime, per Modal docs), runs the bb daemon inside it, clones the project there, and snapshots the filesystem on idle pause. It changes **where** a thread runs and destroys the machine when the thread retires. nono changes **what a process on the machine may reach**, on the same kernel, as the same user, with the same filesystem.

They answer different questions, so neither substitutes for the other:

| Threat | Local thread today | nono on host | Modal machine |
|---|---|---|---|
| Prompt-injected agent reads `~/.ssh`, `~/.aws`, decrypted secrets, service `.env` files | No barrier (the agent runs as the operator) | **Yes** — deny-by-default outside the grant list | **Yes** — different filesystem; host home is absent |
| Agent writes outside its worktree | No barrier | **Mostly** — writes limited to grants; `unlink_protection` allows deletes inside writable grants | **Yes** — only the sandbox filesystem exists |
| Exfiltration of what it can read | No barrier | **Only if egress is restricted**; the spike's profile leaves network open | Partly — the sandbox has its own egress; anything injected into its env is exfiltratable |
| Hostile dependency or `postinstall` running arbitrary code | No barrier | Partly — children inherit the same sandbox, so they are bounded by the same grants | **Yes** — damage stays in the machine |
| Repo-supplied provisioning code (`.bb-env-setup.sh`) | Runs as the daemon, before the agent | **No** — the hook runs before the sandbox exists | **Yes** — runs inside the machine |
| Kernel exploit, or a same-user compromise | No barrier | **No** — nono is a capability model, not a VM model, and it says so | **Yes** — gVisor/VM boundary |
| Agent asks the harness to do the work | n/a | **No** — measured below: the bb API is reachable and unauthenticated from inside the sandbox | Partly — the daemon inside the machine is still a delegation path, but it only commands that machine |
| Persistence (launchd, shell rc, PATH planting) | No barrier | Partly — those paths are not granted, but a writable grant on a `PATH` entry reopens it | **Yes** — machine destroyed |

**What overlaps:** filesystem confinement, credential-env scrubbing, network egress, audit — all four appear in both, at different layers: Modal is a perimeter, nono is a capability system.

**What composes:** everything. nono's own security model documents "nono inside a container or microVM" as a supported shape (fine-grained policy inside a coarse perimeter). A Cove execution-machine container with nono inside it is a coherent future target; a Modal machine with nono inside it is the same idea.

**What nono does not add for locally-run threads,** stated plainly because the temptation is to treat "sandboxed" as "safe":

- No separate kernel or user boundary. A kernel bug, or any process already running as the operator, is outside its reach.
- No protection from anything the profile already grants — and today's drafted profile grants a great deal (§3).
- No protection from the harness. The agent can call `bb`, which spawns unsandboxed work (§3, measured). The harness's neighbours — the Forgejo runner, the Docker socket, MCP servers under ToolHive — are separate processes it can reach only if a grant says so; the danger is that a grant reaching them is exactly the shape the spike's list starts with.
- No protection of the setup hook: `.bb-env-setup.sh` runs in the daemon's environment at thread creation, so a hostile repo executes before the sandbox is applied.
- No coverage of `bb terminal` PTYs, which the daemon creates outside the agent's process tree.

The honest one-line summary: nono makes a local thread *less able to read things it has no business reading*; it does not make a local thread *contained*.

---

## 2. Placement in Cove's ADE stack

The ADE is a server plus machines. `cove-ade-server` stores threads, the database, and settings in a container; agents run on enrolled machines, as children of each machine's bb daemon. Today the Mac is not enrolled to the Cove ADE at all — it runs its own bb server and is its own machine. So "the ADE stack" for sandbox purposes is *the machine daemon*, wherever it points.

| Candidate seam | Fit | What would change | Out of scope |
|---|---|---|---|
| **ACP agent launch (per-agent provider entry)** | **Strong.** Proven end to end by the spike: `customAgents` entry whose `command` is a launcher that execs `nono run --profile … -- opencode acp`. No bb code, no provider change, one new provider id, default off. | Ship a profile + launcher as Cove artifacts; document the one-line registration; add a doctor that proves the profile against the real symlink/TLS surface. | bb's own launch path, other providers, the built-in `acp-opencode` id. |
| **CI (Forgejo runner jobs)** | **Poor.** Jobs already run in disposable sibling containers; the real exposure is the runner's read-write Docker socket mount, which is not a child process of anything nono could wrap. | Nothing worth doing at this seam. | Runner hardening (socket-less runners, rootless Docker) is a separate question with a much bigger payoff. |
| **Dev environments / worker sandboxes (Phase 3 machine containers)** | **Good, later.** A Cove-provisioned machine container is exactly the "nono inside the outer boundary" shape nono recommends. | Machine image gains nono + a profile; policy becomes part of the image rather than an operator step. | Phase 3 itself; this brief assumes it lands. |
| **`cove ade` policy selection** | **Premature and misleading.** The server does not run agents, and ADR-018 states Cove does not govern the operator's own host. A policy flag on `cove ade` would appear to control threads it cannot reach. | Nothing now. If Phase 3 ships, policy travels with the machine image, not with `cove ade`. | New subcommands, new compose env, new `.env` pins. |

**First seam: the ACP agent launch, on one machine, opt-in.** Reasons:

- It is the only seam where the process nono wraps is the process that actually runs the agent.
- It is the only seam that needs no new Cove service, no compose change, and no new default.
- It fails safe for the rest of the stack: an absent nono, a bad profile, or a denied path breaks one provider, not the harness.

Two Cove-specific wrinkles that belong in any adoption note:

1. **The registration is not IaC.** `customAgents` lives in the machine's bb data dir (`bb plugin config provider-acp set customAgents …`), not in a repo. Cove's IaC bias is satisfied for the profile and launcher (wheel resources, data root) and *not* for the registration — that stays a documented runbook line, like the Phase 2 enrollment cutover.
2. **The host is not Cove's to govern.** ADR-018: "the host is the operator's own device; cove does not govern it". Installing nono on the Mac is a host change the operator accepts, as the spike's note already records. Cove can ship the artifacts and the documentation without claiming authority over the machine.

---

## 3. Policy and grant model

### What the spike's list is, and is not

The spike's grant list is ordered by *when it broke* — correct for a proof, wrong for a policy. Measured with nono `0.80.0` and the spike's profile as written, a sandboxed process could read:

| Read inside the spike sandbox | Why it is there | Why it should not be |
|---|---|---|
| `~/.config/cove/compose/.env` | grant `~/.config/cove` for the CA | Holds the LiteLLM master key, UI and Speedtest passwords, provider keys, Bifrost keys |
| `~/.config/cove/pki/rootCA-key.pem` | same grant | The local CA **private key** — mints a trusted cert for any `*.cove` name |
| `~/.bb/bb.db` | grant `~/.bb` for the CLI and worktree | Thread history and state; the worktree is already covered by `--allow-cwd` |
| `~/.config/opencode/.env` | grant `~/.config/opencode` for symlink lookups | Provider API keys |
| `<checkout>/shared/secrets/.decrypted/vars.yml` | grant of the whole main checkout | Plaintext SOPS secrets that a decrypt run leaves behind |
| `~/.ssh/config` (via symlink) | same checkout grant | Dotfiles are symlinked out of `~/.ssh`; the *target* is in the granted tree, so the `~/.ssh` deny does not see it |

That last row is the mirror image of the spike's symlink trap, and the more dangerous half: **a deny on a directory does not cover a symlinked file whose target sits in a granted tree.** Granting the checkout re-admits every dotfile the operator symlinked out of a denied location.

None of this is a defect in nono. It is what a "make it work first" grant list looks like.

### What a Cove agent genuinely needs

| Need | Narrowest grant | Note |
|---|---|---|
| The ACP agent binary | read `~/.opencode` | entry point and `node_modules` |
| Session, auth, state, cache | rw `~/.local/share/opencode`, `~/.cache/opencode`, `~/.local/state/opencode` | provider login lives here; that is the agent's own credential |
| opencode config | read `~/.config/opencode` (the link directory) | directory grant is required by the symlink rule; deny the `.env` inside it |
| git config | read `~/.config/git` (the link directory) | no secrets; needed for `git status` and commit identity |
| Cove CA for `https://litellm.cove` | read **files** `~/.config/cove/pki/rootCA.pem` and `ca-bundle.pem` | never the directory |
| bb CLI | read `/Applications/bb.app`, `~/.local/bin` | `BB_CLI` points into the app bundle |
| The work | rw the thread worktree via `--allow-cwd` | no standing grant; bb already sets cwd |
| Thread storage | rw `~/.bb/thread-storage` (thread subdir if it can be named) | attachments and side-chat artifacts |
| Instructions and skills | read `~/.agents` | resolves into the checkout; see the symlink note |
| Dotfile symlink targets | read the two dotfiles subtrees, not the checkout | `shared/dotfiles`, `macos/dotfiles` |
| Tool caches | rw `~/.cache/uv`, read `~/.local/share/uv` | |
| `ansible-lint` scratch | rw `~/.ansible` | only for repos whose `make test` lints |

### What should be denied, explicitly and by literal path

`filesystem.deny` applies regardless of allow rules, which is the right primitive for "grant the directory, exclude the file". Deny at minimum:

- `~/.config/cove/compose`, `~/.config/cove/state`, `~/.config/cove/pki/rootCA-key.pem` — service credentials, runtime state, CA private key
- `~/.bb/auth.json`, `~/.bb/auth-secret`, `~/.bb/bb.db` and its WAL/SHM — API token and harness state
- the decrypted secrets directories the workstation leaves in the checkout
- `~/.ssh`, `~/.aws`, `~/.config/op` (already in nono's default credential deny; keep them)

Two measured constraints on how the deny list is written:

- **Literal paths only.** Deny patterns that expand across a large tree stalled startup indefinitely, with no output and no error (measured: `$HOME/**/.decrypted/**` and `$HOME/.bb/bb.db*`). Literal entries started instantly and blocked correctly. A profile that hangs is indistinguishable from a hung agent.
- **Verify by execution, not by inspection.** `nono why` canonicalizes before checking, so it printed `ALLOWED` for the symlink the live run refused. `nono why --lexical-profile-path` is not the fix: it matches only literal rules, so it printed `DENIED` for ordinary children of a granted directory. Neither mode reproduces Seatbelt. Trust the run.

### The delegation hole (measured, and bigger than any grant)

From inside the spike sandbox, with only the profile applied:

- `bb status` returned the live project and thread.
- `GET $BB_SERVER_URL/api/v1/plugins` returned `200` with no credentials.

The bb public API permits command execution and file reads without auth (ADE docs say so; ADR-018 records it). So an agent that is denied a file can ask the daemon — or a `bb terminal` PTY, which the daemon spawns outside the agent's tree — to read it. Filesystem policy cannot close this; only an egress policy that blocks the daemon port, or a bb-level tool permission, can. Denying the token is not enough because the daemon does not require it on loopback.

That does not make the sandbox pointless — opportunistic credential reads are the common failure, deliberate harness delegation is the rarer one — but it caps the claim. "Sandboxed agent" here means "an agent whose direct syscalls are bounded", not "a contained agent".

### Keeping the profile honest over time

- **Version it with the thing it describes.** `meta.version` in the profile plus the nono version it was validated against, both pinned in the repo. nono's group semantics are part of the policy; an unpinned nono is an unpinned policy.
- **Static checks catch syntax, not surface.** `nono profile validate` and `nono profile diff` belong in the repo gate (skip if nono is absent), because they are cheap and catch a broken profile before a turn does.
- **A doctor is the only reliable drift check.** It runs the real accesses inside the sandbox — `git status` in a worktree, a TLS request to `litellm.cove`, a read of each symlinked config — and reports a failure as *policy drift*, not as a tool bug. The spike's first thread died on a TLS error that looked like an agent bug; a doctor makes that class of failure self-diagnosing.
- **Do not put the profile in `~/.config/nono/profiles`.** That is a hidden dotfile outside the data root; Cove's Self-Contained rule says uninstalling leaves nothing behind. Pass `--profile <path>` at a path under the Cove data root, as the spike's launcher already does.
- **Untested, do not claim it:** Keychain access (`security find-generic-password`, the `op` CLI's biometric path) from inside the sandbox. nono's default credential deny covers files, not mach services. Measure before writing "credentials are out of reach" anywhere.

---

## 4. Cost, risk, and rollout

**Cost.** One host install. The spike used Homebrew, which is unpinned: `brew upgrade` moves the binary and the policy semantics with it. Cove's Self-Contained principle says the host provides Python, uv, and a container runtime and nothing else — so an adopted nono is either a fourth host requirement the operator waives, or a Cove-downloaded, checksum-pinned release staged under the data root, which is new machinery Cove does not have today. The second is the Cove-shaped answer and the larger piece of work.

**Failure modes to design for** (all observed or directly implied):

| Failure | What it looks like | Mitigation |
|---|---|---|
| CA not granted | ACP turn dies on `UNABLE_TO_VERIFY_LEAF_SIGNATURE`; reads as an agent bug | grant the two PEM files; doctor does a TLS probe |
| Symlink link-directory not granted | `git status` fails `Operation not permitted` while `nono why` says ALLOWED | grant link dirs; doctor runs `git status` |
| Glob or recursive deny | startup stalls with no output | literal denies only; a startup timeout in the doctor |
| Deny does not cover symlinked targets | a "denied" directory's files are readable via a granted tree | deny the target trees as well; doctor probes both directions |
| nono missing or wrong version | provider launch exits 127 or behaves unexpectedly | launcher checks presence and version, fails loud with the expected pin |
| Denied write the agent needs | agent cannot save state; turn fails late | grant the agent's own state dirs; doctor covers them |

**Rollout shape.** One machine (the Mac), one new provider id (`acp-opencode-nono`), default off, alongside the untouched `acp-opencode`. Enable is one config write plus one model-policy classification; disable is removing the entry and the classification. Nothing in compose, nothing in `cove up`, nothing in the ADE server. Before enabling on any second machine, run the doctor there: profiles are host-shaped, and nono says so.

**Audit worth having.** nono records sessions and can sign audit roots; that is the part that makes "what did the agent touch" answerable after the fact. It is also the part with the weakest durability guarantees today (a crashed supervisor can leave a session undiscoverable). Treat it as evidence, not as a compliance record.

---

## 5. Recommendation, the honest alternative, and what would change the answer

**Later.** Four reasons, in order of weight:

1. **The policy is not ready to ship, and a sandbox with a bad policy is worse than no sandbox** — it converts an obvious risk into a believed-mitigated one. The narrowed profile in §3 is the start, not the finish; the Keychain question is open and the delegation hole is not closed by any profile.
2. **The seam sits on an unverified layer.** ADE Phase 2 (machine enrollment) has not been live-verified. Stacking a sandbox on a harness whose server/machine split is still a runbook is how two failures become indistinguishable.
3. **The host dependency conflicts with a stated principle.** Self-Contained names exactly three host requirements; nono is a fourth. Either the operator waives that for this tool or Cove grows a pinned-download path. Both are decisions, not implementation details.
4. **The marginal value today is small, given what is granted.** Until the grant list is narrow, nono denies little that matters. Once it is narrow, the remaining value is real but specific: opportunistic reads, accidental writes outside the worktree, and a record of what happened.

**The honest alternative** is not "do nothing forever". ADR-018 already declares the containerized machine and the per-project container as the step-up modes, and a container gives a filesystem boundary around the whole thread, including the setup hook and the terminals the ACP sandbox cannot reach (a container still shares the host kernel — a separate kernel is what a Modal machine or a VM buys, and it costs provisioning and provider-login work that ADR-018 still lists as open). That is the stronger answer to "a hostile repo ran its tests on my laptop", and it is already on the roadmap. nono is the finer-grained layer that makes the inside of that container less flat — which is why the natural sequencing is *container first, nono inside it*, not nono first.

**What would flip this to "adopt now":**

- A near-miss or incident where a thread read or sent something it should not have. That converts a hypothetical into a measured loss, which is the only currency a step-up like this should be bought with.
- A standing workflow that runs third-party code on the host (reviewing and testing forge PRs from other people) — the strongest legitimate case, and still only partly answered by nono, because the setup hook runs first.
- Phase 3 stalling: if machine containers slip, the on-host launch wrapper becomes the only step-up available and the calculus changes.

**If adopted, the first deliverable is four artifacts and no default:**

1. A profile file in the repo (wheel resource), with `meta.version` and the validated nono version beside it.
2. A launcher that pins the binary, checks it, and passes `--profile` + `--allow-cwd`.
3. A doctor command that proves the profile by execution, not by `nono why`.
4. A documented launch seam in `docs/services/ade.md`: the one-line registration, the off switch, and the delegation caveat.

---

## Open questions for the operator

1. **Does Cove govern machine #1 at all?** ADR-018 says the host is the operator's device and Cove does not govern it. If that stands, nono is documented host tooling, not a Cove feature — which changes what `cove` may install, and where the profile lives.
2. **Fourth host requirement, or a Cove-provisioned binary?** A pinned release staged under the data root is Cove-shaped but is new machinery; a Homebrew install is cheap but unpinned and leaves a system path behind.
3. **Network: open, or allowlist?** Open egress keeps the spike's shape and keeps the delegation hole. An allowlist proxy needs a test that it can reach `.cove` names resolving to loopback, and it must decide whether the bb daemon port stays reachable (today it is, unauthenticated).
4. **Is the forcing case untrusted PR code?** If yes, the container step-up answers it better than this seam does, and the sequencing question answers itself.
5. **Credentials: agent-free, or brokered?** Keeping Cove service credentials and the bb token out of the sandbox is a profile change. Letting nono broker them (keyring, proxy header injection) is a much larger commitment and needs the Keychain question answered first.
6. **Where should the profile live long-term?** A wheel resource (Cove-owned, dies on uninstall) and a signed nono pack (operator-owned, updatable, portable) are both defensible; they are different ownership models for the same file.
