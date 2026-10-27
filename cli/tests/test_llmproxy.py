"""`llmproxy.cove` authentication edge tests.

Coverage:
- The edge vhost requires the client token (401 before any upstream) and
  injects the ACTIVE backend credential; the public vhost carries no secret.
- The rendered edge config (0600) maps the client bearer exactly and pairs each
  backend key with its upstream, so the product swap is one line.
- Rendering fails loud without a client token; an empty token can never become
  a wildcard.
- `cove up` hands the credentials to Ansible as a 0600 extra-vars file; the
  token resolution path (env -> compose .env -> Vault cache -> provision) fails
  loud instead of rendering an unauthenticated edge.
- Mounts and bringup wiring (base + staging compose, assertion, 0600 render).
"""

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from click.testing import CliRunner
from jinja2 import Environment, FileSystemLoader, StrictUndefined, UndefinedError


def _project_root() -> Path:
    start = Path(__file__).resolve().parent
    for _ in range(6):
        if (start / "compose" / "inventory.yml").exists():
            return start
        start = start.parent
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()
COMPOSE_DIR = PROJECT_ROOT / "compose"
NGINX_DIR = COMPOSE_DIR / "nginx"
AUTH_TEMPLATE = "llmproxy-auth.conf.j2"

CLIENT_TOKEN = "sk-cove-test-client-token"
LITELLM_KEY = "sk-litellm-backend-key"
BIFROST_KEY = "sk-bf-bifrost-backend-key"


def _render(template: str, vars_: dict | None = None, strict: bool = True) -> str:
    undefined = StrictUndefined if strict else None
    env = Environment(loader=FileSystemLoader(str(NGINX_DIR)), undefined=undefined)
    return env.get_template(template).render(vars_ or {})


def _render_edge(
    client: str = CLIENT_TOKEN,
    litellm: str = LITELLM_KEY,
    bifrost: str = BIFROST_KEY,
) -> str:
    return _render(AUTH_TEMPLATE, {
        "llmproxy_client_key": client,
        "llmproxy_litellm_key": litellm,
        "llmproxy_bifrost_key": bifrost,
    })


def _llmproxy_block(rendered: str) -> str:
    """The `server { ... }` block for llmproxy.cove (brace-matched)."""
    lines = rendered.split("\n")
    marker = next(
        i for i, line in enumerate(lines) if "server_name llmproxy.cove" in line
    )
    start = marker
    for i in range(marker, max(marker - 12, -1), -1):
        if lines[i].strip().startswith("server {"):
            start = i
            break
    depth = 0
    block = []
    for line in lines[start:]:
        block.append(line)
        depth += line.count("{") - line.count("}")
        if depth == 0 and len(block) > 1:
            break
    return "\n".join(block)


def _find_task(name: str) -> dict:
    with open(COMPOSE_DIR / "bringup.yml") as f:
        data = yaml.safe_load(f)
    tasks = data[0]["tasks"] if isinstance(data, list) else data.get("tasks", [])
    for task in tasks:
        if isinstance(task, dict) and task.get("name") == name:
            return task
    raise AssertionError(f"no bringup task named {name!r}")


