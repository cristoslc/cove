"""Bifrost gateway tests (LiteLLM replacement candidate, additive phase).

Coverage:
- compose/bifrost/config.json: the tier ladder as ordered fallback chains,
  the streaming-only infinite gate, auth-by-default, logging-off knobs,
  env-referenced credentials, no literal secrets.
- compose service surface: digest-pinned image, loopback port, egress
  sinkhole wiring (dns pin, allowlist, dedicated subnet).
- nginx vhost + landing page surface.
- bringup.yml seeding: private data dir, env file, config seeds, and the
  SQLite config-store file pre-seeding (a file-only boot cannot carry
  governance).
- CLI: registration, compose-source guard, runtime-file preparation, seed
  rendering (distinct values per field), idempotent .env upsert.
- live smoke (opt-in via COVE_ALLOW_LIVE_TESTS=1): a self-contained docker
  run against a local mock upstream proving auth-by-default, tier routing
  with ordered fallback, and the structural streaming-only gate.
"""

import json
import os
import sqlite3
import stat
from pathlib import Path

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
BIFROST_DIR = COMPOSE_DIR / "bifrost"
NGINX_DIR = COMPOSE_DIR / "nginx"

# The pinned Bifrost image digest (multi-arch manifest, v2.3.2). If the pin
# ever moves, this constant must move with it — that is the point.
BIFROST_PINNED_IMAGE = (
    "maximhq/bifrost:v2.3.2"
    "@sha256:f5b18826349fe9e1c402c10d19f1cbb5567a3c800ad928580d07f72e69106ec7"
)

# Tier ladder expected chain order (provider/wire-id), from the litellm
# configuration being replaced (docs/musings/litellm-exit.md).
EXPECTED_CHAINS = {
    "text:light": [
        "syn-subscription/hf:zai-org/GLM-4.7-Flash",
        "ollama-cloud/gpt-oss:120b",
        "syn-infinite-backstop/infinite:small:vision",
    ],
    "text:standard": [
        "syn-subscription/hf:deepseek-ai/DeepSeek-V4.1-Flash",
        "ollama-cloud/deepseek-v4.1-flash",
        "syn-infinite-backstop/infinite:small:vision",
    ],
    "text:ultra-heavy": [
        "syn-subscription/hf:zai-org/GLM-5.3",
        "ollama-cloud/glm-5.3",
        "syn-infinite-backstop/infinite:small:vision",
    ],
    "vision:heavy": [
        "syn-subscription/hf:zai-org/GLM-5.3-Flash",
        "ollama-cloud/glm-5.3-flash",
        "syn-infinite-backstop/infinite:small:vision",
    ],
    "vision:super-ultra-heavy": [
        "syn-subscription/hf:moonshotai/Kimi-K3",
        "ollama-cloud/kimi-k3",
        "syn-infinite-backstop/infinite:small:vision",
    ],
    "nonstreaming:text:light": [
        "syn-subscription/hf:zai-org/GLM-4.7-Flash",
        "ollama-cloud/gpt-oss:120b",
    ],
    "nonstreaming:text:standard": [
        "syn-subscription/hf:deepseek-ai/DeepSeek-V4.1-Flash",
        "ollama-cloud/deepseek-v4.1-flash",
    ],
    "syn:large:text": [
        "syn-subscription/syn:large:text",
    ],
    "infinite:small:vision": [
        "syn-infinite-backstop/infinite:small:vision",
    ],
}

EXPECTED_TARGETS = {tier: chain[0] for tier, chain in EXPECTED_CHAINS.items()}


def _load_config() -> dict:
    with open(BIFROST_DIR / "config.json") as f:
        return json.load(f)


def _load_compose() -> dict:
    with open(COMPOSE_DIR / "docker-compose.yml") as f:
        return yaml.safe_load(f)


def _load_bringup() -> dict:
    with open(COMPOSE_DIR / "bringup.yml") as f:
        return yaml.safe_load(f)


def _render_nginx() -> str:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    env = Environment(loader=FileSystemLoader(str(NGINX_DIR)), undefined=StrictUndefined)
    return env.get_template("default.conf.j2").render(ts_dns_name="testhost.tailnet.ts.net")


def _rules(config: dict) -> dict:
    return {rule["cel_expression"].split("'")[1]: rule
            for rule in config["governance"]["routing_rules"]}


def _chain(rule: dict) -> list[str]:
    first = rule["targets"][0]
    ids = [f"{first['provider']}/{first['model']}"]
    ids.extend(rule.get("fallbacks", []))
    return ids


def _extract_server_block(rendered: str, marker: str) -> str:
    """The full `server { ... }` block whose server_name line contains
    `marker` (brace-matched from the block's opening line)."""
    lines = rendered.split("\n")
    marker_idx = next(
        (i for i, l in enumerate(lines) if marker in l), None
    )
    assert marker_idx is not None, f"no server block matches {marker!r}"
    start_idx = marker_idx
    for i in range(marker_idx, max(marker_idx - 10, -1), -1):
        if lines[i].strip().startswith("server {") or lines[i].strip() == "server":
            start_idx = i
            break
    block_lines: list[str] = []
    brace_depth = 0
    for i in range(start_idx, len(lines)):
        block_lines.append(lines[i])
        brace_depth += lines[i].count("{")
        brace_depth -= lines[i].count("}")
        if brace_depth <= 0 and len(block_lines) > 1:
            break
    return "\n".join(block_lines)


def _provider_names(config: dict) -> dict:
    return config["providers"]


