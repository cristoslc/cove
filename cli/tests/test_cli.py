"""Tests for CLI commands and deployment correctness."""

import yaml
from pathlib import Path
from unittest.mock import patch

import pytest

def _project_root() -> Path:
    start = Path(__file__).resolve().parent
    for _ in range(6):
        if (start / "compose" / "inventory.yml").exists():
            return start
        start = start.parent
    raise RuntimeError(f"Cannot find project root from {__file__}")

PROJECT_ROOT = _project_root()
COMPOSE_DIR = PROJECT_ROOT / "compose"

import cove.cli


class TestDeploymentManifests:
    def test_docker_compose_has_signing_env_vars(self):
        dc = COMPOSE_DIR / "docker-compose.yml"
        assert dc.exists(), f"docker-compose.yml not found at {dc}"

        with open(dc) as f:
            data = yaml.safe_load(f)

        forgejo_env = data["services"]["forgejo"]["environment"]
        env_vars = {k: v for k, v in forgejo_env.items()}

        assert "FORGEJO__repository.signing__SIGNING_KEY" in env_vars
        assert env_vars["FORGEJO__repository.signing__SIGNING_KEY"] == "default"
        assert "FORGEJO__repository.signing__SIGNING_NAME" in env_vars
        assert "Forgejo" in env_vars["FORGEJO__repository.signing__SIGNING_NAME"]
        assert "FORGEJO__repository.signing__SIGNING_EMAIL" in env_vars
        assert "forgejo@" in env_vars["FORGEJO__repository.signing__SIGNING_EMAIL"]
        assert "FORGEJO__repository.signing__INITIAL_COMMIT" in env_vars
        assert env_vars["FORGEJO__repository.signing__INITIAL_COMMIT"] == "always"
        assert "FORGEJO__repository.signing__DEFAULT_TRUST_MODEL" in env_vars
        assert env_vars["FORGEJO__repository.signing__DEFAULT_TRUST_MODEL"] == "committer"

    def test_bringup_yml_has_wait_false(self):
        bp = COMPOSE_DIR / "bringup.yml"
        assert bp.exists(), f"bringup.yml not found at {bp}"

        with open(bp) as f:
            data = yaml.safe_load(f)

        tasks = data[0]["tasks"] if isinstance(data, list) else data.get("tasks", [])
        compose_tasks = [
            t for t in tasks
            if isinstance(t, dict) and t.get("name") == "Bring up pod via docker compose"
        ]
        assert compose_tasks, "Missing 'Bring up pod via docker compose' task"
        task = compose_tasks[0]
        module_params = task.get("community.docker.docker_compose_v2", {})
        assert not module_params.get("wait"), (
            "docker_compose_v2 wait should be false to avoid sealed-Vault failures"
        )

    def test_provision_forgejo_has_autodetect_manual_merge(self):
        pf = COMPOSE_DIR / "provision_forgejo.yml"
        assert pf.exists(), f"provision_forgejo.yml not found at {pf}"

        with open(pf) as f:
            data = yaml.safe_load(f)

        tasks = (data[0] if isinstance(data, list) else data).get("tasks", [])
        merge_task = [
            t for t in tasks
            if isinstance(t, dict)
            and t.get("name") == "Enable autodetect manual merge on repo"
        ]
        assert merge_task, (
            "Missing 'Enable autodetect manual merge on repo' task in provision_forgejo.yml"
        )
        task = merge_task[0]
        body = task.get("ansible.builtin.uri", {}).get("body", {})
        assert body.get("autodetect_manual_merge") is True, (
            "autodetect_manual_merge should be true in provision task"
        )

    def test_statefulset_template_has_signing_env_vars(self):
        sst = (
            PROJECT_ROOT / "roles" / "cove" / "templates" / "forgejo-statefulset.yml.j2"
        )
        assert sst.exists(), f"forgejo-statefulset.yml.j2 not found at {sst}"

        text = sst.read_text()
        assert "GITEA__repository.signing__SIGNING_KEY" in text
        assert "value: default" in text
        assert "GITEA__repository.signing__SIGNING_NAME" in text
        assert "value: Forgejo" in text
        assert "GITEA__repository.signing__SIGNING_EMAIL" in text
        assert "GITEA__repository.signing__INITIAL_COMMIT" in text
        assert "value: always" in text
        assert "GITEA__repository.signing__DEFAULT_TRUST_MODEL" in text
        assert "value: committer" in text

    def test_provision_forgejo_no_bare_op(self):
        """provision_forgejo.yml must not call bare 'op' directly — biometric prompt spam."""
        pf = COMPOSE_DIR / "provision_forgejo.yml"
        assert pf.exists(), f"provision_forgejo.yml not found at {pf}"

        with open(pf) as f:
            tasks = yaml.safe_load(f)[0]["tasks"]

        for task in tasks:
            if not isinstance(task, dict):
                continue
            name = task.get("name", "")
            uri_module = task.get("ansible.builtin.uri", {})
            cmd = task.get("ansible.builtin.command", {})
            argv = cmd.get("argv", []) if isinstance(cmd, dict) else []
            if isinstance(argv, list) and len(argv) > 0:
                argv_str = " ".join(str(a) for a in argv)
                has_bare_op = (
                    argv[0] == "op"
                    and "op run" not in argv_str
                )
                assert not has_bare_op, (
                    f"Task '{name}' calls bare 'op' — use 'cove creds batch-pull' + local cache instead"
                )


