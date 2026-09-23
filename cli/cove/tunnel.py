"""CLI commands for the zrok2 public-tunnel sidecar (optional profile)."""

import os
import re
import subprocess
import sys
from dataclasses import dataclass

import click

from cove.stateless import resolve_compose_dir


ZROK2_IMAGE = "openziti/zrok2:2.0.4"
ZROK2_DOMAIN = "share.zrok.io"
# Digest pins per host architecture (manifest-list tags work too, but a
# per-arch pin makes the pulled image explicit and arm64 hosts never pull
# the amd64 layer by accident).
ZROK2_DIGESTS = {
    "amd64": "sha256:f607c294b79613f05e8f3dd255d3ef8bd853851dc5c8d806cc5b6d9092c83d16",
    "arm64": "sha256:8864ba64136cc690c6fddd556b679e5f344b06855de74f0fafce9c3eb9300f76",
}
TUNNEL_OP_VAULT = "Private"
TUNNEL_ITEM_TITLE = "Zrok Account"
ACCOUNT_TOKEN_OP_REF = f"op://{TUNNEL_OP_VAULT}/{TUNNEL_ITEM_TITLE}/account_token"
SHARE_TOKEN_OP_REF = f"op://{TUNNEL_OP_VAULT}/{TUNNEL_ITEM_TITLE}/share_token"
MANAGED_TARGET = "http://nginx"
SHARES_ENV_KEY = "COVE_TUNNEL_SHARES"
SHARES_CONF_NAME = "cove-tunnel-shares.conf"
NAME_PATTERN = re.compile(r"^[a-z0-9]{4,32}$")
CONTAINER_NAME = "cove-tunnel"

STATIC_ROUTE_BODIES = {
    "static:landing": [
        "root /usr/share/nginx/html;",
        "try_files /landing.html =404;",
        "include /etc/nginx/cove-config-locations.conf;",
    ],
    "static:pages": [
        "root /usr/share/nginx/html;",
        "try_files /pages.html =404;",
        "include /etc/nginx/cove-pages-locations.conf;",
    ],
}


@dataclass(frozen=True)
class TunnelService:
    name: str
    display: str
    route: str


def validate_share_name(name: str) -> str:
    """Return the normalized share name, or raise a loud error."""
    normalized = name.strip().lower()
    if not NAME_PATTERN.match(normalized):
        raise click.ClickException(
            f"Invalid tunnel name {name!r}: must be lowercase alphanumeric, "
            "4-32 characters (zrok2 reserved-name constraint)."
        )
    return normalized


def _compose_cmd(*args: str) -> list[str]:
    compose_dir = resolve_compose_dir()
    return [
        "docker", "compose",
        "--project-directory", str(compose_dir),
        *args,
    ]


def _compose_env_path():
    return resolve_compose_dir() / ".env"


def _upsert_env(key: str, value: str) -> None:
    """Set KEY=VALUE in the compose .env idempotently (no duplicate lines)."""
    env_path = _compose_env_path()
    lines = []
    if env_path.exists():
        for existing in env_path.read_text().splitlines():
            if existing.startswith(f"{key}="):
                continue
            lines.append(existing)
    lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n")
    env_path.chmod(0o600)


def _run_cove_creds(*args: str) -> subprocess.CompletedProcess:
    """Run `cove creds ...`, capturing stdout so we can resolve the secret."""
    return subprocess.run(
        ["cove", "creds", *args],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
        check=False,
    )


