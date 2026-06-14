"""Registry download for exact dependency artifacts (design/15 §12).

Downloads pinned artifacts from PyPI and the npm registry and verifies their
integrity. Nothing is executed: no build backends, no install scripts. The HTTP
fetch is a single overridable method so tests can point at a local fixture
server. Network is used only here, never during indexing of the bytes.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass

from beagle.service.dependencies.safe_acquire import verify_hash
from beagle.service.errors import ServiceError, ValidationError


@dataclass
class DownloadedArtifact:
    ecosystem: str
    name: str
    version: str
    data: bytes
    hash: str
    kind: str           # wheel | sdist | tarball
    filename: str


class _BaseRegistry:
    def _get(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": "beagle-service"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except OSError as exc:
            raise ServiceError(f"registry fetch failed: {url}: {exc}") from exc


class PythonRegistry(_BaseRegistry):
    """Downloads wheels/sdists from a PyPI-compatible JSON index."""

    def __init__(self, index_url: str = "https://pypi.org/pypi"):
        self._index = index_url.rstrip("/")

    def download(
        self, name: str, version: str, expected_hash: str | None = None
    ) -> DownloadedArtifact:
        metadata = json.loads(self._get(f"{self._index}/{name}/{version}/json"))
        chosen = self._choose_file(metadata.get("urls", []))
        data = self._get(chosen["url"])
        digest = expected_hash or f"sha256:{chosen['digests']['sha256']}"
        if not verify_hash(data, digest):
            raise ValidationError(f"hash mismatch for {name}=={version}")
        kind = "wheel" if chosen["filename"].endswith(".whl") else "sdist"
        return DownloadedArtifact(
            "python", name, version, data, digest, kind, chosen["filename"]
        )

    @staticmethod
    def _choose_file(urls: list[dict]) -> dict:
        wheels = [u for u in urls if u.get("filename", "").endswith(".whl")]
        # Prefer a pure-python wheel, then any wheel, then an sdist.
        for wheel in wheels:
            if "py3-none-any" in wheel["filename"] or "py2.py3" in wheel["filename"]:
                return wheel
        if wheels:
            return wheels[0]
        sdists = [u for u in urls if u.get("packagetype") == "sdist"]
        if sdists:
            return sdists[0]
        raise ServiceError("no downloadable artifact in registry metadata")


class NpmRegistry(_BaseRegistry):
    """Downloads tarballs from an npm-compatible registry."""

    def __init__(self, registry_url: str = "https://registry.npmjs.org"):
        self._registry = registry_url.rstrip("/")

    def download(
        self, name: str, version: str, expected_hash: str | None = None
    ) -> DownloadedArtifact:
        metadata = json.loads(self._get(f"{self._registry}/{name}"))
        release = metadata.get("versions", {}).get(version)
        if not release:
            raise ServiceError(f"version not found in registry: {name}@{version}")
        dist = release["dist"]
        data = self._get(dist["tarball"])
        digest = expected_hash or dist.get("integrity") or f"sha1:{dist.get('shasum', '')}"
        if not verify_hash(data, digest):
            raise ValidationError(f"hash mismatch for {name}@{version}")
        return DownloadedArtifact(
            "javascript", name, version, data, digest, "tarball",
            dist["tarball"].rsplit("/", 1)[-1],
        )
