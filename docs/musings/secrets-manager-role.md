---
title: "The secrets manager's real job in Cove: scoping, not storage"
created: 2026-10-29
status: Draft
---

# The secrets manager's real job in Cove: scoping, not storage

A secrets manager is usually described by what it stores: a vault, a cache, a rotation engine, a certificate authority. That description misses the property that actually matters here. A secrets manager is an authorization boundary, and everything it stores is downstream of who is allowed to reach it.

Scope is the problem. Today every consumer on this machine shares one identity: the operator's. One root token reads the whole store, one `.env` feeds every container, one cache file holds every resolved reference, and one OS user is both the human and every agent thread. A thread working in any project can therefore read every other project's credentials, and nothing in the stack would notice or record it.

Two rules organize everything that follows. The first is scope: a grant names one project and one consumer, and never spans either. The second is custody: **no model-directed process ever holds a true secret.** Where a boundary exists, it swaps a broad credential for a narrower one, so an agent holds a grant while the secret stays behind the boundary.

Secret reuse across projects is the second problem, and it cannot be solved by fragmentation. Providers do not all issue per-project keys, and a rotation-per-project regime multiplies the secrets an operator must chase. The answer is brokerage: the upstream credential stays in one custody point and each consumer receives a scoped, attributable, revocable grant to use it. Scoping is permission to use, never possession.

The rest of this document works out what those two rules require, in that order: scope first, because a swap needs an identity to swap to.

## 1. The attack path, as it exists in this repo

Three paths lead from a thread to another project's secrets, and all three are open today.

- **The Vault API.** `cli/cove/vault_cache.py` resolves one token: `VAULT_TOKEN` if set, otherwise the root token from the OS keystore (`_vault_token`, lines 71 to 102). That root token has unrestricted authority, and the UI user is not much narrower: `compose/provision_vault_user.yml` writes an `admins` policy of `path "*"` with `sudo` for it. Any process that can read the keystore or the environment reads every mount.
- **The local cache.** `~/.cache/cove/op-cache.json` holds every resolved `op://` value in plaintext, at mode 0600, owned by the operator. An agent thread runs as the operator, so it reads this file without touching Vault at all (`cli/cove/local_cache.py`).
- **The compose `.env`.** Fourteen credential names reach containers through it (`CREDENTIAL_ENV_NAMES` in `cli/cove/credential_env.py`), and the file is readable by anything running as the operator. `cove serve` and `cove update auto` run as the operator too, at login, precisely because the unseal keys live in the login keychain (`cli/cove/serve.py` docstring).

A fourth path is delegation rather than reading: the sandbox brief measured that the bb daemon answers command execution and file reads over its loopback API without authentication, so an agent that is denied a file can ask the daemon for it (`docs/musings/nono-ade-sandbox.md`, "Agent asks the harness to do the work"). Filesystem policy alone cannot close that, which is why section 6 treats the two boundaries as one design.

There is no audit device. `compose/vault/vault.hcl` configures storage, one listener, addresses and the UI, and nothing else; nothing in `cli/` or `compose/` calls `sys/audit`. Even if it were enabled, a single root token makes each record a statement about "the operator", not about a consumer.

## 2. The consumers that need identity

The fleet has more consumers than the architecture admits. Each row is a distinct principal whether or not the stack models it that way.

| Consumer | Identity today | What it can reach today | What it should hold |
|---|---|---|---|
| Operator CLI (`cove creds`, `cove tunnel`, `cove litellm`, `cove bifrost`, `cove speedtest`) | Root token from the keystore, plus the local cache | Every project's cached secrets | A project-scoped token for the project the command is acting on; root authority only for stack lifecycle verbs |
| `cove vault unseal` and the unseal path inside `cove up` | Root token plus Shamir shares from the keystore | Seal state, and by extension everything | Seal material only. This is the bootstrap exception, and it should never be the identity a task runs under |
| launchd `app.cove.serve` | Operator at login, keychain unlocked | The whole store, every project | A stack-lifecycle token: read the stack's own `.env` projection, unseal, nothing project-specific |
| launchd `app.cove.update` (auto-update) | Operator at login | The whole store | A converge token: read pins and the stack projection, write nothing |
| Each bb agent thread | The operator, ambient environment and filesystem | Everything the operator can read, including other projects | A turn-bounded, project-scoped token, plus a filesystem scope that matches it |
| Each service container (Forgejo, ADE, LiteLLM or Bifrost, Speedtest, ToolHive, runner, pages) | Its slice of the shared `.env`, decided at start | Its own variables, but the file it came from is shared | Only its own projection, or a broker-issued, short-lived credential |

