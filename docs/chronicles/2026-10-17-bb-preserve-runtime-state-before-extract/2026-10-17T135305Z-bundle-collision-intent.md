# Prove bundle files cannot replace local runtime paths

Per operator request: keep the allowlist narrowly local even if a future bundled resource accidentally contains `.env`, `nginx/default.conf`, or `.version`. Extend the temp bundle fixture with conflicting marker contents and verify extraction refreshes ordinary resources while runtime values remain. Run focused tests only; do not run the required full gate until parent recovery is complete.
