# Plan: fj repo create AlphaDashDot validation — Docs workaround (#28)

## Issue
`fj repo create` fails with `AlphaDashDot` validation error for any repo name,
making it impossible to create repos via the CLI.

## Scope
Docs-only: update `docs/fj-guide.md` to document this bug and the API
workaround.

## Tasks

### 1. Document the `fj repo create` bug
- Add a troubleshooting section entry noting that `fj repo create` fails with
  `AlphaDashDot` validation for any repo name
- Show the error message: `validation failed: [Name]: AlphaDashDot`
- Note that this is an upstream `fj` bug (not a Cove bug)

### 2. Document the API workaround
- Show the curl command to create a repo via the Forgejo API directly:
  ```shell
  curl -X POST https://git.cove/api/v1/user/repos \
    -H "Authorization: token <token>" \
    -d '{"name":"repo-name"}'
  ```
- Note that the token can be retrieved from the fj auth config at
  `~/Library/Application Support/Cyborus.forgejo-cli/keys.json`
- Reference the `cove creds vault-get` / `cove creds vault-put` pattern for
  token management (per AGENTS.md, do not hardcode secrets)

### 3. Update the repo commands section
- Add a note under `fj repo create` in the commands table that it is
  currently broken and to use the API workaround

## Verification
- `docs/fj-guide.md` renders correctly in the forge web UI
- The workaround curl command is syntactically correct