Two properties make this tractable. First, the consumer set is finite and mostly known to bb already: `BB_PROJECT_ID`, `BB_THREAD_ID` and `BB_ENVIRONMENT_ID` are injected into every thread environment automatically (`bb guide`), and `bb status` resolves project plus environment. The information needed for a project-scoped grant is present at spawn time and is currently unused.

Second, the client already accepts an injected token. `_vault_token()` prefers `VAULT_TOKEN` over the keystore, so a per-consumer token becomes effective with no change to `vault_cache.py`. What is missing is issuance, policy, and a revocation story, not a client rewrite.

## 3. The boundary rule

One rule, applied everywhere: **a grant never spans projects.** Everything else is implementation.

- **Layout.** Each project owns a path prefix in the one KV v2 mount: `secret/data/cove/...` for this repository, one prefix per other project. The vocabulary comes from the project list the orchestrator can already enumerate, which on 2026-10-29 reads `cove`, `hattrick`, `hal`, `trimline`, `bv-brain2`, `houseops`; branch names such as `kepler/` or `sashay/` are branch scopes inside a project, not projects, and get no prefix of their own. The definitive set is declared at cutover from that list, and adding a project later means adding one prefix and one policy, never editing another project's. The current cache moves under the project that owns the references, so `secret/data/op-cache/...` becomes `secret/data/cove/op-cache/...`. References that serve the stack rather than a project (the stack's own admin credentials, the tunnel token, the LLM edge credential) live under a `stack` prefix that only the lifecycle consumers may read.
- **Policies.** One policy per consumer class, not per person, and no wildcard paths:

```
# cove-thread: what an agent thread working in the cove project may read
path "secret/data/cove/*" {
  capabilities = ["read"]
}
path "secret/metadata/cove/*" {
  capabilities = ["list"]
}
# deliberately absent: any grant on secret/data/<other-project>/ or secret/stack/
```

Absence is denial. A thread in another project gets the same document with its own prefix, and cannot construct a request that crosses the boundary because the path prefix is the boundary.

- **Tokens.** Minted per consumer with a TTL: `bao token create -policy=cove-thread -ttl=8h` for a thread, longer for launchd, and no token for the seal path at all. Renewal belongs to whoever minted it, which is the launcher's broker for threads and the CLI for operator sessions.
- **Prefixes versus mounts.** A prefix plus a correct policy is the cheap option and is sufficient for a single-operator fleet. A mount per project is the hard option: cross-project reads become structurally impossible rather than policy-dependent, at the cost of mount bookkeeping, per-mount tuning and more code in provisioning. Take prefixes now. Move a project to its own mount if it ever holds material whose exposure would be a reportable incident.
- **Namespaces are a third tier and are not available on the current pin.** OpenBao ships namespaces in its open-source build; Vault's namespaces are an Enterprise feature, so the current 1.20 OSS pin cannot express them. That is one of the reasons the vendor ruling in section 12 is coupled to this document rather than independent of it.

## 4. No agent holds a true secret

The second rule is blunt: a process a model can direct never holds a real credential. That covers every bb thread, every ACP agent, and anything those spawn. The Synthetic provider key, the ollama-cloud key, the LiteLLM master key, the Bifrost admin and encryption keys, the local CA private key, and every 1Password-sourced value stay out of an agent's environment, argv, working tree and readable paths. What the agent gets instead is a grant that names it, scopes it, and expires.

Where a boundary already exists, it swaps a credential down. Each swap has a name and a direction:

