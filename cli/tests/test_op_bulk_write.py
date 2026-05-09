"""Tests for op_bulk_write module."""

import string
from pathlib import Path

import pytest

from cove import op_bulk_write


class TestGeneratePassword:
    def test_generates_correct_length(self):
        pw = op_bulk_write._generate_password(32)
        assert len(pw) == 32

    def test_generates_correct_length_minimum(self):
        pw = op_bulk_write._generate_password(1)
        assert len(pw) == 1

    def test_uses_valid_characters(self):
        pw = op_bulk_write._generate_password(100)
        alphabet = set(string.ascii_letters + string.digits + "!@#$%^&*()-_=+[]{}")
        for ch in pw:
            assert ch in alphabet

    def test_different_calls_different(self):
        pw1 = op_bulk_write._generate_password(32)
        pw2 = op_bulk_write._generate_password(32)
        assert pw1 != pw2


class TestResolveFieldValue:
    def test_literal_value(self):
        val, secret = op_bulk_write._resolve_field_value("hello")
        assert val == "hello"
        assert not secret

    def test_generate_placeholder(self):
        val, secret = op_bulk_write._resolve_field_value("{{generate:16}}")
        assert len(val) == 16
        assert secret

    def test_generate_minimum_length(self):
        val, secret = op_bulk_write._resolve_field_value("{{generate:4}}")
        assert len(val) == 4
        assert secret

    def test_generate_too_short_raises(self):
        with pytest.raises(ValueError, match="at least 4"):
            op_bulk_write._resolve_field_value("{{generate:3}}")

    def test_generate_zero_raises(self):
        with pytest.raises(ValueError, match="at least 4"):
            op_bulk_write._resolve_field_value("{{generate:0}}")

    def test_file_placeholder(self, tmp_path):
        f = tmp_path / "key.txt"
        f.write_text("ssh-ed25519 AAAA...")
        val, secret = op_bulk_write._resolve_field_value(f"{{{{file:{f}}}}}")
        assert val == "ssh-ed25519 AAAA..."
        assert secret

    def test_file_placeholder_strips_trailing_newline(self, tmp_path):
        f = tmp_path / "key.txt"
        f.write_text("content\n")
        val, secret = op_bulk_write._resolve_field_value(f"{{{{file:{f}}}}}")
        assert val == "content"
        assert secret


class TestBuildCreateCommand:
    def test_basic_item(self):
        item = {
            "title": "Test Item",
            "vault": "Private",
            "category": "login",
            "fields": {"username": "cristos", "password": "s3cret"},
        }
        cmd, masked = op_bulk_write._build_create_command(item)
        assert "--vault=Private" in cmd
        assert "--title=Test Item" in cmd
        assert "--category=login" in cmd
        assert "username=cristos" in cmd
        assert "password=s3cret" in cmd

    def test_masked_hides_password(self):
        item = {
            "title": "Test",
            "vault": "Private",
            "category": "login",
            "fields": {"password": "{{generate:32}}"},
        }
        cmd, masked = op_bulk_write._build_create_command(item)
        for arg in masked:
            if arg.startswith("password="):
                assert "***" in arg
                assert "{{generate" not in arg


class TestRenderScript:
    def test_script_includes_items(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text("items:\n  - title: MyApp\n    vault: Private\n    category: login\n    fields:\n      username: cristos\n      password: s3cret\n")
        script, plan = op_bulk_write.render_script(spec)
        assert "MyApp" in script
        assert "Private" in script
        assert "cristos" in script
        assert "rm -f" in script
        assert "Self-deleting" in script

    def test_plan_shows_items(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text("items:\n  - title: MyApp\n    vault: Private\n    category: login\n    fields:\n      username: cristos\n")
        script, plan = op_bulk_write.render_script(spec)
        assert any("MyApp" in line for line in plan)
        assert any("cristos" in line for line in plan)
        assert any("***" not in line for line in plan)  # literals not masked

    def test_skips_existing_items(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text("items:\n  - title: ExistingApp\n    vault: Private\n    category: login\n    fields:\n      username: cristos\n")
        script, plan = op_bulk_write.render_script(spec)
        assert "op item get" in script
        assert "already exists" in script

    def test_empty_spec(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text("items: []")
        script, plan = op_bulk_write.render_script(spec)
        assert "rm -f" in script
        assert len(plan) == 0

    def test_multiple_items(self, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text(
            "items:\n"
            "  - title: App1\n    vault: Private\n    category: login\n    fields:\n      username: u1\n"
            "  - title: App2\n    vault: Private\n    category: login\n    fields:\n      username: u2\n"
        )
        script, plan = op_bulk_write.render_script(spec)
        assert "App1" in script
        assert "App2" in script
        assert len(plan) == 4  # 2 items × 2 plan lines each (header + field)

    def test_all_field_types(self, tmp_path):
        key_file = tmp_path / "id_rsa"
        key_file.write_text("ssh-private-key-data\n")
        spec = tmp_path / "spec.yaml"
        spec.write_text(
            f"items:\n"
            f"  - title: SSH Key\n    vault: Private\n    category: login\n    fields:\n"
            f"      username: cristos\n"
            f"      password: '{{{{generate:12}}}}'\n"
            f"      key[concealed]: '{{{{file:{key_file}}}}}'\n"
        )
        script, plan = op_bulk_write.render_script(spec)
        assert "SSH Key" in script
        assert "ssh-private-key-data" in script
        assert len(plan) == 4  # header + 3 fields
        plan_str = " ".join(plan)
        assert "concealed" in plan_str
