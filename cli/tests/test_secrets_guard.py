"""Tests for the observe-only edge secrets check (compose/secrets-guard).

Runtime behaviour — the six positives, the six negatives, byte-identical
forwarding, the log having no secret material, one rule load per process — lives
in the Go suite:

    cd compose/secrets-guard && go test ./...

These tests pin the IaC and the single-source ruleset, which is the part Python
can check without a Go toolchain or a container:

* the two spike rules live in the repo's one `.gitleaks.toml`, not a second file;
* the wheel's bundled ruleset is generated from that file, byte for byte;
* the compose service is additive, profile-gated, loopback-only and cannot spawn
  a process per request;
* the CLI seeds the ruleset where the container mounts it and starts only the
  scanner's own profile.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_DIR = REPO_ROOT / "compose"
SERVICE_DIR = COMPOSE_DIR / "secrets-guard"
RULES = REPO_ROOT / ".gitleaks.toml"
DOCS = REPO_ROOT / "docs" / "services" / "secrets-guard.md"
WORKFLOW = REPO_ROOT / ".forgejo" / "workflows" / "secret-scan.yml"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

PROMOTED_RULES = {
    "forgejo-token-context": {
        "secretGroup": 1,
        "keywords": ["token", "bearer", "password", "secret", "api_key", "api-key"],
    },
    "openai-project-key": {"keywords": ["sk-"]},
}


def _sync_module():
    path = REPO_ROOT / "cli" / "scripts" / "sync_compose_resources.py"
    spec = importlib.util.spec_from_file_location("sync_compose_resources", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _compose() -> dict:
    return yaml.safe_load((COMPOSE_DIR / "docker-compose.yml").read_text())


def _gitleaks_rules() -> dict[str, dict]:
    parsed = tomllib.loads(RULES.read_text())
    return {rule["id"]: rule for rule in parsed.get("rules", [])}


def test_rules_are_promoted_into_the_shipped_ruleset():
    rules = _gitleaks_rules()
    for rule_id, expected in PROMOTED_RULES.items():
        assert rule_id in rules, f"{rule_id} is not in the shipped .gitleaks.toml"
        if "secretGroup" in expected:
            assert rules[rule_id]["secretGroup"] == expected["secretGroup"]
        assert rules[rule_id]["keywords"] == expected["keywords"]
        assert rules[rule_id]["regex"]


def test_the_spike_rules_file_is_gone_so_no_copy_can_drift():
    spike_toml = REPO_ROOT / "scripts" / "spikes" / "edge-secrets" / "spike.toml"
    assert not spike_toml.exists(), (
        "spike.toml still carries a second copy of the rules; the scanner and the "
        "commit hook must read the one .gitleaks.toml"
    )
    # The only other file allowed to carry the rules is the wheel's generated
    # copy, which test_bundled_ruleset_is_generated_from_the_one_source proves is
    # byte-identical to this file. Anything else is a hand-maintained fork.
    generated = _sync_module().RULES_DST
    if generated.exists():
        assert generated.read_bytes() == RULES.read_bytes()

    # Tracked files only: a build artifact under cli/build/ is another copy of
    # the generated one, not a hand-maintained fork, and it is checked above.
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT, capture_output=True, check=True
    ).stdout.split(b"\0")
    copies = [
        path
        for name in tracked
        if (path := REPO_ROOT / name.decode()).suffix == ".toml"
        and path.exists()
        and "forgejo-token-context" in path.read_text(errors="ignore")
    ]
    assert copies == [RULES], f"tracked files carrying the rules: {copies}"


def test_bundled_ruleset_is_generated_from_the_one_source(tmp_path):
    module = _sync_module()
    assert module.RULES_SRC == RULES
    assert module.RULES_DST == REPO_ROOT / "cli" / "cove" / "resources" / "compose" / "secrets-guard" / "gitleaks.toml"

    source = tmp_path / ".gitleaks.toml"
    source.write_bytes(RULES.read_bytes())
    destination = tmp_path / "bundled" / "secrets-guard" / "gitleaks.toml"
    module.sync_rules(source, destination)
    assert destination.read_bytes() == RULES.read_bytes()

    with pytest.raises(SystemExit):
        module.sync_rules(tmp_path / "missing.toml", destination)

    # A local `go build` leaves a binary beside the sources; it must never ship
    # in the wheel (it carries a machine-local path, and the PII gate rejects it).
    assert module._should_exclude(
        SERVICE_DIR / "secrets-guard", Path("secrets-guard") / "secrets-guard"
    )


def test_compose_service_is_additive_profile_gated_and_observe_only():
    services = _compose()["services"]
    assert "secrets-guard" in services
    service = services["secrets-guard"]

    # Additive wiring: its own profile, so neither `cove up` nor
    # `cove bifrost up` starts it, and no dependency on the gateway that would
    # drag it into another profile.
    assert service["profiles"] == ["secrets-guard"]
    assert "depends_on" not in service
    assert service["networks"] == ["default"]

    # Observe-only cannot alter a body, so the container has nothing to write.
    assert service["read_only"] is True
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert service["user"] == "65532:65532"

    # Loopback-only, like every other optional service.
    ports = service["ports"]
    assert len(ports) == 1 and ports[0].startswith("127.0.0.1:")

    env = service["environment"]
    assert env["SECRETS_GUARD_UPSTREAM"] == "http://bifrost:8080"
    assert env["SECRETS_GUARD_RULES"] == "/etc/secrets-guard/gitleaks.toml"
    assert env["SECRETS_GUARD_LOG"].startswith("${SECRETS_GUARD_LOG:-")
    assert env["SECRETS_GUARD_LOG"].endswith("}")

    # The ruleset is mounted read-only from the data root the CLI seeds.
    mounts = service["volumes"]
    assert mounts == [
        "${COVE_DATA_ROOT}/secrets-guard/gitleaks.toml:/etc/secrets-guard/gitleaks.toml:ro"
    ]

    # The healthcheck is the binary itself: distroless has no shell or wget.
    assert service["healthcheck"]["test"] == [
        "CMD",
        "/usr/local/bin/secrets-guard",
        "healthcheck",
    ]

    # No `command:` that could spawn a per-request scanner process.
    assert "command" not in service


def test_the_bifrost_service_definition_is_untouched():
    service = _compose()["services"]["bifrost"]
    assert (
        "maximhq/bifrost:v2.3.2@sha256:f5b18826349fe9e1c402c10d19f1cbb5567a3c800ad928580d07f72e69106ec7"
        in service["image"]
    )
    assert "secrets-guard" not in yaml.safe_dump(service)


def test_scanner_image_pins_both_stages_and_links_the_engine():
    dockerfile = (SERVICE_DIR / "Dockerfile").read_text()
    from_lines = [line for line in dockerfile.splitlines() if line.startswith("FROM ")]
    assert len(from_lines) == 2
    for line in from_lines:
        reference = line.split()[1]
        assert re.search(r"@sha256:[0-9a-f]{64}$", reference), f"unpinned base image: {line}"

    # No gitleaks binary: the rule engine is a Go library, so no process can be
    # spawned per request.
    assert "apk add gitleaks" not in dockerfile
    assert "gitleaks_" not in dockerfile
    assert "go mod download" in dockerfile

    # The ruleset is a runtime mount, not a build input: one image works with
    # any ruleset, and the operator can read the exact rules in force.
    copies = "\n".join(
        line for line in dockerfile.splitlines() if line.startswith("COPY")
    )
    assert "/out/secrets-guard /usr/local/bin/secrets-guard" in copies
    assert "gitleaks" not in copies, "the ruleset must not be baked into the image"


def test_engine_version_matches_the_commit_hook_gate():
    go_mod = (SERVICE_DIR / "go.mod").read_text()
    pinned = re.search(r"github.com/zricethezav/gitleaks/v8 v([0-9.]+)", go_mod)
    assert pinned, "go.mod does not pin the gitleaks module"
    workflow_version = re.search(r'GITLEAKS_VERSION: "([0-9.]+)"', WORKFLOW.read_text())
    assert workflow_version
    assert pinned.group(1) == workflow_version.group(1)


def test_go_component_never_spawns_a_process_and_has_tests():
    sources = sorted(SERVICE_DIR.glob("*.go"))
    assert sources
    for source in sources:
        text = source.read_text()
        assert '"os/exec"' not in text, f"{source.name} imports os/exec"
        assert "exec.Command" not in text, f"{source.name} spawns a process"

    tests = sorted(SERVICE_DIR.glob("*_test.go"))
    assert tests, "the Go component has no tests"
    readme = (SERVICE_DIR / "README.md").read_text()
    assert "go test ./..." in readme, "README does not say how to run the Go tests"


def test_cli_up_seeds_the_ruleset_and_starts_only_its_own_profile(tmp_path, monkeypatch):
    from cove import secrets_guard as module

    compose_dir = tmp_path / "compose"
    (compose_dir / "secrets-guard").mkdir(parents=True)
    (compose_dir / "inventory.yml").write_text("all:\n  hosts:\n    localhost:\n")
    (compose_dir / "secrets-guard" / "gitleaks.toml").write_bytes(RULES.read_bytes())
    data_root = tmp_path / "data"
    data_root.mkdir()

    monkeypatch.setenv("COVE_COMPOSE_DIR", str(compose_dir))
    monkeypatch.setenv("COVE_DATA_ROOT", str(data_root))
    monkeypatch.setenv("FORGEJO_DATA_ROOT", str(data_root))

    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = CliRunner().invoke(module.secrets_guard, ["up"])
    assert result.exit_code == 0, result.output

    seeded = data_root / "secrets-guard" / "gitleaks.toml"
    assert seeded.read_bytes() == RULES.read_bytes()
    assert seeded.stat().st_mode & 0o777 == 0o644

    assert len(calls) == 1
    compose_args = calls[0][0]
    assert compose_args[:2] == ["docker", "compose"]
    assert "--profile" in compose_args
    assert compose_args[compose_args.index("--profile") + 1] == "secrets-guard"
    assert "up" in compose_args and "-d" in compose_args and "--build" in compose_args
    assert calls[0][1]["check"] is True


def test_cli_up_fails_loud_without_the_generated_ruleset(tmp_path, monkeypatch):
    from cove import secrets_guard as module

    compose_dir = tmp_path / "compose"
    compose_dir.mkdir()
    (compose_dir / "inventory.yml").write_text("all:\n  hosts:\n    localhost:\n")
    monkeypatch.setenv("COVE_COMPOSE_DIR", str(compose_dir))
    monkeypatch.setenv("COVE_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("FORGEJO_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setattr(
        module.subprocess, "run", lambda *a, **k: pytest.fail("compose was invoked")
    )

    result = CliRunner().invoke(module.secrets_guard, ["up"])
    assert result.exit_code != 0
    assert "sync_compose_resources.py" in result.output


def test_docs_page_covers_sees_does_not_see_and_the_blocking_path():
    text = DOCS.read_text()
    for required in (
        "observe-only",
        "never sent",
        "blocking",
        "Bifrost plugin",
        "digest",
        "fingerprint",
    ):
        assert required.lower() in text.lower(), f"docs page never mentions {required!r}"


def test_changelog_mentions_the_check():
    # The check shipped in 0.15.19, so its entry moved out of "Unreleased".
    # What matters is that the notes call it observe-only, wherever it lives.
    text = CHANGELOG.read_text()
    entry = [line for line in text.splitlines() if "secrets check in front of Bifrost" in line]
    assert entry, "no changelog entry for the edge secrets check"
    assert "observe-only" in entry[0].lower()
