---
title: "fj issue create must ALWAYS use --body-file, not --body"
created: 2026-06-18
status: Draft
---

# fj issue create must ALWAYS use --body-file, not --body

## Problem

`fj issue create --body <text>` passes the body directly on the command line. This has several issues:

- **Shell escaping hell:** body text with newlines, quotes, backticks, or other special chars requires careful escaping that varies by shell context (interactive vs `zsh -i -c` vs subprocess).
- **Command-line length limits:** long bodies can hit `getconf ARG_MAX` (256k on macOS, but still a ceiling).
- **Process table leak:** the full body text appears in `ps aux` output, visible to any user on the system.
- **Inconsistency:** when tools/scripts generate issue bodies programmatically, they inevitably produce multi-line text that's awkward to inline.

`--body-file` fixes all of these: write the body to a temp file, pass the path, done.

## Rule

Every invocation of `fj issue create` MUST use `--body-file` with a file containing the body text. Never use `--body`.

```bash
# BAD — shell escaping, length limits, ps leak
fj issue create "fix: handle edge case" --body "Long body text with
quotes and $variables and all sorts of trouble"

# GOOD — clean, no escaping issues, no ps leak
cat > /tmp/body.md <<'EOF'
Long body text with
quotes and $variables and all sorts of trouble
EOF
fj issue create "fix: handle edge case" --body-file /tmp/body.md
```

## Usage in Agents

When agents (opencode, scripts) create issues, they should:

1. Write the body to a temporary file (e.g., `mktemp` or a predictable path)
2. Pass `--body-file <path>` to `fj issue create`
3. Clean up the temp file after

## Exceptions

None. If `fj` is used interactively by a human and they want to type the body in their `$EDITOR`, that's fine — just omit both `--body` and `--body-file`, and `fj` will open the editor. The rule is: never pass body text as a CLI argument string.

## Addendum: Missing `fj issue` Guidance in `docs/fj-guide.md`

`docs/fj-guide.md` currently covers **only `fj pr`** subcommands. It has zero coverage of `fj issue`, which explains why agents drift:

- **`gh` syntax leakage:** agents call `fj issue create --title "..." --body "..."` because `gh issue create` uses those flags. `fj issue create` does not support `--title` — use positional argument instead.
- **No canonical reference:** without an authoritative `fj issue` pattern in `fj-guide.md`, each agent invents its own, leading to inconsistent usage.

**What `fj issue create` actually accepts** (vetted against Forgejo's CLI):

```bash
# Positional title, no --title flag
fj issue create "Title text"              # position 1 is the title
fj issue create "Title text" --body-file /tmp/body.md
fj issue create "Title text" --body "..." # valid but discouraged — use --body-file
fj issue create                           # opens $EDITOR for both title and body
```

**Recommendation:** add an `fj issue` section to `docs/fj-guide.md` covering:

| Action | Command |
|--------|---------|
| Create issue with body file | `fj issue create "Title" --body-file <path>` |
| Create issue (editor) | `fj issue create` (opens `$EDITOR` for title + body) |
| List issues | `fj issue list` |
| View issue | `fj issue view <id>` |
| Close issue | `fj issue close <id>` |