| Swap | What crosses it | State |
|---|---|---|
| Agent to `llmproxy.cove` | A Cove client token goes in; the edge proves it against an exact-match map, replaces the client's `Authorization` header, and injects the active upstream provider key before `proxy_pass`. The provider key never reaches the client, and the client's own header is never forwarded | Shipped in 0.15.12 (`compose/nginx/default.conf.j2`, `llmproxy` server block; `cli/cove/llmproxy.py`) |
| Agent or tool to a broker | A scoped grant to use a shared upstream credential (Synthetic, ollama-cloud, a virtual key carrying a model allowlist and a budget) without ever copying the credential in. The broker performs the call and records who asked | Not built. The LLM edge is the first instance of the shape, restricted to one credential |
| Consumer to the manager | A short-lived token minted per consumer, which reads only its own prefix. Any service that needs secrets at runtime gets one too, as ToolHive's Phase 2 plan already assumes | The gap: `cli/cove/vault_cache.py` resolves `cove/vault/root-token` from the keystore for every read and write, so every consumer is the operator |
| Launcher to thread | A turn-bounded, project-scoped token instead of ambient `.env` values. bb knows project, thread and environment at spawn; a launcher at the ACP seam asks a local broker, and the daemon never mints anything | Not built |

The residual is decided rather than hypothetical. Agent processes keep the docker socket and the bb daemon port (operator ruling, 2026-10-29). They run as the operator's user, `docker` works from an agent turn because the orchestrator itself uses it, and the daemon's API and terminal stay reachable on loopback. From that position an agent can read any container's environment through `docker inspect`, any mounted volume, any image, and any file the operator can read, whichever token it holds. So until the capability set is reduced, **token work buys attribution, not containment**, and that sentence is the honest description of every step in section 10 that does not also remove a capability.

The sandbox brief measured this shape rather than imagining it: the spike's own grant list handed a sandboxed agent the compose `.env` (LiteLLM master key, UI and Speedtest passwords, provider keys, Bifrost keys), the local CA private key at `~/.config/cove/pki/rootCA-key.pem`, decrypted SOPS variables inside the checkout, and `~/.ssh` through a symlink whose target sat in a granted directory. Separately, from inside that sandbox the agent reached the bb API and asked the harness to do what its own process could not (`docs/musings/nono-ade-sandbox.md`, "Policy and grant model", thread `thr_wxg7pg9ubc`).

The pairing rule follows: **the two halves land together or the boundary is theatre.** Token scope and path scope are one control. A per-thread token protects nothing while the plaintext cache and `.env` remain readable, and a sandbox without a scoped credential still hands the agent a key that opens every project.

One consequence should be designed rather than asserted. A service that needs a provider key at boot, such as LiteLLM or Bifrost, keeps that key in its environment, because a broker cannot serve a process that must hold the key to answer requests. The boundary is not that the key is absent from the machine. It is that an agent cannot read that environment or exec into that container, and today it can: `docker inspect` prints a container's environment, so no container boundary is real while agents keep the socket. Making the sentence true means removing the socket from agent processes, removing the daemon command surface from their reach, and dropping any standing grant on the compose directory. Until that happens, the provider key is on the same side of the boundary as the agent, and the honest label for the arrangement is attribution. The same logic covers the manager's seal material, which lives in the OS keystore and is read by a launchd job at login, not by anything a model directs.

Reuse makes this mandatory rather than optional. Where a provider issues one key for all projects, the key cannot be split, so every project's access to it is a grant to use a shared credential, and the broker is the only place that grant can be enforced.

## 5. Reuse: broker the credential, grant the use

The pattern is brokerage, and its failure mode has a name. Splitting one shared upstream credential into twelve project-shaped copies creates twelve custody problems and solves none, because a copy is still a secret and the operator still has to rotate all twelve.

Cove already runs the correct pattern on the LLM path, and it should be read as the template rather than as a one-off. Since v0.15.12, `llmproxy.cove` is an authentication edge: clients hold a Cove-owned client token, the edge proves it with an exact-match map and then replaces the client's `Authorization` header with the active backend credential before `proxy_pass` (`compose/nginx/default.conf.j2`, the `llmproxy` server block; `cli/cove/llmproxy.py`). Backend keys never reach a client, and a backend swap changes one upstream line.

