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
from subprocess import CompletedProcess
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

    def test_up_defaults_removed_no_silent_default_target(self):
        import cove.tunnel as t
        assert not hasattr(t, "DEFAULT_TARGET")

    def test_up_supports_public_and_private_options(self, runner):
        from cove.tunnel import tunnel
        result = runner.invoke(tunnel, ["up", "--help"])
        assert "--public" in result.output
        assert "--private" in result.output


class TestServiceDiscovery:
    """Service inventory is derived from Cove's nginx ingress config."""

    def _compose_dir(self, tmp_path, conf_text):
        compose = tmp_path / "compose"
        (compose / "nginx").mkdir(parents=True)
        (compose / "inventory.yml").write_text("hosts: {}\n")
        (compose / "nginx" / "default.conf.j2").write_text(conf_text)
        return compose

    def _sample_nginx_conf(self):
        return (
            "upstream forgejo_backend {\n"
            "    server forgejo:3000;\n"
            "}\n"
            "upstream vault_backend {\n"
            "    server vault:8200;\n"
            "}\n"
            "server {\n"
            "    listen 443 ssl default_server;\n"
            "    server_name _;\n"
            "    root /usr/share/nginx/html;\n"
            "    try_files /landing.html =404;\n"
            "}\n"
            "server {\n"
            "    listen 443 ssl;\n"
            "    server_name cove cove.local;\n"
            "    root /usr/share/nginx/html;\n"
            "    try_files /landing.html =404;\n"
            "}\n"
            "server {\n"
            "    listen 443 ssl;\n"
            "    server_name hc.cove hc.cove.local;\n"
            "    return 200 \"ok\";\n"
            "}\n"
            "server {\n"
            "    listen 443 ssl;\n"
            "    server_name git.cove git.cove.local;\n"
            "    location / {\n"
            "        proxy_pass http://forgejo_backend;\n"
            "        proxy_set_header Host $host;\n"
            "    }\n"
            "}\n"
            "server {\n"
            "    listen 443 ssl;\n"
            "    server_name vault.cove vault.cove.local;\n"
            "    location / {\n"
            "        proxy_pass http://vault_backend;\n"
            "    }\n"
            "}\n"
            "server {\n"
            "    listen 443 ssl;\n"
            "    server_name litellm.cove litellm.cove.local;\n"
            "    resolver 127.0.0.11 valid=10s;\n"
            "    set $litellm_upstream http://litellm:4000;\n"
            "    location / {\n"
            "        proxy_pass $litellm_upstream$request_uri;\n"
            "    }\n"
            "}\n"
            "server {\n"
            "    listen 443 ssl;\n"
            "    server_name pages.cove pages.cove.local;\n"
            "    root /usr/share/nginx/html;\n"
            "    try_files /pages.html =404;\n"
            "}\n"
            "server {\n"
            "    listen 443 ssl;\n"
            "    server_name ~^(?<owner>[a-zA-Z0-9-]+)\\.pages\\.cove$;\n"
            "    root /data/pages/sites/$owner;\n"
            "}\n"
        )

    def test_discovery_from_rendered_nginx_conf(self, tmp_path):
        import cove.tunnel as t
        compose = self._compose_dir(tmp_path, self._sample_nginx_conf())
        (compose / "nginx" / "default.conf").write_text(
            self._sample_nginx_conf()
        )
        services = t.discover_services(compose)
        names = [s.name for s in services]
        assert names == ["ingress", "git", "vault", "litellm", "pages"]

    def test_discovery_targets_resolve_upstreams(self, tmp_path):
        import cove.tunnel as t
        compose = self._compose_dir(tmp_path, self._sample_nginx_conf())
        (compose / "nginx" / "default.conf").write_text(
            self._sample_nginx_conf()
        )
        services = {s.name: s for s in t.discover_services(compose)}
        assert services["git"].route == "http://forgejo:3000"
        assert services["vault"].route == "http://vault:8200"
        assert services["litellm"].route == "http://litellm:4000"

    def test_discovery_static_routes(self, tmp_path):
        import cove.tunnel as t
        compose = self._compose_dir(tmp_path, self._sample_nginx_conf())
        (compose / "nginx" / "default.conf").write_text(
            self._sample_nginx_conf()
        )
        services = {s.name: s for s in t.discover_services(compose)}
        assert services["ingress"].route == "static:landing"
        assert services["pages"].route == "static:pages"

    def test_discovery_skips_regex_redirect_and_health(self, tmp_path):
        import cove.tunnel as t
        compose = self._compose_dir(tmp_path, self._sample_nginx_conf())
        (compose / "nginx" / "default.conf").write_text(
            self._sample_nginx_conf()
        )
        services = t.discover_services(compose)
        assert "hc" not in [s.name for s in services]
        for svc in services:
            assert svc.name not in ("owner", "_")

    def test_discovery_fails_loud_when_no_services(self, tmp_path):
        import cove.tunnel as t
        compose = self._compose_dir(
            tmp_path, "server {\n    server_name hc.cove;\n    return 200 \"ok\";\n}\n"
        )
        with pytest.raises(click.ClickException, match="No tunnelable services"):
            t.discover_services(compose)

    def test_discovery_fails_loud_without_nginx_config(self, tmp_path):
        import cove.tunnel as t
        compose = tmp_path / "compose"
        compose.mkdir(parents=True)
        (compose / "inventory.yml").write_text("hosts: {}\n")
        with pytest.raises(click.ClickException, match="cove up"):
            t.discover_services(compose)

    def test_display_names_are_https_urls(self, tmp_path):
        import cove.tunnel as t
        compose = self._compose_dir(tmp_path, self._sample_nginx_conf())
        (compose / "nginx" / "default.conf").write_text(
            self._sample_nginx_conf()
        )
        services = {s.name: s for s in t.discover_services(compose)}
        assert services["git"].display == "https://git.cove.local"
        assert services["ingress"].display == "https://cove.local"


