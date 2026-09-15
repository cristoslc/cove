**Responding to:** test gate failure in cli/tests/test_e2e_stateless.py::TestE2EStatelessPurge::test_purge_removes_dir

Root cause diagnosis (pre-existing on trunk, reproduced on main independently of this branch):

- `cove init` runs `ansible-galaxy collection install -r requirements.yml` (cli/cove/cli.py:93) with `check=False`.
- On a **cold Ansible galaxy cache** (fresh sandbox HOME), galaxy resolves dependency chains: `community.docker` → `community.library_inventory_filtering_v1` and downloads them. Measured wall time: **73-80s**.
- The test harness caps `subprocess.run` at `timeout=60` (cli/tests/conftest.py:120). First `cove_run(["init"])` call in a session with a cold cache exceeds 60s → `subprocess.TimeoutExpired`.
- On the developer's normal machine the cache at `~/.ansible/collections` is warm (collections already installed → "Nothing to do" → sub-second), so the test passes locally but fails after cache eviction or on fresh CI machines.
- The purge test is the first init in its session (fresh sandbox HOME), hence it's the visible victim; any first-init test would fail the same way on a cold cache.

Fix direction (RGR): raise the per-invocation timeout in the `cove_run` fixture to accommodate a cold galaxy run (e.g. 180s) — the timeout is a test-infrastructure constant, not a product SLA. Red test: the existing failing `test_purge_removes_dir` (fails on cold cache) is the failure-expecting test; verify it fails before the fix and passes after, with the cache warmed by the earlier init call.
