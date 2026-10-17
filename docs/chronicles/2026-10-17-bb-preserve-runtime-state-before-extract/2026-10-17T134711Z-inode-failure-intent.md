# Preserve runtime inodes and survive copy failure

Per operator request: keep `.env` and generated `nginx/default.conf` physically in place during resource extraction so bind-mounted inode identity remains stable, and prove they survive a bundled-resource copy failure. Keep the allowlist narrow and retain symlink/FIFO rejection. Add the two regressions first, then revise extraction and run focused tests on temporary roots only. The full gate remains paused until parent recovery is complete.
