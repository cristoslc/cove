**Responding to:** operator ran `cove up`; acceptance verification resumed

Checkpoint: **both core acceptance items verified live.**

- **Runner online in Forgejo admin**: runner `d8bb985d268b` status `idle`, labels `['ubuntu-latest', 'docker']` (verified via `/api/v1/admin/actions/runners`).
- **Trivial workflow executes on push**: scratch repo `cristos/runner-smoke-test`, echo workflow → run #6 `success` (runs 3-5 failed under the old broken labels, expected).

Three live-only defects found and fixed in the branch (each red-test-first):

1. **Wrong registration endpoint**: `GET /api/v1/actions/runners/registration-token` returns 404 on this Forgejo; the working endpoint is `GET /api/v1/admin/actions/runners/registration-token` (the docs-review M-finding, now empirically confirmed). Fixed provision_forgejo.yml + doc + test.
2. **Registration race**: an unregistered daemon crash-loops in <1s cycles, so `docker exec` (and even `container:<name>` netns attach) cannot reliably land. Fixed: register via a one-shot container on `cove_default` — `.runner` lands in the shared volume and the daemon picks it up on its next restart.
3. **Broken job images + two env gaps**: `data.forgejo.org/oci/ubuntu` does not resolve (pull fails → job fails in ~1s). Labels now map both `ubuntu-latest` and `docker` to `gitea/runner-images:ubuntu-latest` (pulled fine). Also fixed live: the image runs as 1000:1000 and the Colima socket is gid 991/660 → `group_add: 991` in compose; and job containers need `container.network: cove_default` (shipped `compose/forgejo-runner/config.yml`) or they can't reach `forgejo:3000`.

**Unit gate: 440 passed, 0 failed** (49 runner tests).

Also handled during this window: unsealed the restored Vault via bootstrap_vault.yml (it had re-sealed on restart) and confirmed the playbook end-to-end from the branch (`failed=0`, summary prints "registered and online"). Debug log level left at `debug` in the shipped config — intentional for the first days of operation; drop to `info` once stable (note in doc TODO).

Cleanup pending: delete scratch repo `cristos/runner-smoke-test` after operator eyeballs the run at https://git.cove.local/cristos/runner-smoke-test/actions

Vault stretch goal remains deferred per plan.