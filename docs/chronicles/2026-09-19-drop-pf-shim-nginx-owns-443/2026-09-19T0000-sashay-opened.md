**Responding to:** operator approval ("very well") to open the sashay on the pf-drop decision

Sashay opened 2026-09-19 for the plan in `docs/plans/drop-pf-shim-nginx-owns-443.md`.
Scope: nginx binds 443 directly, pf rdr shim deleted from bringup, tailscale serve
removed, `cove status` probes 443. Acceptance: HTTPS push to `git.cove` works with pf
disabled; status green when 443 works, red when not. Live cutover is operator-assisted
(sudo). Promote (reinstall `cove`) is post-merge only.