"""`cove creds` masking contract.

Incident 20261026-145212: `cove creds vault-put` printed a live 1Password-
resolved credential value unmasked into an agent transcript. vault-put must
never print the resolved secret — stdout carries the same `****************`
mask batch-pull uses. Internal callers (tunnel/litellm/speedtest up-flows)
resolve the value in-process via `cove.vault_cache.vault_put_op_ref`, never
via stdout.
"""

from click.testing import CliRunner

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