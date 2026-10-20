"""Tests for resource resolution and extraction."""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import click
import pytest

from cove import __version__
from cove.stateless import resolve_compose_dir, extract_resources, ensure_init, maybe_reextract, _bundled_content_hash, _copy_resource


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
        ) as mock_root_fn, patch(
            "cove.stateless._bundled_content_hash", return_value="abc"
        ):
            mock_root = MagicMock()
            mock_root.is_dir.return_value = True
            mock_root.iterdir.return_value = []
            mock_root_fn.return_value = mock_root
            result = extract_resources()
            assert result == target
            assert target.exists()
            assert (target / ".version").read_text() == "abc"

    def test_idempotent_same_version(self, tmp_path, monkeypatch):
        home = tmp_path
        target = home / ".config" / "cove" / "compose"
        target.mkdir(parents=True)
        (target / ".version").write_text("abc")
        (target / "inventory.yml").write_text("---\n")
        with patch("cove.stateless.Path.home", return_value=home), patch(
            "cove.stateless._bundled_compose_root"
        ) as mock_root_fn, patch(
            "cove.stateless.shutil.rmtree"
        ) as mock_rmtree, patch(
            "cove.stateless._bundled_content_hash", return_value="abc"
        ):
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
        ) as mock_rmtree, patch(
            "cove.stateless._bundled_content_hash", return_value="abc"
        ):
            mock_root = MagicMock()
            mock_root.is_dir.return_value = True
            mock_root.iterdir.return_value = []
            mock_root_fn.return_value = mock_root
            result = extract_resources(force=True)
            assert result == target
            mock_rmtree.assert_not_called()
            assert not (target / "inventory.yml").exists()
            assert (target / ".version").read_text() == "abc"

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
        ) as mock_root_fn, patch(
            "cove.stateless._bundled_content_hash", return_value="abc"
        ):
            mock_root = MagicMock()
            mock_root.is_dir.return_value = True
            mock_root.iterdir.return_value = []
            mock_root_fn.return_value = mock_root
            result = ensure_init()
            assert result == target
            assert (target / ".version").read_text() == "abc"

    def test_ensures_init_noop_if_present(self, tmp_path, monkeypatch):
        home = tmp_path
        target = home / ".config" / "cove" / "compose"
        target.mkdir(parents=True)
        (target / ".version").write_text("abc")
        (target / "inventory.yml").write_text("---\n")
        with patch("cove.stateless.Path.home", return_value=home), patch(
            "cove.stateless._bundled_compose_root"
        ) as mock_root_fn, patch(
            "cove.stateless.extract_resources"
        ) as mock_extract, patch(
            "cove.stateless._bundled_content_hash", return_value="abc"
        ):
            mock_root_fn.return_value = MagicMock()
            result = ensure_init()
            assert result == target
            mock_extract.assert_not_called()

class TestMaybeReextract:
    def test_no_reextract_when_version_matches(self, tmp_path, monkeypatch):
        target = tmp_path / ".config" / "cove" / "compose"
        target.mkdir(parents=True)
        (target / ".version").write_text("abc")
        with patch("cove.stateless.Path.home", return_value=tmp_path), patch(
            "cove.stateless.extract_resources"
        ) as mock_extract, patch(
            "cove.stateless._bundled_content_hash", return_value="abc"
        ):
            result = maybe_reextract()
            assert result is False
            mock_extract.assert_not_called()

    def test_reextract_on_version_mismatch(self, tmp_path, monkeypatch):
        target = tmp_path / ".config" / "cove" / "compose"
        target.mkdir(parents=True)
        (target / ".version").write_text("0.0.1")
        with patch("cove.stateless.Path.home", return_value=tmp_path), patch(
            "cove.stateless.extract_resources"
        ) as mock_extract, patch(
            "cove.stateless._bundled_content_hash", return_value="abc"
        ):
            result = maybe_reextract()
            assert result is True
            mock_extract.assert_called_once_with(force=True)

    def test_no_reextract_when_missing(self, tmp_path, monkeypatch):
        with patch("cove.stateless.Path.home", return_value=tmp_path), patch(
            "cove.stateless.extract_resources"
        ) as mock_extract:
            result = maybe_reextract()
            assert result is False
            mock_extract.assert_not_called()

    def test_reextract_preserves_host_vars(self, tmp_path, monkeypatch):
        home = tmp_path
        target = home / ".config" / "cove" / "compose"
        target.mkdir(parents=True)
        (target / ".version").write_text("0.0.1")
        (target / "inventory.yml").write_text("---\n")
        state_hosts = home / ".config" / "cove" / "state" / "hosts"
        state_hosts.mkdir(parents=True)
        (state_hosts / "testhost.yml").write_text("admin_username: testuser\n")
        with patch("cove.stateless.Path.home", return_value=home), patch(
            "cove.stateless._bundled_compose_root"
        ) as mock_root_fn:
            mock_root = MagicMock()
            mock_root.is_dir.return_value = True
            mock_root.iterdir.return_value = []
            mock_root_fn.return_value = mock_root
            result = maybe_reextract()
            assert result is True
            assert (state_hosts / "testhost.yml").read_text() == "admin_username: testuser\n"


