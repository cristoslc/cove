"""Tests for resource resolution and extraction."""

import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import click
import pytest

from cove import __version__
from cove.stateless import resolve_compose_dir, extract_resources, ensure_init


class TestResolveComposeDir:
    def test_resolves_via_env_var(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        monkeypatch.setenv("COVE_COMPOSE_DIR", str(compose_sub))
        monkeypatch.delenv("USER", raising=False)
        with patch.object(Path, "cwd", return_value=tmp_path):
            result = resolve_compose_dir()
            assert result == compose_sub

    def test_resolves_from_cwd(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        monkeypatch.delenv("COVE_COMPOSE_DIR", raising=False)
        with patch.object(Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 1
            result = resolve_compose_dir()
            assert result == compose_sub

    def test_resolves_via_git_root(self, tmp_path, monkeypatch):
        compose_sub = tmp_path / "compose"
        compose_sub.mkdir()
        (compose_sub / "inventory.yml").write_text("---\n")
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        monkeypatch.delenv("COVE_COMPOSE_DIR", raising=False)
        with patch.object(Path, "cwd", return_value=nested), patch(
            "subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = str(tmp_path) + "\n"
            result = resolve_compose_dir()
            assert result == compose_sub

    def test_raises_when_not_found(self, tmp_path, monkeypatch):
        monkeypatch.delenv("COVE_COMPOSE_DIR", raising=False)
        with patch.object(Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch(
            "cove.stateless.Path.home", return_value=tmp_path
        ):
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "not a git repo"
            with pytest.raises(click.ClickException, match="Run `cove init` first"):
                resolve_compose_dir()

    def test_handles_worktree_path(self, tmp_path, monkeypatch):
        wt = tmp_path / ".worktrees" / str(tmp_path.name)
        compose_sub = wt / "compose"
        compose_sub.mkdir(parents=True)
        (compose_sub / "inventory.yml").write_text("---\n")
        monkeypatch.delenv("COVE_COMPOSE_DIR", raising=False)
        with patch.object(Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run:
            mock_run.return_value.returncode = 1
            result = resolve_compose_dir()
            assert result == compose_sub

    def test_falls_back_to_installed_mode(self, tmp_path, monkeypatch):
        installed = tmp_path / "compose"
        installed.mkdir()
        (installed / "inventory.yml").write_text("---\n")
        monkeypatch.delenv("COVE_COMPOSE_DIR", raising=False)
        with patch.object(Path, "cwd", return_value=tmp_path), patch(
            "subprocess.run"
        ) as mock_run, patch(
            "cove.stateless.Path.home", return_value=tmp_path
        ):
            mock_run.return_value.returncode = 1
            result = resolve_compose_dir()
            assert result == installed


class TestExtractResources:
    def test_extracts_to_config_dir(self, tmp_path, monkeypatch):
        home = tmp_path
        target = home / ".config" / "cove" / "compose"
        with patch("cove.stateless.Path.home", return_value=home), patch(
            "cove.stateless._bundled_compose_root"
        ) as mock_root_fn:
            mock_root = MagicMock()
            mock_root.is_dir.return_value = True
            mock_root.iterdir.return_value = []
            mock_root_fn.return_value = mock_root
            result = extract_resources()
            assert result == target
            assert target.exists()
            assert (target / ".version").read_text() == __version__

    def test_idempotent_same_version(self, tmp_path, monkeypatch):
        home = tmp_path
        target = home / ".config" / "cove" / "compose"
        target.mkdir(parents=True)
        (target / ".version").write_text(__version__)
        (target / "inventory.yml").write_text("---\n")
        with patch("cove.stateless.Path.home", return_value=home), patch(
            "cove.stateless._bundled_compose_root"
        ) as mock_root_fn, patch(
            "cove.stateless.shutil.rmtree"
        ) as mock_rmtree:
            mock_root = MagicMock()
            mock_root.is_dir.return_value = True
            mock_root_fn.return_value = mock_root
            result = extract_resources()
            assert result == target
            mock_rmtree.assert_not_called()

    def test_force_re_extracts(self, tmp_path, monkeypatch):
        home = tmp_path
        target = home / ".config" / "cove" / "compose"
        target.mkdir(parents=True)
        (target / ".version").write_text("0.0.1")
        (target / "inventory.yml").write_text("---\n")
        with patch("cove.stateless.Path.home", return_value=home), patch(
            "cove.stateless._bundled_compose_root"
        ) as mock_root_fn, patch(
            "cove.stateless.shutil.rmtree", side_effect=shutil.rmtree
        ) as mock_rmtree:
            mock_root = MagicMock()
            mock_root.is_dir.return_value = True
            mock_root.iterdir.return_value = []
            mock_root_fn.return_value = mock_root
            result = extract_resources(force=True)
            assert result == target
            mock_rmtree.assert_called_once_with(target)
            assert (target / ".version").read_text() == __version__

    def test_raises_when_bundled_missing(self, tmp_path, monkeypatch):
        home = tmp_path
        with patch("cove.stateless.Path.home", return_value=home), patch(
            "cove.stateless._bundled_compose_root"
        ) as mock_root_fn:
            mock_root = MagicMock()
            mock_root.is_dir.return_value = False
            mock_root_fn.return_value = mock_root
            with pytest.raises(click.ClickException, match="Bundled compose resources"):
                extract_resources()


class TestEnsureInit:
    def test_ensures_init_extracts_if_missing(self, tmp_path, monkeypatch):
        home = tmp_path
        target = home / ".config" / "cove" / "compose"
        with patch("cove.stateless.Path.home", return_value=home), patch(
            "cove.stateless._bundled_compose_root"
        ) as mock_root_fn:
            mock_root = MagicMock()
            mock_root.is_dir.return_value = True
            mock_root.iterdir.return_value = []
            mock_root_fn.return_value = mock_root
            result = ensure_init()
            assert result == target
            assert (target / ".version").read_text() == __version__

    def test_ensures_init_noop_if_present(self, tmp_path, monkeypatch):
        home = tmp_path
        target = home / ".config" / "cove" / "compose"
        target.mkdir(parents=True)
        (target / ".version").write_text(__version__)
        (target / "inventory.yml").write_text("---\n")
        with patch("cove.stateless.Path.home", return_value=home), patch(
            "cove.stateless._bundled_compose_root"
        ) as mock_root_fn, patch(
            "cove.stateless.extract_resources"
        ) as mock_extract:
            mock_root_fn.return_value = MagicMock()
            result = ensure_init()
            assert result == target
            mock_extract.assert_not_called()