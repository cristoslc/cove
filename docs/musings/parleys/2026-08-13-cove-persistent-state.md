---
title: "Cove persistent state & stateless-CLI architecture"
created: 2026-08-13
status: Open
---

# Parley: Cove persistent state vs stateless CLI

## Topic

The `cove` CLI is meant to be stateless, but the operator's state MUST persist
across reinstalls, upgrades, and backup transfers to new machines. Where does
durable state live, and is `~/Documents/cove-data/` the right home?

## Opening position

The stateless-CLI principle is in tension with real durable state. State is
currently scattered across ~5 locations with different durability classes, and
`extract_resources()` rmtree's `~/.config/cove/compose/` (wiping certs, the
.env, host_vars) on every reinstall. We painted into a corner where "the wheel
is the single source of truth" collides with "user state must survive
reinstall."

## Tension backlog

- (not yet raised)

## Turn 1 — T1: the framing is wrong; it's source-of-truth, not storage location

**Opening position:** state is two classes — durable (user-owned) vs derived
(regenerable from wheel); the flaw is mixing them in one tree and rmtree'ing it.

**Operator response (widened):** "You're looking at it too narrowly by
discussing machine identity or the compose. The compose issue is a symptom of
an architectural misstep. Regenerable derivations may be synthesized both from
the wheel AND the user's pre-existing config AND the services' current state."

**Resolution:** Not yet resolved — the operator redirected. Storage location is
a symptom; the real problem is *derivation inputs*. The admin creds matter most,
and they interact with the service databases. A derivation may need three
inputs: (1) the wheel's templates/defaults, (2) the user's pre-existing config
(preferences, identity), and (3) the live service's current state (DBs, vault
contents). The CLI's job is a *reconciliation* of those three, not a one-way
render.

## Turn 2 — T2: precedence among sources when they disagree

**Position:** the service DB is a sink (artifact of reconciliation), not a
source; 1Password canonical, Vault offline cache, DB derived sink. A healthy
reconciler may need to heal the DB when it diverges.

**Operator response:** "I think we need a data governance policy, starting with
an inventory, to address this question properly. But this is looking in the
right direction."

**Resolution:** Directional alignment. The concrete next step is NOT the
storage fix — it's a **data governance policy**, and the first artifact is a
**data inventory**. The parley has converged on "what problem are we solving"
(the reframe from storage-location to reconciliation-across-three-inputs) and
is deferring the precedence question until the inventory exists.

**Implication:** The inventory must classify every piece of state Cove touches
by source-of-truth and durability so the precedence questions can be answered
from evidence, not theory.

## Turn 3 — T3: deliverable is a data governance policy + inventory

**Position/reframe (T1, confirmed):** the compose issue is a symptom; the real
problem is derivation inputs (wheel + user config + service state). State must
be reconciled across three external sources of truth, not rendered one-way.

**Operator response:** "I think we need a data governance policy, starting with
an inventory, to address this question properly. But this is looking in the
right direction."

**Resolution:** Aligned. Produced `docs/data-governance-inventory.md` — the
inventory (7 locations, classified by source-of-truth + durability + backup
coverage) as the first artifact of the policy. Parley record closes on the
direction; the precedence rule is deferred to an ADR once the inventory is
reviewed.

## Open items for the ADR / next parley

- Precedence when 1Password / Vault / `.env` / service-DB disagree.
- Physical separation of durable artifacts out of the rmtree'd `compose/`.
- Backup coverage for the control-plane (CA key, keychain).
- New-machine bootstrap (copy vs regenerate vs re-pull).

