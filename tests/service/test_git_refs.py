from __future__ import annotations

from beagle.service.git import refs


def test_namespace_builders():
    assert refs.upstream_head("develop") == "refs/beagle/upstream/heads/develop"
    assert refs.upstream_tag("v1.0") == "refs/beagle/upstream/tags/v1.0"
    assert refs.user_head("user_1", "wip") == "refs/beagle/users/user_1/heads/wip"
    assert refs.workspace_ref("user_1", "ws_9") == "refs/beagle/workspaces/user_1/ws_9"


def test_classify_namespace():
    assert refs.classify_namespace("refs/beagle/upstream/heads/main") == "upstream"
    assert refs.classify_namespace("refs/beagle/upstream/tags/v1") == "upstream"
    assert refs.classify_namespace("refs/beagle/users/u1/heads/x") == "user"
    assert refs.classify_namespace("refs/beagle/workspaces/u1/w1") == "workspace"
    assert refs.classify_namespace("refs/heads/main") == "other"


def test_push_authorization():
    # Owner may push to their own user and workspace namespaces.
    assert refs.is_push_allowed("u1", "refs/beagle/users/u1/heads/feature")
    assert refs.is_push_allowed("u1", "refs/beagle/workspaces/u1/ws1")
    # Never to upstream, another user, or outside the Beagle namespaces.
    assert not refs.is_push_allowed("u1", "refs/beagle/upstream/heads/main")
    assert not refs.is_push_allowed("u1", "refs/beagle/users/u2/heads/feature")
    assert not refs.is_push_allowed("u1", "refs/heads/main")
    # An empty/unknown user authorizes nothing.
    assert not refs.is_push_allowed("", "refs/beagle/users//heads/x")
