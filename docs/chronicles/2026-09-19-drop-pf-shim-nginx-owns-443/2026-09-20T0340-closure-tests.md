**Responding to:** closure loop step 7 (pre-test inventory + automated tests)

Per-sashay delta: nginx port map, bringup pf/serve task removal, status.py
port constant, litellm/speedtest probe URLs, 3 source-string test assertions,
2 new structure tests, 4 docs. Coverage matrix self-healed: added "nginx binds
443 directly" and "bringup has no pf-rdr / tailscale-serve steps" paths (happy
executable; the sad path for bringup removal is structurally N/A — absence is
the feature). Test gate re-run by orchestrator on the subagent's HEAD:
442 passed, 25 deselected (e2e/staging), 0 failed.
