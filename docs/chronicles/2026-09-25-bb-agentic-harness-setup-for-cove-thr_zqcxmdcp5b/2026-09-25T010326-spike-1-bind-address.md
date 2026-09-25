---
type: checkpoint
timestamp: 2026-09-25T010326
responding-to: plan spike 1 — can bb bind non-loopback inside a container
---

## Spike 1 — non-loopback bind works, no bb Connect required

**Responding to:** the plan's Spike 1 (bind address in container), which gates the ingress design.

**Result: PASS.** bb exposes a first-class launcher flag `--server-bind-host <host>` (also env `BB_SERVER_BIND_HOST`), accepting only `127.0.0.1` or `0.0.0.0`. With `--server-bind-host 0.0.0.0` the server binds wildcard IPv4 and is reachable without any Connect pairing. Verified live with an isolated instance (temp data dir, port 38899, not the operator's 38886):

```
$ npx -y bb-app@0.43.4 --data-dir <tmp> --server-bind-host 0.0.0.0 \
    --server-port 38899 --host-daemon-port 38898
✓ Server listening on http://0.0.0.0:38899
$ lsof -nP -iTCP:38899 -sTCP:LISTEN
node ... TCP *:38899 (LISTEN)
$ curl -o /dev/null -w '%{http_code}' http://192.168.0.29:38899/   # LAN IP
200
```

bb's own docs (`docs/multiple-devices.md`) confirm the flag: "Inside a container, `0.0.0.0` listens on the container's IPv4 interfaces; the container runtime must still publish that port to the host." The cove network reaches the container by service name, so no host port publish is needed for ingress.

**Caveat carried into Spike 2:** the same doc calls wildcard binding "security-sensitive" and "for compatibility only" because the public API is unauthenticated. That is an auth decision, not a bind blocker — it is exactly what Spike 2 characterizes.

**Commits in this unit:** none yet (spike investigation, no files changed).
