"""E2E and template-rendering tests for DNS infrastructure.

Template/rendering tests (always runnable):
  - Validate Jinja2 templates render with required variables
  - Check nginx config syntax, location blocks, Content-Types
  - Check DNS script templates exist and are non-empty
  - Verify compose has dnsproxy sidecar for DoH
  - Verify inverse-assertion: missing variables cause TemplateSyntaxError

Integration E2E tests (require live stack; SKIPPED unless
COVE_ALLOW_LIVE_TESTS=1, see live_tier_gate.py):
  - HTTP /config/* endpoints return correct Content-Types
  - DoH /dns-query POST and GET return DNS responses
  - Per-machine regex server blocks proxy correctly
  - Default server returns 444 for unknown paths
  - ca.cove redirects to git.cove/config/ca

Run all:    pytest cli/tests/test_e2e_dns.py
Run unit:   pytest cli/tests/test_e2e_dns.py -m "not e2e"
Run live:   COVE_ALLOW_LIVE_TESTS=1 pytest cli/tests/test_e2e_dns.py -m live
"""

import base64
import os
import re
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined, UndefinedError

WORKTREE = Path(__file__).resolve().parent.parent.parent
COMPOSE_DIR = WORKTREE / "compose"
NGINX_DIR = COMPOSE_DIR / "nginx"
DNSMASQ_DIR = COMPOSE_DIR / "dnsmasq"


def _group_var_dnsmasq_port() -> int:
    """Read dnsmasq_port from compose/group_vars/all.yml — the single source
    of truth for the published dnsmasq host port. Every derived surface
    (compose default, .env, forwarder templates, config page) must agree
    with this value; see TestDnsmasqPortConsistency."""
    text = (COMPOSE_DIR / "group_vars" / "all.yml").read_text()
    match = re.search(r"^dnsmasq_port:\s*(\d+)\s*$", text, re.MULTILINE)
    if not match:
        raise AssertionError(
            "compose/group_vars/all.yml must define `dnsmasq_port: <int>`"
        )
    return int(match.group(1))


DNSMASQ_PORT = _group_var_dnsmasq_port()

MINIMAL_TEMPLATE_VARS = {
    "ansible_hostname": "testhost",
    "ts_ip": "100.64.0.1",
    "ts_status": SimpleNamespace(rc=0),
    "dnsmasq_port": DNSMASQ_PORT,
}

FULL_TEMPLATE_VARS = {
    **MINIMAL_TEMPLATE_VARS,
    "ts_dns_name": "testhost.tailnet.ts.net",
    "ca_uuid": "00000000-0000-0000-0000-000000000001",
    "dns_uuid": "00000000-0000-0000-0000-000000000002",
    "profile_uuid": "00000000-0000-0000-0000-000000000003",
    "root_ca_b64": "dGVzdC1jYS1iNjQ=",
}


def _project_root() -> Path:
    start = Path(__file__).resolve().parent
    for _ in range(6):
        if (start / "compose" / "inventory.yml").exists():
            return start
        start = start.parent
    raise RuntimeError(f"Cannot find project root from {__file__}")


PROJECT_ROOT = _project_root()


