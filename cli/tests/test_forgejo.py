"""Tests for Forgejo webhook allowlist: compose env, bringup .env render,
group_vars default, and adversarial wildcard/empty-value attempts.

Implements issue #44 — Forgejo's upstream default webhook.ALLOWED_HOST_LIST
is `external`, which blocks webhook delivery to loopback/private targets.
Cove overrides it with an explicit, configurable allowlist defaulting to
`loopback` (declared in code per IaC bias).

Unit/config tests (always runnable):
  - Validate compose forgejo env has FORGEJO__webhook__ALLOWED_HOST_LIST
    with resolved default `loopback`
  - Validate bringup.yml .env render includes FORGEJO_WEBHOOK_ALLOWED_HOST_LIST
    with the group_vars default pipeline
  - Validate group_vars/all.yml defines forgejo_webhook_allowed_host_list

Adversarial tests:
  - The resolved compose default must NOT be `*` (wildcard allow-all)
  - The resolved compose default must NOT be empty

Run all:   pytest cli/tests/test_forgejo.py
Run unit:  pytest cli/tests/test_forgejo.py -m "not e2e and not staging"
"""

from pathlib import Path

import yaml

def _project_root() -> Path:
    start = Path(__file__).resolve().parent
    for _ in range(6):
        if (start / "compose" / "inventory.yml").exists():
            return start
        start = start.parent
    raise RuntimeError(f"Cannot find project root from {__file__}")

PROJECT_ROOT = _project_root()
COMPOSE_DIR = PROJECT_ROOT / "compose"


def _load_compose() -> dict:
    with open(COMPOSE_DIR / "docker-compose.yml") as f:
        return yaml.safe_load(f)


def _load_group_vars() -> dict:
    with open(COMPOSE_DIR / "group_vars" / "all.yml") as f:
        return yaml.safe_load(f)


def _compose_default(value: str) -> str:
    """Resolve a `${VAR:-default}` compose substitution to its default."""
    text = str(value).strip()
    if text.startswith("${") and ":-" in text:
        return text[text.index(":-") + 2 : text.rindex("}")]
    return text


class TestComposeWebhookAllowlist:
    """Validate the forgejo service declares webhook.ALLOWED_HOST_LIST."""

    def test_forgejo_service_exists(self):
        data = _load_compose()
        assert "forgejo" in data["services"], "forgejo service missing from compose"

    def test_forgejo_env_has_webhook_allowed_host_list(self):
        data = _load_compose()
        env = data["services"]["forgejo"].get("environment", {})
        assert "FORGEJO__webhook__ALLOWED_HOST_LIST" in env, (
            "forgejo environment must declare FORGEJO__webhook__ALLOWED_HOST_LIST"
        )

    def test_compose_default_is_loopback(self):
        data = _load_compose()
        env = data["services"]["forgejo"].get("environment", {})
        value = env["FORGEJO__webhook__ALLOWED_HOST_LIST"]
        assert _compose_default(value) == "loopback", (
            f"webhook allowlist default must be loopback, got: {value}"
        )

    def test_env_value_is_configurable_via_env_var(self):
        data = _load_compose()
        env = data["services"]["forgejo"].get("environment", {})
        value = str(env["FORGEJO__webhook__ALLOWED_HOST_LIST"])
        assert "FORGEJO_WEBHOOK_ALLOWED_HOST_LIST" in value, (
            "compose must read the allowlist from FORGEJO_WEBHOOK_ALLOWED_HOST_LIST"
        )


class TestBringupEnvRender:
    """Validate bringup.yml renders the allowlist into the compose .env."""

    def test_env_render_includes_webhook_allowlist(self):
        with open(COMPOSE_DIR / "bringup.yml") as f:
            content = f.read()
        assert "FORGEJO_WEBHOOK_ALLOWED_HOST_LIST=" in content, (
            "bringup.yml .env render must include FORGEJO_WEBHOOK_ALLOWED_HOST_LIST="
        )

    def test_env_render_uses_group_vars_default(self):
        with open(COMPOSE_DIR / "bringup.yml") as f:
            content = f.read()
        assert (
            "FORGEJO_WEBHOOK_ALLOWED_HOST_LIST={{ forgejo_webhook_allowed_host_list "
            "| default('loopback') }}"
        ) in content, (
            ".env render must pipe forgejo_webhook_allowed_host_list through "
            "default('loopback')"
        )


class TestGroupVars:
    """Validate group_vars/all.yml declares the allowlist default."""

    def test_group_vars_defines_webhook_allowlist(self):
        data = _load_group_vars()
        assert "forgejo_webhook_allowed_host_list" in data, (
            "group_vars/all.yml must define forgejo_webhook_allowed_host_list"
        )

    def test_group_vars_default_is_loopback(self):
        data = _load_group_vars()
        assert data["forgejo_webhook_allowed_host_list"] == "loopback", (
            f"forgejo_webhook_allowed_host_list must default to 'loopback', "
            f"got: {data['forgejo_webhook_allowed_host_list']!r}"
        )


class TestAdversarial:
    """The allowlist must never ship as wildcard `*` or empty."""

    def test_compose_default_is_not_wildcard(self):
        data = _load_compose()
        env = data["services"]["forgejo"].get("environment", {})
        value = str(env["FORGEJO__webhook__ALLOWED_HOST_LIST"])
        assert _compose_default(value) != "*", (
            "webhook allowlist default must not be wildcard '*' — "
            "that disables the SSRF guard entirely"
        )

    def test_compose_default_is_not_empty(self):
        data = _load_compose()
        env = data["services"]["forgejo"].get("environment", {})
        value = str(env["FORGEJO__webhook__ALLOWED_HOST_LIST"])
        default = _compose_default(value)
        assert default.strip() != "", (
            "webhook allowlist default must not be empty — Forgejo would fall "
            "back to its own (external) default and silently block delivery"
        )

    def test_group_vars_default_is_not_wildcard_or_empty(self):
        data = _load_group_vars()
        value = str(data["forgejo_webhook_allowed_host_list"]).strip()
        assert value not in ("*", ""), (
            f"group_vars default must not be '*' or empty, got: {value!r}"
        )