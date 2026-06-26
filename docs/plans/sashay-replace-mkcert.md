# Sashay: Replace mkcert with Python `cryptography`

**PR:** https://git.cove/cristos/cove/pulls/33
**Branch:** `sashay-replace-mkcert` (new, off `main`)
**Status:** Complete
**Architecture:** `docs/musings/cove-repo-fair.md`, `docs/musings/parleys/2026-06-25-uvx-dependencies.md`

## Scope

Replace the mkcert Go binary dependency with a Python module using `cryptography` to generate the root CA and sign TLS certificates. The system trust store install still needs sudo — that's irreducible. But mkcert itself becomes a host prerequisite eliminated.

## What mkcert does for Cove

Three distinct roles:

1. **Root CA generation + trust store install** — `mkcert -install` creates `rootCA.pem` + `rootCA-key.pem` in `~/Library/Application Support/mkcert/` and installs the cert into the macOS Keychain (or Linux trust store).
2. **Wildcard cert signing** — `mkcert -key-file ... -cert-file ... "*.cove" ...` generates a TLS cert signed by the local CA covering 11 SANs.
3. **CA path discovery** — `mkcert -CAROOT` prints the CA directory path.

## What stays the same

- The root CA files (`rootCA.pem`, `rootCA-key.pem`) — same format, same locations (just managed by Python instead of mkcert).
- The wildcard cert files (`cove.local.pem`, `cove.local-key.pem`) — same format, same location (`{{ cove_data_root }}/certs/`).
- The nginx config that mounts and serves `rootCA.pem` — unchanged.
- The `.mobileconfig` base64-encode step — operates on the PEM file, not mkcert-specific.
- The `openssl` cert validation step — unchanged.
- The `compose/certs/` directory and its mount into nginx — unchanged.

## Changes

### 1. New Python module: `cli/cove/certs.py`

A module that replaces all mkcert operations:

```python
# Key operations:
# - ensure_ca() -> Path  — generate root CA if missing, install to trust store
# - ca_path() -> Path    — return CA directory path
# - root_ca_pem() -> str — return root CA PEM content
# - sign_cert(sans: list[str], key_file: Path, cert_file: Path) — generate signed cert
```

**Root CA location:** `~/.config/cove/pki/` (replaces `~/Library/Application Support/mkcert/`). Cross-platform, no macOS-specific path.

**Trust store install:**
- macOS: `security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain <pem>` (needs sudo)
- Linux: copy to `/usr/local/share/ca-certificates/` and run `update-ca-certificates` (needs sudo)
- Skip if already installed (detect by fingerprint)

**Cert generation:**
- Root CA: RSA-2048 or ECDSA P-256, self-signed, CA:true, 10-year validity
- Leaf certs: ECDSA P-256 (faster than RSA), signed by root CA, 1-year validity, with all SANs

### 2. Update `compose/bringup.yml`

Replace these mkcert tasks (lines 76-164):

| Current task | Replacement |
|---|---|
| `Ensure mkcert is available` | Remove — no longer a prerequisite |
| `Install mkcert CA` | `cove certs ensure-ca` (Ansible `command` module) |
| `Detect mkcert CAROOT path` | `cove certs ca-path` |
| `Read root CA certificate` | `cove certs root-ca-pem` (or read from known path) |
| `Copy rootCA.pem into compose dir` | Unchanged — operates on file, not mkcert |
| `Base64-encode root CA` | Unchanged — operates on file content |
| `Generate mkcert cert for *.cove` | `cove certs sign --sans ...` |
| `Validate TLS cert` | Unchanged — `openssl` validation |

The Ansible tasks call the `cove` CLI's new `certs` subcommand. This keeps the provisioning flow in Ansible (idempotent, declarative) while the actual crypto lives in Python.

### 3. New CLI subcommand: `cove certs`

```python
@click.group()
def certs():
    """Manage TLS certificates."""

@certs.command()
def ensure_ca():
    """Generate root CA if missing and install to system trust store."""

@certs.command()
def ca_path():
    """Print the CA directory path."""

@certs.command()
def root_ca_pem():
    """Print the root CA certificate in PEM format."""

@certs.command()
@click.option("--sans", multiple=True, required=True)
@click.option("--key-file", required=True)
@click.option("--cert-file", required=True)
def sign(sans, key_file, cert_file):
    """Generate a TLS certificate signed by the root CA."""
```

