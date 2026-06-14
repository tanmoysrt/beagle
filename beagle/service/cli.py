"""Administrative CLI for the shared service (``beagle-service``).

Covers the design's simple authenticated admin flow (§3): create organizations
and users, grant repository access, mint and revoke tokens, register and sync
repositories, and run the API server. Configuration comes from options that fall
back to environment variables.
"""

from __future__ import annotations

from pathlib import Path

import typer

from beagle.service.config import ServiceConfig
from beagle.service.container import ServiceContainer

app = typer.Typer(help="Beagle shared service administration.", no_args_is_help=True)

_DB = typer.Option("sqlite:///beagle-service.db", "--database-url", envvar="BEAGLE_DATABASE_URL")
_ROOT = typer.Option("./beagle-repositories", "--repo-root", envvar="BEAGLE_REPO_ROOT")
_SECRET = typer.Option(..., "--secret", envvar="BEAGLE_SERVICE_SECRET")


def _container(database_url: str, repo_root: str, secret: str) -> ServiceContainer:
    config = ServiceConfig(
        database_url=database_url,
        repo_storage_root=Path(repo_root).resolve(),
        jwt_secret=secret,
    )
    return ServiceContainer(config).setup()


@app.command("init-db")
def init_db(database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET) -> None:
    """Create tables and the repository storage root."""
    _container(database_url, repo_root, secret)
    typer.echo("initialized")


@app.command("org-create")
def org_create(
    slug: str, name: str,
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    container = _container(database_url, repo_root, secret)
    with container.database.connect() as conn:
        org = container.identity.create_organization(conn, slug, name)
    typer.echo(org.id)


@app.command("user-create")
def user_create(
    organization_id: str, username: str, display_name: str, email: str,
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    container = _container(database_url, repo_root, secret)
    with container.database.connect() as conn:
        user = container.identity.create_user(conn, organization_id, username, display_name, email)
    typer.echo(user.id)


@app.command("repo-register")
def repo_register(
    organization_id: str, slug: str, name: str,
    remote_url: str = typer.Option(None, "--remote-url"),
    default_branch: str = typer.Option("main", "--default-branch"),
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    container = _container(database_url, repo_root, secret)
    with container.database.connect() as conn:
        repo = container.repository_service.register(
            conn, organization_id, slug, name, remote_url, default_branch
        )
    typer.echo(repo.id)


@app.command("repo-sync")
def repo_sync(
    repository_id: str,
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    container = _container(database_url, repo_root, secret)
    with container.database.connect() as conn:
        result = container.repository_service.sync(conn, repository_id)
    typer.echo(f"synced {result.ref_count} refs")


@app.command("grant")
def grant(
    user_id: str, repository_id: str, permissions: str,
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    """Grant repository access. PERMISSIONS is a comma-separated list."""
    container = _container(database_url, repo_root, secret)
    perms = [p.strip() for p in permissions.split(",") if p.strip()]
    with container.database.connect() as conn:
        container.identity.grant_access(conn, user_id, repository_id, perms)
    typer.echo("granted")


@app.command("token-mint")
def token_mint(
    user_id: str,
    repositories: str = typer.Option("", "--repos", help="comma-separated repo slugs"),
    permissions: str = typer.Option("source:read", "--permissions"),
    ttl_seconds: int = typer.Option(None, "--ttl"),
    label: str = typer.Option("", "--label"),
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    container = _container(database_url, repo_root, secret)
    repos = [r.strip() for r in repositories.split(",") if r.strip()]
    perms = [p.strip() for p in permissions.split(",") if p.strip()]
    with container.database.connect() as conn:
        token, record = container.jwt.mint(conn, user_id, repos, perms, ttl_seconds, label)
    typer.echo(f"jti: {record.jti}")
    typer.echo(token)


@app.command("token-revoke")
def token_revoke(
    jti: str,
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    container = _container(database_url, repo_root, secret)
    with container.database.connect() as conn:
        container.identity.revoke_token(conn, jti)
    typer.echo("revoked")


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    import uvicorn

    from beagle.service.api.app import create_app

    config = ServiceConfig(
        database_url=database_url,
        repo_storage_root=Path(repo_root).resolve(),
        jwt_secret=secret,
    )
    uvicorn.run(create_app(config), host=host, port=port)


if __name__ == "__main__":
    app()
