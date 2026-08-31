# Session stash: 2026-08-31_18-06-tidesman-plan-and-naming

**What this is:** an encrypted capture of a planning session (2026-08-31) that scoped, named, and
wrote the implementation plan for a new standalone companion service for this project, including a
clean-naming search across package registries and a design widening at the end.

## File inventory (everything except this file is encrypted)

| File | What it is |
|------|-----------|
| `resume.md.age` | Progressive-disclosure resume — context-only summary, tiered by line range (see routing) |
| `transcript.md.age` | Full normalized transcript of the session (metadata, phases, decisions log, file-touch map) |
| `file-map.md.age` | Every file the session read/wrote/referenced, and why |
| `git-tag.txt.age` | The repo commit the session is anchored to |
| `patch.diff.age` | The session's only uncommitted work (one new planning document), as a git patch against that commit — verified to recreate the file byte-identically |
| `AGENTS.md` | This router (plaintext, scrubbed) |

There is no `refs/` directory — the session produced no artifacts beyond the planning document.

## Key

- Public key (age): `age1hkutnlvrysljt076mxkfgvk08k56z3xphe6c7n8hlc4rtejdjy3s0drhat`
- Confirmed retrieval source: 1Password secure note `age-key: cove session-stash` (confirmed by the
  operator on 2026-08-12; per `../settings.yaml`, reuse without re-confirmation for this project)
- Decrypt: `age -d -i <private-key-file> <name>.age > <name>`  (or pipe the key in from the secret manager)

## Disclosure routing — read exactly one tier

Tiers are additive; stop at your tier and leave room to think.

- **≤ 32k window:** read `resume.md` lines **1–11** (headline) and stop.
- **≤ 64k:** read `resume.md` lines **1–20** (headline + story).
- **≤ 128k:** read all of `resume.md` (31 lines) + `file-map.md`.
- **≤ 200k:** as above + `git-tag.txt` — you can reconstruct the working state.
- **≥ 500k:** as above + `transcript.md` lines **1–50** (early/mid story).
- **≥ 1M:** read `transcript.md` in full (91 lines), then `file-map.md` in full — audit grade.

## State reconstruction

The session's work product is a single **uncommitted, untracked planning document** captured in
`patch.diff` on top of the commit named in `git-tag.txt`. At stash time it was present in the
working tree at its natural location; after decrypting `file-map.md` you will see exactly where.
If it is still present in the working tree, do **not** re-apply the patch. If it is gone, apply:

```
git apply <patch.diff>   # from the repo root, on the commit in git-tag.txt
```

## Next action

The planning document is complete; its phase plan starts with four verification spikes before any
real implementation. The authoritative next-action statement is in the encrypted transcript's
"Next action" section — read the transcript tier that fits your window.

## Rules for the popping agent

- Popping never modifies this stash. Read-only.
- Do not re-encrypt, rewrite, or "improve" this folder; stash conversion (to a plan/musing/ticket)
  is an explicit operator request and archives the stash to `../backlog/`.
- Fail loud: if decryption fails or a sidecar is missing, stop and tell the operator. Never guess.