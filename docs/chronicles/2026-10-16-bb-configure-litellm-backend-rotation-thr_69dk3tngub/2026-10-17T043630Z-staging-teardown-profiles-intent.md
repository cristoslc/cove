---
type: intent
timestamp: 2026-10-17T043630Z
responding-to: isolated staging teardown left profile services behind
---

## Cover every started staging profile during teardown

**Responding to:** the isolated staging run reported that teardown exited successfully while LiteLLM and its database remained in the staging project.

Per operator request: I will add failing coverage proving teardown enables every profile that can be started in staging, then update its Compose down command. I will also compare teardown's data-root safety checks with deploy's canonical overlap guard and add focused protection if teardown can delete an overlapping live root. Success means the regression tests fail before the script change, the required non-E2E/non-staging gate passes, and no live or staging services are run.

**Commits in this unit:** none yet
