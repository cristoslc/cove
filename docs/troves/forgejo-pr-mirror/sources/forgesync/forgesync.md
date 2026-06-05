---
type: repository
name: Forgesync
url: https://codeberg.org/helvetica/forgesync
fetched: 2026-06-04
language: Python
license: Unknown (Nix flake + container)
---

# Forgesync

Automatically mirrors all Forgejo repositories to GitHub or any Forgejo instance.

## Key Capabilities

- Automatically creates target repositories on destination
- Syncs repository metadata (descriptions, topics, etc.)
- **Supports syncing Pull Requests** via `--feature pull-requests` flag
- Supports syncing Issues via `--feature issues` flag
- Sets up push mirrors directly within the source Forgejo instance
- Filters out forks, mirrors, and private repositories

## PR Sync Details

- PR metadata and state are synced from Forgejo to GitHub (one-way)
- Uses `--feature pull-requests` flag to enable
- PR content sync level: metadata + state (full conversation thread level not explicitly documented)
- Direction: Forgejo → GitHub only

## Deployment Options

- **Nix/NixOS**: Flake package and NixOS module
- **Container**: Docker/Podman with environment variable token configuration
- **CLI**: `forgesync <source-api> <target> [options]`

## Token Requirements

- `SOURCE_TOKEN`: `write:repository`, `read:user`
- `TARGET_TOKEN` (Forgejo): `write:repository`, `write:user`
- `MIRROR_TOKEN` (Forgejo): `write:repository`
- `TARGET_TOKEN` (GitHub): Administration (R/W), Contents (R), Metadata (R)
- `MIRROR_TOKEN` (GitHub): Contents (R/W), Metadata (R)

## Limitations

- One-way only (Forgejo → GitHub)
- Does not track renames
- No state about repository history maintained
- Does not sync PR conversation threads in full fidelity

## CLI Example

```bash
export SOURCE_TOKEN=my_codeberg_token
export TARGET_TOKEN=my_github_token
export MIRROR_TOKEN=my_github_mirror_token

forgesync https://codeberg.org/api/v1 github \
  --remirror \
  --feature issues \
  --feature pull-requests \
  --on-commit \
  --mirror-interval 8h0m0s \
  --exclude myrepo
```