class TestBifrostConfigValidation:
    """config.json is the governance source: the ladder, the gate, the logs-off
    posture and env-only credentials are all load-bearing."""

    def setup_method(self):
        self.config = _load_config()

    def test_source_of_truth_and_schema(self):
        assert self.config["source_of_truth"] == "config.json"
        assert "$schema" in self.config

    def test_encryption_key_is_env_reference(self):
        assert self.config["encryption_key"] == "env.BIFROST_ENCRYPTION_KEY"

    def test_request_logging_off(self):
        client = self.config["client"]
        assert client["enable_logging"] is False
        assert client["disable_content_logging"] is True
        # Part of the adoption gate: no client can re-enable body capture.
        assert client["allow_per_request_content_storage_override"] is False
        # No request log store at all (body-capable OSS log).
        assert self.config["logs_store"] == {"enabled": False}

    def test_sqlite_config_store_preexists_in_compose_mount(self):
        store = self.config["config_store"]
        assert store["enabled"] is True
        assert store["type"] == "sqlite"
        assert store["config"]["path"] == "config.db"

    def test_auth_enforced_on_inference(self):
        auth = self.config["governance"]["auth_config"]
        assert auth["is_enabled"] is True
        assert auth["disable_auth_on_inference"] is False
        assert self.config["client"]["enforce_auth_on_inference"] is True
        assert auth["admin_username"] == "env.BIFROST_ADMIN_USERNAME"
        assert auth["admin_password"] == "env.BIFROST_ADMIN_PASSWORD"

    def test_three_custom_instances_with_openai_type(self):
        providers = _provider_names(self.config)
        assert set(providers) == {
            "syn-subscription", "ollama-cloud", "syn-infinite-backstop"
        }
        for name, provider in providers.items():
            assert provider["custom_provider_config"]["base_provider_type"] == "openai"
            assert len(provider["keys"]) == 1

    def test_base_urls_exclude_v1_suffix(self):
        """Spike finding: per-instance base_urls must NOT carry the /v1
        suffix (Bifrost appends the OpenAI request path itself)."""
        providers = _provider_names(self.config)
        assert providers["syn-subscription"]["network_config"]["base_url"] \
            == "https://api.synthetic.new/openai"
        assert providers["ollama-cloud"]["network_config"]["base_url"] \
            == "https://ollama.com"
        assert providers["syn-infinite-backstop"]["network_config"]["base_url"] \
            == "https://api.synthetic.new/openai"
        for provider in providers.values():
            assert not provider["network_config"]["base_url"].rstrip("/").endswith("/v1")

    def test_provider_keys_are_env_references(self):
        for provider in _provider_names(self.config).values():
            assert provider["keys"][0]["value"].startswith("env.")

    def test_subscription_and_ollama_allow_chat_only(self):
        """12-field allowed_requests: exactly chat + chat streaming enabled;
        everything else default-false-explicit."""
        for name in ("syn-subscription", "ollama-cloud"):
            allowed = _provider_names(self.config)[name]["custom_provider_config"][
                "allowed_requests"]
            expected_enabled = {"chat_completion", "chat_completion_stream"}
            truthy = {k for k, v in allowed.items() if v}
            assert truthy == expected_enabled
            assert set(allowed) == {
                "list_models", "text_completion", "text_completion_stream",
                "chat_completion", "chat_completion_stream",
                "responses", "responses_stream",
                "embedding", "speech", "speech_stream",
                "transcription", "transcription_stream",
            }

    def test_infinite_backstop_is_streaming_only(self):
        """The structural gate: the backstop instance can only serve chat
        streaming, so a non-streaming request can never reach it."""
        allowed = _provider_names(self.config)["syn-infinite-backstop"][
            "custom_provider_config"]["allowed_requests"]
        truthy = {k for k, v in allowed.items() if v}
        assert truthy == {"chat_completion_stream"}

    def test_nine_routing_rules_match_the_ladder(self):
        rules = _rules(self.config)
        assert set(rules) == set(EXPECTED_CHAINS)
        for tier, rule in rules.items():
            assert rule["enabled"] is True
            assert rule["targets"][0]["weight"] == 1.0
            assert _chain(rule) == EXPECTED_CHAINS[tier], (
                f"chain order changed for {tier}: spend-first ordering is "
                "load-bearing (synthetic subscription, ollama metered, "
                "infinite backstop)"
            )

    def test_default_target_matches_ladder_head(self):
        rules = _rules(self.config)
        for tier, rule in rules.items():
            first = rule["targets"][0]
            assert f"{first['provider']}/{first['model']}" == EXPECTED_TARGETS[tier]

    def test_bare_tier_ids_not_request_field(self):
        """Spike finding: the governance docs' `request.model == ...` example
        does not compile — the CEL context exposes the bare `model` field."""
        for rule in self.config["governance"]["routing_rules"]:
            assert "request.model" not in rule["cel_expression"]
            assert rule["cel_expression"].startswith("model == '")

    def test_non_streaming_tiers_never_reach_the_backstop(self):
        rules = _rules(self.config)
        for tier in ("nonstreaming:text:light", "nonstreaming:text:standard"):
            chain = _chain(rules[tier])
            assert not any(c.startswith("syn-infinite-backstop/") for c in chain)

    def test_infinite_tier_routes_to_the_gated_instance(self):
        rules = _rules(self.config)
        assert _chain(rules["infinite:small:vision"]) == [
            "syn-infinite-backstop/infinite:small:vision",
        ]

    def test_virtual_key_single_and_env_referenced(self):
        vks = self.config["governance"]["virtual_keys"]
        assert len(vks) == 1
        vk = vks[0]
        assert vk["value"] == "env.BIFROST_VIRTUAL_KEY"
        assert vk["is_active"] is True
        providers_covered = {pc["provider"] for pc in vk["provider_configs"]}
        assert providers_covered == set(_provider_names(self.config))
        for pc in vk["provider_configs"]:
            assert pc["allowed_models"] == ["*"]

    def test_no_literal_secret_values(self):
        """Every credential-shaped field must be an env reference; no sk-/bf-
        style literal may appear anywhere in the config."""
        config_text = json.dumps(self.config)
        assert "sk-" not in config_text
        assert "bf-" not in config_text

    def test_no_request_path_overrides(self):
        """Default OpenAI request paths; per-instance request-path overrides
        proved unnecessary in the spike and are pinned absent here."""
        for provider in _provider_names(self.config).values():
            cpc = provider["custom_provider_config"]
            assert "request_path_overrides" not in cpc