class TestNginxConfigRendering:
    """Validate nginx Jinja2 templates render and produce valid config."""

    def _render(self, template_name: str, vars_: dict | None = None) -> str:
        env = Environment(loader=FileSystemLoader(str(NGINX_DIR)), undefined=StrictUndefined)
        tmpl = env.get_template(template_name)
        return tmpl.render(vars_ or FULL_TEMPLATE_VARS)

    def test_default_conf_renders_with_minimal_vars(self):
        rendered = self._render("default.conf.j2", MINIMAL_TEMPLATE_VARS)
        assert "server_name _" in rendered
        assert "listen 443 ssl default_server" in rendered

    def test_default_conf_renders_with_full_vars(self):
        rendered = self._render("default.conf.j2", FULL_TEMPLATE_VARS)
        assert "server_name _" in rendered
        assert "server_name testhost.tailnet.ts.net" in rendered

    def test_default_conf_contains_config_locations_include(self):
        rendered = self._render("default.conf.j2", MINIMAL_TEMPLATE_VARS)
        assert "include /etc/nginx/cove-config-locations.conf" in rendered

    def test_default_conf_contains_user_agent_map(self):
        rendered = self._render("default.conf.j2", MINIMAL_TEMPLATE_VARS)
        assert "map $http_user_agent $config_dns_type" in rendered
        assert "~*Macintosh" in rendered
        assert "~*Windows NT" in rendered
        assert "~*Android" in rendered
        assert "~*iPhone" in rendered
        assert "default" in rendered

    def test_default_conf_contains_per_machine_regex_blocks(self):
        rendered = self._render("default.conf.j2", MINIMAL_TEMPLATE_VARS)
        assert "~^git\\.cove\\.[a-zA-Z0-9-]+$" in rendered
        assert "~^git\\.cove\\.local\\.[a-zA-Z0-9-]+$" in rendered
        assert "~^cove\\.[a-zA-Z0-9-]+$" in rendered
        assert "~^cove\\.local\\.[a-zA-Z0-9-]+$" in rendered
        assert "~^vault\\.cove\\.[a-zA-Z0-9-]+$" in rendered
        assert "~^vault\\.cove\\.local\\.[a-zA-Z0-9-]+$" in rendered

    def test_default_conf_has_upstreams(self):
        rendered = self._render("default.conf.j2", MINIMAL_TEMPLATE_VARS)
        assert "upstream forgejo_backend" in rendered
        assert "server forgejo:3000" in rendered
        assert "upstream vault_backend" in rendered
        assert "server vault:8200" in rendered

    def test_default_conf_has_ca_redirect(self):
        rendered = self._render("default.conf.j2", MINIMAL_TEMPLATE_VARS)
        assert "server_name ca.cove" in rendered
        assert "ca.cove.local" in rendered
        assert "return 301 https://git.cove/config/ca" in rendered

    def test_default_conf_has_health_check(self):
        rendered = self._render("default.conf.j2", MINIMAL_TEMPLATE_VARS)
        assert "server_name hc.cove" in rendered
        assert "hc.cove.local" in rendered
        assert 'return 200 "cove ingress ok\\n"' in rendered

    def test_default_conf_has_pages_server(self):
        rendered = self._render("default.conf.j2", MINIMAL_TEMPLATE_VARS)
        assert "~^(?<owner>[a-zA-Z0-9-]+)\\.pages\\.cove$" in rendered
        assert "~^(?<owner>[a-zA-Z0-9-]+)\\.pages\\.cove\\.local$" in rendered

    def test_default_conf_has_pages_portal(self):
        rendered = self._render("default.conf.j2", MINIMAL_TEMPLATE_VARS)
        assert "server_name pages.cove pages.cove.local" in rendered
        assert "try_files /pages.html =404" in rendered
        assert "include /etc/nginx/cove-pages-locations.conf" in rendered

    def test_pages_locations_conf_has_autoindex_api(self):
        content = (NGINX_DIR / "cove-pages-locations.conf").read_text()
        assert "location = /api/owners/" in content
        assert "autoindex on" in content
        assert "autoindex_format json" in content
        assert "alias /data/pages/sites/" in content

    def test_pages_html_exists_and_lists_api(self):
        content = (NGINX_DIR / "pages.html").read_text()
        assert "Cove Pages" in content
        assert "/api/owners/" in content
        assert "pages.cove.local" in content

    def test_landing_page_has_pages_card(self):
        content = (NGINX_DIR / "landing.html").read_text()
        assert "pages.cove.local" in content
        assert "Pages" in content
        assert "dot-pages" in content

    def test_tailscale_block_conditional(self):
        rendered_minimal = self._render("default.conf.j2", MINIMAL_TEMPLATE_VARS)
        rendered_full = self._render("default.conf.j2", FULL_TEMPLATE_VARS)
        assert "ts_dns_name" not in rendered_minimal
        assert "testhost.tailnet.ts.net" in rendered_full

    def test_default_conf_no_jinja2_artifacts(self):
        rendered = self._render("default.conf.j2", FULL_TEMPLATE_VARS)
        assert "{{" not in rendered
        assert "{%" not in rendered
        assert "}}" not in rendered