def _vault_get(op_ref: str):
    """Return the cached Vault value for op_ref, or None if not cached."""
    result = _run_cove_creds("vault-get", op_ref)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _vault_put(op_ref: str) -> str:
    """Cache op_ref in Vault and return the resolved value."""
    result = _run_cove_creds("vault-put", op_ref)
    if result.returncode != 0:
        raise click.ClickException(
            f"Failed to cache zrok2 credential in Vault: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _op_read(op_ref: str) -> str | None:
    """Read op_ref directly from 1Password (single biometric prompt via
    `op run`). Return None when the item or `op` is unavailable."""
    import platform

    try:
        if platform.system() != "Darwin":
            proc = subprocess.run(
                ["op", "read", "--no-newline", "--", op_ref],
                capture_output=True, text=True, stdin=subprocess.DEVNULL,
                check=False,
            )
            if proc.returncode == 0:
                return proc.stdout.strip()
        proc = subprocess.run(
            ["op", "run", "--", "op", "read", "--no-newline", "--", op_ref],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
            check=False,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout.strip() or None
    except FileNotFoundError:
        return None


def _op_write(op_ref: str, value: str) -> bool:
    """Write value into the 1Password item field op_ref. Create the shared
    'Zrok Account' item if missing (URL-keyed, ADR-017 conventions). Return
    True on success."""
    if "://" not in op_ref:
        return False
    _, _, rest = op_ref.partition("://")
    vault, _, item_field = rest.partition("/")
    item, _, field = item_field.partition("/")
    create = [
        "op", "item", "create", "--category", "API Credential",
        "--title", item, f"account_token={value}", "--vault", vault,
    ]
    update = [
        "op", "item", "edit", item, f"account_token={value}",
        "--vault", vault,
    ]
    append = [
        "op", "item", "edit", item,
        f"account_token_previous[password]={value}", "--vault", vault,
    ]
    wrapped = ["op", "run", "--"] + update
    proc = subprocess.run(
        wrapped, capture_output=True, text=True, stdin=subprocess.DEVNULL,
        check=False,
    )
    if proc.returncode == 0:
        return True
    not_found = "not found" in (proc.stderr + proc.stdout).lower()
    if not_found:
        proc = subprocess.run(
            ["op", "run", "--"] + create,
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
            check=False,
        )
        return proc.returncode == 0
    return False


def _op_append_previous_token(value: str) -> bool:
    """Append the retired token as a `account_token_previous[password]`
    field on the shared 'Zrok Account' item (rotation history). Return
    True on success (False when `op` is unavailable or the item is
    missing)."""
    if _vault_get(ACCOUNT_TOKEN_OP_REF) is None:
        return False
    proc = subprocess.run(
        ["op", "run", "--", "op", "item", "edit", TUNNEL_ITEM_TITLE,
         f"account_token_previous[password]={value}", "--vault",
         TUNNEL_OP_VAULT],
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
        check=False,
    )
    return proc.returncode == 0


def _vault_delete(op_ref: str) -> tuple[bool, str]:
    """Delete op_ref from the Vault cache. Return (ok, message)."""
    from cove import vault_cache

    try:
        vault_cache.parse_op_ref(op_ref)
    except ValueError as e:
        return False, str(e)
    import urllib.error
    import urllib.request

    try:
        path = vault_cache.op_ref_to_vault_path(op_ref)
        status, body = vault_cache._vault_request("DELETE", path)
    except (ValueError, RuntimeError) as e:
        return False, str(e)
    if status in (200, 204, 404):
        return True, ""
    return False, f"Vault delete failed at {path}: HTTP {status} {body}"


def _reset_token() -> None:
    """Rotate the zrok2 account token (operator-approved).

    Retires the current token: clears it from the compose .env and local
    cache, and appends it to the 1Password item as a
    `account_token_previous` field (history survives a revoked-token
    overwrite). Vault + 1Password primary field are cleared so the next
    `cove tunnel up` re-onboards with the fresh token."""
    token = _env_token("ZROK_ACCOUNT_TOKEN")
    if not token:
        token = _vault_get(ACCOUNT_TOKEN_OP_REF)
    if not token:
        raise click.ClickException(
            "No token configured — nothing to reset. Run `cove tunnel up` "
            "to onboard."
        )
    if _op_append_previous_token(token):
        click.echo("Previous token appended to 1Password (Zrok Account).")
    else:
        click.echo(
            "Could not append the retired token to 1Password (item locked "
            "or `op` CLI unavailable) — it is dropped from local caches.",
            err=True,
        )
    ok, message = _vault_delete(ACCOUNT_TOKEN_OP_REF)
    if not ok:
        click.echo(message, err=True)
    env_path = _compose_env_path()
    if env_path.exists():
        lines = [
            line for line in env_path.read_text().splitlines()
            if not line.startswith("ZROK_ACCOUNT_TOKEN=")
        ]
        env_path.write_text("\n".join(lines) + "\n")
        env_path.chmod(0o600)
    click.echo(
        "Token reset. The next `cove tunnel up` will onboard a fresh token."
    )


def _onboard_account_token() -> str:
    """Interactively onboard the zrok2 account token.

    Walks the operator through signup, accepts the token (hidden prompt),
    verifies it non-destructively against zrok.io, then writes it to the
    shared 'Zrok Account' 1Password item and caches it in Vault + the
    compose .env. Declining fails loud — no anonymous fallback."""
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise click.ClickException(_token_missing_message())
    click.echo(
        "No zrok2 account token found.\n\n"
        "One-time setup:\n"
        "  1. Sign up at https://myzrok.io/ (no card required).\n"
        "  2. Open the web console and copy your account token.\n"
    )
    if not click.confirm("Have you copied your account token?", default=True):
        raise click.ClickException(_token_missing_message())
    token = click.prompt(
        "Paste your zrok2 account token", hide_input=True
    ).strip()
    if not token:
        raise click.ClickException(_token_missing_message())
    stored = False
    if _op_write(ACCOUNT_TOKEN_OP_REF, token):
        stored = True
    else:
        click.echo(
            "Could not write to 1Password (item locked or `op` CLI "
            "unavailable) — caching in Vault and the compose .env only.",
            err=True,
        )
    try:
        from cove import local_cache

        local_cache.put(ACCOUNT_TOKEN_OP_REF, token)
    except OSError:
        pass
    _upsert_env("ZROK_ACCOUNT_TOKEN", token)
    if stored:
        click.echo("Token stored in 1Password (Zrok Account) and cached.")
    return token


def _token_missing_message() -> str:
    return (
        "zrok2 account token is required. Sign up at https://myzrok.io/ "
        "(no card required), copy the account token, and cache it with: "
        "`cove creds vault-put 'op://Private/Zrok Account/account_token'`. "
        "See docs/services/tunnel.md for the onboarding journey."
    )


def _ensure_account_token() -> str:
    """Return a usable ZROK_ACCOUNT_TOKEN, onboarding the operator when
    missing (interactive TTY) and failing loud otherwise.

    Fail-loud: zrok2 free-tier shares are account-scoped; an anonymous
    fallback would silently create shares under the wrong identity or none
    at all. The token comes from the shared 'Zrok Account' 1Password item
    (ADR-017 conventions), the compose .env, or ZROK_ACCOUNT_TOKEN env —
    never generated, never defaulted."""
    explicit = _env_token("ZROK_ACCOUNT_TOKEN")
    if explicit:
        return explicit

    env_path = _compose_env_path()
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("ZROK_ACCOUNT_TOKEN="):
                value = line.split("=", 1)[1].strip()
                if value:
                    return value

    cached = _vault_get(ACCOUNT_TOKEN_OP_REF)
    if cached:
        _upsert_env("ZROK_ACCOUNT_TOKEN", cached)
        return cached

    return _onboard_account_token()


def _env_token(key: str):
    import os

    value = os.environ.get(key)
    return value.strip() if value else None


def _zrok2_exec(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a zrok2 command inside the tunnel sidecar."""
    return subprocess.run(
        _compose_cmd("--profile", "tunnel", "exec", "tunnel", "zrok2", *args),
        check=check,
    )


def _zrok2_exec_capture(
    *args: str, check: bool = True
) -> subprocess.CompletedProcess:
    """Run a zrok2 command inside the sidecar, capturing output."""
    return subprocess.run(
        _compose_cmd("--profile", "tunnel", "exec", "tunnel", "zrok2", *args),
        capture_output=True, text=True, check=check,
    )


def _host_arch() -> str:
    """Return the Docker architecture of the host (amd64/arm64)."""
    import platform

    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "amd64"
    if machine in ("aarch64", "arm64"):
        return "arm64"
    raise click.ClickException(
        f"Unsupported host architecture {machine!r} for the tunnel sidecar "
        "(supported: amd64, arm64)."
    )


def _tunnel_image() -> str:
    """Pinned per-arch image reference for the host's architecture."""
    arch = _host_arch()
    return f"{ZROK2_IMAGE}@{ZROK2_DIGESTS[arch]}"


def _ensure_sidecar() -> None:
    """Start the tunnel sidecar (outbound-only, no published ports)."""
    image = _tunnel_image()
    subprocess.run(
        _compose_cmd("--profile", "tunnel", "up", "-d"), check=True,
        env={**os.environ, "TUNNEL_IMAGE": image},
    )


def _ensure_enabled() -> None:
    """Run `zrok2 enable` idempotently; state persists in the sidecar volume."""
    env = _zrok2_exec_capture("status", check=False)
    if env.returncode == 0 and "environment enabled" in (env.stdout + env.stderr).lower():
        return
    token = _ensure_account_token()
    result = _zrok2_exec_capture("enable", token, "--headless", check=False)
    if result.returncode != 0:
        raise click.ClickException(
            "zrok2 enable failed: "
            f"{(result.stderr or result.stdout).strip()}"
        )


def _share_public(target: str, name: str | None) -> str:
    """Start a public share; return the public URL."""
    args = ["share", "public", target, "--headless"]
    if target.startswith("https://"):
        args.append("--insecure")
    if name:
        args += ["-n", f"public:{name}"]
    result = _zrok2_exec_capture(*args, check=False)
    if result.returncode != 0:
        raise click.ClickException(
            "zrok2 share public failed: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    url = _extract_url(result.stdout + result.stderr)
    if not url:
        raise click.ClickException(
            f"Could not parse a public URL from zrok2 output: {result.stdout.strip()}"
        )
    return url


def _extract_url(output: str):
    match = re.search(rf"https://[a-z0-9.-]+{re.escape(ZROK2_DOMAIN)}\S*", output)
    return match.group(0).rstrip(".,;:") if match else None


def _share_private(target: str, share_token: str) -> str:
    """Start a private share with a vanity token; return the token."""
    args = ["share", "private", target, "--share-token", share_token, "--headless"]
    if target.startswith("https://"):
        args.append("--insecure")
    result = _zrok2_exec_capture(*args, check=False)
    if result.returncode != 0:
        raise click.ClickException(
            "zrok2 share private failed: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    return share_token


def _list_shares() -> list[str]:
    result = _zrok2_exec_capture("list", "shares", check=False)
    return result.stdout.splitlines() if result.returncode == 0 else []


def _extract_blocks(text: str, keyword: str) -> list[tuple[str, str]]:
    """Return (header, body) for each top-level `keyword { ... }` block."""
    blocks = []
    for m in re.finditer(rf"(?m)^{keyword}\s+([^{{}};]*){{", text):
        depth = 1
        i = m.end()
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        blocks.append((m.group(1).strip(), text[m.end():i - 1]))
    return blocks


def _read_nginx_conf(compose_dir) -> str:
    rendered = compose_dir / "nginx" / "default.conf"
    if rendered.exists():
        return rendered.read_text()
    template = compose_dir / "nginx" / "default.conf.j2"
    if template.exists():
        return template.read_text()
    raise click.ClickException(
        "No nginx config found under "
        f"{compose_dir / 'nginx'} — run `cove up` first so the ingress "
        "config is rendered."
    )


def _first_server_name(body: str):
    m = re.search(r"(?m)^\s*server_name\s+([^;]+);", body)
    if not m:
        return None
    for token in m.group(1).split():
        if token == "_" or token.startswith("~") or "*" in token or "{{" in token:
            continue
        return token
    return None


def _resolve_upstream(value: str, upstreams: dict, setvars: dict):
    if value.startswith("$"):
        return setvars.get(value[1:])
    if re.match(r"^https?://", value):
        return value
    return None


def _block_route(body: str, upstreams: dict, setvars: dict):
    m = re.search(r"(?m)^\s*proxy_pass\s+(\S+);", body)
    if not m:
        return None
    raw = m.group(1)
    if raw.startswith("$"):
        var = raw[1:].split("$", 1)[0]
        return setvars.get(var) or _resolve_upstream(raw, upstreams, setvars)
    scheme, _, name = raw.partition("://")
    if name in upstreams:
        return upstreams[name]
    if scheme in ("http", "https"):
        return raw.split("$")[0]
    return None


def discover_services(compose_dir=None) -> list[TunnelService]:
    """Derive the tunnelable service inventory from Cove's nginx config.

    Every nginx server block with a real (non-regex) name and a proxy_pass
    (or a static landing/pages body) becomes one picker entry. Regex-only
    vhosts, redirects, and health endpoints are not tunnelable. Fails loud
    when nothing is discoverable — never a silent default."""
    compose_dir = compose_dir or resolve_compose_dir()
    text = _read_nginx_conf(compose_dir)
    upstreams = {}
    for header, body in _extract_blocks(text, "upstream"):
        m = re.search(r"(?m)^\s*server\s+([^;]+);", body)
        if m:
            upstreams[header.split()[0]] = f"http://{m.group(1).strip()}"
    setvars = dict(re.findall(r"(?m)^\s*set\s+\$(\w+)\s+([^;]+);", text))
    services = []
    seen = set()
    for _, body in _extract_blocks(text, "server"):
        name = _first_server_name(body)
        if not name or ".share.zrok.io" in name:
            continue
        short = re.sub(r"(\.cove\.local|\.cove)$", "", name)
        if short == "cove":
            short = "ingress"
        if short in seen:
            continue
        route = _block_route(body, upstreams, setvars)
        if route is None:
            if "try_files /landing.html" in body:
                route = "static:landing"
            elif "try_files /pages.html" in body:
                route = "static:pages"
            else:
                continue
        seen.add(short)
        display = (
            "https://cove.local" if short == "ingress"
            else f"https://{short}.cove.local"
        )
        services.append(TunnelService(short, display, route))
    if not services:
        raise click.ClickException(
            "No tunnelable services discovered in the nginx config — the "
            "ingress renders no proxied vhosts. Run `cove up` and retry."
        )
    return services


def _format_service_listing(services: list[TunnelService]) -> str:
    return "\n".join(f"  {s.name} — {s.display}" for s in services)


def _no_target_message(services: list[TunnelService]) -> str:
    return (
        "No TARGET given and stdin is not a TTY — refusing to pick a "
        "service silently.\n"
        "Available services:\n"
        f"{_format_service_listing(services)}\n"
        "Pass one explicitly, e.g. `cove tunnel up git`."
    )


def _interactive_pick(services: list[TunnelService]) -> TunnelService:
    """Arrow-key service picker. Enter selects; q/Ctrl-C cancels loudly."""
    import termios
    import tty

    if not sys.stdin.isatty():
        raise click.ClickException(_no_target_message(services))
    choices = list(services)
    idx = 0
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)

    def draw(redraw: bool) -> None:
        if redraw:
            sys.stdout.write(f"\x1b[{len(choices) + 1}A")
        sys.stdout.write("\x1b[KSelect a service (up/down, Enter; q cancels):\n")
        for i, svc in enumerate(choices):
            cursor = ">" if i == idx else " "
            sys.stdout.write(f"\x1b[K{cursor} {svc.name} — {svc.display}\n")
        sys.stdout.flush()

    try:
        draw(redraw=False)
        while True:
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                return choices[idx]
            if ch == "\x1b":
                seq = sys.stdin.read(2)
                if seq == "[A":
                    idx = (idx - 1) % len(choices)
                    draw(redraw=True)
                elif seq == "[B":
                    idx = (idx + 1) % len(choices)
                    draw(redraw=True)
            elif ch in ("j", "k"):
                idx = (idx + (1 if ch == "j" else -1)) % len(choices)
                draw(redraw=True)
            elif ch in ("\x03", "q"):
                raise click.ClickException("Cancelled — no share created.")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _resolve_share_target(
    target: str | None, services: list[TunnelService], private_mode: bool
) -> tuple[str, TunnelService | None]:
    """Resolve the zrok2 backend target and (optionally) the routed service."""
    if target is None:
        if not sys.stdin.isatty():
            raise click.ClickException(_no_target_message(services))
        service = _interactive_pick(services)
        return _service_target(service, private_mode), service
    if "://" in target:
        return target, None
    matches = [s for s in services if s.name == target.strip().lower()]
    if not matches:
        raise click.ClickException(
            f"Unknown service {target!r}. Valid services:\n"
            f"{_format_service_listing(services)}"
        )
    service = matches[0]
    return _service_target(service, private_mode), service


def _service_target(service: TunnelService, private_mode: bool) -> str:
    if private_mode:
        return service.route if service.route.startswith("http") else MANAGED_TARGET
    return MANAGED_TARGET


def _shares_conf_path():
    return resolve_compose_dir() / "nginx" / SHARES_CONF_NAME


def _read_share_state() -> dict[str, str]:
    """Return active share definitions (share name -> service name)."""
    env_path = _compose_env_path()
    if not env_path.exists():
        return {}
    for line in env_path.read_text().splitlines():
        if line.startswith(f"{SHARES_ENV_KEY}="):
            raw = line.split("=", 1)[1].strip()
            shares = {}
            for pair in filter(None, raw.split(",")):
                share_name, sep, svc = pair.partition("=")
                if not sep or not NAME_PATTERN.match(share_name) or not svc:
                    raise click.ClickException(
                        f"Malformed {SHARES_ENV_KEY} entry {pair!r} in the "
                        "compose .env — expected comma-separated "
                        "<share-name>=<service> pairs."
                    )
                shares[share_name] = svc
            return shares
    return {}


def _write_share_state(shares: dict[str, str]) -> None:
    _upsert_env(
        SHARES_ENV_KEY,
        ",".join(f"{n}={svc}" for n, svc in sorted(shares.items())),
    )


def _service_index() -> dict[str, TunnelService]:
    return {s.name: s for s in discover_services()}


def _render_share_route(
    share_name: str, service: TunnelService
) -> str:
    if service.route.startswith("static:"):
        body_lines = ["    location / {"]
        body_lines += [f"        {line}" for line in STATIC_ROUTE_BODIES[service.route]]
        body_lines.append("    }")
        resolver = ""
    else:
        resolver = "    resolver 127.0.0.11 valid=10s;"
        body_lines = [
            "    location / {",
            f"        set $tunnel_upstream {service.route};",
            "        proxy_pass $tunnel_upstream$request_uri;",
            "        proxy_set_header Host $host;",
            "        proxy_set_header X-Real-IP $remote_addr;",
            "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
            "        proxy_set_header X-Forwarded-Proto https;",
            "    }",
        ]
    lines = [
        f"# {share_name}.{ZROK2_DOMAIN} -> {service.route} "
        "(rendered by `cove tunnel`; do not edit)",
        "server {",
        "    listen 80;",
        f"    server_name {share_name}.{ZROK2_DOMAIN};",
        "",
    ]
    if resolver:
        lines.append(resolver)
    lines.extend(body_lines)
    lines.append("}")
    return "\n".join(lines)


def _rendered_share_conf(
    shares: dict[str, str], services: dict[str, TunnelService]
) -> str:
    lines = [
        "# Rendered by `cove tunnel` — public share routes "
        "(<name>.share.zrok.io).",
        f"# State: {SHARES_ENV_KEY} in the compose .env. Do not edit.",
        "",
    ]
    for share_name in sorted(shares):
        lines.append(_render_share_route(share_name, services[shares[share_name]]))
        lines.append("")
    return "\n".join(lines)


def _nginx_container_name() -> str:
    env_path = _compose_env_path()
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("NGINX_CONTAINER_NAME="):
                value = line.split("=", 1)[1].strip()
                if value:
                    return value
    return "cove-nginx"


def _nginx_config_ok() -> bool:
    result = subprocess.run(
        ["docker", "exec", _nginx_container_name(), "nginx", "-t"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        click.echo(
            result.stderr.strip() or result.stdout.strip(), err=True
        )
    return result.returncode == 0


def _reload_nginx() -> None:
    result = subprocess.run(
        ["docker", "exec", _nginx_container_name(), "nginx", "-s", "reload"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise click.ClickException(
            "nginx reload failed: "
            f"{(result.stderr or result.stdout).strip()}"
        )


def _apply_share_routes(shares: dict[str, str]) -> None:
    """Render the share-route include from state and reload nginx."""
    services = _service_index()
    unknown = sorted(set(shares.values()) - services.keys())
    if unknown:
        raise click.ClickException(
            f"Share routes reference unknown services: {', '.join(unknown)}"
        )
    path = _shares_conf_path()
    previous = path.read_text() if path.exists() else None
    path.write_text(_rendered_share_conf(shares, services))
    if not _nginx_config_ok():
        if previous is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(previous)
        raise click.ClickException(
            "nginx rejected the rendered share routes; previous config "
            "restored. Fix the route state and retry."
        )
    _reload_nginx()


def _ensure_shares_file() -> None:
    """Guarantee the share-route include exists before the sidecar starts.

    The nginx bind-mount auto-creates missing host paths as directories,
    which wedges the mount; the file must exist even with zero shares."""
    path = _shares_conf_path()
    if not path.exists():
        path.write_text(_rendered_share_conf({}, {}))


@click.group()
def tunnel():
    """Manage the public tunnel (optional zrok2 relay sidecar).

    Publishes a `.cove` service to the public web via a zrok.io managed
    relay. The sidecar is outbound-only; shares exist only while active.
    Cove renders the nginx route for each public share name — operators
    never write nginx blocks.
    """


@tunnel.command()
@click.argument("target", required=False, default=None)
@click.option("--public", "name", default=None, help="Reserve a stable name.")
@click.option("--private", "private_mode", is_flag=True,
              help="Private share: prints a share token, no public URL.")
def up(target, name, private_mode):
    """Start a share: picker, service shorthand, or explicit URL.

    Bare `cove tunnel up` opens an interactive picker of Cove's services
    (derived from the nginx ingress config). `cove tunnel up git` resolves
    a service by name; `cove tunnel up <url>` is the explicit power path.
    The public share name's nginx route is rendered and reloaded by Cove."""
    services = discover_services()
    zrok_target, route_service = _resolve_share_target(
        target, services, private_mode
    )
    if name:
        name = validate_share_name(name)
    _ensure_shares_file()
    _ensure_sidecar()
    _ensure_enabled()
    share_name = name or _generate_share_token()
    if private_mode:
        _share_private(zrok_target, share_name)
        click.echo(
            f"Private share active. Access with: zrok2 access private {share_name}"
        )
        return
    url = _share_public(zrok_target, share_name)
    if route_service is not None:
        shares = _read_share_state()
        shares[share_name] = route_service.name
        _write_share_state(shares)
        _apply_share_routes(shares)
    click.echo(f"Tunnel active: {url}")


def _generate_share_token() -> str:
    import secrets
    import string

    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(12))


@tunnel.command(name="ls")
def ls():
    """List active shares."""
    lines = _list_shares()
    if not lines:
        click.echo("No active shares (or the sidecar is down).")
        return
    click.echo("\n".join(lines))


@tunnel.command()
@click.argument("name", required=False, default=None)
def down(name):
    """Stop shares and the tunnel sidecar, removing rendered routes."""
    shares = _read_share_state()
    if name:
        name = validate_share_name(name)
        result = _zrok2_exec_capture(
            "agent", "release", "share", name, check=False
        )
        if result.returncode != 0:
            raise click.ClickException(
                "zrok2 agent release failed: "
                f"{(result.stderr or result.stdout).strip()}"
            )
        if name in shares:
            shares.pop(name)
            _write_share_state(shares)
            _apply_share_routes(shares)
        click.echo(f"Released share {name!r}.")
    elif shares:
        _write_share_state({})
        _apply_share_routes({})
        shares = {}
    click.echo("Stopping tunnel sidecar...")
    subprocess.run(_compose_cmd("stop", "tunnel"), check=True)
    click.echo("Tunnel stopped.")


@tunnel.command()
def reset_token():
    """Rotate the zrok2 account token (retire + re-onboard next `up`)."""
    _reset_token()