class TestFindComposeDir:
    def test_finds_compose_from_cwd(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path):
            result = cove.cli._find_compose_dir()
            assert result == compose_sub

    def test_finds_via_git_root(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)

        with patch.object(cove.cli.Path, "cwd", return_value=nested), patch(
            "subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = str(tmp_path) + "\n"

            result = cove.cli._find_compose_dir()
            assert result == compose_sub

    def test_raises_when_not_found(self, tmp_path, monkeypatch):
        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "not a git repo"

            with pytest.raises(Exception, match="Could not find"):
                cove.cli._find_compose_dir()

    def test_handles_worktree_path(self, tmp_path, monkeypatch):
        wt = tmp_path / ".worktrees" / str(tmp_path.name)
        compose_sub = wt / "compose"
        compose_sub.mkdir(parents=True)
        (compose_sub / "inventory.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path):
            result = cove.cli._find_compose_dir()
            assert result == compose_sub


class TestCoveUpCommand:
    def test_up_passes_ask_become_pass(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 0

            cove.cli.up.callback(no_provision=True, no_sudo=False)

            args_list = [str(a) for a in mock_run.call_args[0][0]]
            assert "-K" in args_list, "cove up must pass -K to ansible-playbook"

    def test_no_sudo_omits_ask_pass(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 0

            cove.cli.up.callback(no_provision=True, no_sudo=True)

            args_list = [str(a) for a in mock_run.call_args[0][0]]
            assert "-K" not in args_list, "cove up --no-sudo must omit -K"

    def test_no_provision_skips_forgejo(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 0

            cove.cli.up.callback(no_provision=True, no_sudo=False)
            assert mock_run.call_count == 1

    def test_full_up_calls_all_in_correct_order(self, tmp_path, monkeypatch):
        """Batch-pull must come first, then bringup, then vault bootstrap, then provision."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")
        (compose_sub / "bootstrap_vault.yml").write_text("---\n")
        (compose_sub / "provision_vault_user.yml").write_text("---\n")
        (compose_sub / "provision_forgejo.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 0

            cove.cli.up.callback(no_provision=False, no_sudo=False)
            assert mock_run.call_count == 5

            all_args = [mock_run.call_args_list[i][0][0] for i in range(5)]

            call_0_args = [str(a) for a in all_args[0]]
            assert any("batch-pull" in a for a in call_0_args), (
                "first call must be batch-pull"
            )

            call_1_args = [str(a) for a in all_args[1]]
            assert any("bringup.yml" in p for p in call_1_args), (
                "second call must be bringup.yml"
            )

            call_2_args = [str(a) for a in all_args[2]]
            assert any("bootstrap_vault.yml" in p for p in call_2_args), (
                "third call must be bootstrap_vault.yml"
            )

            call_3_args = [str(a) for a in all_args[3]]
            assert any("provision_vault_user.yml" in p for p in call_3_args), (
                "fourth call must be provision_vault_user.yml"
            )

            call_4_args = [str(a) for a in all_args[4]]
            assert any("provision_forgejo.yml" in p for p in call_4_args), (
                "fifth call must be provision_forgejo.yml"
            )