class TestConfigLocationsRendering:
    """Validate the cove-config-locations.conf include file."""

    def _load(self) -> str:
        return (NGINX_DIR / "cove-config-locations.conf").read_text()

    def test_config_root_endpoint(self):
        content = self._load()
        assert "location = /config/" in content
        assert "try_files /config.html =404" in content
        assert "Content-Type text/html" in content

    def test_config_ca_endpoint(self):
        content = self._load()
        assert "location = /config/ca" in content
        assert "try_files /rootCA.pem =404" in content
        assert "Content-Type application/x-pem-file" in content
        assert 'filename="cove-root-ca.pem"' in content

    def test_config_dns_autodetect(self):
        content = self._load()
        assert "location = /config/dns" in content
        assert "try_files /$config_dns_type =404" in content
        assert "Content-Type text/x-shellscript" in content

    def test_config_dns_ios(self):
        content = self._load()
        assert "location = /config/dns/ios" in content
        assert "Content-Type application/x-apple-aspen-config" in content
        assert 'filename="cove.mobileconfig"' in content

    def test_config_dns_android(self):
        content = self._load()
        assert "location = /config/dns/android" in content
        assert "Content-Type text/plain" in content

    def test_config_dns_platform_regex(self):
        content = self._load()
        assert r"^/config/dns/(macos|linux|windows)$" in content
        assert "Content-Type text/x-shellscript" in content

    def test_dns_query_proxies_to_dnsproxy(self):
        content = self._load()
        assert "location = /dns-query" in content
        assert "proxy_pass https://dnsproxy:8053/dns-query" in content


class TestDNSScriptTemplates:
    """Validate DNS setup script templates exist and render."""

    PLATFORMS = ["macos", "linux", "windows", "ios", "android", "unknown"]

    def test_all_platform_templates_exist(self):
        for platform in self.PLATFORMS:
            path = NGINX_DIR / "config" / "dns" / f"{platform}.j2"
            assert path.exists(), f"Template missing: {platform}.j2"

    def test_all_platform_templates_render(self):
        env = Environment(loader=FileSystemLoader(str(NGINX_DIR / "config" / "dns")), undefined=StrictUndefined)
        for platform in self.PLATFORMS:
            tmpl = env.get_template(f"{platform}.j2")
            rendered = tmpl.render(**FULL_TEMPLATE_VARS)
            assert len(rendered) > 0, f"Empty render for {platform}.j2"
            assert "{{" not in rendered, f"Unrendered Jinja2 in {platform}.j2"

    def test_ios_template_is_mobileconfig(self):
        env = Environment(loader=FileSystemLoader(str(NGINX_DIR / "config" / "dns")))
        rendered = env.get_template("ios.j2").render(**FULL_TEMPLATE_VARS)
        assert "<!DOCTYPE plist" in rendered or "<plist" in rendered
        assert "PayloadContent" in rendered

    def test_android_template_is_text(self):
        env = Environment(loader=FileSystemLoader(str(NGINX_DIR / "config" / "dns")))
        rendered = env.get_template("android.j2").render(**FULL_TEMPLATE_VARS)
        assert len(rendered) > 0

    def test_macos_template_references_dnsmasq_port(self):
        env = Environment(loader=FileSystemLoader(str(NGINX_DIR / "config" / "dns")))
        rendered = env.get_template("macos.j2").render(**FULL_TEMPLATE_VARS)
        # The rendered resolver file's port must equal the group-var port
        # exactly — the published container port and /etc/resolver/cove
        # change together only when both derive from dnsmasq_port.
        assert f"port {DNSMASQ_PORT}" in rendered


class TestDnsmasqConfigRendering:
    """Validate dnsmasq Jinja2 config template."""

    def test_cove_conf_renders(self):
        env = Environment(loader=FileSystemLoader(str(DNSMASQ_DIR)))
        rendered = env.get_template("cove.conf.j2").render(**MINIMAL_TEMPLATE_VARS)
        assert "address=/cove/127.0.0.1" in rendered
        assert "address=/cove.local/127.0.0.1" in rendered
        assert "address=/cove.testhost/100.64.0.1" in rendered
        assert "address=/cove.local.testhost/100.64.0.1" in rendered
        assert "port=5353" in rendered

    def test_cove_conf_no_jinja2_artifacts(self):
        env = Environment(loader=FileSystemLoader(str(DNSMASQ_DIR)))
        rendered = env.get_template("cove.conf.j2").render(**FULL_TEMPLATE_VARS)
        assert "{{" not in rendered
        assert "{%" not in rendered