class TestEdgeVhost:
    """The public vhost: auth check + server-side injection, no secrets."""

    def test_edge_auth_config_is_included_from_the_public_vhost(self):
        rendered = _render("default.conf.j2")
        assert "include /etc/nginx/llmproxy-auth.conf;" in rendered

    def test_public_vhost_carries_no_credential(self):
        """default.conf is world-readable inside the container: it must only
        reference the variables, never hold a token or backend key."""
        rendered = _render("default.conf.j2")
        for secret in (CLIENT_TOKEN, LITELLM_KEY, BIFROST_KEY):
            assert secret not in rendered

    def test_map_hash_bucket_size_accommodates_the_bearer_key(self):
        """`Bearer <client token>` is longer than nginx's default 64-byte map
        bucket; without this the edge config fails to build (live nginx -t:
        'could not build map_hash, you should increase map_hash_bucket_size')."""
        rendered = _render("default.conf.j2")
        assert "map_hash_bucket_size 256;" in rendered
        assert len(f"Bearer {CLIENT_TOKEN}") < 256

    def test_unknown_clients_are_rejected_before_any_upstream(self):
        block = _llmproxy_block(_render("default.conf.j2"))
        assert "if ($llmproxy_authorized = 0)" in block
        assert "return 401;" in block

    def test_active_backend_credential_is_injected_server_side(self):
        block = _llmproxy_block(_render("default.conf.j2"))
        assert "proxy_set_header Authorization $llmproxy_upstream_key;" in block
        # The client's own Authorization header is replaced, not appended.
        assert block.count("proxy_set_header Authorization") == 1

    def test_streaming_settings_survive_the_edge(self):
        block = _llmproxy_block(_render("default.conf.j2"))
        assert "proxy_buffering off;" in block
        assert "proxy_read_timeout 3600s;" in block
        assert "proxy_pass $llmproxy_upstream$request_uri;" in block


class TestEdgeAuthConfig:
    """The rendered 0600 secret file: exact client match + backend map."""

    def test_client_bearer_is_an_exact_match(self):
        rendered = _render_edge()
        assert "map $http_authorization $llmproxy_authorized {" in rendered
        assert f'"Bearer {CLIENT_TOKEN}"' in rendered
        # Nothing but the exact bearer is authorized.
        auth_map = rendered.split("map $http_authorization", 1)[1].split("}", 1)[0]
        assert " 0;" in auth_map
        assert auth_map.count(" 1;") == 1

    def test_empty_client_token_is_not_a_wildcard(self):
        """Even if a guard is bypassed, an empty token must not accept
        arbitrary authorization values (the map default stays 0)."""
        rendered = _render_edge(client="")
        auth_map = rendered.split("map $http_authorization", 1)[1].split("}", 1)[0]
        assert '"Bearer "' in auth_map
        assert auth_map.count(" 1;") == 1
        assert "default" in auth_map and "0;" in auth_map

    @pytest.mark.parametrize(
        "upstream, key",
        [
            ("http://litellm:4000", LITELLM_KEY),
            ("http://bifrost:8080", BIFROST_KEY),
        ],
    )
    def test_backend_key_pairs_with_the_upstream_variable(self, upstream, key):
        rendered = _render_edge()
        assert f'"{upstream}"' in rendered
        assert f'"Bearer {key}"' in rendered

    def test_unknown_upstream_fails_closed(self):
        rendered = _render_edge()
        key_map = rendered.split("map $llmproxy_upstream", 1)[1].split("}", 1)[0]
        assert "default" in key_map
        assert '""' in key_map

    def test_every_switchable_upstream_in_the_vhost_has_a_key(self):
        """The documented product swap is one line: whatever value the vhost's
        `set $llmproxy_upstream` can name must already be keyed in the map."""
        vhost = _render("default.conf.j2")
        map_block = _render_edge()
        assert "set $llmproxy_upstream http://litellm:4000;" in vhost
        for upstream in ("http://litellm:4000", "http://bifrost:8080"):
            assert f'"{upstream}"' in map_block

    def test_missing_client_token_fails_the_render(self):
        with pytest.raises(UndefinedError):
            _render(AUTH_TEMPLATE, {})


