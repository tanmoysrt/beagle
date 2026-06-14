from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from beagle.service.container import ServiceContainer


def _commit(cwd, message, author, committer, when):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": author[0], "GIT_AUTHOR_EMAIL": author[1],
        "GIT_COMMITTER_NAME": committer[0], "GIT_COMMITTER_EMAIL": committer[1],
        "GIT_AUTHOR_DATE": f"{when} +0000", "GIT_COMMITTER_DATE": f"{when} +0000",
    }
    subprocess.run(["git", *message], cwd=cwd, env=env, check=True, capture_output=True, text=True)


def _upstream(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", "-b", "main"], cwd=path, check=True,
                   capture_output=True)
    (path / "a.txt").write_text("a\n")
    subprocess.run(["git", "add", "a.txt"], cwd=path, check=True, capture_output=True)
    _commit(
        path,
        ["commit", "--quiet", "-m",
         "feat: thing\n\nBody.\n\nCo-authored-by: Alice <alice@example.com>\n"
         "Signed-off-by: Bob <bob@example.com>"],
        author=("Tanmoy", "tanmoy@example.com"),
        committer=("Maint", "maint@example.com"),
        when=1_781_400_001,
    )


@pytest.fixture
def container(config, tmp_path):
    _upstream(tmp_path / "upstream")
    c = ServiceContainer(config).setup()
    c._upstream = str(tmp_path / "upstream")
    return c


def _register_and_sync(container, with_user_email=None):
    with container.database.connect() as conn:
        org = container.identity.create_organization(conn, "frappe", "Frappe")
        if with_user_email:
            container.identity.create_user(conn, org.id, "tanmoy", "Tanmoy", with_user_email)
        repo = container.repository_service.register(
            conn, org.id, "press", "Press", container._upstream
        )
        container.repository_service.sync(conn, repo.id)
        return org.id


def test_identities_harvested_from_all_roles(container):
    org_id = _register_and_sync(container)
    with container.database.connect() as conn:
        identities = {i.email: i for i in container.git_identities.list_identities(conn, org_id)}
    assert set(identities) == {
        "tanmoy@example.com", "maint@example.com", "alice@example.com", "bob@example.com"
    }
    # Author has a commit count; committer-only and trailer-only identities do not.
    assert identities["tanmoy@example.com"].commit_count == 1
    assert identities["maint@example.com"].commit_count == 0
    assert identities["alice@example.com"].name == "Alice"


def test_unclaimed_by_default(container):
    org_id = _register_and_sync(container)
    with container.database.connect() as conn:
        identities = container.git_identities.list_identities(conn, org_id)
    assert all(i.verified_user_id is None for i in identities)


def test_auto_map_by_verified_email(container):
    org_id = _register_and_sync(container, with_user_email="tanmoy@example.com")
    with container.database.connect() as conn:
        ident = container.git_identities.get(conn, org_id, "tanmoy@example.com")
        # Other identities stay unclaimed — no display-name guessing.
        alice = container.git_identities.get(conn, org_id, "alice@example.com")
    assert ident.verified_user_id is not None
    assert ident.verification_method == "email"
    assert alice.verified_user_id is None


def test_explicit_map_and_multiple_emails(container):
    org_id = _register_and_sync(container, with_user_email="tanmoy@example.com")
    with container.database.connect() as conn:
        user = container.identity.create_user(conn, org_id, "bob", "Bob", "bob-primary@x.com")
        # Bob's historical git email differs from his account email — map explicitly.
        container.git_identities.map_identity(conn, org_id, "bob@example.com", user.id, "admin")
        mine = container.git_identities.list_for_user(conn, org_id, user.id)
    assert [i.email for i in mine] == ["bob@example.com"]


def test_harvest_is_idempotent(container):
    org_id = _register_and_sync(container, with_user_email="tanmoy@example.com")
    with container.database.connect() as conn:
        container.git_identities.harvest(conn, org_id)
        again = container.git_identities.list_identities(conn, org_id)
        ident = container.git_identities.get(conn, org_id, "tanmoy@example.com")
    assert len(again) == 4
    # Re-harvest must not clobber an existing mapping.
    assert ident.verified_user_id is not None