class TestConfigHtmlRendering:
    """Validate the config info page template."""

    def test_config_html_renders(self):
        env = Environment(loader=FileSystemLoader(str(NGINX_DIR)))
        rendered = env.get_template("config.html.j2").render(**FULL_TEMPLATE_VARS)
        assert "testhost" in rendered

    def test_config_html_has_endpoints(self):
        env = Environment(loader=FileSystemLoader(str(NGINX_DIR)))
        rendered = env.get_template("config.html.j2").render(**FULL_TEMPLATE_VARS)
        assert "/config/" in rendered
        assert "/config/ca" in rendered
        assert "/config/dns" in rendered

    def test_config_html_documents_node_ca_trust(self):
        env = Environment(loader=FileSystemLoader(str(NGINX_DIR)))
        rendered = env.get_template("config.html.j2").render(**FULL_TEMPLATE_VARS)
        assert "NODE_EXTRA_CA_CERTS" in rendered
        assert "rootCA.pem" in rendered
        assert "curl -kL -o cove-root-ca.pem https://ca.cove/config/ca" in rendered
        assert "add-trusted-cert" in rendered
        assert "update-ca-certificates" in rendered

    def test_config_html_no_jinja2_artifacts(self):
        env = Environment(loader=FileSystemLoader(str(NGINX_DIR)))
        rendered = env.get_template("config.html.j2").render(**FULL_TEMPLATE_VARS)
        assert "{{" not in rendered
        assert "{%" not in rendered


class TestDnsmasqDockerfile:
    """Validate the dnsmasq Dockerfile is clean (no custom Go build)."""

    def test_dockerfile_exists(self):
        assert (DNSMASQ_DIR / "Dockerfile").exists()

    def test_dockerfile_no_custom_build_stage(self):
        dockerfile = (DNSMASQ_DIR / "Dockerfile").read_text()
        assert "golang" not in dockerfile.lower()
        assert "doh-proxy" not in dockerfile.lower()
        assert "COPY --from=" not in dockerfile

    def test_dockerfile_is_simple_alpine(self):
        dockerfile = (DNSMASQ_DIR / "Dockerfile").read_text()
        assert "alpine" in dockerfile
        assert "dnsmasq" in dockerfile

    def test_no_custom_doh_proxy_source(self):
        assert not (DNSMASQ_DIR / "doh-proxy-src").exists(), \
            "doh-proxy-src/ directory should not exist — dnsproxy sidecar handles DoH"


