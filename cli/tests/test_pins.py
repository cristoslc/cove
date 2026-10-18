"""Tests for the pinned-artifact inventory (cove.pins) and `cove --sbom`."""

import json
from pathlib import Path

import yaml
from cove.pins import Pin, _classifier, _component_name, _resolve_ref, all_pins

REPO_ROOT = Path(__file__).resolve().parents[2]


def _compose_dir() -> Path:
    """Use the real repo compose dir when present; else a synthetic fixture."""
    if (REPO_ROOT / "compose" / "docker-compose.yml").exists():
        return REPO_ROOT / "compose"
    return _write_synthetic()


def _write_synthetic() -> Path:
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="pins-test-"))
    (tmp / "inventory.yml").write_text("compose: {}\n")
    (tmp / "docker-compose.yml").write_text(
        yaml.safe_dump(
            {
                "services": {
                    "dnsproxy": {
                        "image": "adguard/dnsproxy:v0.86.0@sha256:abc",
                        "command": ["--https-port=8053"],
                    },
                    "web": {"image": "nginx:1.27-alpine"},
                    "floater": {"image": "ghcr.io/org/floater:latest@sha256:xyz"},
                    "built-svc": {
                        "build": {
                            "context": "./svc",
                            "dockerfile": "Dockerfile",
                            "args": {"APP_VERSION": "${APP_VERSION:-1.2.3}"},
                        },
                        "image": "cove-built-svc:1.2.3",
                    },
                }
            }
        )
    )
    svc_dir = tmp / "svc"
    svc_dir.mkdir()
    (svc_dir / "Dockerfile").write_text("FROM node:24-bookworm-slim\nRUN echo hi\n")
    return tmp


def _as_dict(pins: list[Pin]) -> dict[tuple[str, str], Pin]:
    return {(p.name, p.kind): p for p in pins}


def test_resolve_ref_env_default():
    assert _resolve_ref("${ADE_IMAGE:-cove-ade:0.44.0}") == "cove-ade:0.44.0"
    assert _resolve_ref("nginx:1.27-alpine") == "nginx:1.27-alpine"


def test_classifier_kinds():
    assert _classifier("adguard/dnsproxy:v0.86.0@sha256:abc") == "tag+digest"
    assert _classifier("ghcr.io/org/floater:latest@sha256:xyz") == "digest"
    assert _classifier("hashicorp/vault:1.20@sha256:268") == "tag+digest"
    assert _classifier("nginx:1.27-alpine") == "tag"
    assert _classifier("postgres:16-alpine") == "tag"
    assert _classifier("codeberg.org/forgejo/forgejo:15") == "tag"


def test_component_name():
    assert _component_name("data.forgejo.org/forgejo/runner:11") == "runner"
    assert _component_name("nginx:1.27-alpine") == "nginx"
    assert _component_name("ghcr.io/stacklok/toolhive:v0.51.4@sha256:abc") == "toolhive"


def test_inventory_parses_real_compose():
    pins = _as_dict(all_pins(REPO_ROOT / "compose"))
    assert pins[("dnsproxy", "image")].classified == "tag+digest"
    assert pins[("dnsproxy", "image")].ref.startswith("adguard/dnsproxy:v0.86.0@")
    assert pins[("vault", "image")].classified == "tag+digest"
    # group_vars is authoritative: digest comes from there, location reflects it
    assert pins[("vault", "image")].location == "group_vars/all.yml"
    assert pins[("forgejo", "image")].location == "group_vars/all.yml"
    assert pins[("litellm", "image")].classified == "built"
    assert pins[("ade", "image")].classified == "built"
    assert pins[("ade.BB_APP_VERSION", "dependency")].ref == "0.44.0"
    assert any(p.name == "alpine" and p.kind == "base" for p in pins.values())
    assert any(p.name == "python" and p.kind == "base" for p in pins.values())
    assert any(p.name == "node" and p.kind == "base" for p in pins.values())
    # no latest without digest survives
    for p in pins.values():
        if p.classified == "digest":
            assert ":latest@" in p.ref


def test_pins_module_json_output():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "cove.pins", str(REPO_ROOT / "compose")],
        capture_output=True,
        text=True,
        cwd=cli_dir(),
        check=False,  # returncode asserted below
    )
    assert result.returncode == 0, result.stderr
    inventory = json.loads(result.stdout)
    assert any(p["name"] == "dnsproxy" and p["classified"] == "tag+digest" for p in inventory)


def cli_dir() -> str:
    return str(Path(__file__).resolve().parents[1])


def test_sbom_about_flag_prints_matrix():
    from click.testing import CliRunner

    from cove.cli import app

    fixture = _write_synthetic()
    result = CliRunner(env={"COVE_COMPOSE_DIR": str(fixture)}).invoke(app, ["--sbom"])
    assert result.exit_code == 0, result.output
    assert "dnsproxy" in result.output
    assert "v0.86.0@sha256:abc" in result.output
    assert "scripts/sbom.sh" in result.output


def test_sbom_about_flag_is_about_only():
    """The flag must never mutate: no sbom/ directory is created or written."""
    from click.testing import CliRunner

    from cove.cli import app

    fixture = _write_synthetic()
    result = CliRunner(env={"COVE_COMPOSE_DIR": str(fixture)}).invoke(app, ["--sbom"])
    assert result.exit_code == 0, result.output
    assert not (Path.cwd() / "sbom").exists()
    assert not (fixture / "sbom").exists()