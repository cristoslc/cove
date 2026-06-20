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
    computer_name = os.environ.get("COMPUTER_NAME") or os.uname().nodename.split(".")[0]
    home = Path.home()
    return {
        "forgejo_domain": forgejo.get("FORGEJO__server__DOMAIN", "localhost"),
        "forgejo_root_url": forgejo.get("FORGEJO__server__ROOT_URL", "http://localhost:3000/"),
        "forgejo_ssh_domain": forgejo.get("FORGEJO__server__SSH_DOMAIN", "localhost"),
        "forgejo_ssh_port": forgejo.get("FORGEJO__server__SSH_PORT", "2222"),
        "admin_username": admin_username,
        "repo_owner": admin_username,
        "repo_name": "cove",
        "computer_name": computer_name.lower(),
        "cove_data_root": str(home / "Documents" / "cove-data"),
        "vault_addr": vault.get("VAULT_ADDR", "http://127.0.0.1:8200"),
    }


def _render_guidance(forgejo: dict, vault: dict) -> str:
    template_text = (
        files("cove.templates").joinpath("detail-cove.md.j2").read_text()
    )
    ctx = _render_context(forgejo, vault)
    env = Environment(loader=BaseLoader())
    return env.from_string(template_text).render(**ctx)


def _render_agents_block(ctx: dict, detail_ref: str) -> str:
    parent = detail_ref.rsplit("/", 1)[0] if "/" in detail_ref else "."
    return (
        f"## Cove\n\n"
        f"This machine runs Cove — a local developer platform (forge, vault, CI, registry, pages). "
        f"All services are offline-first.\n\n"
f"- **Forgejo** at `https://git.cove/` (TLS via nginx+mkcert). "
f"CLI: `fj` (see `{parent}/fj.md`). "
f"PRs with `WIP:` title prefix are drafts and cannot be merged until the prefix is removed.\n"
f"- **GitHub** CLI: `gh` (see `{parent}/gh.md`). "
f"Use `gh pr ready` / `gh pr ready --undo` to toggle draft status.\n"
        f"- **Vault** at `https://vault.cove/` (TLS via nginx+mkcert). "
        f"Use `cove creds vault-get` / `cove creds vault-put` — never hardcode secrets.\n"
        f"- **Prerequisites (macOS):** `brew install colima mkcert && colima start && mkcert -install`\n"
        f"- **Constraints:** No cloud dependencies. No internet during builds/CI. "
        f"All git remotes go to Forgejo.\n\n"
        f"**Full reference:** `{detail_ref}`\n"
        f"**Project override:** `.agents/cove/agents-md/cove.md` "
        f"(if it exists, it augments/overrides the global doc for that repo)\n\n"
        f"When triggered by any Cove-related keyword (credentials, forgejo, pages, services), "
        f"load the spoke doc above."
    )


def _write_detail_cove(detail_path: Path, rendered: str) -> None:
    detail_path.parent.mkdir(parents=True, exist_ok=True)
    detail_path.write_text(rendered.strip() + "\n")
    click.echo(f"Wrote cove details to {detail_path}")


def _write_fj_detail(fj_path: Path) -> None:
    fj_path.parent.mkdir(parents=True, exist_ok=True)
    template_text = (
        files("cove.templates").joinpath("fj-reference.md.j2").read_text()
    )
    fj_path.write_text(template_text.strip() + "\n")
    click.echo(f"Wrote fj CLI reference to {fj_path}")


def _write_gh_detail(gh_path: Path) -> None:
    gh_path.parent.mkdir(parents=True, exist_ok=True)
    template_text = (
        files("cove.templates").joinpath("gh-reference.md.j2").read_text()
    )
    gh_path.write_text(template_text.strip() + "\n")
    click.echo(f"Wrote gh CLI reference to {gh_path}")


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
        f"- Web: `{ctx['forgejo_root_url']}`\n\n"
        "## Local dev workflow\n\n"
        "For development on Cove itself, see `compose/` for service definitions.\n"
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