class TestComposeConfig:
    """Validate docker-compose.yml has DNS infrastructure services."""

    def _load_compose(self) -> dict:
        with open(COMPOSE_DIR / "docker-compose.yml") as f:
            return yaml.safe_load(f)

    def test_dnsmasq_service_exists(self):
        data = self._load_compose()
        assert "dnsmasq" in data["services"]

    def test_dnsmasq_builds_from_local(self):
        data = self._load_compose()
        build = data["services"]["dnsmasq"].get("build", "")
        assert "dnsmasq" in str(build)

    def test_dnsmasq_host_port_default_follows_group_var(self):
        data = self._load_compose()
        ports = data["services"]["dnsmasq"]["ports"]
        port_str = str(ports[0])
        # Host side must keep the ${DNSMASQ_PORT:-<default>} parameterized
        # shape, with the default equal to the group var. The container side
        # stays 5353 (dnsmasq's internal listen port).
        match = re.search(r"\$\{DNSMASQ_PORT:-(\d+)\}:5353/udp", port_str)
        assert match, (
            "dnsmasq publish must be 0.0.0.0:${DNSMASQ_PORT:-<default>}:5353/udp, "
            f"got: {port_str}"
        )
        assert int(match.group(1)) == DNSMASQ_PORT, (
            f"compose default {match.group(1)} disagrees with group_vars "
            f"dnsmasq_port={DNSMASQ_PORT}"
        )

    def test_dnsmasq_publishes_udp(self):
        data = self._load_compose()
        ports = data["services"]["dnsmasq"]["ports"]
        # Accept ${DNSMASQ_PORT:-<default>} parameterization: assert on the
        # protocol suffix and container port, not the host port literal.
        udp_entries = [p for p in ports if str(p).endswith(":5353/udp")]
        assert udp_entries, (
            "dnsmasq must publish UDP alongside the TCP publish (DNS is "
            "UDP-first, so a TCP-only publish leaves the /etc/resolver/cove "
            f"path dead). Got: {ports}"
        )

    def test_dnsmasq_keeps_tcp_publish(self):
        data = self._load_compose()
        ports = data["services"]["dnsmasq"]["ports"]
        tcp_entries = [
            p for p in ports if str(p).endswith(":5353") and not str(p).endswith("/udp")
        ]
        assert tcp_entries, (
            "dnsmasq must keep the TCP publish alongside UDP for "
            f"large/truncated DNS responses. Got: {ports}"
        )

    def test_dnsproxy_service_exists(self):
        data = self._load_compose()
        assert "dnsproxy" in data["services"]

    def test_dnsproxy_uses_adguard_image(self):
        data = self._load_compose()
        image = data["services"]["dnsproxy"].get("image", "")
        assert "adguard/dnsproxy" in image

    def test_dnsproxy_upstream_points_to_dnsmasq(self):
        data = self._load_compose()
        cmd = data["services"]["dnsproxy"].get("command", [])
        upstream_args = [a for a in cmd if "upstream" in a]
        assert len(upstream_args) > 0
        assert "dnsmasq" in upstream_args[0]
        assert "5353" in upstream_args[0]

    def test_dnsproxy_has_https_port(self):
        data = self._load_compose()
        cmd = data["services"]["dnsproxy"].get("command", [])
        port_args = [a for a in cmd if "https-port" in a]
        assert len(port_args) > 0
        assert "8053" in port_args[0]

    def test_dnsproxy_mounts_certs(self):
        data = self._load_compose()
        volumes = data["services"]["dnsproxy"].get("volumes", [])
        volume_strs = [str(v) for v in volumes]
        assert any("cove.local.pem" in v for v in volume_strs)
        assert any("cove.local-key.pem" in v for v in volume_strs)

    def test_dnsproxy_depends_on_dnsmasq(self):
        data = self._load_compose()
        deps = data["services"]["dnsproxy"].get("depends_on", {})
        assert "dnsmasq" in deps

    def test_nginx_service_exists(self):
        data = self._load_compose()
        assert "nginx" in data["services"]

    def test_nginx_mounts_config_locations(self):
        data = self._load_compose()
        volumes = data["services"]["nginx"]["volumes"]
        volume_paths = [str(v) for v in volumes]
        assert any("cove-config-locations.conf" in v for v in volume_paths)

    def test_nginx_mounts_config_html(self):
        data = self._load_compose()
        volumes = data["services"]["nginx"]["volumes"]
        volume_paths = [str(v) for v in volumes]
        assert any("config.html" in v for v in volume_paths)

    def test_nginx_mounts_config_dns(self):
        data = self._load_compose()
        volumes = data["services"]["nginx"]["volumes"]
        volume_paths = [str(v) for v in volumes]
        assert any("config/dns" in v for v in volume_paths)

    def test_nginx_mounts_root_ca(self):
        data = self._load_compose()
        volumes = data["services"]["nginx"]["volumes"]
        volume_paths = [str(v) for v in volumes]
        assert any("rootCA.pem" in v for v in volume_paths)

    def test_nginx_mounts_pages_html(self):
        data = self._load_compose()
        volumes = data["services"]["nginx"]["volumes"]
        volume_paths = [str(v) for v in volumes]
        assert any("pages.html" in v for v in volume_paths)

    def test_nginx_mounts_pages_locations(self):
        data = self._load_compose()
        volumes = data["services"]["nginx"]["volumes"]
        volume_paths = [str(v) for v in volumes]
        assert any("cove-pages-locations.conf" in v for v in volume_paths)


