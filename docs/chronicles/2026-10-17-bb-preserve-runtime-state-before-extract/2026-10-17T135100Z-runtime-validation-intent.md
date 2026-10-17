# Tighten runtime file validation and recovery notes

Per operator request: retain `.env` and generated `nginx/default.conf` inode identity, fail before pruning on unsafe runtime paths, and preserve a private `.env` mode. Add targeted parent-symlink and mode coverage, then clarify the plan and operator docs. Work remains confined to the temporary worktree and test roots; defer the full gate until recovery is complete.
