from __future__ import annotations

import os
import subprocess

import pytest
from fastapi.testclient import TestClient

from beagle.service.config import ServiceConfig
from beagle.service.api.app import create_app


@pytest.fixture
def admin_config(tmp_path) -> ServiceConfig:
    return ServiceConfig(
        database_url=f"sqlite:///{tmp_path / 'svc.db'}",
        repo_storage_root=tmp_path / "repos",
        jwt_secret="test-secret-do-not-use-in-prod-0123456789",
        admin_password="hunter2",
    )


@pytest.fixture
def client(admin_config):
    return TestClient(create_app(admin_config))


def _login(client, password="hunter2"):
    res = client.post("/v1/admin/login", json={"password": password})
    return res


def _admin_headers(client):
    token = _login(client).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_admin_page_served(client):
    page = client.get("/admin")
    assert page.status_code == 200
    assert "beagle" in page.text and "Admin password" in page.text


def test_login_rejects_wrong_password(client):
    assert _login(client, "wrong").status_code == 401


def test_login_returns_admin_token(client):
    res = _login(client)
    assert res.status_code == 200
    assert res.json()["token"]


def test_login_disabled_without_password(tmp_path):
    config = ServiceConfig(
        database_url=f"sqlite:///{tmp_path / 's.db'}",
        repo_storage_root=tmp_path / "r",
        jwt_secret="test-secret-do-not-use-in-prod-0123456789",
        admin_password=None,
    )
    client = TestClient(create_app(config))
    # Disabled -> not a successful login (500 service error, not a token).
    res = client.post("/v1/admin/login", json={"password": "anything"})
    assert res.status_code >= 400
    assert "token" not in res.json()


def test_admin_can_create_user_and_list(client):
    headers = _admin_headers(client)
    created = client.post("/v1/users", json={"username": "alice", "email": "a@e.com"}, headers=headers)
    assert created.status_code == 200
    assert created.json()["user"]["username"] == "alice"
    users = client.get("/v1/users", headers=headers).json()["users"]
    # admin user is auto-provisioned on login, plus alice
    assert {"admin", "alice"} <= {u["username"] for u in users}


def test_admin_mint_token_for_user_defaults_to_all_repos(client):
    headers = _admin_headers(client)
    client.post("/v1/users", json={"username": "alice"}, headers=headers)
    res = client.post("/v1/admin/tokens", json={"user": "alice"}, headers=headers).json()
    assert res["user"] == "alice"
    assert res["repositories"] == ["*"]
    assert res["jti"].startswith("token_")


def test_minted_token_actually_works(client):
    # A token minted via the admin UI must authenticate against the API.
    headers = _admin_headers(client)
    client.post("/v1/users", json={"username": "alice"}, headers=headers)
    token = client.post("/v1/admin/tokens", json={"user": "alice"}, headers=headers).json()["token"]
    me = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "alice"
    assert me.json()["repositories"] == ["*"]


def test_user_endpoints_require_admin(client):
    # A plain token (minted for a normal user) cannot create users.
    headers = _admin_headers(client)
    client.post("/v1/users", json={"username": "alice"}, headers=headers)
    plain = client.post(
        "/v1/admin/tokens",
        json={"user": "alice", "permissions": ["source:read"], "repositories": ["press"]},
        headers=headers,
    ).json()["token"]
    res = client.post(
        "/v1/users", json={"username": "bob"},
        headers={"Authorization": f"Bearer {plain}"},
    )
    assert res.status_code == 403