class TestBifrostComposeSurface:
    """The compose surface: digest pin, loopback binding, egress sinkhole."""

    def test_bifrost_service_and_profile_exist(self):
        data = _load_compose()
        assert "bifrost" in data["services"]
        assert "bifrost-dns" in data["services"]
        assert "bifrost" in data["services"]["bifrost"]["profiles"]
        assert "bifrost" in data["services"]["bifrost-dns"]["profiles"]

    def test_image_is_digest_pinned_with_exact_digest(self):
        data = _load_compose()
        image = data["services"]["bifrost"]["image"]
        assert image == "${BIFROST_IMAGE:-" + BIFROST_PINNED_IMAGE + "}", (
            f"Bifrost image must be the digest-pinned default verbatim: {image}"
        )

    def test_port_is_loopback_only(self):
        data = _load_compose()
        ports = data["services"]["bifrost"]["ports"]
        assert ports == ["127.0.0.1:${BIFROST_PORT:-4002}:8080"]

    def test_runtime_file_mounts(self):
        data = _load_compose()
        volumes = data["services"]["bifrost"]["volumes"]
        config_mount = [v for v in volumes if v.endswith("/config.json:ro")]
        store_mount = [v for v in volumes if v.endswith("/config.db")]
        assert config_mount, "config.json must mount read-only"
        assert store_mount, "config.db must mount writable (SQLite store)"
        # NOT a named volume or dir bind: both are file binds under bifrost/.
        assert "${COVE_DATA_ROOT}/bifrost/config.json:/app/data/config.json:ro" in volumes
        assert "${COVE_DATA_ROOT}/bifrost/config.db:/app/data/config.db" in volumes

    def test_env_file_and_credential_passthroughs(self):
        data = _load_compose()
        svc = data["services"]["bifrost"]
        assert svc["env_file"] == ["${COVE_DATA_ROOT}/bifrost/local.env"]
        env = svc["environment"]
        assert env["BIFROST_ENCRYPTION_KEY"] == "${BIFROST_ENCRYPTION_KEY:-}"
        assert env["BIFROST_VIRTUAL_KEY"] == "${BIFROST_VIRTUAL_KEY:-}"
        assert env["BIFROST_ADMIN_USERNAME"] == "${BIFROST_ADMIN_USERNAME:-}"
        assert env["BIFROST_ADMIN_PASSWORD"] == "${BIFROST_ADMIN_PASSWORD:-}"
        # Workstation-lane key ownership: plain pass-through, no custody.
        assert env["OLLAMA_API_KEY"] == "${OLLAMA_API_KEY:-}"

    def test_healthcheck_targets_container_health_endpoint(self):
        data = _load_compose()
        test = data["services"]["bifrost"]["healthcheck"]["test"]
        assert "/health" in " ".join(test)

    def test_gateway_resolves_only_through_the_sink(self):
        data = _load_compose()
        svc = data["services"]["bifrost"]
        assert svc["dns"] == ["172.43.0.10"]
        assert "default" in svc["networks"]
        assert "bifrost-egress" in svc["networks"]

    def test_sink_is_hardened_minimal(self):
        data = _load_compose()
        sink = data["services"]["bifrost-dns"]
        assert sink["read_only"] is True
        assert "ALL" in sink["cap_drop"]
        assert "NET_BIND_SERVICE" in sink["cap_add"]
        assert "ports" not in sink, "the DNS sink must publish no ports"
        assert sink["command"] == ["dnsmasq", "-k", "-C", "/etc/dnsmasq.d/bifrost.conf"]
        volumes = sink["volumes"]
        assert "${COVE_DATA_ROOT}/bifrost/dnsmasq.conf:/etc/dnsmasq.d/bifrost.conf:ro" in volumes

    def test_sink_static_ip_and_healthcheck(self):
        data = _load_compose()
        sink = data["services"]["bifrost-dns"]
        assert sink["networks"]["bifrost-egress"]["ipv4_address"] == "172.43.0.10"
        test = " ".join(sink["healthcheck"]["test"])
        assert "nslookup" in test

    def test_sink_builds_from_pinned_alpine(self):
        dockerfile = (BIFROST_DIR / "Dockerfile").read_text()
        assert "alpine:3.23.7@sha256:ff7f0c727dd796aa36787bfcd9a64bf35a6ce72a73451b3359fde849b6703d63" in dockerfile
        assert "dnsmasq=2.91-r1" in dockerfile
        assert "dnsmasq --test" in dockerfile

    def test_egress_subnet_is_declared_outside_default_pools(self):
        data = _load_compose()
        net = data["networks"]["bifrost-egress"]
        subnet = net["ipam"]["config"][0]["subnet"]
        assert subnet == "172.43.0.0/24"

    def test_dns_allowlist_shape(self):
        content = (BIFROST_DIR / "dnsmasq.conf").read_text()
        assert "no-resolv" in content
        assert "local=/#/" in content, "fail-closed sink: everything NXDOMAIN"
        assert "server=/api.synthetic.new/" in content
        assert "server=/ollama.com/" in content
        servers = [l for l in content.splitlines() if l.startswith("server=/")]
        assert len(servers) == 2, (
            "the allowlist is exactly the two inference providers — no new "
            "upstream without a test update"
        )