### 4. Update `scripts/staging/deploy.sh`

- Remove `command -v mkcert` prereq check (line 52)
- Remove `MKCERT_CAROOT` export and `REAL_CAROOT` logic (lines 86-92)
- Replace with `cove certs ensure-ca` call and direct path references to `~/.config/cove/pki/`
- Keep the cert symlink logic (lines 128-129) — unchanged

### 5. Update `cli/cove/project.py`

- Remove mkcert from the prerequisites list in generated project docs
- Update the TLS description to reference Cove's own PKI

### 6. Update templates

- `cli/cove/templates/detail-cove.md.j2` — replace mkcert references
- `cli/cove/templates/project-guidance.md.j2` — replace mkcert references

### 7. Update documentation

- `README.md` — remove mkcert from prerequisites
- `AGENTS.md` — update sudo note (still needs sudo for trust store, but no mkcert)
- `docs/architecture.md` — update TLS section
- `docs/pages.md` — update mkcert reference

### 8. Add `cryptography` to `pyproject.toml` dependencies

```toml
dependencies = [
    ...
    "cryptography>=42.0.0",
]
```

### 9. Tests

- **Unit tests for `certs.py`:** generate CA, sign cert, verify cert chain, verify SANs match
- **Unit test for trust store install:** mock the OS-specific commands, verify correct invocation
- **Unit test for idempotency:** running `ensure_ca` twice doesn't regenerate
- **E2E test:** `cove certs ensure-ca` + `cove certs sign` produces a valid cert that `openssl verify` accepts
- **E2E test:** `cove up` succeeds without mkcert installed (requires full staging deploy)
- **Regression test:** existing E2E DNS tests still pass (they check nginx config, not mkcert)

### 10. Remove mkcert from `.gitignore`

The `# TLS infra` section ignores `/compose/certs/`. That stays — the certs are still auto-copied by bringup. But the mkcert-specific comment should be updated.

## Chronicle

**Completed:** 2026-06-25
**Commits:** 5 (b8359ac → 2b2769a)
**Tests:** 212 passed (35 new + 177 existing)
**Staging:** Cert generation verified end-to-end. Docker mount error on nginx container is pre-existing (Colima read-only filesystem), not related to this change.

### Deviations from plan

- **`certs.py` location:** Root CA stored at `~/.config/cove/pki/` (not `~/Library/Application Support/mkcert/`). Cross-platform, no macOS-specific path.
- **`--skip-trust-store` flag:** Added to `cove certs ensure-ca` for staging deploy, which runs without sudo. Corresponding `cove_skip_ca_install` Ansible var added to `bringup.yml`.
- **Staging PATH fix:** Ansible calls `cove` from system PATH, not the staging venv. Added `export PATH="$UV_VENV/bin:$PATH"` before `cove up` in `deploy.sh`.
- **Staging cert handling:** `deploy.sh` now runs `cove certs ensure-ca --skip-trust-store` and copies `rootCA.pem` directly before `cove up`, since the Ansible `when` conditions on CA tasks don't fire in staging (different HOME).
- **`.gitignore` comment:** Updated from "mkcert" to "CA" — no structural change needed.
- **`ansible-core` dependency:** Not added in this sashay — deferred to the compose drift sashay per the parley.

### Files changed

18 files, +1138 / -114 lines across `cli/`, `compose/`, `scripts/`, `docs/`, and project root.

- System trust store install without sudo — irreducible (kernel-level requirement on both macOS and Linux).
- Replacing the `openssl` cert validation step — that's a separate concern.
- The compose drift fix (Option D from the musing) — separate sashay.
- Renaming the package to `cove` on PyPI — separate sashay.
- Adding `ansible-core` to dependencies — small enough to do inline.

## Sashay steps

1. Create worktree `.worktrees/sashay-replace-mkcert`, branch off `main`.
2. Write `cli/cove/certs.py` with full test suite (test-first per discipline).
3. Add `cove certs` CLI subcommand.
4. Add `cryptography` to `pyproject.toml`.
5. Update `compose/bringup.yml` to call `cove certs` instead of mkcert.
6. Update `scripts/staging/deploy.sh`.
7. Update templates and documentation.
8. Run full test suite: `uv run --directory cli pytest tests/ -q`.
9. Staging E2E: deploy, verify `cove up` works without mkcert, verify TLS certs valid, teardown.
10. Code review.
11. Chronicle + PR.
