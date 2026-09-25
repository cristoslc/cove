---
type: review-response
timestamp: 2026-09-25T130610
responding-to: delta review of PR #55 (3 items: N1 ADE_PORT source of truth, N2 matrix honesty, N3 test/comment nits)
---

## Delta review response — N1, N2, N3 resolved

**Responding to:** the PR #55 delta review, which returned ACTIONABLE with two no-security-risk items on the `ADE_PORT` source of truth and coverage honesty plus a nit, and required a green gate before squash-merge.

### N1 (major) — `ade_port` is now the live-path single source of truth

The real defect: `compose/nginx/default.conf.j2:203` renders the Ansible var `ade_port`, but `ade_port` was undefined (fell back to the inline default), while `compose/bringup.yml` wrote `ADE_PORT` into the compose `.env` from that same possibly-undefined var. An operator setting `ADE_PORT` in the environment moved the container port while nginx kept proxying to the old one.

Fix, one Ansible var mirroring `nginx_https_port`:

- `compose/group_vars/all.yml:64-65` adds `ade_container_name: cove-ade-server` and `ade_port: 38886` under an "ADE (bb server, optional)" block.
- `compose/nginx/default.conf.j2:203` now resolves `ade_port` from group_vars (no silent inline fallback required).
- `compose/bringup.yml:516-524` adds "Ensure ADE env matches the Ansible vars": a `lineinfile` that re-syncs `.env` `ADE_PORT`/`ADE_CONTAINER_NAME` from `ade_port`/`ade_container_name` on **every** `cove up` (not just first boot), so a changed `ade_port` cannot leave the container ahead of the rendered nginx. This closes the "first-boot-only .env" gap the review named: nginx is re-rendered and `.env` re-synced in the same run.
- `docs/services/ade.md` configuration section rewritten: `ade_port` (Ansible) is labeled the **live-path knob**; the change procedure is "set `ade_port` in `host_vars`/`group_vars` and re-run `cove up`". The `.env` `ADE_PORT` row now states it is derived and rewritten, explicitly not a durable hand-edit override.
- Tests: `test_ade_port_defined_in_group_vars` (group_vars defines `ade_port`=38886 and `ade_container_name`) and `test_nginx_upstream_and_env_share_ade_port_var` (nginx references `ade_port`; bringup `.env` sets `ADE_PORT` from `ade_port`). `test_ade_port_is_threaded_from_ade_port` still covers the compose default.

### N2 (minor) — matrix honesty

- Access-control row renamed to `ade.cove access control (allow loopback + private ranges + tailnet; deny public)` (`docs/test-coverage-matrix.yaml:401`), matching the widened allow-list from `bca608e`.
- `ade container image build` (`:436`) downgraded `happy: executable` → `manual`: no default-gate test builds the image, so the cell no longer lies. **Correction note:** my prior review-response chronicle (`2026-09-25T012919-review-response.md`) claimed the image-build row had been downgraded to `manual` in the first fix unit; in fact only the live `/health` and `/ws` rows were, and this row carried `happy: executable` until now (a later staging commit briefly re-set health/ws happy to executable). This entry supersedes that claim for the image-build row.

### N3 (nit) — test assertion + teardown comment

- `cli/tests/test_ade.py:480` now asserts `allow ::1;` in the rendered `ade.cove` block (full loopback + private-range + tailnet list).
- `scripts/staging/teardown.sh:69` Guard 4 comment corrected: the code checks equality with the live root plus the `"staging"` substring marker, not an ancestor walk.

### Verification

- Focused: `pytest tests/test_ade.py` → **45 passed**.
- Gate: `uv run --directory cli pytest -x -q -m "not e2e and not staging"` → **608 passed, 28 deselected, 0 failed** (300s budget; took 162s).
- `ansible-playbook --syntax-check compose/bringup.yml` → valid.
- Rendered nginx with `ade_port=38886` from group_vars → `set $ade_upstream http://ade:38886;`.
- Live stack untouched: read-only checks only; operator's bb on 38886 still 200; live container uptimes unchanged.

### Not fixed

None; all three items resolved.

**Commits in this unit:** <this commit>.
