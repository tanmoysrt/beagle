from __future__ import annotations

import hashlib
import io
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from beagle.service.container import ServiceContainer
from beagle.service.dependencies.js_manifests import parse_package_lock
from beagle.service.dependencies.python_manifests import parse_requirements, parse_uv_lock
from beagle.service.dependencies.safe_acquire import (
    safe_extract_tar,
    verify_hash,
)
from beagle.service.errors import ValidationError

UV_LOCK = """
version = 1

[[package]]
name = "requests"
version = "2.31.0"

[[package.wheels]]
url = "https://example/requests-2.31.0-py3-none-any.whl"
hash = "sha256:abc123"

[[package]]
name = "frappe"
version = "15.0.0"
source = { git = "https://github.com/frappe/frappe" }
"""

PACKAGE_LOCK = """
{
  "lockfileVersion": 3,
  "packages": {
    "": {"name": "app", "version": "1.0.0"},
    "node_modules/vue": {"version": "3.4.0", "integrity": "sha512-deadbeef", "resolved": "https://r/vue"},
    "node_modules/@scope/util": {"version": "2.0.0", "integrity": "sha512-cafe", "dev": true}
  }
}
"""


def test_parse_uv_lock():
    packages = {p.name: p for p in parse_uv_lock(UV_LOCK)}
    assert packages["requests"].version == "2.31.0"
    assert packages["requests"].hash == "sha256:abc123"
    assert packages["requests"].source_type == "wheel"
    assert packages["frappe"].source_type == "git"


def test_parse_requirements_with_hashes():
    text = "requests==2.31.0 --hash=sha256:abcd\n# comment\nflask==3.0.0\n"
    packages = {p.name: p for p in parse_requirements(text)}
    assert packages["requests"].hash == "sha256:abcd"
    assert packages["flask"].version == "3.0.0"
    assert packages["flask"].hash is None


def test_parse_package_lock_v3():
    packages = {p.name: p for p in parse_package_lock(PACKAGE_LOCK)}
    assert packages["vue"].version == "3.4.0"
    assert packages["vue"].hash == "sha512-deadbeef"
    assert packages["@scope/util"].group == "dev"


def test_verify_hash_both_styles():
    data = b"hello"
    sha256 = hashlib.sha256(data).hexdigest()
    assert verify_hash(data, f"sha256:{sha256}")
    assert not verify_hash(data, "sha256:0000")
    import base64
    b64 = base64.b64encode(hashlib.sha512(data).digest()).decode()
    assert verify_hash(data, f"sha512-{b64}")


def _make_tar(names_and_data: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in names_and_data.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def test_safe_extract_tar_ok(tmp_path):
    archive = _make_tar({"pkg/a.py": b"x=1\n", "pkg/b.py": b"y=2\n"})
    count = safe_extract_tar(archive, tmp_path)
    assert count == 2
    assert (tmp_path / "pkg" / "a.py").read_text() == "x=1\n"


def test_safe_extract_rejects_traversal(tmp_path):
    archive = _make_tar({"../escape.py": b"bad\n"})
    with pytest.raises(ValidationError):
        safe_extract_tar(archive, tmp_path)


def test_safe_extract_rejects_symlink(tmp_path):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        link = tarfile.TarInfo("evil")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tar.addfile(link)
    with pytest.raises(ValidationError):
        safe_extract_tar(buffer.getvalue(), tmp_path)


def test_safe_extract_enforces_file_limit(tmp_path):
    archive = _make_tar({f"f{i}.txt": b"x" for i in range(5)})
    with pytest.raises(ValidationError):
        safe_extract_tar(archive, tmp_path, max_files=3)


# --- end-to-end snapshot from a real revision -----------------------------

def _git(cwd, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "U", "GIT_AUTHOR_EMAIL": "u@e.com",
           "GIT_COMMITTER_NAME": "U", "GIT_COMMITTER_EMAIL": "u@e.com"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)


@pytest.fixture
def synced(config, tmp_path):
    upstream = tmp_path / "upstream"
    upstream.mkdir(parents=True)
    _git(upstream, "init", "--quiet", "-b", "main")
    (upstream / "uv.lock").write_text(UV_LOCK)
    (upstream / "package-lock.json").write_text(PACKAGE_LOCK)
    _git(upstream, "add", ".")
    _git(upstream, "commit", "--quiet", "-m", "deps")
    container = ServiceContainer(config).setup()
    with container.database.connect() as conn:
        org = container.identity.create_organization(conn, "frappe", "Frappe")
        repo = container.repository_service.register(conn, org.id, "app", "App", str(upstream))
        container.repository_service.sync(conn, repo.id)
    return container, repo.id


def test_analyze_revision_builds_snapshot(synced):
    container, repo_id = synced
    sha = container.mirror.resolve(repo_id, "refs/beagle/upstream/heads/main")
    result = container.dependency_service.analyze_revision(repo_id, sha)
    assert set(result.sources) == {"uv.lock", "package-lock.json"}
    assert result.package_count == 4  # requests, frappe, vue, @scope/util

    with container.database.connect() as conn:
        snapshot = container.dependencies.get_snapshot(conn, repo_id, sha)
        found = container.dependencies.search_packages(conn, repo_id, "vue")
    names = {p["name"] for p in snapshot["packages"]}
    assert {"requests", "frappe", "vue", "@scope/util"} <= names
    assert found[0]["name"] == "vue"


def test_analyze_is_idempotent(synced):
    container, repo_id = synced
    sha = container.mirror.resolve(repo_id, "refs/beagle/upstream/heads/main")
    container.dependency_service.analyze_revision(repo_id, sha)
    container.dependency_service.analyze_revision(repo_id, sha)
    with container.database.connect() as conn:
        snapshot = container.dependencies.get_snapshot(conn, repo_id, sha)
    assert snapshot["package_count"] == 4  # not doubled
