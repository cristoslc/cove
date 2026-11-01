"""`cove creds` masking contract.

Incident 20261026-145212: `cove creds vault-put` printed a live 1Password-
resolved credential value unmasked into an agent transcript. vault-put must
never print the resolved secret — stdout carries the same `****************`
mask batch-pull uses. Internal callers (tunnel/litellm/speedtest up-flows)
resolve the value in-process via `cove.vault_cache.vault_put_op_ref`, never
via stdout.
"""

from click.testing import CliRunner
from unittest.mock import patch

SECRET = "op-secret-value-never-print"
OP_REF = "op://Private/My Secret/password"


def test_vault_put_stdout_masks_secret(monkeypatch):
    from cove import vault_cache
    from cove.creds import vault_put

    monkeypatch.setattr(
        vault_cache, "vault_put_op_ref",
        lambda op_ref, force_refresh=False: SECRET,
    )
    result = CliRunner().invoke(vault_put, [OP_REF])
    assert result.exit_code == 0, result.output
    assert SECRET not in result.output, "vault-put must never print the secret"
    assert "****************" in result.output, "stdout must carry the batch-pull mask"


def test_vault_put_force_refresh_passes_through(monkeypatch):
    from cove import vault_cache
    from cove.creds import vault_put

    seen = {}

    def fake(op_ref, force_refresh=False):
        seen["op_ref"] = op_ref
        seen["force_refresh"] = force_refresh
        return SECRET

    monkeypatch.setattr(vault_cache, "vault_put_op_ref", fake)
    result = CliRunner().invoke(vault_put, [OP_REF, "--force-refresh"])
    assert result.exit_code == 0, result.output
    assert seen == {"op_ref": OP_REF, "force_refresh": True}


def test_vault_put_failure_is_click_exception(monkeypatch):
    from cove import vault_cache
    from cove.creds import vault_put

    def boom(op_ref, force_refresh=False):
        raise RuntimeError("op read failed")

    monkeypatch.setattr(vault_cache, "vault_put_op_ref", boom)
    result = CliRunner().invoke(vault_put, [OP_REF])
    assert result.exit_code != 0
    assert SECRET not in result.output


def test_vault_put_bare_rereads_1password_after_rotation(monkeypatch):
    """RED (cove issue #93): with the value already cached (stale after a
    downstream 1Password rotation), bare `cove creds vault-put` must still
    re-read 1Password, push the fresh value into both caches, and exit 0.
    rc 0 while the read path is never invoked is the defect."""
    from cove.creds import vault_put

    fresh = "fresh-rotated-value"
    with patch("cove.vault_cache.local_cache.get", return_value="stale-cache-value"), \
         patch("cove.vault_cache._op_read", return_value=fresh) as mock_op_read, \
         patch("cove.vault_cache._vault_write") as mock_vault_write, \
         patch("cove.vault_cache.local_cache.put") as mock_local_put:

        result = CliRunner().invoke(vault_put, [OP_REF])

    assert result.exit_code == 0, result.output
    mock_op_read.assert_called_once_with(OP_REF)
    mock_vault_write.assert_called_once_with(OP_REF, fresh)
    mock_local_put.assert_called_once_with(OP_REF, fresh)
    assert fresh not in result.output, "vault-put must never print the fresh value"


def test_vault_put_op_read_failure_exits_nonzero_and_leaves_cache_intact(monkeypatch):
    """RED (cove issue #93, inverse edge): when the 1Password read fails while
    a cached value is present, vault-put must exit non-zero (fail loud, no
    silent fallback to the cached value) and leave both caches intact."""
    from cove.creds import vault_put

    with patch("cove.vault_cache.local_cache.get", return_value="cached-value"), \
         patch("cove.vault_cache._op_read", side_effect=RuntimeError("op read failed")), \
         patch("cove.vault_cache._vault_write") as mock_vault_write, \
         patch("cove.vault_cache.local_cache.put") as mock_local_put:

        result = CliRunner().invoke(vault_put, [OP_REF])

    assert result.exit_code != 0, result.output
    assert mock_vault_write.call_count == 0
    assert mock_local_put.call_count == 0
    assert SECRET not in result.output