class TestDnsmasqPortConsistency:
    """The published dnsmasq host port has ONE source of truth: the
    dnsmasq_port group var. The rendered /etc/resolver (or dnsmasq.d)
    forwarder files and the published container port MUST change together —
    that coupling only holds while every surface derives from the group
    var. These grep-based guards fail if any surface drifts back to a
    hardcoded literal or disagrees with the group var."""

    COMPOSE_FILE = COMPOSE_DIR / "docker-compose.yml"
    ENV_EXAMPLE = COMPOSE_DIR / ".env.example"
    BRINGUP = COMPOSE_DIR / "bringup.yml"
    FORWARDER_TEMPLATES = [
        NGINX_DIR / "config" / "dns" / "macos.j2",
        NGINX_DIR / "config" / "dns" / "linux.j2",
    ]
    CONFIG_HTML_TPL = NGINX_DIR / "config.html.j2"

    def test_group_var_defines_port(self):
        # _group_var_dnsmasq_port() raises (fail loud) when the var is
        # missing or malformed, so reaching here means it parsed.
        assert DNSMASQ_PORT > 0

    def test_compose_default_matches_group_var(self):
        text = self.COMPOSE_FILE.read_text()
        defaults = re.findall(r"\$\{DNSMASQ_PORT:-(\d+)\}", text)
        assert defaults, (
            "docker-compose.yml must parameterize the dnsmasq host port as "
            "${DNSMASQ_PORT:-<default>} on both the /udp and TCP publishes"
        )
        assert set(defaults) == {str(DNSMASQ_PORT)}, (
            f"compose default(s) {sorted(set(defaults))} disagree with "
            f"group_vars dnsmasq_port={DNSMASQ_PORT}"
        )

    def test_env_example_matches_group_var(self):
        text = self.ENV_EXAMPLE.read_text()
        match = re.search(r"^DNSMASQ_PORT=(\d+)$", text, re.MULTILINE)
        assert match, ".env.example must set DNSMASQ_PORT"
        assert int(match.group(1)) == DNSMASQ_PORT, (
            f".env.example DNSMASQ_PORT={match.group(1)} disagrees with "
            f"group_vars dnsmasq_port={DNSMASQ_PORT}"
        )

    def test_bringup_derives_env_and_probe_from_group_var(self):
        text = self.BRINGUP.read_text()
        assert "DNSMASQ_PORT={{ dnsmasq_port }}" in text, (
            "bringup.yml must render the .env DNSMASQ_PORT from the group var"
        )
        assert 'port: "{{ dnsmasq_port }}"' in text, (
            "bringup.yml wait_for probe must use the group var port"
        )

    def test_bringup_repoints_macos_resolver_files_to_group_var(self):
        """The macOS /etc/resolver/cove* files are installed out of band (the
        served macos.j2 script is never run by `cove up`), so moving the
        published port used to leave them stale and the resolver path silently
        dead. bringup must re-point every existing cove* file at the group-var
        port on each up: Darwin-only, idempotent (replace), become (the same
        privilege path as the /etc/hosts task), and non-fatal so a no-TTY run
        without passwordless sudo cannot hang or abort."""
        data = yaml.safe_load(self.BRINGUP.read_text())
        task = None
        find_task = None
        for play in data:
            for candidate in play.get("tasks", []):
                if "cove_resolver_files" in str(candidate.get("loop", "")):
                    task = candidate
                if candidate.get("register") == "cove_resolver_files":
                    find_task = candidate
        assert find_task is not None, (
            "bringup.yml must discover the existing macOS /etc/resolver files"
        )
        assert find_task.get("when") == 'ansible_system == "Darwin"', (
            "the /etc/resolver scan is macOS-only"
        )
        assert task is not None, (
            "bringup.yml must re-point /etc/resolver/cove* at dnsmasq_port"
        )
        assert task.get("become") is True, (
            "writing /etc/resolver needs root; follow the /etc/hosts become path"
        )
        assert task.get("failed_when") is False, (
            "a run without passwordless sudo must not abort `cove up`; the "
            "drift is reported by `cove status` instead"
        )
        when = task.get("when")
        when_text = " ".join(when) if isinstance(when, list) else str(when)
        assert "Darwin" in when_text, "the resolver re-point is macOS-only"
        replace_args = task.get("ansible.builtin.replace")
        assert replace_args, "the resolver re-point must use the replace module"
        assert replace_args["replace"] == "port {{ dnsmasq_port }}", (
            "the resolver port must derive from the dnsmasq_port group var"
        )
        assert replace_args["regexp"] == '^port\\s+\\d+\\s*$', (
            "the replace must target only the port line, leaving nameserver intact"
        )

    def test_forwarder_templates_derive_from_group_var(self):
        for tpl in self.FORWARDER_TEMPLATES:
            text = tpl.read_text()
            assert "{{ dnsmasq_port }}" in text, (
                f"{tpl.name} must derive the forwarder port from the group "
                "var — a hardcoded port here desynchronizes the rendered "
                "resolver file from the published container port"
            )

    def test_forwarder_templates_have_no_hardcoded_port(self):
        # Any `port <digits>` / `#<digits>` literal in these templates is
        # drift waiting to happen; the rendered resolver config and the
        # publish must both come from {{ dnsmasq_port }}.
        for tpl in [*self.FORWARDER_TEMPLATES, self.CONFIG_HTML_TPL]:
            text = tpl.read_text()
            literals = re.findall(r"(?:port |#)\d{4,5}\b", text)
            assert not literals, (
                f"{tpl.name} hardcodes port literal(s) {literals} — derive "
                "them from {{ dnsmasq_port }} instead"
            )