The generalization is a **broker**: a process that holds the upstream secret, authenticates the caller, decides whether this caller may use this credential for this purpose, performs the call, and records who did it. The caller holds a grant, never the secret. Scope lives in the grant, so a shared credential is not the same thing as a shared permission. Section 7 turns that into an operable object: the grant's fields, its lifetime, and the surface where a new one gets decided.

Which of Cove's current secrets belong in each class:

| Secret | Class | Where it must live | Who uses it | Grant shape |
|---|---|---|---|---|
| Synthetic provider key (`SYNTHETIC_API_KEY`) | Brokered | The LLM edge or gateway (`local.env`, 0600) | Every LLM client across every project | Per-client virtual key with a model allowlist; the key itself never leaves the edge |
| ollama-cloud key (`OLLAMA_API_KEY`) | Brokered | The same edge, and per the workstation-lane ruling it is not Cove's to custody long-term | Same | Same shape; the edge is a pass-through, not an owner |
| Bifrost client virtual key (`BIFROST_CLIENT_VIRTUAL_KEY`) | Grant, not secret | Generated by the gateway, projected into `.env` | Every LLM client | Today one key for everyone; the gateway can mint several, each with policy and its own identity in the logs |
| Forgejo admin password, Speedtest admin identity and `APP_KEY`, Zrok account token | Stack-held | 1Password, projected into `.env` for the service that needs it | Stack lifecycle only | Service-scoped projection; no project thread needs any of them |
| LiteLLM master key, Bifrost admin and encryption keys | Stack-held | `.env` and 1Password | The stack itself | Lifecycle token only, never a thread token |
| Vault root token and Shamir shares | Held, by exception | OS keystore | Unseal, emergency administration | No grant exists. A token that can read everything cannot be scoped, so it must not travel |

The Bifrost row is the honest one. The gateway already supports more than one virtual key with its own policy, and Cove mints exactly one and hands it to every client, which means the LLM edge has an identity mechanism and no identities. Fixing that is the smallest complete demonstration of the model, and it needs no new component.

## 6. The launch seam is the broker, and the sandbox is the other half

bb knows which project and which worktree a thread belongs to, and it already injects context into the environment. It should hand that context to a launcher rather than mint the credential itself.

The ruling (2026-10-29) is that the thread token is minted by a broker reached from the ACP launch seam, not by bb. The reasoning is this document's own argument turned on the harness: bb already carries the strongest bypass surface on the machine, because its API and terminal can execute commands and read files, and the sandbox spike demonstrated exactly that from inside a sandbox. Giving the same process the authority to mint credentials would concentrate the one risk the token model exists to reduce.

The launch seam is the right boundary for four reasons that compound. It is per-thread. It already knows the project and worktree from the spawn context. It exists today: bb spawns an ACP agent by command, and the spike proved a wrapper can sit there with no bb change. And it is where the sandbox wrapper has to go anyway, so token scope and path scope get installed at one seam instead of two.

Mechanically, the launcher asks a local broker for a project-scoped token, carrying project, worktree and thread as the identity and a TTL tied to the turn. It injects the result into the agent's environment as `VAULT_TOKEN`, which `cli/cove/vault_cache.py` already prefers over the keystore, so the client side needs no change. At turn end the token is revoked, or simply expires. Every spawn stays non-interactive and the daemon never touches the secret path.

The broker itself stays swappable. Today it can be a small local service; later it can be a per-consumer identity issued by the manager, and the launcher does not change because it only ever asks for a grant.

The other half is filesystem scope, and its state is stated in section 4: it does not exist yet, and a token model is inert without it. That is why the launcher step in section 10 is the point where containment starts, not the point where a nicer token format arrives.

## 7. Grants the operator can actually decide

The boundary described so far fails at the only moment it touches the operator. Today any thread can run `op`, and the OS prompt that follows says only that something wants 1Password. It does not say which project, which thread, what the thread is doing, which item, or why now. The operator approves blind, which is not an authorization decision; it is a reflex trained by repetition. That is auth spam, and it has a second cost: it teaches the wrong architecture, because it makes per-command interactive approval look like the normal way to obtain a secret when the workflow has no use for one-time grants at all.

