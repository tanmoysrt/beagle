from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import tarfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from beagle.service.container import ServiceContainer
from beagle.service.dependencies.js_manifests import parse_pnpm_lock, parse_yarn_lock
from beagle.service.dependencies.registry import NpmRegistry, PythonRegistry


# --- lockfile parsers -----------------------------------------------------

def test_parse_pnpm_lock():
    text = (
        "lockfileVersion: '9.0'\n"
        "packages:\n"
        "  vue@3.4.0:\n"
        "    resolution: {integrity: sha512-abc}\n"
        "  '@scope/util@2.0.0':\n"
        "    resolution: {integrity: sha512-def}\n"
    )
    packages = {p.name: p for p in parse_pnpm_lock(text)}
    assert packages["vue"].version == "3.4.0"
    assert packages["vue"].hash == "sha512-abc"
    assert packages["@scope/util"].version == "2.0.0"


def test_parse_yarn_lock():
    text = (
        '# yarn lockfile v1\n\n'
        '"@scope/pkg@^1.0.0", "@scope/pkg@~1.2.0":\n'
        '  version "1.2.3"\n'
        '  resolved "https://r/x"\n\n'
        'lodash@^4.0.0:\n'
        '  version "4.17.21"\n'
    )
    packages = {p.name: p for p in parse_yarn_lock(text)}
    assert packages["@scope/pkg"].version == "1.2.3"
    assert packages["lodash"].version == "4.17.21"


# --- local fixture registry ----------------------------------------------

def _build_wheel() -> bytes:
    """A pure-python wheel exposing frappe.model.document.Document."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("frappe/__init__.py", "")
        zf.writestr("frappe/model/__init__.py", "")
        zf.writestr(
            "frappe/model/document.py",
            "class Document:\n    def save(self):\n        return True\n",
        )
        zf.writestr("frappe-15.0.0.dist-info/METADATA", "Name: frappe\nVersion: 15.0.0\n")
    return buffer.getvalue()


def _build_npm_tarball() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        content = b"export function createApp() { return {}; }\n"
        info = tarfile.TarInfo("package/index.js")
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
        pkg = b'{"name":"vue","version":"3.4.0"}'
        pinfo = tarfile.TarInfo("package/package.json")
        pinfo.size = len(pkg)
        tar.addfile(pinfo, io.BytesIO(pkg))
    return buffer.getvalue()


class _RegistryHandler(BaseHTTPRequestHandler):
    wheel = _build_wheel()
    tarball = _build_npm_tarball()

    def log_message(self, *args):  # silence
        pass

    def do_GET(self):
        wheel_sha = hashlib.sha256(self.wheel).hexdigest()
        import base64
        tar_integrity = "sha512-" + base64.b64encode(hashlib.sha512(self.tarball).digest()).decode()
        host = self.headers.get("Host")
        if self.path == "/pypi/frappe/15.0.0/json":
            self._json({"urls": [{
                "filename": "frappe-15.0.0-py3-none-any.whl",
                "url": f"http://{host}/files/frappe.whl",
                "digests": {"sha256": wheel_sha},
                "packagetype": "bdist_wheel",
            }]})
        elif self.path == "/files/frappe.whl":
            self._bytes(self.wheel)
        elif self.path == "/npm/vue":
            self._json({"versions": {"3.4.0": {"dist": {
                "tarball": f"http://{host}/files/vue.tgz",
                "integrity": tar_integrity,
            }}}})
        elif self.path == "/files/vue.tgz":
            self._bytes(self.tarball)
        else:
            self.send_error(404)

    def _json(self, obj):
        self._bytes(json.dumps(obj).encode(), "application/json")

    def _bytes(self, data, content_type="application/octet-stream"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def registry_server():
    server = HTTPServer(("127.0.0.1", 0), _RegistryHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base
    finally:
        server.shutdown()


def test_python_registry_download_verifies_hash(registry_server):
    registry = PythonRegistry(index_url=f"{registry_server}/pypi")
    artifact = registry.download("frappe", "15.0.0")
    assert artifact.kind == "wheel"
    assert artifact.hash.startswith("sha256:")


def test_npm_registry_download_verifies_hash(registry_server):
    registry = NpmRegistry(registry_url=f"{registry_server}/npm")
    artifact = registry.download("vue", "3.4.0")
    assert artifact.kind == "tarball"
    assert artifact.hash.startswith("sha512-")


# --- full cross-package resolution ---------------------------------------

def _git(cwd, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "U", "GIT_AUTHOR_EMAIL": "u@e.com",
           "GIT_COMMITTER_NAME": "U", "GIT_COMMITTER_EMAIL": "u@e.com"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)


@pytest.fixture
def project(config, tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir(parents=True)
    _git(upstream, "init", "--quiet", "-b", "main")
    (upstream / "uv.lock").write_text(
        '[[package]]\nname = "frappe"\nversion = "15.0.0"\n'
    )
    (upstream / "site.py").write_text(
        "from frappe.model.document import Document\n\n"
        "class Site(Document):\n    def deploy(self):\n        return self.save()\n"
    )
    _git(upstream, "add", ".")
    _git(upstream, "commit", "--quiet", "-m", "app")
    container = ServiceContainer(config).setup()
    with container.database.connect() as conn:
        org = container.identity.create_organization(conn, "frappe", "Frappe")
        repo = container.repository_service.register(conn, org.id, "press", "Press", str(upstream))
        container.repository_service.sync(conn, repo.id)
    return container, repo.id


def test_resolve_revision_links_project_to_dependency(project, registry_server):
    container, repo_id = project
    # Point the resolution service at the local fixture registry.
    container.dependency_resolution._python = PythonRegistry(index_url=f"{registry_server}/pypi")
    sha = container.mirror.resolve(repo_id, "refs/beagle/upstream/heads/main")
    container.dependency_service.analyze_revision(repo_id, sha)

    summary = container.dependency_resolution.resolve_revision(repo_id, sha)
    assert summary.downloaded == 1
    assert summary.indexed_modules >= 1
    assert summary.resolved >= 1

    with container.database.connect() as conn:
        resolutions = container.dependency_resolution.list_resolutions(conn, repo_id, sha)
    document = [r for r in resolutions if r["symbol"] == "Document"]
    assert document and document[0]["resolved"] == 1
    assert document[0]["package"] == "frappe"
    assert document[0]["version"] == "15.0.0"


def test_artifact_cache_reuses_by_hash(project, registry_server):
    container, repo_id = project
    registry = PythonRegistry(index_url=f"{registry_server}/pypi")
    artifact = registry.download("frappe", "15.0.0")
    first = container.artifact_cache.acquire(artifact)
    second = container.artifact_cache.acquire(artifact)
    assert first.index_path == second.index_path
    assert Path(first.index_path).exists()
    assert first.module_count >= 1