class TestEdgeWiring:
    """Bringup + compose: the guard, the 0600 render, and the mounts."""
    def test_bringup_asserts_the_client_token(self):
        task = _find_task("Assert the llmproxy edge client token was provided")
        assert task["ansible.builtin.assert"]["that"] == [
            "llmproxy_client_key | default('', true) | string | length > 0"
        ]
        # The message must be legible: it names the variable and the fix, and
        # never carries the token, so no_log would only hide the guidance.
        assert "no_log" not in task
        assert "Cove LLM Proxy Client Key" in task["ansible.builtin.assert"]["fail_msg"]

    def test_bringup_renders_the_edge_config_private(self):
        task = _find_task("Render llmproxy edge auth config from template")
        args = task["ansible.builtin.template"]
        assert args["src"].endswith("llmproxy-auth.conf.j2")
        assert args["dest"].endswith("llmproxy-auth.conf")
        assert args["mode"] == "0600"
        assert task.get("notify") == "Reload nginx"

    def test_bringup_guards_the_mount_target(self):
        task = _find_task("Assert nginx bind-mount targets are not directories")
        assert "llmproxy-auth.conf" in task["loop"]

    @pytest.mark.parametrize(
        "compose_file",
        ["docker-compose.yml", "docker-compose.staging.yml"],
    )
    def test_compose_mounts_the_edge_config(self, compose_file):
        text = (COMPOSE_DIR / compose_file).read_text()
        assert (
            "llmproxy-auth.conf:/etc/nginx/llmproxy-auth.conf:ro" in text
        )

    def test_staging_deploy_renders_the_edge_config(self):
        script = (PROJECT_ROOT / "scripts" / "staging" / "deploy-isolated.sh").read_text()
        assert "llmproxy-auth.conf.j2" in script
        assert "llmproxy-auth.conf" in script
        assert "STAGING_LLMPROXY_CLIENT_KEY" in script


@pytest.fixture
def edge_compose(tmp_path, monkeypatch):
    """A compose dir with the llmproxy seed, isolated from the operator's."""
    compose_dir = tmp_path / "compose"
    seeds = compose_dir / "seeds"
    seeds.mkdir(parents=True)
    (compose_dir / "inventory.yml").write_text("all:\n  hosts: {}\n")
    (seeds / "llmproxy-creds.yaml.example").write_text(
        (COMPOSE_DIR / "seeds" / "llmproxy-creds.yaml.example").read_text()
    )
    monkeypatch.setenv("COVE_COMPOSE_DIR", str(compose_dir))
    monkeypatch.delenv("COVE_LLM_PROXY_CLIENT_KEY", raising=False)
    return compose_dir


