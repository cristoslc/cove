---
type: verification
timestamp: 2026-10-17T13:53:17Z
responding-to: bundled path collision intent
---

## Bundled paths cannot replace local runtime files

Per operator request: the temporary bundle now contains conflicting `.env`, `nginx/default.conf`, and `.version` files. The 11 focused resource-preservation cases pass, and the expanded resource plus isolated CLI set passes **43 tests**. Extraction kept the local env/config inode and bytes, wrote the newly computed marker after copying, and refreshed ordinary Compose files. The full gate remains pending parent recovery completion.