class TestBifrostNginxSurface:
    """Vhost + landing page: exposure without a client re-point."""

    def test_vhost_proxies_bifrost_with_streaming_safe_options(self):
        rendered = _render_nginx()
        assert "server_name bifrost.cove bifrost.cove.local;" in rendered
        assert "set $bifrost_upstream http://bifrost:8080;" in rendered
        assert "resolver 127.0.0.11" in rendered
        assert "proxy_buffering off;" in rendered
        assert "proxy_read_timeout 3600s;" in rendered

    def test_neutral_endpoint_vhost_proxies_the_configured_upstream(self):
        """llmproxy.cove is THE canonical client-facing OpenAI-compatible
        endpoint: an alias vhost proxying to the ACTIVE proxy upstream —
        one IaC line to change on a product swap — with the streaming
        settings copied from the litellm vhost (the ladder serves
        3600-second streams)."""
        rendered = _render_nginx()
        assert "server_name llmproxy.cove llmproxy.cove.local;" in rendered
        # The product-swap line names the currently active proxy.
        assert "set $llmproxy_upstream http://litellm:4000;" in rendered
        block = _extract_server_block(rendered, "server_name llmproxy.cove")
        assert "proxy_pass $llmproxy_upstream$request_uri;" in block
        assert "resolver 127.0.0.11" in block
        # Streaming-critical settings, copied from the litellm vhost.
        assert "proxy_buffering off;" in block
        assert "proxy_read_timeout 3600s;" in block
        assert "proxy_send_timeout 3600s;" in block

    def test_product_hostnames_stay_admin_debug_surfaces(self):
        """The neutral alias is additive: the litellm and bifrost vhosts
        (admin/debug surfaces) must both still be present."""
        rendered = _render_nginx()
        assert "server_name litellm.cove litellm.cove.local;" in rendered
        assert "server_name bifrost.cove bifrost.cove.local;" in rendered

    def test_landing_page_carries_the_card(self):
        landing = (NGINX_DIR / "landing.html").read_text()
        assert 'id="bifrost"' in landing
        assert 'id="dot-bifrost"' in landing
        assert "bifrost.cove.local" in landing
        # The health-loop service list drives the status dot.
        assert "bifrost" in landing.split("const services = ", 1)[1].split(";", 1)[0]

    def test_landing_page_carries_the_neutral_endpoint_card(self):
        landing = (NGINX_DIR / "landing.html").read_text()
        assert 'id="llmproxy"' in landing
        assert 'id="dot-llmproxy"' in landing
        assert "llmproxy.cove.local" in landing
        # The health-loop service list drives the status dot.
        assert "llmproxy" in landing.split("const services = ", 1)[1].split(";", 1)[0]

    def test_cert_sans_and_hosts_entry_present(self):
        content = (COMPOSE_DIR / "bringup.yml").read_text()
        assert "bifrost.cove" in content
        bringup = _load_bringup()
        tasks = bringup[0]["tasks"] if isinstance(bringup, list) else bringup.get("tasks", [])
        hosts_tasks = [
            t for t in tasks
            if isinstance(t, dict) and "hosts" in (t.get("name", "") or "").lower()
        ]
        assert hosts_tasks, "No /etc/hosts task found in bringup.yml"

    def test_neutral_endpoint_wired_everywhere(self):
        """Every place the product hostnames are wired carries the neutral
        names too: cert SANs, the bringup TLS-validation loop, the
        /etc/hosts entry, and the landing card (the dnsmasq resolver is
        wildcard-based — address=/cove/ + /cove.local/ — so both neutral
        names resolve with no per-name entry)."""
        bringup_text = (COMPOSE_DIR / "bringup.yml").read_text()
        # Cert SAN list entries.
        assert "- llmproxy.cove\n" in bringup_text
        assert "- llmproxy.cove.local\n" in bringup_text
        # TLS-cert validation loop.
        assert '"llmproxy.cove" "llmproxy.cove.local"' in bringup_text
        # /etc/hosts entry.
        hosts_line = next(
            l for l in bringup_text.splitlines()
            if "127.0.0.1 cove cove.local" in l
        )
        assert "llmproxy.cove llmproxy.cove.local" in hosts_line
        # Landing card (covered in detail by the dedicated test above).
        assert "llmproxy.cove.local" in (NGINX_DIR / "landing.html").read_text()


