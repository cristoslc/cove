# Cove Stateless Config — Workflow First

I keep jumping to file paths. Let me think about the actual workflow.

## The end-user workflow

```
uv tool install cove-cli
cove up
```

That's it. Two commands. The user doesn't have the repo, doesn't know what Ansible is, doesn't care about compose files. `cove up` either works or it doesn't.

If it doesn't work because Ansible isn't installed, the error message should say: "Install Ansible: `brew install ansible`" — not "extract resources to ~/.config/cove/".

## The developer workflow

```
git clone ...
uv run --directory cli cove up
```

The developer edits `compose/bringup.yml` and runs `cove up` to test. No rebuild, no reinstall, no extraction step. The repo checkout IS the source of truth.

When the developer is done, they commit. The package is rebuilt on `uv tool install` — the `compose/` directory is bundled as a resource.

## The migration workflow

The question is: how do we verify the migration is correct?

Option A: Move files, test, fix bugs.
Option B: Generate the new structure from the old one, diff them, verify they match, then switch over.

Option B is better. Write a script that:
1. Reads the current `compose/` directory
2. Generates the package resource structure
3. Diffs the two
4. If they match, the migration is correct

But wait — the current `compose/` directory IS the package resource structure. We don't need to generate anything. The migration is just:
1. Add `compose/` to the package manifest
2. Write extraction logic
3. Write resource resolution
4. Done

No files move. No structure changes. The migration is adding code, not moving files.

## The real question

Is this migration worth doing? What does it buy us?

| Before | After |
|--------|-------|
| `git clone && cove up` | `uv tool install cove-cli && cove up` |
| Repo required | No repo needed |
| PII in tracked files | No PII in tracked files |
| Dev mode = same as installed | Dev mode = repo checkout, installed = extracted |

The benefit is: no repo needed. The cost is: extraction logic + resource resolution + Ansible dependency.

For a single-developer tool that you install from source, the benefit is marginal. The real win is the PII cleanup — which is independent of the stateless migration.

## Recommendation

Do the PII cleanup now (it's quick and independent). Defer the stateless migration until there's a real need for `uv tool install` without the repo. The musing captures the design for when that day comes.