class TestInverseAssertions:
    """Failure-path tests: verify that invalid inputs produce errors."""

    def test_template_rendering_fails_without_hostname(self):
        env = Environment(loader=FileSystemLoader(str(NGINX_DIR)), undefined=StrictUndefined)
        tmpl = env.get_template("config.html.j2")
        with pytest.raises(UndefinedError):
            tmpl.render()

    def test_dnsmasq_config_fails_without_hostname(self):
        env = Environment(loader=FileSystemLoader(str(DNSMASQ_DIR)), undefined=StrictUndefined)
        tmpl = env.get_template("cove.conf.j2")
        with pytest.raises(UndefinedError):
            tmpl.render()

    def test_compose_missing_dnsmasq_raises(self):
        data = {
            "services": {
                "forgejo": {"image": "forgejo:15"},
                "nginx": {"image": "nginx:1.27-alpine"},
                "vault": {"image": "vault:1.20"},
            }
        }
        assert "dnsmasq" not in data["services"]

    def test_dnsproxy_missing_from_minimal_compose(self):
        data = {
            "services": {
                "forgejo": {"image": "forgejo:15"},
                "dnsmasq": {"build": "./dnsmasq"},
                "nginx": {"image": "nginx:1.27-alpine"},
            }
        }
        assert "dnsproxy" not in data["services"]


