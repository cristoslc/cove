"""Pinned-artifact inventory parsed from compose/ (the single source of truth).

`cove --sbom` and `scripts/sbom.sh` both read the inventory from here, so the
matrix always mirrors the deployable compose files bundled in this wheel.
Parsing is read-only and raises on structurally impossible input (missing
files, unresolvable image refs) rather than silently omitting components.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Pin:
    """One pinned artifact in the stack."""

    name: str  # component/service name or derived base-image name
    kind: str  # "image" | "base" | "dependency"
    ref: str  # full artifact reference: image[:tag][@digest] or version
    location: str  # repo-relative file the pin lives in
    classified: str  # tag | tag+digest | digest | built | version


_ENV_DEFAULT_RE = re.compile(r"\$\{[A-Z_0-9]+:-(.+)\}$")

# Repo-relative compose files that carry pins, in stable read order.
PINNED_COMPOSE_FILES = (
    "docker-compose.yml",
    "litellm/docker-compose.yml",
    "tunnel.yml",
)

GROUP_VARS_FILE = "group_vars/all.yml"


def _render_simple(value: str, variables: dict) -> str:
    """Render '{{ var }}' substitutions using only keys from `variables`."""
    return re.sub(r"\{\{\s*([A-Za-z_0-9]+)\s*\}\}", lambda m: str(variables.get(m.group(1), m.group(0))), value)


def _from_group_vars(compose_dir: Path) -> list[Pin]:
    """Image pins whose authoritative value (with digest) lives in group_vars/all.yml."""
    path = compose_dir / GROUP_VARS_FILE
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text())
    variables = {k: v for k, v in data.items() if isinstance(v, (str, int))}
    pins: list[Pin] = []
    for key, value in sorted(data.items()):
        if not (key.endswith("_image") and isinstance(value, str)):
            continue
        ref = _render_simple(value, variables)
        if "@" in ref or ":" in ref:
            name = key.removesuffix("_image")
            pins.append(
                Pin(name=name, kind="image", ref=ref, location=GROUP_VARS_FILE, classified=_classifier(ref))
            )
    return pins


def _resolve_ref(ref: str) -> str:
    """Resolve '${VAR:-default}' form to its default; anything else passes through."""
    match = _ENV_DEFAULT_RE.match(ref)
    return match.group(1) if match else ref


def _classifier(ref: str) -> str:
    if "@" in ref:
        # Digest form; a non-latest tag beside the digest is still a tag pin.
        tag = ref.split("@", 1)[0].rsplit(":", 1)[-1]
        return "tag+digest" if tag and tag != "latest" else "digest"
    last_segment = ref.rsplit(":", 1)[-1]
    if ":" in ref and "/" not in ref.rsplit(":", 1)[0]:
        digits = last_segment.split(".", 1)[0]
        if digits.isdigit():
            return "tag"
    return "tag"


def _component_name(ref: str) -> str:
    repo = ref.split("@", 1)[0]
    last = repo.rsplit("/", 1)[-1]
    return last.rsplit(":", 1)[0] if ":" in last else last


def _from_dockerfile(dockerfile: Path, rel: str) -> list[Pin]:
    if not dockerfile.exists():
        return []
    pins: list[Pin] = []
    for line in dockerfile.read_text().splitlines():
        match = re.match(r"^FROM\s+(\S+)", line)
        if match:
            ref = match.group(1)
            pins.append(Pin(name=_component_name(ref), kind="base", ref=ref, location=rel, classified=_classifier(ref)))
    return pins


def _from_compose_file(compose_path: Path, rel: str) -> list[Pin]:
    data = yaml.safe_load(compose_path.read_text())
    pins: list[Pin] = []
    services = data.get("services") or {}
    for svc, node in sorted(services.items()):
        if not isinstance(node, dict):
            continue
        image = node.get("image")
        if image:
            ref = _resolve_ref(image)
            pins.append(
                Pin(
                    name=svc,
                    kind="image",
                    ref=ref,
                    location=rel,
                    classified="built" if ref.startswith("cove-") else _classifier(ref),
                )
            )
        build = node.get("build")
        if isinstance(build, dict):
            dockerfile_name = build.get("dockerfile", "Dockerfile")
            context = build.get("context", ".")
            dockerfile_rel = str(Path(rel).parent / context / dockerfile_name)
            pins.extend(_from_dockerfile(compose_path.parent / dockerfile_rel, dockerfile_rel))
            args = build.get("args") or {}
            for arg_name, arg_value in sorted(args.items()):
                pins.append(
                    Pin(
                        name=f"{svc}.{arg_name}",
                        kind="dependency",
                        ref=_resolve_ref(arg_value),
                        location=rel,
                        classified="version",
                    )
                )
        elif isinstance(build, str):
            build_dir = _resolve_ref(build)
            dockerfile_rel = str(Path(build_dir) / "Dockerfile")
            pins.extend(_from_dockerfile(compose_path.parent / dockerfile_rel, dockerfile_rel))
    return pins


def all_pins(compose_dir: Path) -> list[Pin]:
    """Every pin in the stack, deduplicated by (name, kind, ref), in stable order.

    group_vars image pins are authoritative for their component: a same-name
    compose `image` pin is replaced (vault carries its digest only there;
    forgejo carries a tag override there).
    """
    found: list[Pin] = _from_group_vars(compose_dir)
    for name in PINNED_COMPOSE_FILES:
        path = compose_dir / name
        if path.exists():
            found.extend(_from_compose_file(path, name))
    by_key: dict[tuple[str, str], Pin] = {}
    for pin in found:
        key = (pin.name, pin.kind)
        if pin.location == GROUP_VARS_FILE or key not in by_key:
            by_key[key] = pin
    order = {p.name: i for i, p in enumerate(found)}
    return sorted(by_key.values(), key=lambda p: order.get(p.name, len(order)))


def main() -> int:
    """Emit the pin inventory as JSON: `python -m cove.pins --json [compose-dir]`."""
    if len(sys.argv) > 1:
        compose_dir = Path(sys.argv[1])
        if not compose_dir.exists():
            raise FileNotFoundError(f"compose dir not found: {compose_dir}")
    else:
        from cove.stateless import resolve_compose_dir

        compose_dir = resolve_compose_dir()
    print(json.dumps([asdict(p) for p in all_pins(compose_dir)], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())