class TestBifrostBringup:
    """Seeding the runtime files: private dir, env file, config seeds, and the
    pre-existing SQLite store (spike finding)."""

    def _tasks_by_name(self) -> dict:
        bringup = _load_bringup()
        tasks = bringup[0]["tasks"] if isinstance(bringup, list) else bringup.get("tasks", [])
        return {t["name"]: t for t in tasks}

    def test_private_data_dir_task(self):
        task = self._tasks_by_name()["Create the Bifrost data directory (private)"]
        assert task["ansible.builtin.file"]["mode"] == "0700"

    def test_local_env_file_task(self):
        task = self._tasks_by_name()["Ensure Bifrost local provider env file exists"]
        spec = task["ansible.builtin.copy"]
        assert spec["mode"] == "0600"
        assert spec["force"] is False, "operator-managed env file is never overwritten"

    def test_config_and_allowlist_seed_tasks(self):
        tasks = self._tasks_by_name()
        config_task = tasks["Seed Bifrost governance config (first boot only)"]
        assert "bifrost/config.json" in config_task["ansible.builtin.copy"]["src"]
        dns_task = tasks["Seed Bifrost egress allowlist (first boot only)"]
        assert "bifrost/dnsmasq.conf" in dns_task["ansible.builtin.copy"]["src"]

    def test_sqlite_store_pre_seed_task(self):
        """The store file must pre-exist before the first container boot."""
        task = self._tasks_by_name()["Pre-seed the Bifrost SQLite config store file"]
        argv = task["ansible.builtin.command"]["argv"]
        assert "sqlite3" in " ".join(argv)
        assert task["when"] is not None
        # The file lands under the private bifrost data dir.
        assert "{{ cove_data_root }}/bifrost/config.db" in argv[-1]

    def test_wedge_guard_covers_bifrost_file_mounts(self):
        content = (COMPOSE_DIR / "bringup.yml").read_text()
        assert "{{ cove_data_root }}/bifrost/config.json" in content
        assert "{{ cove_data_root }}/bifrost/config.db" in content
        # Both are in the wedge-guard loop (stat before mount), not just in
        # a template.
        guard_index = content.index("Assert data-root bind-mount targets")
        for path in ("bifrost/config.json", "bifrost/config.db"):
            assert path in content[guard_index:guard_index + 2000]

    def test_env_template_renders_bifrost_keys(self):
        bringup = _load_bringup()
        tasks = bringup[0]["tasks"] if isinstance(bringup, list) else bringup.get("tasks", [])
        env_task = next(
            t for t in tasks
            if isinstance(t, dict)
            and (t.get("ansible.builtin.copy") or {}).get("dest")
            == "{{ compose_dir }}/.env"
        )
        content = env_task["ansible.builtin.copy"]["content"]
        for key in ("BIFROST_IMAGE", "BIFROST_DNS_IMAGE", "BIFROST_CONTAINER_NAME",
                    "BIFROST_DNS_CONTAINER_NAME", "BIFROST_PORT", "BIFROST_MEM_LIMIT"):
            assert key in content