class TestRuntimeResourcePreservation:
    def _bundle(self, tmp_path):
        bundle = tmp_path / "bundle"
        (bundle / "nginx").mkdir(parents=True)
        (bundle / "inventory.yml").write_text("hosts: fresh-bundle\n")
        (bundle / "docker-compose.yml").write_text("services: fresh-pins\n")
        (bundle / ".env").write_text("BUNDLED_ENV=must-not-replace-local\n")
        (bundle / ".version").write_text("stale-bundle-marker\n")
        (bundle / "nginx" / "default.conf").write_text("bundled config must not replace runtime\n")
        (bundle / "nginx" / "default.conf.j2").write_text("fresh nginx template\n")
        return bundle

    def _extract(self, home, bundle, *, force):
        with patch("cove.stateless.Path.home", return_value=home), patch(
            "cove.stateless._bundled_compose_root", return_value=bundle
        ):
            return extract_resources(force=force)

    @pytest.mark.parametrize("reextract", [False, True], ids=["force", "hash-change"])
    def test_preserves_only_runtime_files_and_refreshes_bundled_resources(
        self, tmp_path, reextract
    ):
        home = tmp_path / "home"
        target = home / ".config" / "cove" / "compose"
        (target / "nginx").mkdir(parents=True)
        (target / ".version").write_text("old-bundle-hash")
        (target / "docker-compose.yml").write_text("services: stale-pins\n")

        env_bytes = b"COVE_DATA_ROOT=/data/cove\nOPERATOR_VALUE=keep-this-byte-for-byte\n"
        env_path = target / ".env"
        env_path.write_bytes(env_bytes)
        env_path.chmod(0o600)

        nginx_bytes = b"server { # generated runtime config\n}\n"
        runtime_nginx = target / "nginx" / "default.conf"
        runtime_nginx.write_bytes(nginx_bytes)
        runtime_nginx.chmod(0o644)
        env_inode = env_path.stat().st_ino
        nginx_inode = runtime_nginx.stat().st_ino

        bundle = self._bundle(tmp_path)
        if reextract:
            self._extract(home, bundle, force=False)
        else:
            self._extract(home, bundle, force=True)

        assert env_path.read_bytes() == env_bytes
        assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
        assert runtime_nginx.read_bytes() == nginx_bytes
        assert stat.S_IMODE(runtime_nginx.stat().st_mode) == 0o644
        assert env_path.stat().st_ino == env_inode
        assert runtime_nginx.stat().st_ino == nginx_inode
        assert (target / "docker-compose.yml").read_text() == "services: fresh-pins\n"
        assert (target / "nginx" / "default.conf.j2").read_text() == "fresh nginx template\n"
        assert (target / ".version").read_text().strip() != "old-bundle-hash"


    def test_restricts_env_permissions_without_replacing_inode(self, tmp_path):
        home = tmp_path / "home"
        target = home / ".config" / "cove" / "compose"
        target.mkdir(parents=True)
        env_path = target / ".env"
        env_path.write_bytes(b"PRIVATE=value\n")
        env_path.chmod(0o644)
        inode = env_path.stat().st_ino

        self._extract(home, self._bundle(tmp_path), force=True)

        assert env_path.read_bytes() == b"PRIVATE=value\n"
        assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
        assert env_path.stat().st_ino == inode


    def test_preserves_runtime_files_when_bundled_copy_fails(self, tmp_path):
        home = tmp_path / "home"
        target = home / ".config" / "cove" / "compose"
        (target / "nginx").mkdir(parents=True)
        (target / ".version").write_text("old-bundle-hash")
        (target / "old-resource.txt").write_text("to be pruned")
        env_path = target / ".env"
        env_path.write_bytes(b"PRIVATE=value\n")
        env_path.chmod(0o600)
        nginx_path = target / "nginx" / "default.conf"
        nginx_path.write_bytes(b"generated runtime nginx\n")
        nginx_path.chmod(0o644)
        env_inode = env_path.stat().st_ino
        nginx_inode = nginx_path.stat().st_ino

        bundle = self._bundle(tmp_path)
        with patch("cove.stateless.Path.home", return_value=home), patch(
            "cove.stateless._bundled_compose_root", return_value=bundle
        ), patch(
            "cove.stateless._bundled_content_hash", return_value="new-bundle-hash"
        ):
            copy_count = [0]

            def copy_then_fail(*args, **kwargs):
                if copy_count[0]:
                    raise OSError("simulated copy failure")
                copy_count[0] += 1
                return _copy_resource(*args, **kwargs)

            with patch("cove.stateless._copy_resource", side_effect=copy_then_fail):
                with pytest.raises(OSError, match="simulated copy failure"):
                    extract_resources(force=True)

        assert env_path.read_bytes() == b"PRIVATE=value\n"
        assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
        assert env_path.stat().st_ino == env_inode
        assert nginx_path.read_bytes() == b"generated runtime nginx\n"
        assert nginx_path.stat().st_ino == nginx_inode
        assert not (target / ".version").exists()

    def test_force_copy_failure_invalidates_marker_and_ensure_init_repairs(self, tmp_path):
        home = tmp_path / "home"
        target = home / ".config" / "cove" / "compose"
        (target / "nginx").mkdir(parents=True)
        (target / ".version").write_text("current-bundle-hash")
        (target / "docker-compose.yml").write_text("services: old-pins\n")
        env_path = target / ".env"
        env_path.write_bytes(b"PRIVATE=value\n")
        env_path.chmod(0o600)
        nginx_path = target / "nginx" / "default.conf"
        nginx_path.write_bytes(b"generated runtime nginx\n")
        env_inode = env_path.stat().st_ino
        nginx_inode = nginx_path.stat().st_ino
        bundle = self._bundle(tmp_path)

        with patch("cove.stateless.Path.home", return_value=home), patch(
            "cove.stateless._bundled_compose_root", return_value=bundle
        ), patch("cove.stateless._bundled_content_hash", return_value="current-bundle-hash"):
            copy_count = [0]

            def copy_then_fail(*args, **kwargs):
                if copy_count[0]:
                    raise OSError("simulated forced-copy failure")
                copy_count[0] += 1
                return _copy_resource(*args, **kwargs)

            with patch("cove.stateless._copy_resource", side_effect=copy_then_fail):
                with pytest.raises(OSError, match="simulated forced-copy failure"):
                    extract_resources(force=True)

            assert not (target / ".version").exists()
            assert env_path.read_bytes() == b"PRIVATE=value\n"
            assert env_path.stat().st_ino == env_inode
            assert nginx_path.read_bytes() == b"generated runtime nginx\n"
            assert nginx_path.stat().st_ino == nginx_inode

            assert ensure_init() == target

        assert (target / ".version").read_text() == "current-bundle-hash"
        assert (target / "docker-compose.yml").read_text() == "services: fresh-pins\n"
        assert env_path.stat().st_ino == env_inode
        assert nginx_path.stat().st_ino == nginx_inode

    @pytest.mark.parametrize("relative_path", [".env", "nginx/default.conf"])
    def test_rejects_symlinked_runtime_files_before_removing_tree(self, tmp_path, relative_path):
        home = tmp_path / "home"
        target = home / ".config" / "cove" / "compose"
        (target / "nginx").mkdir(parents=True)
        (target / ".version").write_text("old-bundle-hash")
        (target / "docker-compose.yml").write_text("services: old-pins\n")

        outside = tmp_path / "outside-runtime-file"
        outside.write_bytes(b"external file must not be changed")
        symlink = target / relative_path
        symlink.symlink_to(outside)

        bundle = self._bundle(tmp_path)
        with pytest.raises(click.ClickException, match="regular file|symlink"):
            self._extract(home, bundle, force=True)

        assert symlink.is_symlink()
        assert outside.read_bytes() == b"external file must not be changed"
        assert (target / "docker-compose.yml").read_text() == "services: old-pins\n"
        assert (target / ".version").read_text() == "old-bundle-hash"

    def test_rejects_symlinked_runtime_parent_before_pruning(self, tmp_path):
        home = tmp_path / "home"
        target = home / ".config" / "cove" / "compose"
        target.mkdir(parents=True)
        (target / ".version").write_text("old-bundle-hash")
        (target / "docker-compose.yml").write_text("services: old-pins\n")
        outside_dir = tmp_path / "external-nginx"
        outside_dir.mkdir()
        external_config = outside_dir / "default.conf"
        external_config.write_bytes(b"external config\n")
        (target / "nginx").symlink_to(outside_dir, target_is_directory=True)

        with pytest.raises(click.ClickException, match="real directory"):
            self._extract(home, self._bundle(tmp_path), force=True)

        assert (target / "nginx").is_symlink()
        assert external_config.read_bytes() == b"external config\n"
        assert (target / "docker-compose.yml").read_text() == "services: old-pins\n"
        assert (target / ".version").read_text() == "old-bundle-hash"

    def test_rejects_symlinked_compose_parent_before_pruning(self, tmp_path):
        home = tmp_path / "home"
        external_config = tmp_path / "external-config"
        external_target = external_config / "cove" / "compose"
        external_target.mkdir(parents=True)
        (external_target / ".version").write_text("old-bundle-hash")
        (external_target / ".env").write_text("EXTERNAL=keep\n")
        (external_target / "docker-compose.yml").write_text("services: old-pins\n")
        home.mkdir()
        (home / ".config").symlink_to(external_config, target_is_directory=True)

        with pytest.raises(click.ClickException, match="real directory"):
            self._extract(home, self._bundle(tmp_path), force=True)

        assert (external_target / ".env").read_text() == "EXTERNAL=keep\n"
        assert (external_target / "docker-compose.yml").read_text() == "services: old-pins\n"
        assert (external_target / ".version").read_text() == "old-bundle-hash"

    def test_rejects_symlinked_version_marker_without_writing_target(self, tmp_path):
        home = tmp_path / "home"
        target = home / ".config" / "cove" / "compose"
        target.mkdir(parents=True)
        outside = tmp_path / "outside-version"
        outside.write_text("external marker\n")
        (target / ".version").symlink_to(outside)
        (target / ".env").write_text("PRIVATE=value\n")

        with pytest.raises(click.ClickException, match="regular file|symlink"):
            self._extract(home, self._bundle(tmp_path), force=True)

        assert outside.read_text() == "external marker\n"
        assert (target / ".version").is_symlink()
        assert (target / ".env").read_text() == "PRIVATE=value\n"

    @pytest.mark.parametrize("relative_path", [".env", ".version"])
    def test_rejects_fifo_without_blocking(self, tmp_path, relative_path):
        home = tmp_path / "home"
        target = home / ".config" / "cove" / "compose"
        target.mkdir(parents=True)
        if relative_path != ".version":
            (target / ".version").write_text("old-bundle-hash")
        os.mkfifo(target / relative_path)

        script = (
            "from cove.stateless import extract_resources; "
            "extract_resources(force=True)"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env={**os.environ, "HOME": str(home)},
            timeout=5,
        )
        assert result.returncode != 0
        assert "regular file" in result.stderr
        if relative_path == ".version":
            assert stat.S_ISFIFO((target / ".version").lstat().st_mode)
        else:
            assert (target / ".version").read_text() == "old-bundle-hash"


