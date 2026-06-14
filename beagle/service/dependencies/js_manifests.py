"""JavaScript manifest and lockfile parsing (design/15 §11).

Prefers the repository's lockfile. ``package-lock.json`` (v2/v3) is parsed for
pinned versions and integrity hashes; ``package.json`` yields declared ranges
when no lockfile is present. YAML lockfiles (pnpm/yarn) are a follow-up — they
would add a YAML dependency, deferred to keep the parser stdlib-only.
"""

from __future__ import annotations

import json

from beagle.service.dependencies import ParsedPackage


def parse_package_lock(text: str) -> list[ParsedPackage]:
    data = json.loads(text)
    if "packages" in data:
        return _from_packages(data["packages"])
    if "dependencies" in data:
        return _from_dependencies(data["dependencies"], "default")
    return []


def _from_packages(packages: dict) -> list[ParsedPackage]:
    result = []
    for path, info in packages.items():
        if not path or "version" not in info:
            continue  # skip the root project entry ("")
        name = _name_from_path(path)
        group = "dev" if info.get("dev") else "default"
        result.append(
            ParsedPackage(
                "javascript", name, info["version"], info.get("integrity"),
                "git" if info.get("resolved", "").startswith("git") else "registry", group,
            )
        )
    return result


def _from_dependencies(deps: dict, group: str) -> list[ParsedPackage]:
    result = []
    for name, info in deps.items():
        version = info.get("version") if isinstance(info, dict) else info
        integrity = info.get("integrity") if isinstance(info, dict) else None
        result.append(ParsedPackage("javascript", name, version, integrity, "registry", group))
    return result


def _name_from_path(path: str) -> str:
    # "node_modules/a/node_modules/@scope/b" -> "@scope/b"
    return path.split("node_modules/")[-1]


def parse_package_json(text: str) -> list[ParsedPackage]:
    data = json.loads(text)
    result = []
    for field, group in (("dependencies", "default"), ("devDependencies", "dev")):
        for name, version in (data.get(field) or {}).items():
            result.append(ParsedPackage("javascript", name, version, None, "manifest", group))
    return result


def parse_pnpm_lock(text: str) -> list[ParsedPackage]:
    """Parse a pnpm-lock.yaml (v6/v9). Packages are keyed by name@version."""
    import yaml

    data = yaml.safe_load(text) or {}
    result = []
    for key, info in (data.get("packages") or {}).items():
        name, version = _split_pnpm_key(key)
        if not name or not version:
            continue
        integrity = None
        if isinstance(info, dict):
            resolution = info.get("resolution") or {}
            integrity = resolution.get("integrity")
        result.append(ParsedPackage("javascript", name, version, integrity, "registry", "default"))
    return result


def _split_pnpm_key(key: str) -> tuple[str | None, str | None]:
    # "/@scope/pkg@1.2.3" or "@scope/pkg@1.2.3" or "pkg@1.2.3"
    key = key.lstrip("/")
    at = key.rfind("@")
    if at <= 0:
        return None, None
    version = key[at + 1:].split("(")[0]  # strip peer-dep suffixes
    return key[:at], version


def parse_yarn_lock(text: str) -> list[ParsedPackage]:
    """Parse a yarn.lock v1 (custom indented format, not YAML)."""
    result = []
    current_names: list[str] = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[0].isspace() and line.rstrip().endswith(":"):
            current_names = _yarn_entry_names(line)
        elif line.strip().startswith("version") and current_names:
            version = line.split(None, 1)[1].strip().strip('"')
            for name in current_names:
                result.append(ParsedPackage("javascript", name, version, None, "registry", "default"))
            current_names = []
    return result


def _yarn_entry_names(line: str) -> list[str]:
    # '"@scope/pkg@^1.0.0", "@scope/pkg@~1.2.0":' -> ['@scope/pkg']
    specs = [s.strip().strip('"') for s in line.rstrip(":").split(",")]
    names = []
    for spec in specs:
        at = spec.rfind("@")
        name = spec[:at] if at > 0 else spec
        if name and name not in names:
            names.append(name)
    return names