What follows specifies the replacement: what a grant is, how long it lasts, how a new or expiring grant reaches the operator with enough context to rule on it, and how the path through the broker is enforced rather than merely requested.

### What a grant is

A grant is a record with five fields:

| Field | Meaning | Constraint |
|---|---|---|
| Project | The prefix the grant can reach, from the fixed vocabulary in section 3 | Exactly one. Cross-project grants are not expressible in the schema |
| Consumer | The identity that may use it: a thread, a tool, a service, or an operator session | Exactly one |
| Scope | The items and fields covered, by `op://` reference or path | A subset of the project prefix. `op-cache` entries qualify only when the project owns the reference |
| Capabilities | `read`, and separately `rotate`, meaning write a rotated value back | `rotate` is never implied by `read` |
| Lifetime | An absolute expiry plus the reason it was set | Bounded by the table below |

A grant is not a password and not a copy of the value. Reading it yields a decision, not bytes: the broker resolves the reference, checks the grant, and returns the value to that consumer for that purpose.

### Lifetimes

| Class | Floor | Default | Maximum | Renewal |
|---|---|---|---|---|
| Thread grant | 1 hour | 12 hours | 7 days | Explicit, by a request that cites the previous one |
| Tool or service grant | 1 hour | 24 hours | 7 days | Explicit, same path |
| Operator session grant (CLI, launchd) | 1 hour | 12 hours | 7 days | Reissued at the next unlock |

One hour is the shortest session in which a grant does real work, so it is a floor rather than a target. Twelve hours covers a working day from one unlock. Seven days bounds what a leaked grant can reach while surviving a weekend. Expiry is absolute and never silently extended: the broker may raise a renewal request before expiry, but it may not roll the grant forward on its own, because a grant that renews itself is not a grant.

**One-time grants are removed from the design.** Not deprecated and not hidden behind a flag: the schema has no use counter, the broker has no verb that issues one, and the request surface has no control for it. The operator's workflow has no case that needs it, and keeping the option would re-create the per-command approval pattern this section exists to eliminate.

### Where a request lands

Three candidate surfaces, one chosen:

- **The OS dialog.** Rejected. It is the current defect: any process that can call `op` can raise it, it carries no project or task context, and it trains the reflex it is supposed to inform.
- **A bb notification.** Rejected as the primary surface. It is transient, it cannot hold state, and it gets dismissed with the same muscle memory as a dialog. It is useful as a nudge and useless as a ledger.
- **A grants inbox, rendered as Focus Board cards in a reserved group.** Chosen. Cards persist, group, and carry a status; the board is where the operator already triages threads, so a request arrives in the surface that already means "something needs a decision"; and an inbox makes volume visible, which is the quantity that keeps auth spam from returning. A queue of eleven pending grants is itself the signal that something upstream is asking too often.

The card is a decision surface, not a dialog. It carries the context block below and two actions of equal weight: approve, or deny with a reason. An unresolved card stays visible; resolving it records the outcome in the ledger and closes it.

### The context block

Every request, new or renewal, renders the same shape, complete enough to rule on without a follow-up question:

```
GRANT REQUEST  g-7f3a2c                       new
project     cove
consumer    thread thr_j38wx2bb3f (lane lieutenant, "secrets brief")
purpose     confirm the audit device is off before citing it in
            docs/musings/secrets-manager-role.md
items       op://Private/Vault <hostname> admin/password    [read]
            op://Private/Cove Admin/password                [read]
lifetime    12h, default for thread grants
excludes    rotate on either item; every other project prefix; the
            stack prefix; the 1Password CLI itself
if denied   the claim stays unverified and the section is marked open
```

and for a renewal:

```
GRANT REQUEST  g-7f3a2c                       refresh: expires in 41m
project     cove
consumer    thread thr_j38wx2bb3f (lane lieutenant, "secrets brief")
purpose     same task, second session; first grant saw 3 reads
items       op://Private/Vault <hostname> admin/password    [read]
previous    12h, issued 2026-10-30 09:14, 3 reads, 0 denials
why now     expiry, not rotation
excludes    unchanged
```

