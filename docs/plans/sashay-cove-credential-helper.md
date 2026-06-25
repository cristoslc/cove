# Sashay: Cove Credential Helper — `cove creds git-helper`

**Musing:** [cove-credential-helper.md](../musings/cove-credential-helper.md)
**Branch:** `sashay-cove-credential-helper`

## Problem

`git push` to `https://git.cove/...` fails with "Credentials are incorrect or have expired" because GCM's Generic provider returns cached OAuth access tokens without checking expiry or refreshing them. The user's `fj` `keys.json` has a valid Application token, but GCM doesn't read it.

## Solution

Add `cove creds git-helper` — a `git credential` protocol helper that reads `fj`'s `keys.json`, returns Application tokens directly (no expiry), and refreshes OAuth tokens when expired. Configured as:

```
git config --global credential.https://git.cove.helper '!/path/to/cove creds git-helper'
```

## Tasks

### 1. Add `git-helper` command to `creds.py`

Create the `git_helper` function in `creds.py`:

**Input (stdin):** `git credential` protocol — `key=value\n` lines, blank-line terminated.
```
protocol=https
host=git.cove
username=cristos

```

**Logic:**
1. Parse stdin into a dict
2. Determine host from `host` key
3. Read `~/Library/Application Support/Cyborus.forgejo-cli/keys.json`
4. Look up `hosts[host]`:
   - **Application token:** return `username=<name>\npassword=<token>\n` — no expiry
   - **OAuth token:** check `expires_at`. If not expired, return it. If expired, refresh via `POST https://<host>/login/oauth/access_token` with `grant_type=refresh_token`, update `keys.json` atomically, return new token
   - **Not found:** exit 0 with no output (fall through to next credential helper)
5. If `keys.json` doesn't exist or can't be parsed, exit 0 with no output

**Output (stdout):** `git credential` protocol — `key=value\n` lines, blank-line terminated.
```
username=cristos
password=3632690a299c3579b1475f31c8953dddaf86eea1

```

**Client ID resolution** (for OAuth refresh):
1. Check `~/.config/forgejo-cli/client_ids` (same as `fj`)
2. Check `/etc/fj/client_ids`
3. Fall back to well-known Gitea client ID: `e90ee53c-94e2-48ac-9358-a874fb9e0662`

**`expires_at` format:** `fj` serializes `time::OffsetDateTime` as a 9-element JSON array: `[year, ordinal_day, hour, minute, second, nanosecond, ...]`. Convert to Unix timestamp for comparison.

**Atomic write:** Write updated `keys.json` to a temp file in the same directory, then `os.rename()`.

### 2. Register command in `creds.py` Click group

Add `@creds.command("git-helper")` decorator. No arguments — reads from stdin.

### 3. Add tests

Create `tests/test_credential_helper.py`:

- **Test: application token returned directly** — mock `keys.json` with an Application entry, verify correct username/password output
- **Test: OAuth token not expired returned directly** — mock with future `expires_at`, verify no refresh call
- **Test: OAuth token expired triggers refresh** — mock with past `expires_at`, verify HTTP POST to token endpoint, verify updated `keys.json`
- **Test: host not found falls through** — mock `keys.json` without the host, verify empty stdout, exit 0
- **Test: no keys.json falls through** — verify empty stdout, exit 0
- **Test: refresh fails falls through** — mock HTTP 400, verify empty stdout, exit 0
- **Test: expires_at parsing** — verify correct conversion from `[2026, 172, 14, 30, 0, 0, 0, 0, 0]` to timestamp
- **Test: atomic write** — verify temp file + rename pattern

### 4. Update `cove install` to configure the helper

In `cli.py`'s `install` command (or a new `cove creds install-helper` subcommand), add logic to:
1. Check if `credential.https://git.cove.helper` is already set
2. If not, set it: `git config --global credential.https://git.cove.helper '!/path/to/cove creds git-helper'`
3. Use the full path to the `cove` binary (resolve via `shutil.which`)

### 5. Manual verification

After implementation:
1. `cove creds git-helper` with stdin for git.cove → should return the Application token from `keys.json`
2. `git ls-remote https://git.cove/cristos/cove.git` → should succeed without auth prompt
3. Simulate OAuth expiry by editing `keys.json` `expires_at` to the past → verify refresh

## Dependencies

- `requests` (already in `pyproject.toml`)
- No new dependencies needed

## Verification

```bash
# Unit tests
uv run --directory cli pytest tests/test_credential_helper.py -v

# Manual: test the helper directly
echo -e "protocol=https\nhost=git.cove\n" | uv run --directory cli cove creds git-helper

# Manual: test git uses it
git ls-remote https://git.cove/cristos/cove.git
```
