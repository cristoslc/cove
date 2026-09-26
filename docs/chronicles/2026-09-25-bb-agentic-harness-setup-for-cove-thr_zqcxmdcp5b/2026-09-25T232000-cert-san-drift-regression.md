---
type: regression-fix
timestamp: 2026-09-25T232000
responding-to: operator hit `cove up` failure (MISSING: ade.cove) minutes after the v0.7.0 promote — first real-world exercise of the release
---

## The v0.7.0 upgrade regression — TLS cert SAN drift

**Symptom.** `cove up` on the live machine (MBPBK-202602) failed at *Validate
TLS cert covers required hostnames*: `MISSING: ade.cove`. The operator's cert
predates ADE Phase 1; the new validation demands SANs the old leaf lacks.
Phase 1's staging deploy always generated fresh certs (with the SANs), so the
upgrade path was never exercised. Staging isolated, live broken — the exact
blind spot the isolated-staging work bought, and the limit of it.

**Root cause — three layers stacked:**

1. bringup's cert task carried a `creates:` guard, so the drift-aware
   `sign_cert` (which already regenerated on SAN-set divergence) never ran on
   existing deployments. The register `cert_check` was wired to nothing — a
   tripwire with no healing path behind it.
2. Once the guard is removed, a second latent bug surfaces: the SAN comparison
   compared requested strings against parsed cert entries, and IPs parse as
   `IPv4Address`/`IPv6Address` objects — never equal to `"127.0.0.1"`. Every
   real SAN list carries IPs, so *any* run would have regenerated forever.
   Found not by the unit suite (pure-DNS vectors) but by the E2E simulation of
   the operator's state — the third run printed `Signed:` instead of
   `Up-to-date:`.
3. `cove certs sign` printed `Signed:` unconditionally, so Ansible had no
   changed/skipped signal to key `changed_when` (or the nginx reload) off.

**Fix (PR #56).** The sign task runs on every `cove up`: `sign_cert` heals SAN
drift and settles idempotent (canonical `(kind, value)` comparison keys); the
CLI prints an honest `Signed:`/`Up-to-date:` verdict; `changed_when` reads it
and a regenerated leaf notifies *Reload nginx* (otherwise nginx keeps serving
the stale cert); the fail-loud validation remains as the safety net. New
parity test: the validation host list must be a subset of the sign argv SANs —
the divergence class that caused this can not silently recur. Healed leaf
verifies against the *same* CA, so system trust is preserved (leaf re-issue,
not CA rotation).

**Meta.** The bug shipped because the only tested deploy path was
fresh-cert (staging) and the only untested path was the operator's own
machine. The validation task was correct as a tripwire; what was missing was
the self-heal behind it. Gate after fix: 621 passed / 28 deselected.
Release: 0.7.1 (changelog carries the full diagnosis).