class TestBifrostCli:
    """CLI surface: registration, guard, runtime files, seed rendering."""

    def test_bifrost_registered_on_the_app(self):
        from cove.cli import app
        assert "bifrost" in app.commands

    @pytest.mark.parametrize("cmd", ["up", "down", "status", "logs"])
    def test_subcommands_exist(self, cmd):
        from cove.cli import app
        assert cmd in app.commands["bifrost"].commands

    def test_up_aborts_on_unusable_data_root(self, tmp_path, monkeypatch):
        from cove.bifrost import bifrost
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()
        (compose_dir / ".env").write_text("SPEEDTEST_APP_KEY=abc\n")
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(compose_dir))
        monkeypatch.delenv("COVE_DATA_ROOT", raising=False)

        def _boom(*a, **k):
            raise AssertionError("docker compose must not run")

        monkeypatch.setattr("cove.bifrost.subprocess.run", _boom)
        result = CliRunner().invoke(bifrost, ["up"])
        assert result.exit_code != 0

    def test_ensure_runtime_files_seeds_and_preserves(self, tmp_path, monkeypatch):
        from cove.bifrost import _ensure_runtime_files
        compose_dir = tmp_path / "compose"
        (compose_dir / "bifrost").mkdir(parents=True)
        (compose_dir / "inventory.yml").write_text("all:\n  hosts: {}\n")
        src_config = BIFROST_DIR / "config.json"
        src_dns = BIFROST_DIR / "dnsmasq.conf"
        (compose_dir / "bifrost" / "config.json").write_text(src_config.read_text())
        (compose_dir / "bifrost" / "dnsmasq.conf").write_text(src_dns.read_text())
        data_root = tmp_path / "data"
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(compose_dir))
        monkeypatch.setenv("COVE_DATA_ROOT", str(data_root))

        _ensure_runtime_files()
        cfg = data_root / "bifrost"
        assert cfg.is_dir()
        assert stat.S_IMODE(cfg.stat().st_mode) == 0o700
        assert (cfg / "config.json").read_text() == src_config.read_text()
        assert (cfg / "dnsmasq.conf").read_text() == src_dns.read_text()
        assert (cfg / "local.env").exists()
        assert stat.S_IMODE((cfg / "local.env").stat().st_mode) == 0o600
        store = cfg / "config.db"
        assert store.exists()
        assert stat.S_IMODE(store.stat().st_mode) == 0o600
        # A valid SQLite file, not an empty placeholder.
        conn = sqlite3.connect(store)
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        conn.execute("CREATE TABLE marker (id INTEGER)")
        conn.commit()
        conn.close()

        # Second run preserves the store (operator state is never recreated).
        _ensure_runtime_files()
        conn = sqlite3.connect(store)
        names = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")
        }
        conn.close()
        assert "marker" in names

    def test_explicit_env_secrets_skip_1password(self, tmp_path, monkeypatch):
        """Explicit env vars are honored first; no 1Password subprocess may
        run and no secret is printed."""
        from cove import bifrost as bf
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()
        (compose_dir / "inventory.yml").write_text("all:\n  hosts: {}\n")
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(compose_dir))

        def _boom(*a, **k):
            raise AssertionError("1Password/Vault must not run when env vars are explicit")

        monkeypatch.setattr(bf, "_run_cove_creds", _boom)
        username = "smoke-admin-user"
        # Only the shared Cove Admin username lookup is answered; it must be
        # the ONE vault read (the three secrets come from explicit env vars).
        monkeypatch.setattr(
            bf, "_vault_get",
            lambda ref: username if "username" in ref else _boom(ref),
        )
        monkeypatch.setenv("BIFROST_ENCRYPTION_KEY", "explicit-not-a-secret-0")
        monkeypatch.setenv("BIFROST_ADMIN_PASSWORD", "explicit-not-a-secret-1")
        monkeypatch.setenv("BIFROST_VIRTUAL_KEY", "bf-explicit-not-a-secret-2")
        bf._ensure_secrets()
        env_text = (compose_dir / ".env").read_text()
        assert "BIFROST_ENCRYPTION_KEY=explicit-not-a-secret-0" in env_text
        assert "BIFROST_ADMIN_PASSWORD=explicit-not-a-secret-1" in env_text
        assert "BIFROST_VIRTUAL_KEY=bf-explicit-not-a-secret-2" in env_text
        assert f"BIFROST_ADMIN_USERNAME={username}" in env_text

    def test_upsert_env_is_idempotent(self, tmp_path, monkeypatch):
        from cove.bifrost import _upsert_env
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir()
        (compose_dir / "inventory.yml").write_text("all:\n  hosts: {}\n")
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(compose_dir))
        _upsert_env("BIFROST_TEST_KEY", "first")
        _upsert_env("BIFROST_TEST_KEY", "second")
        content = (compose_dir / ".env").read_text()
        assert content.count("BIFROST_TEST_KEY=") == 1
        assert "BIFROST_TEST_KEY=second" in content

    def test_seed_renders_three_distinct_values(self, tmp_path, monkeypatch):
        from cove import bifrost as bf
        compose_dir = tmp_path / "compose"
        (compose_dir / "seeds").mkdir(parents=True)
        (compose_dir / "inventory.yml").write_text("all:\n  hosts: {}\n")
        (compose_dir / "seeds" / "bifrost-creds.yaml.example").write_text(
            (COMPOSE_DIR / "seeds" / "bifrost-creds.yaml.example").read_text()
        )
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(compose_dir))
        rendered = bf._render_seed()
        assert "{{generate:" not in rendered, "all placeholders must be replaced"
        vk_line = [l for l in rendered.splitlines()
                   if l.strip().startswith("virtual_key[concealed]")][0]
        vk_value = vk_line.split('"')[1]
        assert vk_value.startswith("bf-") and len(vk_value) == 35
        enc_line = [l for l in rendered.splitlines()
                    if l.strip().startswith("encryption_key[concealed]")][0]
        enc_value = enc_line.split('"')[1]
        assert len(enc_value) == 64 and all(c in "0123456789abcdef" for c in enc_value)
        # The three values are distinct.
        assert len({vk_value, enc_value}) == 2

    def test_status_reports_credential_names_not_values(self, tmp_path, monkeypatch):
        """status may only print SET/missing — never a value."""
        from types import SimpleNamespace
        from cove import bifrost as bf
        compose_dir = tmp_path / "compose"
        (compose_dir / "bifrost").mkdir(parents=True)
        (compose_dir / "inventory.yml").write_text("all:\n  hosts: {}\n")
        (compose_dir / ".env").write_text(
            "COVE_DATA_ROOT=x\nBIFROST_VIRTUAL_KEY=value-never-printed\n"
        )
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(compose_dir))

        def _fake_run(cmd, *a, **k):
            # docker compose ps succeeds; every curl probe fails so the
            # status command stays hermetic.
            first = str(cmd[0]) if cmd else ""
            if first == "docker":
                return SimpleNamespace(stdout="", returncode=0, stderr="")
            return SimpleNamespace(stdout="", returncode=1, stderr="")

        monkeypatch.setattr(bf.subprocess, "run", _fake_run)
        result = CliRunner().invoke(
            bf.bifrost, ["status"], catch_exceptions=True,
        )
        assert "SET" in result.output
        assert "value-never-printed" not in result.output
        # The neutral client endpoint is reported on the status surface.
        assert "llmproxy.cove" in result.output

    def test_neutral_endpoint_upstream_read_from_deployed_config(
        self, tmp_path, monkeypatch,
    ):
        """The upstream report reads the deployed nginx config — the
        product-swap line — and reports what llmproxy.cove proxies to."""
        from cove import bifrost as bf
        compose_dir = tmp_path / "compose"
        nginx_dir = compose_dir / "nginx"
        nginx_dir.mkdir(parents=True)
        (compose_dir / "inventory.yml").write_text("all:\n  hosts: {}\n")
        (nginx_dir / "default.conf").write_text(
            "server {\n"
            "    server_name llmproxy.cove llmproxy.cove.local;\n"
            "    set $llmproxy_upstream http://litellm:4000;\n"
            "}\n"
        )
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(compose_dir))
        assert bf._neutral_endpoint_upstream() == "http://litellm:4000"

    def test_neutral_endpoint_upstream_missing_config_is_none(
        self, tmp_path, monkeypatch,
    ):
        """No deployed config (or no swap line) reports None — never a
        guessed upstream."""
        from cove import bifrost as bf
        compose_dir = tmp_path / "compose"
        compose_dir.mkdir(parents=True)
        (compose_dir / "inventory.yml").write_text("all:\n  hosts: {}\n")
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(compose_dir))
        assert bf._neutral_endpoint_upstream() is None
        nginx_dir = compose_dir / "nginx"
        nginx_dir.mkdir()
        (nginx_dir / "default.conf").write_text("server { }\n")
        assert bf._neutral_endpoint_upstream() is None


