---
type: intent
timestamp: 2026-10-17T13:43:30Z
responding-to: operator request to preserve persistent runtime Compose files across resource extraction
---

## Add temp-root regressions for the narrow runtime preservation allowlist

Per operator request: preserve only the persistent `.env` and generated `nginx/default.conf` across extraction, keep backup staging outside the extracted tree, preserve file bytes and modes, reject symlink sources before deleting anything, and continue refreshing bundled files such as compose source/pins. I will add these regressions against temporary roots before implementing the extraction change.

**Commits in this unit:** none yet
