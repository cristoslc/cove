"""Tests for CLI commands and deployment correctness."""

import yaml
from pathlib import Path
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from cove.project import (
    _inject, _strip, _render_agents_block, _render_context,
    _write_detail_cove, _write_project_override,
    _remove_detail_cove, _remove_project_override,
    SENTINEL_START, SENTINEL_END,
)

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
from cove.stateless import resolve_compose_dir


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
        monkeypatch.delenv("COVE_COMPOSE_DIR", raising=False)

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 1
            result = resolve_compose_dir()
            assert result == compose_sub

    def test_finds_via_git_root(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        monkeypatch.delenv("COVE_COMPOSE_DIR", raising=False)

        with patch.object(cove.cli.Path, "cwd", return_value=nested), patch(
            "subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = str(tmp_path) + "\n"

            result = resolve_compose_dir()
            assert result == compose_sub

    def test_raises_when_not_found(self, tmp_path, monkeypatch):
        monkeypatch.delenv("COVE_COMPOSE_DIR", raising=False)
        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch(
            "cove.stateless.Path.home", return_value=tmp_path
        ):
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "not a git repo"

            with pytest.raises(Exception, match="Run `cove init` first"):
                resolve_compose_dir()

    def test_handles_worktree_path(self, tmp_path, monkeypatch):
        wt = tmp_path / ".worktrees" / str(tmp_path.name)
        compose_sub = wt / "compose"
        compose_sub.mkdir(parents=True)
        (compose_sub / "inventory.yml").write_text("---\n")
        monkeypatch.delenv("COVE_COMPOSE_DIR", raising=False)

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 1
            result = resolve_compose_dir()
            assert result == compose_sub


class TestCoveUpCommand:
    def test_up_passes_ask_become_pass(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch(
            "cove.cli.ensure_host_vars", return_value=tmp_path / "nonexistent.yml"
        ):
            mock_run.return_value.returncode = 0

            cove.cli.up.callback(no_provision=True, no_sudo=False, no_upgrade=True, log=False)

            args_list = [str(a) for a in mock_run.call_args[0][0]]
            assert "-K" in args_list, "cove up must pass -K to ansible-playbook"

    def test_no_sudo_omits_ask_pass(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch("click.prompt") as mock_prompt, patch(
            "cove.cli.ensure_host_vars", return_value=tmp_path / "nonexistent.yml"
        ):
            mock_run.return_value.returncode = 0

            cove.cli.up.callback(no_provision=True, no_sudo=True, no_upgrade=True, log=False)

            args_list = [str(a) for a in mock_run.call_args[0][0]]
            assert "ansible_become=no" in " ".join(args_list)
            mock_prompt.assert_not_called()

            args_list = [str(a) for a in mock_run.call_args[0][0]]
            assert "-K" not in args_list, "cove up --no-sudo must omit -K"

    def test_no_provision_skips_forgejo(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch("click.prompt", return_value="pw"), patch(
            "cove.cli.ensure_host_vars", return_value=tmp_path / "nonexistent.yml"
        ):
            mock_run.return_value.returncode = 0

            cove.cli.up.callback(no_provision=True, no_sudo=False, no_upgrade=True, log=False)
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
        ) as mock_run, patch("click.prompt", return_value="pw"), patch(
            "cove.cli.ensure_host_vars", return_value=tmp_path / "nonexistent.yml"
        ):
            mock_run.return_value.returncode = 0

            cove.cli.up.callback(no_provision=False, no_sudo=False, no_upgrade=True, log=False)
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


class TestCoveDownCommand:
    def test_down_runs_docker_compose(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 0

            cove.cli.down.callback(volumes=False)

            assert mock_run.call_count == 1
            args = [str(a) for a in mock_run.call_args[0][0]]
            assert args[0] == "docker"
            assert "down" in args

    def test_down_with_volumes(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 0

            cove.cli.down.callback(volumes=True)

            args = [str(a) for a in mock_run.call_args[0][0]]
            assert "--volumes" in args, "cove down --volumes must pass --volumes to docker compose"


class TestCoveUninstallCommand:
    def test_uninstall_default_prompts_and_only_strips_guidance(self, tmp_path, monkeypatch):
        """Default (no flags): prompts for confirmation, only strips guidance — does NOT touch containers."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        cache_dir = tmp_path / ".cache" / "cove"
        cache_dir.mkdir(parents=True)
        (cache_dir / "op-cache.json").write_text("{}")

        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "# My Project\n\n"
            "<!-- cove-guidance start -->\n"
            "## Cove\n\nsome guidance\n"
            "<!-- cove-guidance end -->\n"
        )

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "cove.cli.Path.home", return_value=tmp_path
        ), patch("subprocess.run") as mock_run, patch("shutil.rmtree") as mock_rmtree:
            mock_run.return_value.returncode = 0

            runner = CliRunner()
            result = runner.invoke(cove.cli.app, ["uninstall"], input="y\n")

            assert result.exit_code == 0
            assert "guidance" in result.output.lower()
            compose_down_calls = [
                c for c in mock_run.call_args_list
                if "compose" in str(c[0][0][:3])
            ]
            assert len(compose_down_calls) == 0, (
                "default uninstall must not run docker compose down"
            )
            mock_rmtree.assert_not_called(), (
                "default uninstall must not remove cache dir"
            )

        remaining = agents_md.read_text()
        assert "cove-guidance" not in remaining
        assert "# My Project" in remaining

    def test_uninstall_default_aborts_on_no(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path):
            runner = CliRunner()
            result = runner.invoke(cove.cli.app, ["uninstall"], input="n\n")
            assert result.exit_code != 0, "uninstall without confirmation must abort"

    def test_uninstall_force_skips_prompt_strips_guidance(self, tmp_path, monkeypatch):
        """-f without --all: skips prompt, only strips guidance."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        cache_dir = tmp_path / ".cache" / "cove"
        cache_dir.mkdir(parents=True)
        (cache_dir / "op-cache.json").write_text("{}")

        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "# My Project\n\n"
            "<!-- cove-guidance start -->\n"
            "## Cove\n\nsome guidance\n"
            "<!-- cove-guidance end -->\n"
        )

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "cove.cli.Path.home", return_value=tmp_path
        ), patch("subprocess.run") as mock_run, patch("shutil.rmtree") as mock_rmtree:
            mock_run.return_value.returncode = 0

            runner = CliRunner()
            result = runner.invoke(cove.cli.app, ["uninstall", "-f"])

            assert result.exit_code == 0
            compose_down_calls = [
                c for c in mock_run.call_args_list
                if "compose" in str(c[0][0][:3])
            ]
            assert len(compose_down_calls) == 0, (
                "-f without --all must not run docker compose down"
            )
            mock_rmtree.assert_not_called()

        remaining = agents_md.read_text()
        assert "cove-guidance" not in remaining

    def test_uninstall_all_stops_containers_and_strips_guidance(self, tmp_path, monkeypatch):
        """--all -f: stops containers, removes credentials, strips guidance."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        cache_dir = tmp_path / ".cache" / "cove"
        cache_dir.mkdir(parents=True)
        (cache_dir / "op-cache.json").write_text("{}")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "cove.cli.Path.home", return_value=tmp_path
        ), patch("subprocess.run") as mock_run, patch("shutil.rmtree"):
            mock_run.return_value.returncode = 0

            cove.cli.uninstall.callback(all_=True, force=True, global_=False)

            compose_down_calls = [
                c for c in mock_run.call_args_list
                if "compose" in str(c[0][0][:3])
            ]
            assert len(compose_down_calls) >= 1, (
                "--all must run docker compose down"
            )

    def test_uninstall_all_prompts_without_force(self, tmp_path, monkeypatch):
        """--all without -f: prompts for confirmation."""
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")

        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "cove.cli.Path.home", return_value=tmp_path
        ), patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0

            runner = CliRunner()
            result = runner.invoke(cove.cli.app, ["uninstall", "--all"], input="n\n")

            assert result.exit_code != 0, "--all without -f must prompt and abort on no"
            compose_down_calls = [
                c for c in mock_run.call_args_list
                if "compose" in str(c[0][0][:3])
            ]
            assert len(compose_down_calls) == 0, (
                "--all aborted must not run docker compose down"
            )

    def test_uninstall_no_project_dir_exits_cleanly(self, tmp_path, monkeypatch):
        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path):
            runner = CliRunner()
            with patch("cove.cli.resolve_compose_dir", side_effect=click.ClickException("no project")):
                result = runner.invoke(cove.cli.app, ["uninstall", "-f"])
            assert result.exit_code != 0, "uninstall with no compose dir should fail"

    def test_uninstall_all_strips_cove_guidance_from_agents_md(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")

        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "# My Project\n\n"
            "<!-- cove-guidance start -->\n"
            "## Cove\n\nsome guidance\n"
            "<!-- cove-guidance end -->\n"
        )

        with patch("cove.cli.Path.home", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch("shutil.rmtree"), patch.object(cove.cli.Path, "cwd", return_value=tmp_path):
            mock_run.return_value.returncode = 0

            cove.cli.uninstall.callback(all_=True, force=True, global_=False)

            remaining = agents_md.read_text()
            assert "cove-guidance" not in remaining
            assert "# My Project" in remaining

    def test_uninstall_all_removes_agents_md_if_only_guidance(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")

        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "<!-- cove-guidance start -->\n"
            "## Cove\n\nsome guidance\n"
            "<!-- cove-guidance end -->\n"
        )

        with patch("cove.cli.Path.home", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch("shutil.rmtree"), patch.object(cove.cli.Path, "cwd", return_value=tmp_path):
            mock_run.return_value.returncode = 0

            cove.cli.uninstall.callback(all_=True, force=True, global_=False)

        assert not agents_md.exists(), "AGENTS.md with only guidance should be deleted"


class TestProjectUninstall:
    def test_strip_removes_guidance_block(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "# My Project\n\n"
            "<!-- cove-guidance start -->\n"
            "## Cove\n\nsome guidance\n"
            "<!-- cove-guidance end -->\n"
        )
        _strip(agents_md)
        remaining = agents_md.read_text()
        assert "cove-guidance" not in remaining
        assert "# My Project" in remaining

    def test_strip_deletes_file_if_only_guidance(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "<!-- cove-guidance start -->\n"
            "## Cove\n\nsome guidance\n"
            "<!-- cove-guidance end -->\n"
        )
        _strip(agents_md)
        assert not agents_md.exists()

    def test_strip_noop_if_no_guidance(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# Just project notes\n")
        _strip(agents_md)
        assert agents_md.read_text() == "# Just project notes\n"

    def test_strip_noop_if_file_missing(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        _strip(agents_md)
        assert not agents_md.exists()

    def test_inject_then_strip_roundtrip(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# My Project\n")
        rendered = "## Cove\n\nForgejo at localhost\n"
        _inject(agents_md, rendered)
        assert SENTINEL_START in agents_md.read_text()
        _strip(agents_md)
        assert agents_md.read_text().strip() == "# My Project"


class TestProgressiveDisclosure:
    def test_write_detail_cove_creates_file_with_content(self, tmp_path):
        detail = tmp_path / "agents-md-detail" / "cove.md"
        _write_detail_cove(detail, "## Cove\n\nForgejo info here")
        assert detail.exists()
        content = detail.read_text()
        assert "Forgejo info here" in content

    def test_write_detail_cove_no_trailing_blank_line(self, tmp_path):
        detail = tmp_path / "cove.md"
        _write_detail_cove(detail, "some content\n")
        assert detail.read_text() == "some content\n"

    def test_remove_detail_cove_deletes_existing_file(self, tmp_path):
        detail = tmp_path / "cove.md"
        detail.write_text("content")
        _remove_detail_cove(detail)
        assert not detail.exists()

    def test_remove_detail_cove_noop_when_missing(self, tmp_path):
        detail = tmp_path / "nonexistent.md"
        _remove_detail_cove(detail)
        assert not detail.exists()

    def test_fj_spoke_doc_includes_issue_commands_and_title_caveat(self, tmp_path):
        """Installed fj.md must document issue creation and warn about --title flag."""
        from importlib.resources import files
        from jinja2 import Environment, BaseLoader

        template_text = files("cove.templates").joinpath("fj-reference.md.j2").read_text()
        rendered = Environment(loader=BaseLoader()).from_string(template_text).render()

        assert "fj issue create" in rendered, (
            "fj-reference.md.j2 must document issue creation commands"
        )
        assert "--title" in rendered, (
            "fj-reference.md.j2 must warn that fj issue create has no --title flag"
        )
        assert "positional argument" in rendered.lower(), (
            "fj-reference.md.j2 must explain title is a positional argument"
        )

    def test_inject_agents_block_contains_cove_info(self, tmp_path):
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# Project\n")
        ctx = {
            "forgejo_root_url": "https://example.com:3000/",
            "vault_addr": "http://127.0.0.1:8200",
            "admin_username": "testuser",
            "forgejo_domain": "example.com",
            "forgejo_ssh_domain": "example.com",
            "forgejo_ssh_port": "2222",
        }
        block = _render_agents_block(ctx, ".agents/agents-md-detail/cove.md")
        _inject(agents_md, block)
        content = agents_md.read_text()
        assert SENTINEL_START in content
        assert "git.cove" in content
        assert "Forgejo" in content
        assert "agents-md-detail/cove.md" in content
        assert "Project override" in content
        assert "origin" in content
        assert "secondary remote" in content
        assert "fj" in content
        assert "gh" in content
        assert "gl" in content

    def test_uninstall_strips_guidance_block(self, tmp_path):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")

        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "# My Project\n\n"
            "<!-- cove-guidance start -->\n"
            "## Cove\n\n"
            "Full reference in `.agents/agents-md-detail/cove.md`.\n"
            "<!-- cove-guidance end -->\n"
        )
        detail = tmp_path / ".agents" / "agents-md-detail" / "cove.md"
        detail.parent.mkdir(parents=True)
        detail.write_text("full guidance content")
        override = tmp_path / ".agents" / "cove" / "agents-md" / "cove.md"
        override.parent.mkdir(parents=True)
        override.write_text("project-level override")

        with patch("cove.cli.Path.home", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch("shutil.rmtree"), patch.object(cove.cli.Path, "cwd", return_value=tmp_path):
            mock_run.return_value.returncode = 0

            cove.cli.uninstall.callback(all_=True, force=True, global_=False)

        remaining = agents_md.read_text()
        assert "cove-guidance" not in remaining
        assert "# My Project" in remaining
        assert not detail.exists(), "detail cove.md should be removed during uninstall"
        assert not override.exists(), "project override should be removed during uninstall"

    def test_full_roundtrip_progressive_disclosure(self, tmp_path):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")

        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# Existing Project\n")
        detail = tmp_path / ".agents" / "agents-md-detail" / "cove.md"
        override = tmp_path / ".agents" / "cove" / "agents-md" / "cove.md"

        with patch("cove.cli._container_env") as mock_env, patch.object(
            cove.cli.Path, "cwd", return_value=tmp_path
        ):
            mock_env.side_effect = [
                {"FORGEJO__server__ROOT_URL": "https://example.com:3000/",
                 "FORGEJO__server__DOMAIN": "example.com",
                 "FORGEJO__server__SSH_DOMAIN": "example.com",
                 "FORGEJO__server__SSH_PORT": "2222"},
                {"VAULT_ADDR": "http://127.0.0.1:8200"},
            ]

            runner = CliRunner()
            result = runner.invoke(cove.cli.app, ["install"])
            assert result.exit_code == 0

        assert detail.exists()
        detail_text = detail.read_text()
        assert "example.com" in detail_text

        assert override.exists()
        override_text = override.read_text()
        assert "example.com" in override_text
        assert "project-level override" in override_text
        assert "origin" in override_text
        assert "fj" in override_text

        agents_text = agents_md.read_text()
        assert "agents-md-detail/cove.md" in agents_text
        assert "Forgejo" in agents_text
        assert "Vault" in agents_text
        assert "Project override" in agents_text
        assert "# Existing Project" in agents_text


class TestNoUpgradeFlag:
    def test_no_upgrade_skips_reextract(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        (compose_sub / "bringup.yml").write_text("---\n")
        with patch.object(cove.cli.Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch(
            "cove.cli.ensure_host_vars", return_value=tmp_path / "nonexistent.yml"
        ), patch("cove.cli.maybe_reextract") as mock_reextract:
            mock_run.return_value.returncode = 0
            cove.cli.up.callback(
                no_provision=True, no_sudo=False, no_upgrade=True, log=False
            )
            mock_reextract.assert_not_called()


class TestInitPurge:
    def test_init_purge_removes_compose_dir(self, tmp_path, monkeypatch):
        compose_dir = tmp_path / ".config" / "cove" / "compose"
        compose_dir.mkdir(parents=True)
        (compose_dir / ".version").write_text("0.1.0")
        (compose_dir / "inventory.yml").write_text("---\n")
        with patch("cove.cli.Path.home", return_value=tmp_path):
            runner = CliRunner()
            result = runner.invoke(cove.cli.app, ["init", "--purge"])
            assert result.exit_code == 0
            assert not compose_dir.exists()

    def test_init_purge_when_absent(self, tmp_path, monkeypatch):
        with patch("cove.cli.Path.home", return_value=tmp_path):
            runner = CliRunner()
            result = runner.invoke(cove.cli.app, ["init", "--purge"])
            assert result.exit_code == 0
            assert "Nothing to remove" in result.output
