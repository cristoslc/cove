"""Unit tests for cove.resolver — the macOS /etc/resolver port drift check.

No real sudo and no real /etc/resolver: every test points the module at a
temporary resolver directory and a temporary compose source, so the drift
decision is exercised in isolation from the host.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cove import resolver


def _compose_with_port(tmp_path: Path, port: str = "5354") -> Path:
    compose = tmp_path / "compose"
    (compose / "group_vars").mkdir(parents=True)
    (compose / "group_vars" / "all.yml").write_text(
        f"---\nfoo: 1\ndnsmasq_port: {port}\n"
    )
    return compose


class TestExpectedDnsmasqPort:
    def test_reads_the_group_var(self, tmp_path):
        compose = _compose_with_port(tmp_path, "5354")
        assert resolver.expected_dnsmasq_port(compose) == 5354

    def test_fails_loud_when_var_missing(self, tmp_path):
        compose = tmp_path / "compose"
        (compose / "group_vars").mkdir(parents=True)
        (compose / "group_vars" / "all.yml").write_text("foo: 1\n")
        with pytest.raises(RuntimeError, match="dnsmasq_port"):
            resolver.expected_dnsmasq_port(compose)

    def test_fails_loud_when_var_malformed(self, tmp_path):
        compose = _compose_with_port(tmp_path, "not-a-port")
        with pytest.raises(RuntimeError, match="dnsmasq_port"):
            resolver.expected_dnsmasq_port(compose)


class TestDriftedResolverFiles:
    def test_mismatch_is_reported_with_its_current_port(self, tmp_path):
        rdir = tmp_path / "resolver"
        rdir.mkdir()
        (rdir / "cove").write_text("nameserver 127.0.0.1\nport 5353\n")
        assert resolver.drifted_resolver_files(5354, resolver_dir=rdir) == {
            rdir / "cove": 5353
        }

    def test_matching_port_is_not_drift(self, tmp_path):
        """The expected resolver content derives from dnsmasq_port: a file
        carrying that exact port has no drift."""
        rdir = tmp_path / "resolver"
        rdir.mkdir()
        (rdir / "cove").write_text("nameserver 127.0.0.1\nport 5354\n")
        assert resolver.drifted_resolver_files(5354, resolver_dir=rdir) == {}

    def test_expected_content_derives_from_dnsmasq_port(self, tmp_path):
        """The same body is drift for one expected port and clean for another,
        proving the decision is the expected port (dnsmasq_port), not the
        file's own value."""
        rdir = tmp_path / "resolver"
        rdir.mkdir()
        body = "nameserver 127.0.0.1\nport 5354\n"
        (rdir / "cove.MBPBK-202602").write_text(body)
        assert resolver.drifted_resolver_files(5354, resolver_dir=rdir) == {}
        assert resolver.drifted_resolver_files(9999, resolver_dir=rdir) == {
            rdir / "cove.MBPBK-202602": 5354
        }

    def test_file_without_port_line_is_ignored(self, tmp_path):
        rdir = tmp_path / "resolver"
        rdir.mkdir()
        (rdir / "cove-notours").write_text("nameserver 1.1.1.1\n")
        assert resolver.drifted_resolver_files(5354, resolver_dir=rdir) == {}

    def test_non_cove_files_are_ignored(self, tmp_path):
        rdir = tmp_path / "resolver"
        rdir.mkdir()
        (rdir / "example.com").write_text("nameserver 1.1.1.1\nport 5353\n")
        assert resolver.drifted_resolver_files(5354, resolver_dir=rdir) == {}

    def test_absent_resolver_dir_is_no_drift(self, tmp_path):
        assert resolver.drifted_resolver_files(
            5354, resolver_dir=tmp_path / "nope"
        ) == {}


class TestResolverDrift:
    def test_none_when_files_already_track_the_port(self, tmp_path):
        compose = _compose_with_port(tmp_path, "5354")
        rdir = tmp_path / "resolver"
        rdir.mkdir()
        (rdir / "cove").write_text("nameserver 127.0.0.1\nport 5354\n")
        assert resolver.resolver_drift(compose, resolver_dir=rdir) is None

    def test_returns_expected_port_and_drifted_files(self, tmp_path):
        compose = _compose_with_port(tmp_path, "5354")
        rdir = tmp_path / "resolver"
        rdir.mkdir()
        (rdir / "cove").write_text("nameserver 127.0.0.1\nport 5353\n")
        expected, drifted = resolver.resolver_drift(compose, resolver_dir=rdir)
        assert expected == 5354
        assert drifted == {rdir / "cove": 5353}


class TestCorrectiveCommand:
    def test_names_the_expected_port_and_the_cove_glob(self):
        cmd = resolver.corrective_command(5354)
        assert "port 5354" in cmd
        assert "/etc/resolver/cove*" in cmd
