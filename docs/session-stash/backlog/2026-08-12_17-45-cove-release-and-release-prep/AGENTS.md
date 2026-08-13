# Stash AGENTS.md — Cove release close-out + next sashay prep

Date: 2026-08-12. Topic: releasing a local platform tool and prepping its next dependency-fix sashay.

This is a **portable session stash**. It lets any agent resume the session in any harness. Everything in this folder is encrypted at rest **except this file** (which is scrubbed to be safe to publish). Popping never modifies the stash.

## What this stash is

The tail end of a platform release: shipped a new service (a WAN-link speed monitor), released the tool on a public package channel, and prepped the next sashay (a dependency security fix). The next action is starting that sashay.

## Files in this folder

- `AGENTS.md` — this router (plaintext).
- `resume.md.age` — summarized context, tiered by line range (encrypted).
- `transcript.md.age` — full session narrative (encrypted).
- `file-map.md.age` — which files the session touched (encrypted).
- `git-tag.txt.age` — anchor commit (encrypted).
- `patch.diff.age` — uncommitted session work (encrypted).
- `refs/` — reference artifacts (encrypted).

## Disclosure routing (by context window)

- ≤ 32k: read `resume.md` lines 1–40 (headline). Stop.
- ≤ 64k: read `resume.md` lines 1–120.
- ≤ 128k: read all of `resume.md` + `file-map.md`.
- ≤ 200k: read all of `resume.md`, `file-map.md`, `git-tag.txt`.
- ≥ 500k: also read `transcript.md` in full (audit-grade).

## Decryption

Decrypt the `.age` files with the **cove project age key**, public key:

`age1hkutnlvrysljt076mxkfgvk08k56z3xphe6c7n8hlc4rtejdjy3s0drhat`

The private key is in 1Password as the secure note **`age-key: cove session-stash`** (tags `age-key`, `session-stash`, `cove`). Retrieval source was confirmed with the operator on 2026-08-12. Decrypt with:

```
age -d -i <keyfile> resume.md.age
```

## Next action (resume point)

Start the dependency-fix sashay whose draft PR already exists. The plan and musing live at `docs/plans/fix-idna-dependabot-vuln.md` and `docs/musings/idna-dependabot-vuln.md`. Work only inside the sashay worktree per the repo's sashay workflow. Do not promote/release until the test gate is green and the PR is merged to main.