class TestClientKeyResolution:
    """env -> compose .env -> Vault cache -> provision; fail loud, never print."""

    def test_env_override_wins(self, edge_compose, monkeypatch):
        from cove import llmproxy
        monkeypatch.setenv("COVE_LLM_PROXY_CLIENT_KEY", "sk-cove-explicit")
        monkeypatch.setattr(
            llmproxy, "_cached_client_key",
            lambda: (_ for _ in ()).throw(AssertionError("cache must not run")),
        )
        assert llmproxy.ensure_client_key() == "sk-cove-explicit"

    def test_compose_env_entry_is_used(self, edge_compose, monkeypatch):
        from cove import llmproxy
        (edge_compose / ".env").write_text(
            "COVE_DATA_ROOT=/tmp/x\nCOVE_LLM_PROXY_CLIENT_KEY=sk-cove-from-env\n"
        )
        monkeypatch.setattr(
            llmproxy, "_cached_client_key",
            lambda: (_ for _ in ()).throw(AssertionError("cache must not run")),
        )
        assert llmproxy.ensure_client_key() == "sk-cove-from-env"

    def test_vault_cache_is_used_before_provisioning(self, edge_compose, monkeypatch):
        from cove import llmproxy
        monkeypatch.setattr(
            llmproxy, "_cached_client_key", lambda: "sk-cove-cached"
        )
        monkeypatch.setattr(
            llmproxy, "_provision_client_key",
            lambda: (_ for _ in ()).throw(AssertionError("must not provision")),
        )
        assert llmproxy.ensure_client_key() == "sk-cove-cached"

    def test_provisions_the_shared_item_when_absent(self, edge_compose, monkeypatch):
        from cove import llmproxy
        monkeypatch.setattr(llmproxy, "_cached_client_key", lambda: None)
        calls: list[tuple] = []

        def _fake_creds(*args):
            calls.append(args)
            if args[0] == "1p-bulk-write":
                seed = Path(args[1])
                assert seed.exists()
                rendered = seed.read_text()
                assert "{{generate:client_key}}" not in rendered
                assert "sk-cove-" in rendered
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(llmproxy, "_run_cove_creds", _fake_creds)
        monkeypatch.setattr(
            "cove.vault_cache.vault_put_op_ref", lambda ref: "sk-cove-provisioned"
        )
        assert llmproxy.ensure_client_key() == "sk-cove-provisioned"
        assert calls and calls[0][0] == "1p-bulk-write"
        # The rendered seed is a temp file and is removed afterwards.
        assert not Path(calls[0][1]).exists()

    def test_1password_write_failure_fails_loud(self, edge_compose, monkeypatch):
        import click
        from cove import llmproxy
        monkeypatch.setattr(llmproxy, "_cached_client_key", lambda: None)
        monkeypatch.setattr(
            llmproxy, "_run_cove_creds",
            lambda *a: SimpleNamespace(
                returncode=1, stdout="", stderr="account is not signed in"
            ),
        )
        with pytest.raises(click.ClickException) as exc:
            llmproxy.ensure_client_key()
        assert "could not be provisioned" in str(exc.value)

    def test_empty_provisioned_value_fails_loud(self, edge_compose, monkeypatch):
        import click
        from cove import llmproxy
        monkeypatch.setattr(llmproxy, "_cached_client_key", lambda: None)
        monkeypatch.setattr(
            llmproxy, "_run_cove_creds",
            lambda *a: SimpleNamespace(returncode=0, stdout="", stderr=""),
        )
        monkeypatch.setattr("cove.vault_cache.vault_put_op_ref", lambda ref: "")
        with pytest.raises(click.ClickException) as exc:
            llmproxy.ensure_client_key()
        assert "empty" in str(exc.value)

    def test_seed_renders_a_prefixed_token(self, edge_compose):
        from cove import llmproxy
        rendered = llmproxy._render_seed()
        assert "{{generate:client_key}}" not in rendered
        assert "sk-cove-" in rendered
        assert "Cove LLM Proxy Client Key" in rendered


class TestEdgeVarsFile:
    """The 0600 extra-vars file `cove up` hands to Ansible."""

    def test_file_is_private_and_carries_the_three_values(
        self, edge_compose, monkeypatch
    ):
        from cove import llmproxy
        monkeypatch.setattr(llmproxy, "ensure_client_key", lambda: CLIENT_TOKEN)
        monkeypatch.setattr(
            llmproxy, "_env_value",
            lambda key: {"LITELLM_MASTER_KEY": LITELLM_KEY,
                         "BIFROST_CLIENT_VIRTUAL_KEY": BIFROST_KEY}[key],
        )
        path = llmproxy.edge_secret_vars_file()
        try:
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            data = yaml.safe_load(path.read_text())
            assert data == {
                "llmproxy_client_key": CLIENT_TOKEN,
                "llmproxy_litellm_key": LITELLM_KEY,
                "llmproxy_bifrost_key": BIFROST_KEY,
            }
        finally:
            os.unlink(path)

    def test_backend_keys_are_read_from_the_compose_env(self, edge_compose):
        from cove import llmproxy
        (edge_compose / ".env").write_text(
            "LITELLM_MASTER_KEY=sk-litellm-from-env\n"
            "BIFROST_CLIENT_VIRTUAL_KEY=sk-bf-from-env\n"
        )
        assert llmproxy._env_value("LITELLM_MASTER_KEY") == "sk-litellm-from-env"
        assert (
            llmproxy._env_value("BIFROST_CLIENT_VIRTUAL_KEY") == "sk-bf-from-env"
        )


