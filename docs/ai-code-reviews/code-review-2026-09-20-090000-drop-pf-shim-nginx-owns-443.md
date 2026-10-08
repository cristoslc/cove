# Code Review: drop-pf-shim-nginx-owns-443 (fjl/main...HEAD)

**Refs:** fjl/main...HEAD (PR #50, draft)
**Platform:** forgejo
**Diff method:** git-ref-diff
**Dispatch:** specialist
**Date:** 2026-09-20T09:00:00-04:00

---

## Models

**Report author (orchestrator):** glm-5.3-flash (zai)

**Review subagents:**

| Role | Model |
|------|-------|
| security | inherited (glm-5.3-flash) |
| style | inherited (glm-5.3-flash) |
| logic | inherited (glm-5.3-flash) |
| docs | inherited (glm-5.3-flash) |
| synthesis | inherited (glm-5.3-flash) |

---

## Recommendation: needs_changes

No critical or high findings: the security agent passed clean, noting the pf shim removal actually reduces host firewall exposure and the 0.0.0.0:443 publish keeps the access surface equivalent. However, three independent medium findings converge on the same theme: incomplete propagation of the port migration. The documented pf remediation targets an anchor that never held the rule, so upgraded machines keep blackholing loopback HTTPS even after following the docs exactly (flagged by two agents); the upgrade notes skip git-remote/GCM-credential migration off :8443; and the port-coupling comment in status.py omits the litellm.py/speedtest.py modules that hardcode 443, setting up split-brain health probes. Three low findings reinforce the same duplication/inconsistency pattern (hardcoded URLs, README contradicting architecture.md on the nginx bind, an invalid tailscale serve command). Fix the pf remediation command, add the 8443 credential/remote migration note, and reconcile the port coupling (constant + comment + probes + guard tests) before merge.

---

### security — passed

No actionable security findings. The port migration changes the published host port from 0.0.0.0:8443 to 0.0.0.0:443, which keeps the network exposure surface equivalent since both publishes bind all interfaces and the pf shim only affected loopback traffic. Removing the pf task eliminates a ruleset that loaded 'pass all' on the host firewall, a security improvement, and removing the tailscale serve task does not reduce or expand access since the direct 0.0.0.0:443 binding covers the same tailnet reachability. No secrets, credentials, or tokens were introduced in the new docs, chronicle, or prompt files. Auth posture, the LiteLLM nginx route whitelist, and all input handling are unchanged. The new guard tests pin the removal so bringup cannot resurrect the pf or tailscale serve configuration.

### style — warning

1. **[low] Hardcoded 443 URL literals duplicate the NGINX_HTTPS_PORT constant in litellm.py and speedtest.py** — cli/cove/status.py owns the ingress port as NGINX_HTTPS_PORT and formats all of its URLs from it. litellm.py:237 and speedtest.py:281 instead write the port into their curl URLs by hand. If the publish port moves again, status.py picks up the change from one constant while these two probes keep dialing the old port, so `cove litellm status` and `cove speedtest status` report UNREACHABLE against a healthy stack. Fix: import NGINX_HTTPS_PORT from cove.status in both files, build the curl URLs via f-strings, and flip the guard-test assertions to the parameterized form in the same change.
2. **[low] README services table still says nginx HTTPS access is 127.0.0.1:443** — README.md:11 contradicts docs/architecture.md and compose (0.0.0.0:443). An operator debugging LAN access from the README chases the wrong cause, and the README understates the ingress's real exposure. Fix: update the nginx row to `0.0.0.0:443` (HTTPS), `:8080` (HTTP).
3. **[low] Duplicate review report committed under two names for the same HEAD** — docs/ai-code-reviews/ carries two reports for f43912e with identical bodies and verdicts (code-review-2026-09-19-... and code-review-2026-09-20-034410-...). A reader cannot tell which is canonical. Fix: `git rm docs/ai-code-reviews/code-review-2026-09-19-drop-pf-shim-nginx-owns-443.md`.

### logic — warning

1. **[medium] Upgrade remediation flushes an empty pf anchor and leaves the stale 443 to 8443 redirect active** — the old shim task wrote the rdr rule into the MAIN pf ruleset (`pfctl -ef -`); the cove-https anchor was never populated. `sudo pfctl -a cove-https -F all` is a no-op, so loopback 443 keeps redirecting to dead 8443 even after the operator follows every documented step; the shim's 'pass all' ruleset also persists. Fix: replace the pf bullet's command with `sudo pfctl -f /etc/pf.conf` (reload default ruleset) and state the rule lives in the main ruleset.
2. **[medium] Upgrade notes omit migration for git remotes and GCM credentials keyed to port 8443** — data-inventory.md documents GCM keychain entries named 'git:https://cove.local:8443'. After this branch removes the last 8443 publish, those remotes get connection refused and GCM will not match stored :8443 credentials, forcing unexpected re-auth or failed push — breaking the branch's own acceptance criterion (HTTPS push to git.cove) on exactly the machines the upgrade section targets. Fix: add an upgrade bullet for `git remote set-url` off :8443 and clearing stale GCM keychain entries.

### docs — warning

1. **[medium] status.py port-constant comment omits the CLI modules that hardcode the same port** — the comment on NGINX_HTTPS_PORT (cli/cove/status.py:40) only warns about the compose publish, but cli/cove/litellm.py:237 and cli/cove/speedtest.py:281 also hardcode https://127.0.0.1:443/ independently. A developer raising the port would edit the constant plus compose and reasonably assume the rest of the CLI follows, producing split-brain health checks. Fix: extend the comment to list litellm.py and speedtest.py as lockstep coupling points.
2. **[medium] pf shim remediation command targets an anchor that never held the rule** — same root cause as logic finding 1 (merged above in recommendation).
3. **[low] tailscale serve remediation names a command the current serve CLI does not have** — the upgrade section says `tailscale serve off`; the current serve CLI exposes `reset` (the repo's own cutover plan uses `tailscale serve reset`). Operators hit a command-not-found error and leave the stale 443→8443 forward active. Fix: use `tailscale serve reset`.
4. **[low] README services table understates the nginx binding the same file documents** — same as style finding 2.

---

## Finding Counts

| Source | Critical | High | Medium | Low | Total |
|---|---|---|---|---|---|
| security | 0 | 0 | 0 | 0 | 0 |
| style | 0 | 0 | 0 | 3 | 3 |
| logic | 0 | 0 | 2 | 0 | 2 |
| docs | 0 | 0 | 2 | 2 | 4 |
| synthesis (deduped) | 0 | 0 | 3 | 3 | 6 |

---

*Generated by code-review — multi-agent code review system*