@pytest.mark.live
@pytest.mark.e2e
@pytest.mark.staging
class TestE2EDNSEndpoints:
    """Live-stack tests. Skipped unless COVE_ALLOW_LIVE_TESTS=1.

    These issue real HTTP/DoH requests to the live Cove ingress on
    127.0.0.1:443 and the live DNS resolver; they read live state and are
    gated by live_tier_gate.py.

    Run with: COVE_ALLOW_LIVE_TESTS=1 pytest -m live

    These tests require:
      - Docker/Colima running
      - Cove stack up (cove up or docker compose up)
      - Templates rendered via bringup.yml
    """

    COVE_HTTPS_PORT = int(os.environ.get("COVE_HTTPS_PORT", "443"))
    COVE_HTTP_PORT = int(os.environ.get("COVE_HTTP_PORT", "8080"))
    COVE_DNS_PORT = int(os.environ.get("COVE_DNS_PORT", "5354"))
    BASE_URL = os.environ.get("COVE_BASE_URL", "https://git.cove")
    VERIFY_SSL = os.environ.get("COVE_VERIFY_SSL", "false").lower() == "true"

    @pytest.fixture(autouse=True)
    def _check_stack(self):
        import requests
        try:
            r = requests.get(
                f"https://127.0.0.1:{self.COVE_HTTPS_PORT}/config/",
                headers={"Host": "git.cove"},
                verify=self.VERIFY_SSL,
                timeout=5,
            )
        except Exception:
            pytest.skip("Cove stack not running — start with 'cove up'")

    def _get(self, path: str, host: str = "git.cove", **kwargs):
        import requests
        url = f"https://127.0.0.1:{self.COVE_HTTPS_PORT}{path}"
        headers = kwargs.pop("headers", {})
        headers["Host"] = host
        return requests.get(
            url, headers=headers, verify=self.VERIFY_SSL, **kwargs
        )

    def test_config_root_returns_html(self):
        r = self._get("/config/")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("Content-Type", "")

    def test_config_ca_returns_pem(self):
        r = self._get("/config/ca")
        assert r.status_code == 200
        assert "x-pem-file" in r.headers.get("Content-Type", "")
        assert "BEGIN CERTIFICATE" in r.text

    def test_config_dns_autodetect_linux(self):
        r = self._get("/config/dns", headers={"User-Agent": "curl/7.0 (Linux)"})
        assert r.status_code == 200
        assert "text/x-shellscript" in r.headers.get("Content-Type", "")

    def test_config_dns_ios(self):
        r = self._get("/config/dns/ios")
        assert r.status_code == 200
        assert "apple-aspen-config" in r.headers.get("Content-Type", "")

    def test_config_dns_android(self):
        r = self._get("/config/dns/android")
        assert r.status_code == 200
        assert "text/plain" in r.headers.get("Content-Type", "")

    def test_config_dns_macos(self):
        r = self._get("/config/dns/macos")
        assert r.status_code == 200
        assert "text/x-shellscript" in r.headers.get("Content-Type", "")

    def test_ca_redirect(self):
        r = self._get("/", host="ca.cove", allow_redirects=False)
        assert r.status_code == 301
        assert "/config/ca" in r.headers.get("Location", "")

    def test_default_server_returns_landing_page(self):
        """The default server serves the Cove landing page for unknown hosts.
        This is safe because it's static HTML served by nginx — no backend
        proxying occurs."""
        r = self._get("/", host="unknown-host.cove")
        assert r.status_code == 200
        assert "Cove" in r.text
        assert "Forgejo" in r.text
        assert "Vault" in r.text

    def test_health_check(self):
        r = self._get("/", host="hc.cove")
        assert r.status_code == 200
        assert "cove ingress ok" in r.text

    @staticmethod
    def _build_dns_query(domain: str, qtype: int = 1) -> bytes:
        txid = b"\xaa\xbb"
        flags = b"\x01\x00"
        qdcount = b"\x00\x01"
        ancount = b"\x00\x00"
        nscount = b"\x00\x00"
        arcount = b"\x00\x00"
        header = txid + flags + qdcount + ancount + nscount + arcount
        qname = b""
        for label in domain.split("."):
            qname += struct.pack("B", len(label)) + label.encode("ascii")
        qname += b"\x00"
        question = qname + struct.pack("!HH", qtype, 1)
        return header + question

    def test_doh_post_query(self):
        import requests

        query = self._build_dns_query("git.cove")
        url = f"https://127.0.0.1:{self.COVE_HTTPS_PORT}/dns-query"
        r = requests.post(
            url,
            data=query,
            headers={
                "Host": "git.cove",
                "Content-Type": "application/dns-message",
            },
            verify=self.VERIFY_SSL,
            timeout=10,
        )
        assert r.status_code == 200
        assert "application/dns-message" in r.headers.get("Content-Type", "")

    def test_doh_get_query(self):
        import requests

        query = self._build_dns_query("git.cove")
        encoded = base64.urlsafe_b64encode(query).rstrip(b"=").decode("ascii")
        url = f"https://127.0.0.1:{self.COVE_HTTPS_PORT}/dns-query?dns={encoded}"
        r = requests.get(
            url,
            headers={"Host": "git.cove"},
            verify=self.VERIFY_SSL,
            timeout=10,
        )
        assert r.status_code == 200
        assert "application/dns-message" in r.headers.get("Content-Type", "")