"""Tests for Speedtest Tracker: compose config, nginx routing, CLI module,
TLS SANs, and adversarial route-bypass attempts.

Per the plan (`docs/plans/speedtest-tracker-internet-monitoring.md`), Speedtest
Tracker is an optional profiled Cove service (`profile: speedtest`) that
monitors the operator's WAN link. It mirrors the litellm hardening pattern.

Unit/integration tests (always runnable):
  - Validate compose service definitions (profiles, ports, healthcheck, memory,
    sqlite, image pinning, app_key)
  - Validate nginx template renders speedtest.cove server block with deferred DNS
  - Validate CLI module imports and has correct subcommands
  - Validate bringup.yml includes speedtest.cove in cert SANs, hosts, .env
  - Validate landing page + status optional-services
  - Validate bundled resources are in sync with compose/ (integrity)
  - Inverse-assertions: wrong host does not route; not in required SERVICES;
    auth posture is documented

Run all:   pytest cli/tests/test_speedtest.py
Run unit:  pytest cli/tests/test_speedtest.py -m "not e2e"
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined


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
RESOURCES_COMPOSE_DIR = (
    PROJECT_ROOT / "cli" / "cove" / "resources" / "compose"
)

MINIMAL_TEMPLATE_VARS = {
    "ansible_hostname": "testhost",
    "ts_ip": "100.64.0.1",
    "ts_status": SimpleNamespace(rc=0),
}

FULL_TEMPLATE_VARS = {
    **MINIMAL_TEMPLATE_VARS,
    "ts_dns_name": "testhost.tailnet.ts.net",
    "ca_uuid": "00000000-0000-0000-0000-000000000001",
    "dns_uuid": "00000000-0000-0000-0000-000000000002",
    "profile_uuid": "00000000-0000-0000-0000-000000000003",
    "root_ca_b64": "dGVzdC1jYS1iNjQ=",
}


def _load_compose() -> dict:
    with open(COMPOSE_DIR / "docker-compose.yml") as f:
        return yaml.safe_load(f)


def _load_bringup() -> dict:
    with open(COMPOSE_DIR / "bringup.yml") as f:
        return yaml.safe_load(f)


def _render_nginx() -> str:
    env = Environment(loader=FileSystemLoader(str(NGINX_DIR)), undefined=StrictUndefined)
    tmpl = env.get_template("default.conf.j2")
    return tmpl.render(FULL_TEMPLATE_VARS)


def _fake_provision_run(*args, **kwargs):
    """Fake subprocess.run for the auto-gen flow.

    Returns a CompletedProcess that emits a base64 key for `vault-put`/`vault-get`
    (the CLI resolves the secret via stdout), and succeeds for compose invocations.
    """
    import subprocess
    argv = args[0] if args and isinstance(args[0], list) else []
    argv_str = " ".join(str(a) for a in argv)
    if "creds" in argv_str and "vault-put" in argv_str:
        return subprocess.CompletedProcess(argv, 0, stdout="base64:TESTKEY")
    if "creds" in argv_str and "vault-get" in argv_str:
        return subprocess.CompletedProcess(argv, 2, stdout="")  # not cached
    return subprocess.CompletedProcess(argv, 0, stdout="")


class TestComposeServiceDefinition:
    """Validate the speedtest-tracker service definition in docker-compose.yml."""

    def test_speedtest_service_exists(self):
        data = _load_compose()
        assert "speedtest-tracker" in data["services"], (
            "speedtest-tracker service missing from compose"
        )

    def test_speedtest_has_profile(self):
        data = _load_compose()
        profiles = data["services"]["speedtest-tracker"].get("profiles", [])
        assert "speedtest" in profiles, (
            "speedtest-tracker service must have profiles: [\"speedtest\"]"
        )

    def test_speedtest_binds_localhost_only(self):
        data = _load_compose()
        ports = data["services"]["speedtest-tracker"].get("ports", [])
        port_strs = [str(p) for p in ports]
        assert any("127.0.0.1" in p for p in port_strs), (
            "speedtest-tracker must bind to 127.0.0.1 only, not 0.0.0.0"
        )
        for p in port_strs:
            assert "0.0.0.0" not in p, (
                f"speedtest-tracker must not bind to 0.0.0.0, got: {p}"
            )

    def test_speedtest_has_healthcheck(self):
        data = _load_compose()
        hc = data["services"]["speedtest-tracker"].get("healthcheck")
        assert hc is not None, "speedtest-tracker must have a healthcheck"

    def test_speedtest_has_memory_limit(self):
        data = _load_compose()
        deploy = data["services"]["speedtest-tracker"].get("deploy", {})
        limits = deploy.get("resources", {}).get("limits", {})
        assert "memory" in limits, "speedtest-tracker must have a memory limit"

    def test_speedtest_uses_sqlite(self):
        data = _load_compose()
        env = data["services"]["speedtest-tracker"].get("environment", {})
        assert env.get("DB_CONNECTION") == "sqlite", (
            "speedtest-tracker must use DB_CONNECTION=sqlite (single-container)"
        )

    def test_speedtest_image_pinned(self):
        data = _load_compose()
        image = str(data["services"]["speedtest-tracker"].get("image", ""))
        assert ":latest" not in image, (
            f"speedtest-tracker image must be version-pinned, got: {image}"
        )
        assert ":" in image, (
            f"speedtest-tracker image must have a version tag, got: {image}"
        )

    def test_speedtest_app_key_compose_non_blocking_form(self):
        """APP_KEY must use the non-blocking compose form (`${...:-}`), NOT the
        fail-loud `:?` form. The key is auto-generated by `cove speedtest up`
        (see T0-27), so the optional service's secret must not abort the global
        `cove up` / `docker compose config` path when SPEEDTEST_APP_KEY is
        unset."""
        data = _load_compose()
        env = data["services"]["speedtest-tracker"].get("environment", {})
        assert "APP_KEY" in env, "speedtest-tracker must accept APP_KEY env var"
        app_key = str(env.get("APP_KEY", ""))
        assert "${SPEEDTEST_APP_KEY:-" in app_key, (
            f"APP_KEY must use the non-blocking ${{SPEEDTEST_APP_KEY:-}} form, got: {app_key!r}"
        )
        assert ":?" not in app_key, (
            f"APP_KEY must NOT use the fail-loud :? form (breaks global cove up), got: {app_key!r}"
        )

    def test_compose_config_succeeds_without_app_key(self):
        """`docker compose config` must succeed when SPEEDTEST_APP_KEY is unset —
        the core platform (forge/vault/nginx) must not be blocked by the
        optional speedtest service's secret."""
        import os
        import subprocess

        env = dict(os.environ)
        env.pop("SPEEDTEST_APP_KEY", None)
        result = subprocess.run(
            ["docker", "compose", "--project-directory", str(COMPOSE_DIR), "config"],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0, (
            "docker compose config must succeed without SPEEDTEST_APP_KEY; "
            f"got rc={result.returncode}: {result.stderr}"
        )

    def test_speedtest_app_url_env(self):
        data = _load_compose()
        env = data["services"]["speedtest-tracker"].get("environment", {})
        assert "APP_URL" in env, "speedtest-tracker must accept APP_URL env var"

    def test_speedtest_container_name_cove_prefix(self):
        data = _load_compose()
        name = str(data["services"]["speedtest-tracker"].get("container_name", ""))
        assert "cove-" in name, (
            f"container_name must default to cove- prefix, got: {name}"
        )

    def test_speedtest_runs_non_root(self):
        """Non-root via PUID/PGID user namespace params (linuxserver images run
        the app as the PUID/PGID user, not root)."""
        data = _load_compose()
        env = data["services"]["speedtest-tracker"].get("environment", {})
        assert "PUID" in env and "PGID" in env, (
            "speedtest-tracker must set PUID/PGID to run non-root"
        )

    def test_speedtest_data_volume_from_data_root(self):
        """Data must be persisted under COVE_DATA_ROOT/speedtest."""
        data = _load_compose()
        volumes = data["services"]["speedtest-tracker"].get("volumes", [])
        volume_strs = [str(v) for v in volumes]
        assert any("speedtest" in v and "/config" in v for v in volume_strs), (
            "speedtest-tracker must mount data volume to /config under COVE_DATA_ROOT"
        )


class TestNginxConfig:
    """Validate nginx template renders speedtest.cove with deferred DNS."""

    def test_nginx_renders_speedtest_block(self):
        rendered = _render_nginx()
        assert "server_name speedtest.cove" in rendered
        assert "speedtest.cove.local" in rendered

    def test_nginx_uses_deferred_dns(self):
        rendered = _render_nginx()
        assert "resolver 127.0.0.11" in rendered
        assert "$speedtest_upstream" in rendered
        assert "http://speedtest-tracker:80" in rendered

    def test_speedtest_block_proxies_all_paths(self):
        rendered = _render_nginx()
        assert "proxy_pass $speedtest_upstream" in rendered


class TestCLI:
    """Validate the cove speedtest CLI module."""

    def test_speedtest_group_imports(self):
        from cove.speedtest import speedtest
        assert speedtest is not None

    def test_speedtest_group_registered(self):
        from cove.cli import app
        commands = list(app.commands.keys())
        assert "speedtest" in commands, "speedtest group must be registered in cli.py"

    def test_speedtest_has_up_command(self):
        from cove.speedtest import speedtest
        commands = list(speedtest.commands.keys())
        assert "up" in commands

    def test_speedtest_has_down_command(self):
        from cove.speedtest import speedtest
        commands = list(speedtest.commands.keys())
        assert "down" in commands

    def test_speedtest_has_status_command(self):
        from cove.speedtest import speedtest
        commands = list(speedtest.commands.keys())
        assert "status" in commands

    def test_speedtest_has_logs_command(self):
        from cove.speedtest import speedtest
        commands = list(speedtest.commands.keys())
        assert "logs" in commands

    def test_speedtest_up_uses_profile_flag(self):
        """cove speedtest up must use --profile speedtest so it doesn't start
        core services."""
        source = (PROJECT_ROOT / "cli" / "cove" / "speedtest.py").read_text()
        assert "--profile" in source and "speedtest" in source, (
            "cove speedtest up must use --profile speedtest"
        )

    def test_speedtest_down_uses_stop(self):
        """cove speedtest down must use 'stop' not 'down' to avoid stopping
        core Cove services."""
        source = (PROJECT_ROOT / "cli" / "cove" / "speedtest.py").read_text()
        assert '"stop"' in source or "'stop'" in source, (
            "cove speedtest down must use 'stop' command, not 'down'"
        )

    def test_speedtest_status_checks_through_nginx(self):
        """cove speedtest status must check through nginx (Host: speedtest.cove)
        on 8443, not a direct port."""
        source = (PROJECT_ROOT / "cli" / "cove" / "speedtest.py").read_text()
        assert "speedtest.cove" in source, (
            "cove speedtest status must reference speedtest.cove Host header"
        )
        assert "8443" in source, (
            "cove speedtest status must check through nginx on 8443"
        )

    def test_speedtest_up_does_not_fail_loud_without_app_key(self, monkeypatch, tmp_path):
        """cove speedtest up must succeed WITHOUT the operator manually setting
        SPEEDTEST_APP_KEY — no fail-loud on unset (T0-27)."""
        from click.testing import CliRunner
        import cove.speedtest as st
        from cove.speedtest import up

        monkeypatch.delenv("SPEEDTEST_APP_KEY", raising=False)
        env_file = tmp_path / ".env"
        monkeypatch.setattr(st, "_compose_env_path", lambda: env_file)
        seed = tmp_path / "speedtest-creds.yaml.example"
        seed.write_text(
            'items:\n  - title: "Speedtest {{ hostname }} APP_KEY"\n'
            "    vault: Private\n    category: login\n    fields:\n"
            '      username: "cove-speedtest"\n'
            '      password: "{{generate:64}}"\n'
        )
        monkeypatch.setattr(st, "_seed_example_path", lambda: seed)

        runner = CliRunner()
        with patch("cove.speedtest.subprocess.run", side_effect=_fake_provision_run) as mock_run:
            result = runner.invoke(up)

        assert result.exit_code == 0, result.output
        compose_calls = [
            c.args[0] for c in mock_run.call_args_list
            if isinstance(c.args[0], list)
        ]
        assert any("--profile" in args and "speedtest" in args for args in compose_calls)


class TestAppKeyAutoGen:
    """cove speedtest up must auto-generate SPEEDTEST_APP_KEY and store it in
    1Password + Vault + the compose .env on first run, then reuse the cached
    value on subsequent runs (idempotent). No manual key-setting required."""

    def _patch_env(self, monkeypatch, tmp_path):
        import cove.speedtest as st
        monkeypatch.delenv("SPEEDTEST_APP_KEY", raising=False)
        env_file = tmp_path / ".env"
        monkeypatch.setattr(st, "_compose_env_path", lambda: env_file)
        seed = tmp_path / "speedtest-creds.yaml.example"
        seed.write_text(
            'items:\n  - title: "Speedtest {{ hostname }} APP_KEY"\n'
            "    vault: Private\n    category: login\n    fields:\n"
            '      username: "cove-speedtest"\n'
            '      password: "{{generate:64}}"\n'
        )
        monkeypatch.setattr(st, "_seed_example_path", lambda: seed)
        return env_file

    def test_up_writes_app_key_to_1p_vault_and_env(self, monkeypatch, tmp_path):
        """First `up` auto-generates the key: 1p-bulk-write --execute creates the
        1P item, vault-put caches it in Vault, and the .env gets the key."""
        from click.testing import CliRunner
        from cove.speedtest import up

        env_file = self._patch_env(monkeypatch, tmp_path)
        runner = CliRunner()
        with patch("cove.speedtest.subprocess.run", side_effect=_fake_provision_run) as mock_run:
            result = runner.invoke(up)

        assert result.exit_code == 0, result.output
        calls = [
            c.args[0] for c in mock_run.call_args_list
            if isinstance(c.args[0], list)
        ]
        assert any("1p-bulk-write" in args and "--execute" in args for args in calls), (
            "expected cove creds 1p-bulk-write --execute call"
        )
        assert any("vault-put" in args for args in calls), (
            "expected cove creds vault-put call"
        )
        assert env_file.exists(), ".env must be written"
        content = env_file.read_text()
        assert "SPEEDTEST_APP_KEY=base64:TESTKEY" in content, (
            f".env must contain the generated key, got: {content}"
        )

    def test_up_reuses_cached_key_no_duplicate(self, monkeypatch, tmp_path):
        """A second `up` with the key already in .env must NOT regenerate,
        write to 1Password, or cache in Vault again (idempotent)."""
        from click.testing import CliRunner
        from cove.speedtest import up

        env_file = self._patch_env(monkeypatch, tmp_path)
        env_file.write_text("SPEEDTEST_APP_KEY=base64:EXISTING\n")
        runner = CliRunner()
        with patch("cove.speedtest.subprocess.run", side_effect=_fake_provision_run) as mock_run:
            result = runner.invoke(up)

        assert result.exit_code == 0, result.output
        calls = [
            c.args[0] for c in mock_run.call_args_list
            if isinstance(c.args[0], list)
        ]
        assert not any("1p-bulk-write" in args for args in calls), (
            "must not write to 1Password when key is cached"
        )
        assert not any("vault-put" in args for args in calls), (
            "must not re-cache in Vault when key is cached"
        )
        content = env_file.read_text()
        assert content.count("SPEEDTEST_APP_KEY=") == 1, (
            f".env must not get a duplicate SPEEDTEST_APP_KEY line, got: {content}"
        )
        assert "SPEEDTEST_APP_KEY=base64:EXISTING" in content

    def test_up_reuses_vault_cached_key(self, monkeypatch, tmp_path):
        """If .env is empty but the key is already cached in Vault (via
        vault-get), `up` reuses it instead of regenerating."""
        from click.testing import CliRunner
        import cove.speedtest as st
        from cove.speedtest import up

        env_file = self._patch_env(monkeypatch, tmp_path)
        monkeypatch.setattr(
            st, "_vault_get", lambda op_ref: "base64:FROMVAULT"
        )
        runner = CliRunner()
        with patch("cove.speedtest.subprocess.run", side_effect=_fake_provision_run) as mock_run:
            result = runner.invoke(up)

        assert result.exit_code == 0, result.output
        calls = [
            c.args[0] for c in mock_run.call_args_list
            if isinstance(c.args[0], list)
        ]
        assert not any("1p-bulk-write" in args for args in calls), (
            "must not regenerate when key is cached in Vault"
        )
        assert "SPEEDTEST_APP_KEY=base64:FROMVAULT" in env_file.read_text()

    def test_up_respects_operator_env_override(self, monkeypatch, tmp_path):
        """An operator-set SPEEDTEST_APP_KEY env var is honored and written to
        .env without touching 1Password/Vault."""
        from click.testing import CliRunner
        from cove.speedtest import up

        env_file = self._patch_env(monkeypatch, tmp_path)
        monkeypatch.setenv("SPEEDTEST_APP_KEY", "base64:OPERATOR")
        runner = CliRunner()
        with patch("cove.speedtest.subprocess.run", side_effect=_fake_provision_run) as mock_run:
            result = runner.invoke(up)

        assert result.exit_code == 0, result.output
        calls = [
            c.args[0] for c in mock_run.call_args_list
            if isinstance(c.args[0], list)
        ]
        assert not any("1p-bulk-write" in args for args in calls)
        assert not any("vault-put" in args for args in calls)
        assert "SPEEDTEST_APP_KEY=base64:OPERATOR" in env_file.read_text()


class TestEnvFilePermissions:
    """The compose .env holds the generated SPEEDTEST_APP_KEY — it must never be
    world-readable. `_upsert_env` uses `write_text`, which creates a fresh .env at
    0644 (umask default) when the file does not already exist. The fix must chmod
    it to 0600, mirroring local_cache.py's 0600 handling."""

    def _write_key(self, monkeypatch, tmp_path):
        import cove.speedtest as st
        env_file = tmp_path / ".env"
        monkeypatch.setattr(st, "_compose_env_path", lambda: env_file)
        st._upsert_env("SPEEDTEST_APP_KEY", "base64:TESTKEY")
        return env_file

    def test_fresh_env_is_0600(self, monkeypatch, tmp_path):
        """A freshly created .env (file did NOT pre-exist) must be mode 0600, NOT
        the 0644 write_text default. Prevents leaking the generated APP_KEY
        world-readable when `cove speedtest up` runs before first `cove up`."""
        env_file = self._write_key(monkeypatch, tmp_path)
        assert env_file.exists()
        mode = env_file.stat().st_mode & 0o777
        assert mode == 0o600, f".env must be 0600 after fresh write, got {oct(mode)}"

    def test_existing_0600_env_stays_0600(self, monkeypatch, tmp_path):
        """An already-restricted .env must stay 0600 after _upsert_env rewrites it."""
        import cove.speedtest as st
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\n")
        env_file.chmod(0o600)
        monkeypatch.setattr(st, "_compose_env_path", lambda: env_file)
        st._upsert_env("SPEEDTEST_APP_KEY", "base64:TESTKEY")
        mode = env_file.stat().st_mode & 0o777
        assert mode == 0o600, f".env must remain 0600, got {oct(mode)}"


class TestSeedRendering:
    """The seed file must render the runtime hostname so the 1Password item title
    matches the op_ref, and the temp seed must be cleaned up after use."""

    def test_render_seed_replaces_hostname(self, monkeypatch, tmp_path):
        """_render_seed must substitute the placeholder with the runtime hostname
        (not leave `{{ hostname }}` or the ansible variant)."""
        import cove.speedtest as st
        seed = tmp_path / "speedtest-creds.yaml.example"
        seed.write_text(
            'items:\n  - title: "Speedtest {{ hostname }} APP_KEY"\n'
            '      host[text]: "{{ hostname }}"\n'
        )
        monkeypatch.setattr(st, "_seed_example_path", lambda: seed)
        monkeypatch.setattr(st, "_hostname", lambda: "myhost")
        rendered = st._render_seed()
        assert "{{ hostname }}" not in rendered
        assert "{{ ansible_hostname }}" not in rendered
        assert "myhost" in rendered

    def test_seed_temp_file_unlinked(self, monkeypatch, tmp_path):
        """The temp seed file written for 1p-bulk-write must be removed after
        _ensure_app_key runs — no orphaned seed files left behind."""
        import os
        from pathlib import Path
        import cove.speedtest as st

        monkeypatch.delenv("SPEEDTEST_APP_KEY", raising=False)
        env_file = tmp_path / ".env"
        monkeypatch.setattr(st, "_compose_env_path", lambda: env_file)
        seed = tmp_path / "speedtest-creds.yaml.example"
        seed.write_text(
            'items:\n  - title: "Speedtest {{ hostname }} APP_KEY"\n'
            "    vault: Private\n    category: login\n    fields:\n"
            '      username: "cove-speedtest"\n'
            '      password: "{{generate:64}}"\n'
        )
        monkeypatch.setattr(st, "_seed_example_path", lambda: seed)

        seen_paths = []
        real_run = st.subprocess.run

        def capture_run(*args, **kwargs):
            argv = args[0] if args and isinstance(args[0], list) else []
            if "1p-bulk-write" in " ".join(argv):
                seed_arg = argv[argv.index("1p-bulk-write") + 1]
                seen_paths.append(Path(seed_arg))
                assert Path(seed_arg).exists(), "seed arg must exist at call time"
            return _fake_provision_run(*args, **kwargs)

        with patch("cove.speedtest.subprocess.run", side_effect=capture_run):
            st._ensure_app_key()

        assert seen_paths, "expected a 1p-bulk-write call with a seed path"
        for p in seen_paths:
            assert not p.exists(), (
                f"temp seed file not unlinked after use: {p}"
            )


class TestAppKeyAutoGen1PBulkWrite:
    """`1p-bulk-write --execute` must be checked for failure — a non-zero return
    must surface the real 1Password root cause, not a misleading Vault error."""

    def test_failed_1p_bulk_write_raises_clear_error(self, monkeypatch, tmp_path):
        """When 1p-bulk-write --execute fails, _ensure_app_key must raise an error
        naming the 1Password write failure (not a generic 'Failed to cache in
        Vault' that masks the root cause)."""
        import subprocess
        import click
        import cove.speedtest as st

        monkeypatch.delenv("SPEEDTEST_APP_KEY", raising=False)
        env_file = tmp_path / ".env"
        monkeypatch.setattr(st, "_compose_env_path", lambda: env_file)
        seed = tmp_path / "speedtest-creds.yaml.example"
        seed.write_text(
            'items:\n  - title: "Speedtest {{ hostname }} APP_KEY"\n'
        )
        monkeypatch.setattr(st, "_seed_example_path", lambda: seed)

        def fake_run(*args, **kwargs):
            argv = args[0] if args and isinstance(args[0], list) else []
            if "1p-bulk-write" in " ".join(argv):
                return subprocess.CompletedProcess(
                    argv, 1, stdout="", stderr="op: item already exists"
                )
            if "vault-get" in " ".join(argv):
                return subprocess.CompletedProcess(argv, 2, stdout="")
            return subprocess.CompletedProcess(argv, 0, stdout="base64:TESTKEY")

        with patch("cove.speedtest.subprocess.run", side_effect=fake_run):
            with pytest.raises(click.ClickException) as excinfo:
                st._ensure_app_key()
        assert "1Password" in str(excinfo.value), (
            f"error must name the 1Password write failure, got: {excinfo.value}"
        )
        assert "op: item already exists" in str(excinfo.value)


class TestBringupIntegration:
    """Validate bringup.yml includes speedtest.cove in cert SANs, hosts, .env,
    and creates the data directory."""

    def test_bringup_sans_include_speedtest(self):
        with open(COMPOSE_DIR / "bringup.yml") as f:
            content = f.read()
        assert "speedtest.cove" in content, (
            "bringup.yml must include speedtest.cove in cert SANs"
        )
        assert "speedtest.cove.local" in content

    def test_bringup_hosts_include_speedtest(self):
        bringup = _load_bringup()
        tasks = bringup[0]["tasks"] if isinstance(bringup, list) else bringup.get("tasks", [])
        hosts_task = [
            t for t in tasks
            if isinstance(t, dict) and "hosts" in (t.get("name", "") or "").lower()
        ]
        assert hosts_task, "No /etc/hosts task found in bringup.yml"
        line = str(hosts_task[0].get("ansible.builtin.lineinfile", {}).get("line", ""))
        assert "speedtest.cove" in line, (
            f"/etc/hosts entry must include speedtest.cove, got: {line}"
        )

    def test_bringup_env_includes_speedtest_vars(self):
        with open(COMPOSE_DIR / "bringup.yml") as f:
            content = f.read()
        assert "SPEEDTEST_IMAGE" in content, "bringup.yml .env must include SPEEDTEST_IMAGE"
        assert "SPEEDTEST_PORT" in content, "bringup.yml .env must include SPEEDTEST_PORT"
        assert "SPEEDTEST_CONTAINER_NAME" in content, (
            "bringup.yml .env must include SPEEDTEST_CONTAINER_NAME"
        )
        assert "SPEEDTEST_APP_KEY" in content, (
            "bringup.yml .env must include SPEEDTEST_APP_KEY"
        )

    def test_bringup_creates_data_dir(self):
        bringup = _load_bringup()
        tasks = bringup[0]["tasks"] if isinstance(bringup, list) else bringup.get("tasks", [])
        data_dir_tasks = [
            t for t in tasks
            if isinstance(t, dict) and "data" in (t.get("name", "") or "").lower()
        ]
        assert data_dir_tasks, "No data directory task found in bringup.yml"
        loop = data_dir_tasks[0].get("loop", [])
        assert any("speedtest" in str(item) for item in loop), (
            "bringup.yml must create the speedtest data directory"
        )

    def test_bringup_cert_validation_includes_speedtest(self):
        with open(COMPOSE_DIR / "bringup.yml") as f:
            content = f.read()
        assert "speedtest.cove" in content, (
            "bringup.yml cert validation must include speedtest.cove"
        )


class TestLandingPage:
    """Validate landing.html has a speedtest.cove card + status dot."""

    def test_landing_page_has_speedtest(self):
        with open(NGINX_DIR / "landing.html") as f:
            content = f.read()
        assert "speedtest.cove" in content, "landing.html must reference speedtest.cove"
        assert "dot-speedtest" in content, (
            "landing.html must have a dot-speedtest status entry"
        )


class TestStatusOptionalServices:
    """Validate status.py includes Speedtest as an optional service."""

    def test_speedtest_in_optional_services(self):
        from cove.status import OPTIONAL_SERVICES
        names = [name for _, name in OPTIONAL_SERVICES]
        assert "Speedtest" in names, "Speedtest must be in OPTIONAL_SERVICES"

    def test_speedtest_not_in_required_services(self):
        """Speedtest is optional — it must NOT be in the required SERVICES list."""
        from cove.status import SERVICES
        names = [name for _, name in SERVICES]
        assert "Speedtest" not in names, (
            "Speedtest must NOT be in required SERVICES — it's optional"
        )


class TestResourcesSync:
    """Validate the bundled compose resources reflect the compose/ source
    (integrity/drift guard). The resources dir is a build artifact synced via
    cli/scripts/sync_compose_resources.py."""

    def test_resources_tree_in_sync(self):
        """SHA-256 of the synced resources tree must match compose/ for the
        speedtest additions (exclude rendered + PII files, same rules as the
        sync script)."""
        if not RESOURCES_COMPOSE_DIR.is_dir():
            pytest.fail(
                "cli/cove/resources/compose/ missing — run "
                "python3 cli/scripts/sync_compose_resources.py"
            )
        excluded_names = {".env", "default.conf", "cove.conf"}
        for rel in [
            "docker-compose.yml",
            "bringup.yml",
            "nginx/default.conf.j2",
            "nginx/landing.html",
        ]:
            src = COMPOSE_DIR / rel
            dst = RESOURCES_COMPOSE_DIR / rel
            if src.name in excluded_names:
                continue
            assert dst.exists(), (
                f"bundled resources missing {rel} — run sync_compose_resources.py"
            )
            assert src.read_bytes() == dst.read_bytes(), (
                f"bundled resources out of sync for {rel} — run sync_compose_resources.py"
            )


class TestAuthPosture:
    """Adversarial/security assertions: no unauthenticated dashboard silently
    regresses, and the posture is documented."""

    def test_auth_posture_documented(self):
        """docs/speedtest.md must state the auth posture explicitly, including
        the login gate (or basic-auth fallback) so an unauthenticated dashboard
        can't silently regress."""
        doc = PROJECT_ROOT / "docs" / "speedtest.md"
        assert doc.exists(), "docs/speedtest.md must exist"
        content = doc.read_text().lower()
        assert "auth" in content, "docs/speedtest.md must state the auth posture"
        assert "login" in content, (
            "docs/speedtest.md must confirm app login is enforced (or basic-auth)"
        )
        assert "unauthenticated" in content, (
            "docs/speedtest.md must address the unauthenticated-by-default hazard "
            "(an open dashboard is not acceptable)"
        )
        assert "basic-auth" in content, (
            "docs/speedtest.md must document the nginx basic-auth fallback posture"
        )

    def test_wrong_host_does_not_route_to_speedtest(self):
        """A non-cove Host header must not route to the speedtest upstream —
        the default server serves the landing page instead of proxying."""
        rendered = _render_nginx()
        assert "server_name _" in rendered
        assert "landing.html" in rendered
        default_block = rendered[rendered.index("server_name _;"):]
        default_block = default_block[:default_block.index("}") + 1]
        assert "proxy_pass" not in default_block

    def test_no_direct_port_access_in_cli(self):
        """The CLI status check must go through nginx on 8443, not a direct port."""
        source = (PROJECT_ROOT / "cli" / "cove" / "speedtest.py").read_text()
        assert "8443" in source, "status must check through nginx (8443), not direct port"
        assert "speedtest.cove" in source, (
            "status must reference speedtest.cove Host header"
        )

    def test_app_key_no_weak_literal_in_compose(self):
        """APP_KEY must not be a weak literal default — the key is auto-generated
        at the `cove speedtest up` CLI boundary (`_ensure_app_key`, T0-27), not
        via a compose `:?` interpolation that would break the global `cove up`
        path."""
        data = _load_compose()
        env = data["services"]["speedtest-tracker"].get("environment", {})
        app_key = str(env.get("APP_KEY", ""))
        assert "${SPEEDTEST_APP_KEY:-" in app_key, (
            "APP_KEY must use the non-blocking ${SPEEDTEST_APP_KEY:-} form"
        )
        assert ":?" not in app_key, (
            "APP_KEY must NOT use the fail-loud :? form (breaks global cove up)"
        )


@pytest.mark.e2e
@pytest.mark.staging
class TestE2ESpeedtestStack:
    """Integration tests requiring a live Cove stack with speedtest profile.

    Run with: pytest cli/tests/test_speedtest.py -m e2e
    """

    def test_speedtest_up_starts_container(self):
        import subprocess
        from cove.speedtest import up
        up()
        result = subprocess.run(
            ["docker", "ps", "--filter", "name=cove-speedtest-tracker",
             "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=15,
        )
        assert "cove-speedtest-tracker" in result.stdout

    def test_speedtest_ui_returns_200(self):
        """speedtest.cove serves the UI through nginx (unauthenticated request
        reaches the app; login is enforced by the app itself)."""
        import requests
        resp = requests.get(
            "https://127.0.0.1:8443/",
            headers={"Host": "speedtest.cove"},
            verify=False,
            timeout=10,
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def test_speedtest_requires_auth(self):
        """An unauthenticated request must NOT land on a naked dashboard. The
        pinned Speedtest Tracker version enforces app login on first run and
        redirects unauthenticated visitors away from the dashboard. We assert
        either a login redirect (301/302 to a /login route) or a 401 — never a
        bare 200 serving dashboard content."""
        import requests
        resp = requests.get(
            "https://127.0.0.1:8443/",
            headers={"Host": "speedtest.cove"},
            verify=False,
            timeout=10,
            allow_redirects=False,
        )
        if resp.status_code == 200:
            # A 200 must be the login page, NOT the unauthenticated dashboard.
            # Speedtest Tracker redirects unauth'd / to /login; a 200 body with
            # a login form is acceptable only if it is verifiably the login page.
            assert "login" in resp.text.lower(), (
                "Unauthenticated request returned 200 but no login content — "
                "this looks like an open dashboard; auth posture is violated"
            )
        else:
            assert resp.status_code in (301, 302, 401), (
                f"Expected login redirect (301/302) or 401, got {resp.status_code}"
            )
            loc = resp.headers.get("location", "").lower()
            if resp.status_code in (301, 302):
                assert "login" in loc, (
                    f"Redirect must target a login route, got Location: {loc!r}"
                )