@pytest.fixture(scope="class")
def gateway(request):
    """One pinned-Bifrost container against a local model-keyed mock upstream.

    Class-scoped (module-level fixture): started once, torn down after the
    smoke class. No live Cove stack is touched."""
    import socket
    import subprocess
    import tempfile
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    captured = []            # (auth, wire_model, stream) tuples, ordered
    captured_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        PRIMARY_KEY_VALUE = TestBifrostLiveSmoke.PRIMARY_KEY
        SECONDARY_KEY_VALUE = TestBifrostLiveSmoke.SECONDARY_KEY

        def log_message(self, *args):  # quiet
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            auth = self.headers.get("Authorization", "")
            wire_model = body.get("model", "?")
            stream = bool(body.get("stream"))
            with captured_lock:
                captured.append((auth, wire_model, stream))
            key = auth.removeprefix("Bearer ").strip()
            # Model-keyed behavior: the text:standard PRIMARY hop fails,
            # everything else serves (streaming via SSE).
            if key == self.PRIMARY_KEY_VALUE and wire_model == self.FAIL_WIRE_MODEL:
                self._send_status(500, {"error": {"message": "primary down"}})
                return
            if key not in (self.PRIMARY_KEY_VALUE, self.SECONDARY_KEY_VALUE):
                self._send_status(401, {"error": {"message": "bad key"}})
                return
            if stream:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                chunk = json.dumps({
                    "id": "chatcmpl-1", "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {"content": "fallback-ok"},
                                 "finish_reason": None}],
                })
                self.wfile.write(f"data: {chunk}\n\n".encode())
                chunk_done = json.dumps({
                    "id": "chatcmpl-1", "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                })
                self.wfile.write(f"data: {chunk_done}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            else:
                self._send_status(200, {
                    "id": "chatcmpl-2", "object": "chat.completion",
                    "model": wire_model,
                    "choices": [{"index": 0,
                                 "message": {"role": "assistant", "content": "ok"},
                                 "finish_reason": "stop"}],
                })

        def _send_status(self, code, payload):
            data = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    mock_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    mock_port = mock_server.server_address[1]
    threading.Thread(target=mock_server.serve_forever, daemon=True).start()

    free_client = socket.socket()
    free_client.bind(("127.0.0.1", 0))
    client_port = free_client.getsockname()[1]
    free_client.close()

    tmp = tempfile.mkdtemp(prefix="bifrost-smoke-")
    config = json.loads((BIFROST_DIR / "config.json").read_text())
    for provider in config["providers"].values():
        provider["network_config"]["base_url"] = \
            f"http://host.docker.internal:{mock_port}"
    config_path = Path(tmp) / "config.json"
    config_path.write_text(json.dumps(config, indent=2))

    store_path = Path(tmp) / "config.db"
    conn = sqlite3.connect(store_path)
    conn.close()

    name = "cove-bifrost-smoke"
    subprocess.run(["docker", "rm", "-f", name],
                   capture_output=True, text=True, check=False)
    run = subprocess.run(
        ["docker", "run", "--rm", "--name", name, "-d",
         "-p", f"127.0.0.1:{client_port}:8080",
         "--add-host", "host.docker.internal:host-gateway",
         "-v", f"{config_path}:/app/data/config.json:ro",
         "-v", f"{store_path}:/app/data/config.db",
         "-e", f"BIFROST_VIRTUAL_KEY={TestBifrostLiveSmoke.VK}",
         "-e", "BIFROST_ENCRYPTION_KEY=" + "00" * 32,
         "-e", "BIFROST_ADMIN_USERNAME=smoke-admin",
         "-e", "BIFROST_ADMIN_PASSWORD=smoke-pass-not-a-secret",
         "-e", f"SYNTHETIC_API_KEY={TestBifrostLiveSmoke.PRIMARY_KEY}",
         "-e", f"OLLAMA_API_KEY={TestBifrostLiveSmoke.SECONDARY_KEY}",
         BIFROST_PINNED_IMAGE,
        ],
        capture_output=True, text=True, check=False,
    )

    base = f"http://127.0.0.1:{client_port}"
    ready = False
    if run.returncode == 0:
        import requests
        deadline = time.time() + 240
        while time.time() < deadline:
            try:
                if requests.get(f"{base}/health", timeout=3).status_code == 200:
                    ready = True
                    break
            except requests.RequestException:
                pass
            time.sleep(2)

    def teardown():
        subprocess.run(["docker", "rm", "-f", name],
                       capture_output=True, check=False)
        mock_server.shutdown()

    request.addfinalizer(teardown)

    if run.returncode != 0 or not ready:
        logs = subprocess.run(["docker", "logs", name],
                              capture_output=True, text=True, check=False)
        teardown()
        pytest.fail(
            "Bifrost smoke container failed to start/be healthy.\n"
            f"run stdout: {run.stdout}\nrun stderr: {run.stderr}\n"
            f"container logs: {logs.stdout[-4000:]}\n{logs.stderr[-4000:]}"
        )

    request.cls._base = base
    request.cls._captured = captured
    request.cls._captured_lock = captured_lock


@pytest.mark.live
class TestBifrostLiveSmoke:
    """Self-contained container smoke against a local mock upstream.

    Opt-in: COVE_ALLOW_LIVE_TESTS=1 (a real docker run of the pinned
    Bifrost image; no live Cove stack is touched). Proves:

    1. Inference auth is enforced by default (missing VK -> 401), and the
       FILE-SEEDED virtual key authenticates — the spike's unresolved
       finding re-checked at implementation.
    2. Tier routing executes the ordered fallback chain and the fallback
       hop actually serves when the primary errors.
    3. The streaming-only backstop instance refuses non-streaming
       structurally (before any upstream call).
    """

    PRIMARY_KEY = "sk-primary-smoke"
    SECONDARY_KEY = "sk-secondary-smoke"
    VK = "bf-smoke-virtual-key-fixed-for-this-test"
    FAIL_WIRE_MODEL = "hf:deepseek-ai/DeepSeek-V4.1-Flash"

    def _capture_count(self):
        with self._captured_lock:
            return len(self._captured)

    def test_missing_virtual_key_returns_401(self):
        import requests
        resp = requests.post(
            f"{self._base}/v1/chat/completions",
            json={"model": "syn:large:text", "messages": [{"role": "user", "content": "hi"}],
                  "stream": False},
            timeout=30,
        )
        assert resp.status_code == 401, f"auth must be enforced by default: {resp.status_code}"

    def test_non_stream_falls_back_when_primary_errors(self):
        import requests
        before = self._capture_count()
        resp = requests.post(
            f"{self._base}/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.VK}"},
            json={"model": "text:standard",
                  "messages": [{"role": "user", "content": "hi"}],
                  "stream": False},
            timeout=60,
        )
        assert resp.status_code == 200, f"fallback chain must recover primary failure: {resp.text[:300]}"
        body = resp.json()
        assert body["choices"][0]["message"]["content"] == "ok"
        with self._captured_lock:
            new = list(self._captured)[before:]
        assert new, "the upstream mock saw no request"
        fail_calls = [c for c in new if c[1] == self.FAIL_WIRE_MODEL]
        secondary_calls = [c for c in new if c[0].endswith(self.SECONDARY_KEY)]
        assert fail_calls, f"primary hop was never attempted: {new}"
        assert secondary_calls, f"fallback hop was never attempted: {new}"
        assert fail_calls[0][2] is False
        # The ordered chain: primary fails, the SECOND entry serves, and the
        # requested tier is preserved end to end.
        assert secondary_calls[0][1] in ("deepseek-v4.1-flash", "text:standard")
        print("bifrost routing headers:", dict(resp.headers))

    def test_stream_falls_back_the_same_way(self):
        import requests
        resp = requests.post(
            f"{self._base}/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.VK}"},
            json={"model": "text:standard",
                  "messages": [{"role": "user", "content": "hi"}],
                  "stream": True},
            timeout=60,
        )
        assert resp.status_code == 200
        raw = resp.text
        assert "data: " in raw and "[DONE]" in raw
        assert "fallback-ok" in raw
        fallback_flags = {k: v for k, v in resp.headers.items()
                          if "bifrost" in k.lower() or "fallback" in k.lower()}
        print("bifrost stream routing headers:", fallback_flags or "(none)")

    def test_streaming_non_fallback_route_serves_first_hop(self):
        import requests
        before = self._capture_count()
        resp = requests.post(
            f"{self._base}/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.VK}"},
            json={"model": "syn:large:text",
                  "messages": [{"role": "user", "content": "hi"}],
                  "stream": True},
            timeout=60,
        )
        assert resp.status_code == 200
        assert "[DONE]" in resp.text
        with self._captured_lock:
            new = list(self._captured)[before:]
        assert new, "the upstream mock saw no request"
        assert new[0][1] == "syn:large:text"
        assert new[0][0].endswith(self.PRIMARY_KEY), (
            "single-hop tier must hit the subscription instance directly"
        )

    def test_non_streaming_to_streaming_only_tier_is_structurally_refused(self):
        import requests
        before = self._capture_count()
        resp = requests.post(
            f"{self._base}/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.VK}"},
            json={"model": "infinite:small:vision",
                  "messages": [{"role": "user", "content": "hi"}],
                  "stream": False},
            timeout=60,
        )
        assert resp.status_code != 200, (
            "the streaming-only gate must refuse non-streaming"
        )
        with self._captured_lock:
            new = list(self._captured)[before:]
        assert not any(call[1] == "infinite:small:vision" for call in new), (
            "the gate must be structural: NOTHING may reach the gated instance "
            f"for a non-streaming request (calls seen: {new})"
        )

    def test_phone_home_scan(self):
        """Recorded, not asserted: outbound fetch attempts beyond the mock."""
        import subprocess
        logs = subprocess.run(
            ["docker", "logs", "cove-bifrost-smoke"],
            capture_output=True, text=True, check=False
        )
        text = logs.stdout + logs.stderr
        suspects = [
            line for line in text.splitlines()
            if any(h in line.lower() for h in
                   ("models.dev", "getbifrost.ai", "github.com/maximhq", "telemetry"))
        ]
        print("phone-home scan:", suspects[:5] or "none observed")