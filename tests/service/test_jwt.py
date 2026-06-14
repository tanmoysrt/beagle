from __future__ import annotations

import jwt as pyjwt
import pytest

from beagle.service.errors import AuthenticationError, PermissionDenied
from beagle.service.permissions import SOURCE_READ, REPO_SYNC


def _make_user(db, identity):
    with db.connect() as conn:
        org = identity.create_organization(conn, "frappe", "Frappe")
        user = identity.create_user(conn, org.id, "tanmoy", "Tanmoy", "t@example.com")
        return user


def test_mint_and_validate_roundtrip(db, identity, jwt_service):
    user = _make_user(db, identity)
    with db.connect() as conn:
        token, record = jwt_service.mint(
            conn, user.id, ["press", "frappe"], [SOURCE_READ, REPO_SYNC]
        )
    with db.connect() as conn:
        ident = jwt_service.validate(conn, token)
    assert ident.user_id == user.id
    assert ident.organization_id == user.organization_id
    assert ident.repositories == ["press", "frappe"]
    assert SOURCE_READ in ident.permissions
    assert ident.jti == record.jti


def test_unknown_permission_rejected_at_mint(db, identity, jwt_service):
    user = _make_user(db, identity)
    with db.connect() as conn:
        with pytest.raises(PermissionDenied):
            jwt_service.mint(conn, user.id, ["press"], ["source:read", "bogus:perm"])


def test_revoked_token_rejected(db, identity, jwt_service):
    user = _make_user(db, identity)
    with db.connect() as conn:
        token, record = jwt_service.mint(conn, user.id, ["press"], [SOURCE_READ])
    with db.connect() as conn:
        identity.revoke_token(conn, record.jti)
    with db.connect() as conn:
        with pytest.raises(AuthenticationError):
            jwt_service.validate(conn, token)


def test_expired_token_rejected(db, identity, jwt_service):
    user = _make_user(db, identity)
    with db.connect() as conn:
        token, _ = jwt_service.mint(
            conn, user.id, ["press"], [SOURCE_READ], ttl_seconds=-10
        )
    with db.connect() as conn:
        with pytest.raises(AuthenticationError):
            jwt_service.validate(conn, token)


def test_tampered_signature_rejected(db, identity, jwt_service):
    user = _make_user(db, identity)
    with db.connect() as conn:
        token, _ = jwt_service.mint(conn, user.id, ["press"], [SOURCE_READ])
    forged = pyjwt.encode(
        {**pyjwt.decode(token, options={"verify_signature": False})},
        "wrong-secret",
        algorithm="HS256",
    )
    with db.connect() as conn:
        with pytest.raises(AuthenticationError):
            jwt_service.validate(conn, forged)


def test_unrecorded_jti_rejected(db, identity, jwt_service, config):
    user = _make_user(db, identity)
    forged = pyjwt.encode(
        {
            "sub": user.id,
            "org": user.organization_id,
            "repos": [],
            "permissions": [SOURCE_READ],
            "iat": 1781395200,
            "exp": 4000000000,
            "jti": "token_never_recorded",
            "iss": config.jwt_issuer,
        },
        config.jwt_secret,
        algorithm="HS256",
    )
    with db.connect() as conn:
        with pytest.raises(AuthenticationError):
            jwt_service.validate(conn, forged)