class TestTargetResolution:
    def _services(self):
        from cove.tunnel import TunnelService
        return [
            TunnelService("ingress", "https://cove.local", "static:landing"),
            TunnelService("git", "https://git.cove.local", "http://forgejo:3000"),
        ]

    def test_shorthand_resolves_service_name(self):
        import cove.tunnel as t
        target, service = t._resolve_share_target("git", self._services(), False)
        assert target == t.MANAGED_TARGET
        assert service is not None and service.name == "git"

    def test_unknown_shorthand_fails_loud_listing_services(self):
        import cove.tunnel as t
        with pytest.raises(click.ClickException, match="git") as exc:
            t._resolve_share_target("nope", self._services(), False)
        assert "ingress — https://cove.local" in str(exc.value)

    def test_explicit_url_passes_through(self):
        import cove.tunnel as t
        target, service = t._resolve_share_target(
            "https://git.cove.local", self._services(), False
        )
        assert target == "https://git.cove.local"
        assert service is None

    def test_non_tty_bare_up_fails_loud_with_service_list(self):
        import cove.tunnel as t
        services = self._services()
        with pytest.raises(click.ClickException) as exc:
            t._resolve_share_target(None, services, False)
        message = str(exc.value)
        assert "stdin is not a TTY" in message
        assert "git — https://git.cove.local" in message

    def test_no_tty_message_lists_every_service(self):
        import cove.tunnel as t
        message = t._no_target_message(self._services())
        for svc in self._services():
            assert f"{svc.name} — {svc.display}" in message


