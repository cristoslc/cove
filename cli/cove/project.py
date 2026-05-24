"""Project integration: inject/strip cove guidance in AGENTS.md."""

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


def _render_context(forgejo: dict, vault: dict) -> dict:
    admin_username = os.environ.get("USER") or os.environ.get("LOGNAME") or "cove"
    return {
        "forgejo_domain": forgejo.get("FORGEJO__server__DOMAIN", "localhost"),
        "forgejo_root_url": forgejo.get("FORGEJO__server__ROOT_URL", "http://localhost:3000/"),
        "forgejo_ssh_domain": forgejo.get("FORGEJO__server__SSH_DOMAIN", "localhost"),
        "forgejo_ssh_port": forgejo.get("FORGEJO__server__SSH_PORT", "2222"),
        "admin_username": admin_username,
        "vault_addr": vault.get("VAULT_ADDR", "http://127.0.0.1:8200"),
    }


def _render_guidance(forgejo: dict, vault: dict) -> str:
    template_text = (
        files("cove.templates").joinpath("project-guidance.md.j2").read_text()
    )
    ctx = _render_context(forgejo, vault)
    env = Environment(loader=BaseLoader())
    return env.from_string(template_text).render(**ctx)


def _render_agents_block(ctx: dict, detail_ref: str) -> str:
    return (
        f"## Cove\n\n"
        f"This machine runs Cove — a local developer platform (forge, vault, CI, registry, pages).\n\n"
        f"**Full reference:** `{detail_ref}`\n"
        f"**Project override:** `.agents/cove/agents-md/cove.md` (if it exists, it augments/overrides the global doc for that repo)\n\n"
        f"### Quick facts\n\n"
        f"- **Forgejo** at `{ctx["forgejo_root_url"]}`. "
        f"CLI: `fjl` (via `zsh -i -c`). SSH: `git@forgejo-localhost:{ctx["admin_username"]}/repo.git` (port 2222).\n"
        f"- **Vault** at `{ctx["vault_addr"]}`. "
        f"Use `cove creds vault-get` / `cove creds vault-put` — never hardcode secrets.\n"
        f"- **Constraints:** No cloud dependencies. No internet during builds/CI. All git remotes go to Forgejo.\n\n"
        f"### Triggers\n\n"
        f"Load and follow the spoke doc when the conversation involves:\n\n"
        f"| Trigger | Examples |\n"
        f"|---------|----------|\n"
        f"| Credential management | `vault://`, `op://`, `cove creds`, `cove install`, `cove up/down` |\n"
        f"| Forgejo / git remotes | `forgejo`, `forge`, `fjl`, `fj`, `git remote`, pushing/pulling non-GitHub |\n"
        f"| Pages / hosting | `cove pages`, static hosting, site deployment |\n"
        f"| Services / infra | `cove`, `woodpecker`, `registry`, `down`, `uninstall`, service health |\n\n"
        f"When triggered, consult `{detail_ref}` first. "
        f"If a project-level `.agents/cove/agents-md/cove.md` exists, consult it second — it may override or extend."
    )


def _write_detail_cove(detail_path: Path, rendered: str) -> None:
    detail_path.parent.mkdir(parents=True, exist_ok=True)
    detail_path.write_text(rendered.strip() + "\n")
    click.echo(f"Wrote cove details to {detail_path}")


def _write_project_override(project_root: Path, ctx: dict) -> Path:
    override_dir = project_root / ".agents" / "cove" / "agents-md"
    override_path = override_dir / "cove.md"
    override_dir.mkdir(parents=True, exist_ok=True)
    content = (
        "# Cove (project-level override)\n\n"
        "This file augments/overrides the global cove spoke doc for this repository.\n"
        "Consult the global doc (referenced in AGENTS.md) first.\n\n"
        f"## Instance\n\n"
        f"- Forgejo: `{ctx['forgejo_root_url']}`\n"
        f"- Vault: `{ctx['vault_addr']}`\n"
        f"- Admin: `{ctx['admin_username']}`\n\n"
        f"## Remotes\n\n"
        f"- SSH: `git@forgejo-localhost:{ctx['admin_username']}/repo.git`\n"
        f"- Web: `{ctx['forgejo_root_url']}`\n\n"
        "## Local dev workflow\n\n"
        "For development on Cove itself, see `playbooks/` and `compose/` for service definitions.\n"
        "Run `cove up` from the project root to start services.\n"
    )
    override_path.write_text(content)
    click.echo(f"Wrote project-level cove override to {override_path}")
    return override_path


def _remove_detail_cove(detail_path: Path) -> None:
    if detail_path.exists():
        detail_path.unlink()
        click.echo(f"Removed {detail_path}")


def _remove_project_override(project_root: Path) -> None:
    override_path = project_root / ".agents" / "cove" / "agents-md" / "cove.md"
    if override_path.exists():
        override_path.unlink()
        click.echo(f"Removed {override_path}")


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


def _strip(target: Path) -> None:
    if not target.exists():
        click.echo(f"No cove guidance found (no {target}).")
        return
    text = target.read_text()
    if SENTINEL_START not in text:
        click.echo(f"No cove guidance block found in {target}.")
        return
    start = text.index(SENTINEL_START)
    end = text.index(SENTINEL_END) + len(SENTINEL_END)
    remaining = (text[:start] + text[end:]).strip()
    if remaining:
        target.write_text(remaining + "\n")
        click.echo(f"Removed cove guidance from {target}.")
    else:
        target.unlink()
        click.echo(f"Removed {target} (was only cove guidance).")
