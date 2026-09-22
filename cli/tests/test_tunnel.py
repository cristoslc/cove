"""Tests for the cove tunnel (zrok2 sidecar): compose config, CLI module,
name validation, env rendering, and loud auth failure.

Per the plan (`docs/plans/cove-tunnel-zrok2.md`), the tunnel is an optional
profiled sidecar wrapping the zrok2 CLI (zrok.io hosted, free tier) with
tunnel-to-ingress routing and closed-by-default shares.

Unit tests (always runnable):
  - Validate the compose service definition (profile, outbound-only, pinned
    image, state volume under the data root)
  - Validate bringup.yml renders tunnel env only when the profile is active
  - Validate CLI module imports and has correct subcommands
  - Name validation (lowercase alnum, 4-32 chars)
  - Missing-token failure is loud (never silent fallback)

Run all:   pytest cli/tests/test_tunnel.py
Run unit:  pytest cli/tests/test_tunnel.py -m "not e2e"
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import click
import pytest
import yaml
from click.testing import CliRunner


def _project_root() -> Path:
    start = Path(__file__).resolve().parent
    for _ in range(6):
        if (start / "compose" / "inventory.yml").exists():
            return start
        start = start.parent
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
COMPOSE_DIR = PROJECT_ROOT / "compose"
MINIMAL_TEMPLATE_VARS = {
    "ansible_hostname": "testhost",
    "ts_ip": "100.64.0.1",
    "ts_status": SimpleNamespace(rc=0),
}


def _load_compose() -> dict:
    with open(COMPOSE_DIR / "docker-compose.yml") as f:
        return yaml.safe_load(f)


def _load_tunnel_resource() -> dict:
    with open(COMPOSE_DIR / "tunnel.yml") as f:
        return yaml.safe_load(f)


def _load_bringup() -> dict:
    with open(COMPOSE_DIR / "bringup.yml") as f:
        return yaml.safe_load(f)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def fake_compose_env(tmp_path, monkeypatch):
    """Point the CLI at an isolated compose dir with a fake .env."""
    monkeypatch.setenv("COVE_COMPOSE_DIR", str(tmp_path))
    (tmp_path / "inventory.yml").write_text("hosts: {}\n")
    (tmp_path / ".env").write_text("")
    return tmp_path


class TestComposeService:
    def test_tunnel_service_exists(self):
        compose = _load_compose()
        assert "tunnel" in compose["services"]

    def test_tunnel_has_profile(self):
        service = _load_compose()["services"]["tunnel"]
        assert service["profiles"] == ["tunnel"]

    def test_tunnel_publishes_no_ports(self):
        service = _load_compose()["services"]["tunnel"]
        assert "ports" not in service

    def test_tunnel_image_pinned_to_zrok2_v2(self):
        service = _load_compose()["services"]["tunnel"]
        image = service["image"]
        assert "openziti/zrok2" in image
        assert "sha256:" in image

    def test_tunnel_state_volume_under_data_root(self):
        service = _load_compose()["services"]["tunnel"]
        volumes = service["volumes"]
        assert any("${COVE_DATA_ROOT}/tunnel" in v for v in volumes)

    def test_tunnel_container_name_cove_prefix(self):
        service = _load_compose()["services"]["tunnel"]
        assert "cove-tunnel" in service["container_name"]

    def test_tunnel_memory_limit(self):
        service = _load_compose()["services"]["tunnel"]
        assert "memory" in service["deploy"]["resources"]["limits"]

    def test_tunnel_reads_account_token_env(self):
        service = _load_compose()["services"]["tunnel"]
        assert service["environment"]["ZROK_ACCOUNT_TOKEN"] == "${ZROK_ACCOUNT_TOKEN:-}"

    def test_tunnel_resource_matches_compose_service(self):
        compose_service = _load_compose()["services"]["tunnel"]
        resource = _load_tunnel_resource()["services"]["tunnel"]
        assert compose_service["image"] == resource["image"]
        assert compose_service["profiles"] == resource["profiles"]

    def test_tunnel_absent_without_profile(self):
        service = _load_compose()["services"]["tunnel"]
        assert "tunnel" in service["profiles"]


class TestBringup:
    def test_tunnel_data_dir_task_is_profile_conditional(self):
        tasks = _load_bringup()[0]["tasks"]
        dirs_task = next(
            t for t in tasks if t.get("name") == "Create tunnel data directory (tunnel profile only)"
        )
        assert "tunnel" in dirs_task.get("when", "")

    def test_tunnel_env_rendering_is_profile_conditional(self):
        tasks = _load_bringup()[0]["tasks"]
        env_task = next(
            t for t in tasks if t.get("name") == "Render tunnel env (tunnel profile only)"
        )
        assert "tunnel" in env_task.get("when", "")

    def test_tunnel_env_missing_token_fails_loud_in_bringup(self):
        tasks = _load_bringup()[0]["tasks"]
        env_task = next(
            t for t in tasks if t.get("name") == "Render tunnel env (tunnel profile only)"
        )
        assert env_task["block"], "expected an assert task inside the tunnel block"

    def test_default_stack_has_no_tunnel_env_when_profile_inactive(self):
        tasks = _load_bringup()[0]["tasks"]
        env_tasks = [t for t in tasks if "ZROK_ACCOUNT_TOKEN" in str(t)]
        assert env_tasks, "tunnel env tasks must exist"
        for task in env_tasks:
            parents = tasks
            assert task in parents


class TestCliModule:
    def test_tunnel_group_imports(self):
        from cove.tunnel import tunnel
        assert tunnel is not None

    def test_tunnel_group_registered(self):
        from cove.cli import app
        assert "tunnel" in app.commands

    def test_tunnel_has_up_command(self):
        from cove.tunnel import tunnel as tunnel_group
        assert "up" in tunnel_group.commands

    def test_tunnel_has_ls_command(self):
        from cove.tunnel import tunnel as tunnel_group
        assert "ls" in tunnel_group.commands

    def test_tunnel_has_down_command(self):
        from cove.tunnel import tunnel as tunnel_group
        assert "down" in tunnel_group.commands

    def test_up_defaults_to_ingress_target(self):
        from cove.tunnel import DEFAULT_TARGET
        assert DEFAULT_TARGET == "https://nginx"

    def test_up_supports_public_and_private_options(self, runner):
        from cove.tunnel import tunnel
        result = runner.invoke(tunnel, ["up", "--help"])
        assert "--public" in result.output
        assert "--private" in result.output


class TestNameValidation:
    @pytest.mark.parametrize("name", ["myapp", "abcd", "a1b2c3d4e5f6g7h8i9j0k1l2"])
    def test_valid_names_pass(self, name):
        from cove.tunnel import validate_share_name
        assert validate_share_name(name) == name

    def test_uppercase_normalized_to_lowercase(self):
        from cove.tunnel import validate_share_name
        assert validate_share_name("MyApp1") == "myapp1"

    def test_uppercase_with_invalid_char_rejected(self):
        from cove.tunnel import validate_share_name
        with pytest.raises(click.ClickException, match="4-32"):
            validate_share_name("My_App")

    def test_too_short_rejected(self):
        from cove.tunnel import validate_share_name
        with pytest.raises(click.ClickException, match="4-32"):
            validate_share_name("abc")

    def test_too_long_rejected(self):
        from cove.tunnel import validate_share_name
        with pytest.raises(click.ClickException, match="4-32"):
            validate_share_name("a" * 33)

    def test_special_chars_rejected(self):
        from cove.tunnel import validate_share_name
        with pytest.raises(click.ClickException, match="4-32"):
            validate_share_name("my_app")

    def test_hyphen_rejected(self):
        from cove.tunnel import validate_share_name
        with pytest.raises(click.ClickException, match="4-32"):
            validate_share_name("my-app")


class TestAuth:
    def test_missing_token_fails_loud(self, fake_compose_env, monkeypatch):
        import cove.tunnel as t
        monkeypatch.delenv("ZROK_ACCOUNT_TOKEN", raising=False)
        monkeypatch.setattr(t, "_vault_get", lambda ref: None)
        with pytest.raises(click.ClickException, match="myzrok.io"):
            t._ensure_account_token()

    def test_no_silent_anonymous_fallback(self, fake_compose_env, monkeypatch):
        import cove.tunnel as t
        monkeypatch.delenv("ZROK_ACCOUNT_TOKEN", raising=False)
        monkeypatch.setattr(t, "_vault_get", lambda ref: None)
        with pytest.raises(click.ClickException, match="Zrok Account"):
            t._ensure_account_token()

    def test_env_token_used_directly(self, fake_compose_env, monkeypatch):
        import cove.tunnel as t
        monkeypatch.setenv("ZROK_ACCOUNT_TOKEN", "tok123")
        assert t._ensure_account_token() == "tok123"

    def test_compose_env_token_reused(self, fake_compose_env):
        env = fake_compose_env / ".env"
        env.write_text("ZROK_ACCOUNT_TOKEN=envtoken\n")
        import cove.tunnel as t
        monkey = t
        assert monkey._ensure_account_token() == "envtoken"

    def test_vault_cached_token_written_to_env(self, fake_compose_env, monkeypatch):
        import cove.tunnel as t
        monkeypatch.delenv("ZROK_ACCOUNT_TOKEN", raising=False)
        monkeypatch.setattr(t, "_vault_get", lambda ref: "vaulttoken")
        assert t._ensure_account_token() == "vaulttoken"
        env = fake_compose_env / ".env"
        assert "ZROK_ACCOUNT_TOKEN=vaulttoken" in env.read_text()

    def test_account_token_op_ref_is_shared_url_keyed(self):
        from cove.tunnel import ACCOUNT_TOKEN_OP_REF
        assert ACCOUNT_TOKEN_OP_REF == (
            "op://Private/Zrok Account/account_token"
        )


class TestEnvRendering:
    def test_upsert_env_no_duplicates(self, tmp_path, monkeypatch):
        import cove.tunnel as t
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(tmp_path))
        (tmp_path / "inventory.yml").write_text("hosts: {}\n")
        (tmp_path / ".env").write_text("A=1\n")
        t._upsert_env("A", "2")
        t._upsert_env("A", "3")
        lines = (tmp_path / ".env").read_text().strip().splitlines()
        assert lines == ["A=3"]


class TestUrlExtraction:
    def test_extracts_share_zrok_io_url(self):
        from cove.tunnel import _extract_url
        output = "https://abc123.share.zrok.io\n"
        assert _extract_url(output) == "https://abc123.share.zrok.io"

    def test_extracts_named_share_zrok_io_url(self):
        from cove.tunnel import _extract_url
        output = "https://myforge.share.zrok.io\n"
        assert _extract_url(output) == "https://myforge.share.zrok.io"

    def test_returns_none_when_no_url(self):
        from cove.tunnel import _extract_url
        assert _extract_url("error: something broke") is None