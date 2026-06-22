# Plan: fj pr create UX issues — Docs workaround (#26)

## Issue
`fj pr create` has two UX issues:
1. `--title` flag does not exist — title is a positional argument
2. No `$EDITOR` fallback when `--body`/`--body-file` not provided

## Scope
Docs-only: update `docs/fj-guide.md` to document these quirks and workarounds.

## Tasks

### 1. Document `--title` positional argument quirk
- Add a note to the PR Commands section that `fj pr create` takes title as
  the first positional argument, NOT via `--title`
- Show the correct usage: `fj pr create "WIP: <title>"`
- Add a troubleshooting note about the `unexpected argument --title found` error

### 2. Document `$EDITOR` fallback issue
- Add a note that `fj pr create` without `--body`/`--body-file` opens `$EDITOR`
- Warn that it fails if `$EDITOR` is unset
- Recommend always using `--body-file` (already the preferred pattern per
  existing docs)
- Suggest setting `EDITOR=vim` as a fallback

### 3. Update troubleshooting section
- Add entries for both issues with error messages and solutions

## Verification
- `docs/fj-guide.md` renders correctly in the forge web UI
- All existing references to `fj pr create` remain accurate