class TestBifrostStatusStatesTheModel:
    def test_status_reports_edge_auth_and_backend_key_state(
        self, tmp_path, monkeypatch
    ):
        from cove import bifrost as bf
        compose_dir = tmp_path / "compose"
        nginx_dir = compose_dir / "nginx"
        nginx_dir.mkdir(parents=True)
        (compose_dir / "inventory.yml").write_text("all:\n  hosts: {}\n")
        (compose_dir / ".env").write_text("COVE_DATA_ROOT=x\n")
        (nginx_dir / "default.conf").write_text(
            "server_name llmproxy.cove llmproxy.cove.local;\n"
            "set $llmproxy_upstream http://litellm:4000;\n"
        )
        (nginx_dir / "llmproxy-auth.conf").write_text(
            'map $llmproxy_upstream $llmproxy_upstream_key {\n'
            '    default                 "";\n'
            '    "http://litellm:4000"   "Bearer sk-injected";\n'
            '    "http://bifrost:8080"   "Bearer ";\n'
            "}\n"
        )
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(compose_dir))
        monkeypatch.setattr(
            bf.subprocess, "run",
            lambda *a, **k: SimpleNamespace(stdout="", returncode=0),
        )
        monkeypatch.setattr(bf, "_probe_health_code", lambda host: 200)
        result = CliRunner().invoke(bf.bifrost, ["status"], catch_exceptions=True)
        assert result.exit_code == 0, result.output
        assert "clients authenticate at the edge" in result.output
        assert "backend credentials never reach clients" in result.output
        assert "llmproxy.cove backend key: SET (injected server-side)" in result.output
        # Never a key value.
        assert "sk-injected" not in result.output

    def test_missing_active_backend_key_reports_missing(self, tmp_path, monkeypatch):
        from cove import bifrost as bf
        compose_dir = tmp_path / "compose"
        nginx_dir = compose_dir / "nginx"
        nginx_dir.mkdir(parents=True)
        (compose_dir / "inventory.yml").write_text("all:\n  hosts: {}\n")
        (compose_dir / ".env").write_text("COVE_DATA_ROOT=x\n")
        (nginx_dir / "default.conf").write_text(
            "set $llmproxy_upstream http://litellm:4000;\n"
        )
        (nginx_dir / "llmproxy-auth.conf").write_text(
            '"http://litellm:4000"   "Bearer ";\n'
        )
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(compose_dir))
        assert bf._neutral_endpoint_backend_key_state() == "missing"

    def test_edge_config_absent_is_reported_not_guessed(self, tmp_path, monkeypatch):
        from cove import bifrost as bf
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()
        (compose_dir / "inventory.yml").write_text("all:\n  hosts: {}\n")
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(compose_dir))
        assert bf._neutral_endpoint_backend_key_state() is None


class TestRenderedEdgeConfigIsRuntimeState:
    """The rendered file is secret runtime state: extraction must preserve its
    inode, `cove update` must not read it as a pin change, and the wheel build
    must never copy it."""

    def test_extraction_preserves_the_rendered_file(self):
        from cove.stateless import RUNTIME_PRESERVED_FILES
        assert "nginx/llmproxy-auth.conf" in RUNTIME_PRESERVED_FILES

    def test_update_treats_it_as_generated(self):
        from cove.update import _is_generated_compose_file
        assert _is_generated_compose_file("nginx/llmproxy-auth.conf")

    def test_wheel_sync_excludes_the_rendered_secret(self):
        import importlib.util
        script = PROJECT_ROOT / "cli" / "scripts" / "sync_compose_resources.py"
        spec = importlib.util.spec_from_file_location("sync_resources", script)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        assert mod._should_exclude(
            COMPOSE_DIR / "nginx" / "llmproxy-auth.conf",
            Path("nginx/llmproxy-auth.conf"),
        )
        assert not mod._should_exclude(
            COMPOSE_DIR / "nginx" / "llmproxy-auth.conf.j2",
            Path("nginx/llmproxy-auth.conf.j2"),
        )