class TestBundledResourceFiles:
    """`bundled_resource_files` names the bundle files extraction rewrites.

    Extraction prunes then re-copies every non-preserved bundled file, giving
    each a fresh inode even when its bytes are unchanged, so a running
    container that bind-mounts any of them holds a stale, deleted inode and
    must be restarted. This listing is the set `cove up` intersects against
    running containers' bind sources."""

    def test_lists_only_bundle_files_that_extraction_rewrites(self, tmp_path):
        from cove.stateless import bundled_resource_files

        bundle = tmp_path / "bundle"
        (bundle / "nginx").mkdir(parents=True)
        (bundle / "docker-compose.yml").write_text("services: {}\n")
        (bundle / ".env").write_text("BUNDLED=1\n")
        (bundle / ".version").write_text("hash\n")
        (bundle / "nginx" / "default.conf").write_text("generated\n")
        (bundle / "nginx" / "landing.html").write_text("<html>\n")

        with patch("cove.stateless._bundled_compose_root", return_value=bundle):
            assert bundled_resource_files() == frozenset(
                {"docker-compose.yml", "nginx/landing.html"}
            )

    def test_empty_when_bundle_missing(self, tmp_path):
        from cove.stateless import bundled_resource_files

        with patch("cove.stateless._bundled_compose_root", return_value=tmp_path / "nope"):
            assert bundled_resource_files() == frozenset()
