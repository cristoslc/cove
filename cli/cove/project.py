"""CLI commands for project integration."""

import json
import os
import subprocess
from importlib.resources import files
from pathlib import Path

import click
from jinja2 import Environment, BaseLoader

SENTINEL_START = "<!-- cove-guidance start -->"
SENTINEL_END = "<!-- cove-guidance end -->"


def _container_env(container_name: str) -> dict[str, str]:
    try:
        result = subprocess.run(
            ["docker", "inspect", container_name, "--format", "{{json .Config.Env}}"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        raise click.ClickException(
            f"Container '{container_name}' not found. Is Cove running?"
        )
    return dict(item.split("=", 1) for item in json.loads(result.stdout.strip()))


def _render_guidance(forgejo: dict, vault: dict) -> str:
    template_text = (
        files("cove.templates").joinpath("project-guidance.md.j2").read_text()
    )
    admin_username = os.environ.get("USER") or os.environ.get("LOGNAME") or "cove"
    env = Environment(loader=BaseLoader())
    return env.from_string(template_text).render(
        forgejo_domain=forgejo.get("FORGEJO__server__DOMAIN", "localhost"),
        forgejo_root_url=forgejo.get("FORGEJO__server__ROOT_URL", "http://localhost:3000/"),
        forgejo_ssh_domain=forgejo.get("FORGEJO__server__SSH_DOMAIN", "localhost"),
        forgejo_ssh_port=forgejo.get("FORGEJO__server__SSH_PORT", "2222"),
        admin_username=admin_username,
        vault_addr=vault.get("VAULT_ADDR", "http://127.0.0.1:8200"),
    )


def _inject(target: Path, rendered: str) -> None:
    block = f"{SENTINEL_START}\n{rendered.strip()}\n{SENTINEL_END}\n"
    if target.exists():
        text = target.read_text()
        if SENTINEL_START in text:
            start = text.index(SENTINEL_START)
            end = text.index(SENTINEL_END) + len(SENTINEL_END)
            target.write_text(text[:start] + block + text[end:].lstrip("\n"))
            click.echo(f"Updated cove guidance in {target}")
            return
        target.write_text(text.rstrip("\n") + "\n\n" + block)
    else:
        target.write_text(block)
    click.echo(f"Installed cove guidance in {target}")


@click.group()
def project():
    """Manage cove project integration."""


@project.command()
@click.option("-g", "--global", "global_", is_flag=True, help="Install to ~/.claude/CLAUDE.md")
def install(global_: bool):
    """Inject cove service guidance into the project or global Claude config."""
    forgejo = _container_env("cove-forgejo")
    vault = _container_env("cove-vault")
    rendered = _render_guidance(forgejo, vault)

    if global_:
        target = Path.home() / ".claude" / "CLAUDE.md"
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        target = Path.cwd() / "AGENTS.md"

    _inject(target, rendered)