Three properties matter more than the prose. The block names the consumer the way the operator recognizes it, thread id plus the human-readable name the board already shows. It names what the grant does **not** allow, so the decision is bounded rather than open-ended. And it states the cost of denial, so "no" is an answer about consequences rather than a shrug.

### Approval, denial, audit

Approval is one action on the card. The broker writes the grant to its ledger with who approved, what was granted, the stated purpose and the expiry, then serves reads under that grant id. Every later read is logged against the grant, which is what makes the audit records in section 8 attributable.

Denial is one action too, recorded with its reason. A denial also sets a cooldown for that consumer and scope, so the same request cannot be re-raised on the next turn or the next retry. Without a cooldown denial is just a slower form of nagging; with one, a refusal becomes a fact the thread has to work around, which is what a decision is supposed to mean.

### Refresh and rotation

Two events produce a renewal, and the block must say which, because they call for different answers:

- **Expiry.** The grant is about to end while the work continues. The broker raises a refresh an hour before expiry for thread grants, carrying the previous lifetime and its use count.
- **Rotation.** An item changed underneath a live grant, because the operator or a service rotated it. The broker detects it by comparing the item's version and field hashes against the snapshot taken at approval, marks every dependent grant stale, and raises a refresh at once. This is also where `rotate` capability earns its keep: the broker, not the agent, writes the new value back.

Operator effort is one card, not a re-entry of context, because a refresh carries the previous grant as its baseline. On approval the new grant gets a fresh lifetime and the old one is revoked rather than left to expire, so there is never more than one live grant for a consumer and scope.

### Enforcement, not etiquette

A grant model agents can ignore is documentation. Four things make it real:

- **The broker is the only process that talks to 1Password.** Its vault access is unlocked once per operator session, and every downstream consumer reaches the broker instead of `op`. That collapses N OS prompts into one deliberate unlock per session, which is the point of the change.
- **The 1Password CLI is absent from the agent's path.** Not shadowed, not wrapped: the binary is missing from the sandbox image and from the PATH the launcher hands the agent, so `op` in an agent turn fails with "command not found", which is a clear signal rather than a silent fallback.
- **The launcher injects a broker token, not a 1Password one.** The token is the grant id plus a scoped bearer, and the agent's tools speak to the broker.
- **The sandbox is the other half.** None of the above survives an agent that can reach the daemon's command surface or read `~/.cache/cove/op-cache.json`, and the sandbox brief measured both. Removing `op` from PATH closes the polite path only, so path scope and token scope still ship together, per section 4.

What this does not claim: an agent that keeps the docker socket can still read a container's environment, and the operator can still run `op` by hand. The claim is narrower and defensible: an agent cannot obtain a secret except through a recorded grant.

### The worst case

If the broker is down or locked, agents fail loud with the one command that fixes it (`cove grants unlock`), and nothing falls back to prompting 1Password behind the operator's back.

## 8. Attribution and audit

Audit is the payoff of identity, not a separate feature. With one root token, an audit device would record that "the operator" read a path, which cannot distinguish a careless thread from a deliberate act, and cannot answer which project's secret was touched. With per-consumer tokens, the same records answer who, which project, and when, and a revocation story becomes provable rather than asserted.

Concretely this needs three things Cove does not have: an audit device enabled on the server (a file device under the data root, rotated), tokens whose identity survives into the record, and a decision about what the log may contain. The third is the hard one, because Vault-family audit devices log request and response payloads in some configurations, and a secrets store's audit log is itself a secret store if it is written carelessly.

## 9. One cache of record

A value can currently exist in four places: the 1Password item, the Vault KV entry, `~/.cache/cove/op-cache.json`, and for some secrets the compose `.env`. Two of those are caches with equal authority, which is not a tidiness problem. The stale-cache defect behind issue #93 was exactly this: a read path served a cached value after an upstream rotation, because two caches disagreed and neither was declared authoritative.

The target is one custody point and one runtime cache:

- **1Password is custody of record.** It is where a secret is created, rotated and audited for the human.
- **The manager's KV is the runtime cache of record.** It is what the platform reads when 1Password is locked or offline.
- **The local file cache becomes a latency cache.** It either disappears, or it gains a TTL and a provenance stamp and stops being readable as authoritative. It must not be the thing `cove creds vault-get` trusts first, which is what it is today.
- **The `.env` becomes a projection.** Derived from the cache of record at converge time, with the values it carries hashed and compared, never a source that a later read trusts.

