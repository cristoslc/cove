"""Cove CLI."""
# Single source of truth is cli/pyproject.toml. importlib.metadata resolves
# the installed distribution version (so `cove --version` can never drift from
# the wheel); the literal is only a fallback for editable/odd installs.
try:
    from importlib.metadata import version as _dist_version

    __version__ = _dist_version("cove-cli")
except Exception:  # pragma: no cover - editable installs without dist-info
    __version__ = "0.7.0"
