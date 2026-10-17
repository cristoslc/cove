---
type: intent
timestamp: 2026-10-17T140717Z
responding-to: 0.14.1 package metadata and changelog are prepared
---

## Run the required post-merge gate without touching installed Compose resources

**Responding to:** package version, lock version, and dated changelog section now agree on 0.14.1, with a fresh Unreleased heading.

Per operator request: snapshot the installed Compose manifest, run `uv run --directory cli pytest -x -q -m "not e2e and not staging"`, then compare the manifest. Success means the gate passes and the installed resource tree is unchanged; no Cove lifecycle or extraction command will run.

**Commits in this unit:** none yet