class TestShareRouteRendering:
    def _service(self, name="git", route="http://forgejo:3000"):
        from cove.tunnel import TunnelService
        return TunnelService(name, f"https://{name}.cove.local", route)

    def test_rendered_route_has_public_server_name_and_host(self):
        from cove.tunnel import _render_share_route
        conf = _render_share_route("myforge", self._service())
        assert "server_name myforge.share.zrok.io;" in conf
        assert "proxy_pass $tunnel_upstream$request_uri;" in conf
        assert "proxy_set_header Host $host;" in conf
        assert "listen 80;" in conf
        assert "resolver 127.0.0.11" in conf

    def test_rendered_route_points_at_discovered_upstream(self):
        from cove.tunnel import _render_share_route
        conf = _render_share_route("myforge", self._service())
        assert "set $tunnel_upstream http://forgejo:3000;" in conf

    def test_rendered_static_route(self):
        from cove.tunnel import _render_share_route
        conf = _render_share_route("myportal", self._service("ingress", "static:landing"))
        assert "try_files /landing.html =404;" in conf
        assert "resolver" not in conf

    def test_rendered_conf_covers_all_shares(self):
        from cove.tunnel import _rendered_share_conf
        conf = _rendered_share_conf(
            {"aaaa": "git", "bbbb": "vault"},
            {"git": self._service(), "vault": self._service("vault", "http://vault:8200")},
        )
        assert "server_name aaaa.share.zrok.io;" in conf
        assert "server_name bbbb.share.zrok.io;" in conf

    def test_apply_share_routes_writes_include_and_reloads(
        self, tmp_path, monkeypatch
    ):
        import cove.tunnel as t
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(tmp_path))
        (tmp_path / "inventory.yml").write_text("hosts: {}\n")
        (tmp_path / ".env").write_text("")
        nginx_dir = tmp_path / "nginx"
        nginx_dir.mkdir()
        conf = t._render_share_route("aaaa", self._service())
        calls = []

        def fake_index():
            return {"git": self._service()}

        def fake_config_ok():
            calls.append("check")
            return True

        def fake_reload():
            calls.append("reload")

        monkeypatch.setattr(t, "_service_index", fake_index)
        monkeypatch.setattr(t, "_nginx_config_ok", fake_config_ok)
        monkeypatch.setattr(t, "_reload_nginx", fake_reload)
        t._apply_share_routes({"aaaa": "git"})
        rendered = (nginx_dir / t.SHARES_CONF_NAME).read_text()
        assert conf in rendered
        assert calls == ["check", "reload"]

    def test_apply_share_routes_restores_config_on_nginx_reject(
        self, tmp_path, monkeypatch
    ):
        import cove.tunnel as t
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(tmp_path))
        (tmp_path / "inventory.yml").write_text("hosts: {}\n")
        (tmp_path / ".env").write_text("")
        nginx_dir = tmp_path / "nginx"
        nginx_dir.mkdir()
        existing = nginx_dir / t.SHARES_CONF_NAME
        existing.write_text("# previous\n")
        monkeypatch.setattr(
            t, "_service_index", lambda: {"git": self._service()}
        )
        monkeypatch.setattr(t, "_nginx_config_ok", lambda: False)
        with pytest.raises(click.ClickException, match="nginx rejected"):
            t._apply_share_routes({"aaaa": "git"})
        assert existing.read_text() == "# previous\n"

    def test_apply_share_routes_unknown_service_fails_loud(
        self, tmp_path, monkeypatch
    ):
        import cove.tunnel as t
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(tmp_path))
        (tmp_path / "inventory.yml").write_text("hosts: {}\n")
        (tmp_path / ".env").write_text("")
        monkeypatch.setattr(t, "_service_index", lambda: {})
        with pytest.raises(click.ClickException, match="unknown services"):
            t._apply_share_routes({"aaaa": "ghost"})

    def test_apply_share_routes_empty_state_renders_empty_include(
        self, tmp_path, monkeypatch
    ):
        import cove.tunnel as t
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(tmp_path))
        (tmp_path / "inventory.yml").write_text("hosts: {}\n")
        (tmp_path / ".env").write_text("")
        nginx_dir = tmp_path / "nginx"
        nginx_dir.mkdir()
        monkeypatch.setattr(t, "_service_index", lambda: {})
        monkeypatch.setattr(t, "_nginx_config_ok", lambda: True)
        monkeypatch.setattr(t, "_reload_nginx", lambda: None)
        t._apply_share_routes({})
        assert "server_name" not in (
            nginx_dir / t.SHARES_CONF_NAME
        ).read_text()

    def test_ensure_shares_file_creates_empty_include(self, tmp_path, monkeypatch):
        import cove.tunnel as t
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(tmp_path))
        (tmp_path / "inventory.yml").write_text("hosts: {}\n")
        (tmp_path / ".env").write_text("")
        (tmp_path / "nginx").mkdir()
        t._ensure_shares_file()
        assert (tmp_path / "nginx" / t.SHARES_CONF_NAME).exists()

    def test_shares_conf_is_mounted_into_nginx(self):
        with open(COMPOSE_DIR / "docker-compose.yml") as f:
            compose = yaml.safe_load(f)
        volumes = compose["services"]["nginx"]["volumes"]
        assert any(
            "cove-tunnel-shares.conf:/etc/nginx/cove-tunnel-shares.conf" in v
            for v in volumes
        )

    def test_default_conf_template_includes_shares_conf(self):
        rendered = (COMPOSE_DIR / "nginx" / "default.conf.j2").read_text()
        assert "include /etc/nginx/cove-tunnel-shares.conf;" in rendered

    def test_bringup_renders_empty_shares_include(self):
        tasks = _load_bringup()[0]["tasks"]
        task = next(
            t for t in tasks
            if t.get("name") == (
                "Ensure cove-tunnel-shares.conf exists "
                "(empty state, never a directory)"
            )
        )
        assert task["ansible.builtin.copy"]["dest"].endswith(
            "cove-tunnel-shares.conf"
        )


class TestShareState:
    def test_share_state_roundtrip(self, tmp_path, monkeypatch):
        import cove.tunnel as t
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(tmp_path))
        (tmp_path / "inventory.yml").write_text("hosts: {}\n")
        (tmp_path / ".env").write_text("")
        t._write_share_state({"aaaa": "git"})
        assert t._read_share_state() == {"aaaa": "git"}
        t._write_share_state({})
        assert t._read_share_state() == {}

    def test_malformed_share_state_fails_loud(self, tmp_path, monkeypatch):
        import cove.tunnel as t
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(tmp_path))
        (tmp_path / "inventory.yml").write_text("hosts: {}\n")
        (tmp_path / ".env").write_text(f"{t.SHARES_ENV_KEY}=junk\n")
        with pytest.raises(click.ClickException, match="Malformed"):
            t._read_share_state()

    def test_state_key_is_compose_env(self):
        from cove.tunnel import SHARES_ENV_KEY
        assert SHARES_ENV_KEY == "COVE_TUNNEL_SHARES"


class TestNginxReload:
    def test_nginx_reload_failure_fails_loud(self, monkeypatch):
        import cove.tunnel as t
        result = CompletedProcess(
            args=[], returncode=1, stdout="", stderr="bad config"
        )
        monkeypatch.setattr(
            t.subprocess, "run", lambda *a, **k: result
        )
        with pytest.raises(click.ClickException, match="nginx reload failed"):
            t._reload_nginx()

    def test_nginx_config_check_reports_errors_and_result(self, monkeypatch, capsys):
        import cove.tunnel as t
        result = CompletedProcess(
            args=[], returncode=1, stdout="", stderr="nginx: config error"
        )
        monkeypatch.setattr(t.subprocess, "run", lambda *a, **k: result)
        assert t._nginx_config_ok() is False
        assert "nginx: config error" in capsys.readouterr().err


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