## 10. Roadmap, reordered

The order is deliberate: a capability without a boundary mostly increases the number of places a leak can start.

1. **Now: declare one cache of record and enable audit.** Cheap, reversible, and it makes every later step measurable. Without it, per-consumer tokens would produce records that cannot be trusted to reflect reality.
2. **Next: identity, prefixes, and the first real swap.** Move the KV layout under project prefixes, write one policy per consumer class, mint tokens for the CLI and the two launchd agents, and stop the CLI from using the root token for task work. The swap principle ships alongside this step rather than after it: identity without a swap leaves the root token in place, and a swap without identity has nothing to swap to.
3. **Then: the ACP launch seam issues turn-bounded tokens, and the grants inbox goes live,** paired with a filesystem scope for agent threads. This is where containment starts: before this step the boundary is theatre, because the agent still holds docker and the daemon. It is also where the launcher sits, so the broker, the inbox and the sandbox wrapper install at the same seam, and the first grant request is the moment the operator finds out whether the design is usable.
4. **Then: brokerage for shared provider keys.** Start with per-client virtual keys on the LLM edge, because the mechanism exists and the identities do not. Generalize only when a second credential needs the same treatment.
5. **Later: dynamic credentials and PKI.** Database leases for the Postgres instances and a PKI engine for TLS remain worthwhile. They moved down, not out, for one reason: a lease is still a credential, and issuing short-lived credentials to an identity that can read everything just rotates the same exposure more often. PKI additionally removes the CA private key from disk, which is a genuine gain, and it still only matters once the requester has a name.

## 11. Non-goals

- **Not a config store.** Non-secret configuration stays in IaC: compose files, `bringup.yml`, `group_vars`, seeds. A secrets manager that also holds tuning knobs becomes a second, undeclared configuration surface.
- **Not a replacement for the workstation lane's SOPS custody.** Those keys remain the workstation lane's. Only pass-through projections cross the boundary, and the `OLLAMA_API_KEY` ruling from the LiteLLM exit is the precedent: Cove does not take custody of what it only forwards.
- **Never a network dependency for container boot.** A container must start from its `.env` projection and its image without reaching the manager, or a sealed or restarting manager becomes a stack outage.

## 12. What this does to the vendor ruling

The OpenBao decision currently open in `docs/musings/openbao-vs-vault.md` is not independent of this document, and it should not be decided first.

- **If the manager becomes the authorization boundary described here,** then license, governance, release cadence, audit support and namespace isolation all carry weight, and they point at OpenBao: MPL-2.0 instead of a BSL relicensing vendor, signed and SBOM'd releases, an actual patch cadence, and namespaces in the open-source build.
- **If the manager stays a cache,** then the honest description of the current Vault is "a local key-value store with a UI", a full manager is overkill for that job, and migrating is cosmetic churn with a real migration cost.

So the two rulings should be taken together: decide the role first, then the product. Taking the product first would pick a vendor for a job the operator has not yet defined, and the migration work would then be aimed at the wrong target either way.

## 13. Open questions

1. **Is the project the right boundary, or the repository?** A worktree of the same repository is the same project in bb's model, so this is mostly settled. The open part is whether two repositories that share deploy targets should share a prefix.
2. **What does the audit log hold, and who rotates it?** A file device under the data root with a size cap and a retention rule is the simple answer; the operator needs to accept that the log may contain path names and timestamps, and decide whether payload logging is ever on.
3. **Do the per-client LLM virtual keys land now or after scoping?** They are the cheapest demonstration of the model, and they also require a decision about which project name each client key carries.
4. **Is twelve hours the right default for a thread grant?** The floor and the maximum in section 7 are structural; the default is a knob, and it should match how long a working session actually runs on this machine.

Two questions that were open here are settled. The thread token is minted by a broker at the ACP launch seam, not by the daemon (section 6, operator ruling 2026-10-29). And the six project names in section 3 stand unless the operator corrects them; the definitive set is declared at cutover.
