---
type: intent
timestamp: 2026-10-17T13:35:15Z
responding-to: required gate failure showing the bundled nginx template had not been synchronized
---

## Synchronize the packaged Compose resource

Per operator request: the required gate exposed that the generated bundled copy of `nginx/default.conf.j2` does not match the source tree. I will run Cove's resource sync script so the wheel carries the streaming ingress fix, then rerun the gate. This changes repository packaging resources only; no deployment is involved.

**Commits in this unit:** none yet
