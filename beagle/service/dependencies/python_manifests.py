"""Python manifest and lockfile parsing (design/15 §11).

Prefers lockfiles (exact, hashed) over loose manifests. Parsing is static and
deterministic — no manifest code is executed, ``setup.py`` is not run. Each
parser returns pinned :class:`ParsedPackage` records.
"""

from __future__ import annotations

import re
import tomllib

from beagle.service.dependencies import ParsedPackage

_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*([^\s;#]+)")
_REQ_HASH = re.compile(r"--hash=([a-z0-9]+:[a-f0-9]+)")


def parse_uv_lock(text: str) -> list[ParsedPackage]:
    data = tomllib.loads(text)
    packages = []
    for entry in data.get("package", []):
        name, version = entry.get("name"), entry.get("version")
        if not name or not version:
            continue
        packages.append(
            ParsedPackage("python", name, version, _uv_hash(entry), _uv_source(entry), "default")
        )
    return packages


def _uv_hash(entry: dict) -> str | None:
    sdist = entry.get("sdist")
    if isinstance(sdist, dict) and sdist.get("hash"):
        return sdist["hash"]
    wheels = entry.get("wheels")
    if isinstance(wheels, list) and wheels and wheels[0].get("hash"):
        return wheels[0]["hash"]
    return None


def _uv_source(entry: dict) -> str:
    source = entry.get("source", {})
    if "git" in source:
        return "git"
    if entry.get("wheels"):
        return "wheel"
    if entry.get("sdist"):
        return "sdist"
    return "registry"


def parse_poetry_lock(text: str) -> list[ParsedPackage]:
    data = tomllib.loads(text)
    packages = []
    for entry in data.get("package", []):
        name, version = entry.get("name"), entry.get("version")
        if not name or not version:
            continue
        files = entry.get("files") or []
        hash_value = files[0].get("hash") if files and isinstance(files[0], dict) else None
        group = "dev" if entry.get("category") == "dev" else "default"
        packages.append(ParsedPackage("python", name, version, hash_value, "registry", group))
    return packages


def parse_requirements(text: str) -> list[ParsedPackage]:
    packages = []
    for line in text.splitlines():
        match = _REQ_LINE.match(line)
        if not match:
            continue
        hash_match = _REQ_HASH.search(line)
        packages.append(
            ParsedPackage(
                "python", match.group(1), match.group(2),
                hash_match.group(1) if hash_match else None, "registry", "default",
            )
        )
    return packages


def parse_pylock(text: str) -> list[ParsedPackage]:
    """Parse a PEP 751 pylock.toml."""
    data = tomllib.loads(text)
    packages = []
    for entry in data.get("packages", []):
        name, version = entry.get("name"), entry.get("version")
        if not name or not version:
            continue
        packages.append(
            ParsedPackage("python", name, version, _pylock_hash(entry), "registry", "default")
        )
    return packages


def _pylock_hash(entry: dict) -> str | None:
    for key in ("sdist", "wheels"):
        value = entry.get(key)
        if isinstance(value, dict) and value.get("hashes"):
            return next(iter(value["hashes"].items()), (None, None))[1]
        if isinstance(value, list) and value and value[0].get("hashes"):
            return next(iter(value[0]["hashes"].values()), None)
    return None
