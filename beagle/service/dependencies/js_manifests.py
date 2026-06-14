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