# Short-name resolution: `cove creds vault-get forgejo-token` is the documented
# read path for the Renovate merge automation (docs/guides/renovate.md). Before
# this, a bare name reached vault_cache.parse_op_ref and died with "Not an
# op:// reference", so the documented vault-put could never create the entry.

RENOVATE_REF = "op://Private/Renovate Bot (git.cove)/token"


def test_resolve_ref_maps_the_short_name_without_a_hostname_lookup(monkeypatch):
    from cove import creds

    def boom():
        raise AssertionError("a placeholder-free ref must not spawn scutil")

    monkeypatch.setattr(creds, "_hostname", boom)
    assert creds.resolve_ref("forgejo-token") == RENOVATE_REF


def test_resolve_ref_passes_an_op_ref_through():
    from cove import creds

    assert creds.resolve_ref(OP_REF) == OP_REF


def test_resolve_ref_formats_hostname_placeholders(monkeypatch):
    from cove import creds

    monkeypatch.setattr(creds, "_hostname", lambda: "MBP")
    monkeypatch.setattr(creds, "USERNAME", "cristos")
    assert creds.resolve_ref("forgejo-admin") == "op://Private/Forgejo MBP Admin/password"


def test_resolve_ref_rejects_an_unknown_name():
    import pytest

    from cove import creds

    with pytest.raises(ValueError) as excinfo:
        creds.resolve_ref("not-a-credential")
    assert "not-a-credential" in str(excinfo.value)
    assert "forgejo-token" in str(excinfo.value)


def test_vault_get_resolves_the_short_name_before_the_cache(monkeypatch):
    from cove import creds, local_cache

    seen = {}

    def fake_get(key):
        seen["key"] = key
        return SECRET

    monkeypatch.setattr(local_cache, "get", fake_get)
    result = CliRunner().invoke(creds.vault_get, ["forgejo-token"])
    assert result.exit_code == 0, result.output
    assert seen["key"] == RENOVATE_REF, "the cache must be keyed by the op ref"
    assert result.output == SECRET


def test_vault_put_resolves_the_short_name_and_stays_masked(monkeypatch):
    from cove import creds, vault_cache

    seen = {}

    def fake_put(op_ref, force_refresh=False):
        seen["ref"] = op_ref
        return SECRET

    monkeypatch.setattr(vault_cache, "vault_put_op_ref", fake_put)
    result = CliRunner().invoke(creds.vault_put, ["forgejo-token"])
    assert result.exit_code == 0, result.output
    assert seen["ref"] == RENOVATE_REF
    assert SECRET not in result.output


def test_vault_get_rejects_an_unknown_name_loudly(monkeypatch):
    from cove import creds, local_cache

    monkeypatch.setattr(local_cache, "get", lambda key: SECRET)
    result = CliRunner().invoke(creds.vault_get, ["not-a-credential"])
    assert result.exit_code != 0
    assert "not-a-credential" in result.output
    assert SECRET not in result.output


def test_batch_pull_leaves_the_operator_only_ref_alone(monkeypatch):
    """batch-pull runs on every `cove up`. A machine that never runs the merge
    automation must not see `cove up` fail because the Renovate Bot 1Password
    item is absent."""
    from cove import creds, local_cache

    seen = {}

    def fake_batch(refs):
        seen["refs"] = list(refs)
        return {ref: "x" for ref in refs}

    monkeypatch.setattr(local_cache, "get", lambda key: None)
    monkeypatch.setattr(local_cache, "batch_pull", fake_batch)
    result = CliRunner().invoke(creds.batch_pull_op, [])
    assert result.exit_code == 0, result.output
    assert RENOVATE_REF not in seen["refs"]
    assert "op://Private/Speedtest Tracker/app_key" in seen["refs"]
