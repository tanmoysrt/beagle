from __future__ import annotations

import base64

import pytest

from beagle.service.errors import PermissionDenied
from beagle.service.jwt_service import AuthenticatedIdentity
from beagle.service import permissions
from beagle.service.git import smart_http


def _identity(perms, repos=("press",)):
    return AuthenticatedIdentity("user_1", "org_1", list(repos), list(perms), "token_1")


def test_upload_pack_requires_source_read():
    smart_http.authorize_git_service(
        _identity([permissions.SOURCE_READ]), "press", "git-upload-pack"
    )
    with pytest.raises(PermissionDenied):
        smart_http.authorize_git_service(
            _identity([permissions.REPO_SYNC]), "press", "git-upload-pack"
        )


def test_receive_pack_requires_write_scope():
    smart_http.authorize_git_service(
        _identity([permissions.REPO_SYNC]), "press", "git-receive-pack"
    )
    smart_http.authorize_git_service(
        _identity([permissions.WORKSPACE_CREATE]), "press", "git-receive-pack"
    )
    with pytest.raises(PermissionDenied):
        smart_http.authorize_git_service(
            _identity([permissions.SOURCE_READ]), "press", "git-receive-pack"
        )


def test_repository_scope_enforced():
    with pytest.raises(PermissionDenied):
        smart_http.authorize_git_service(
            _identity([permissions.SOURCE_READ], repos=("frappe",)),
            "press",
            "git-upload-pack",
        )


def test_extract_token_bearer_and_basic():
    assert smart_http._extract_token({"authorization": "Bearer abc.def"}) == "abc.def"
    basic = base64.b64encode(b"beagle:tok123").decode()
    assert smart_http._extract_token({"authorization": f"Basic {basic}"}) == "tok123"
    assert smart_http._extract_token({}) is None


def test_resolve_service():
    assert (
        smart_http._resolve_service("GET", "info/refs", "service=git-upload-pack")
        == "git-upload-pack"
    )
    assert (
        smart_http._resolve_service("POST", "git-receive-pack", "")
        == "git-receive-pack"
    )
    with pytest.raises(PermissionDenied):
        smart_http._resolve_service("GET", "info/refs", "")
