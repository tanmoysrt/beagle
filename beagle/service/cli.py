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


@app.command("user-list")
def user_list(
    organization_id: str,
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    """List users in an organization (id, username, email)."""
    container = _container(database_url, repo_root, secret)
    with container.database.connect() as conn:
        users = container.identity.list_users(conn, organization_id)
    for user in users:
        typer.echo(f"{user.id}  {user.username}  <{user.email}>")


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
    typer.echo(f"synced {result.ref_count} refs, indexed {result.commit_count} new commits")


@app.command("commit-search")
def commit_search(
    repository_id: str, query: str,
    limit: int = typer.Option(20, "--limit"),
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    container = _container(database_url, repo_root, secret)
    with container.database.connect() as conn:
        commits = container.commits.search(conn, repository_id, query, limit)
    for commit in commits:
        typer.echo(f"{commit['sha'][:12]}  {commit['subject']}")


@app.command("commit-show")
def commit_show(
    repository_id: str, sha: str,
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    container = _container(database_url, repo_root, secret)
    with container.database.connect() as conn:
        commit = container.commits.get_commit(conn, repository_id, sha)
    typer.echo(f"{commit['sha']}  ({commit['author_name']} <{commit['author_email']}>)")
    typer.echo(commit["subject"])
    if commit["trailers"]:
        typer.echo("trailers: " + ", ".join(f"{t['key']}={t['value']}" for t in commit["trailers"]))


@app.command("grant")
def grant(
    user: str, repository_id: str, permissions: str,
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    """Grant repository access. USER is a user id or username. PERMISSIONS is comma-separated."""
    container = _container(database_url, repo_root, secret)
    perms = [p.strip() for p in permissions.split(",") if p.strip()]
    with container.database.connect() as conn:
        resolved = container.identity.resolve_user(conn, user)
        container.identity.grant_access(conn, resolved.id, repository_id, perms)
    typer.echo("granted")


@app.command("token-mint")
def token_mint(
    user: str,
    repositories: str = typer.Option("", "--repos", help="comma-separated repo slugs"),
    permissions: str = typer.Option("source:read", "--permissions"),
    ttl_seconds: int = typer.Option(None, "--ttl"),
    label: str = typer.Option("", "--label"),
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    """Mint a JWT. USER is a user id or a username unique across organizations."""
    container = _container(database_url, repo_root, secret)
    repos = [r.strip() for r in repositories.split(",") if r.strip()]
    perms = [p.strip() for p in permissions.split(",") if p.strip()]
    with container.database.connect() as conn:
        resolved = container.identity.resolve_user(conn, user)
        token, record = container.jwt.mint(conn, resolved.id, repos, perms, ttl_seconds, label)
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


@app.command("index-revision")
def index_revision(
    repository_id: str, revision: str,
    history: int = typer.Option(0, "--history", help="also index N ancestors, parent-first"),
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    container = _container(database_url, repo_root, secret)
    if history:
        snapshots = container.revision_indexer.index_history(repository_id, revision, history)
        typer.echo(f"indexed/reused {len(snapshots)} snapshots")
        return
    snapshot = container.revision_indexer.index_revision(repository_id, revision)
    typer.echo(f"{snapshot.commit_sha[:12]}  {snapshot.status}  entities={snapshot.entity_count}")


@app.command("snapshot-list")
def snapshot_list(
    repository_id: str,
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    container = _container(database_url, repo_root, secret)
    with container.database.connect() as conn:
        snapshots = container.snapshots.list_for_repository(conn, repository_id)
    for snap in snapshots:
        typer.echo(f"{snap.commit_sha[:12]}  {snap.status}  entities={snap.entity_count}")


@app.command("episode-create")
def episode_create(
    repository_id: str, title: str, created_by: str,
    summary: str = typer.Option("", "--summary"),
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    container = _container(database_url, repo_root, secret)
    with container.database.connect() as conn:
        episode = container.decisions.create_episode(conn, repository_id, title, summary, created_by)
    typer.echo(episode.id)


@app.command("decision-record")
def decision_record(
    episode_id: str, repository_id: str, decision: str, created_by: str,
    problem: str = typer.Option("", "--problem"),
    rationale: str = typer.Option("", "--rationale"),
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    container = _container(database_url, repo_root, secret)
    with container.database.connect() as conn:
        rec = container.decisions.record_decision(
            conn, episode_id, repository_id, decision, created_by, problem, "", rationale
        )
    typer.echo(rec.id)


@app.command("decision-history")
def decision_history(
    repository_id: str,
    entity: str = typer.Option(None, "--entity"),
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    container = _container(database_url, repo_root, secret)
    with container.database.connect() as conn:
        decisions = container.decisions.list_decisions(conn, repository_id, entity)
    for dec in decisions:
        roles = ", ".join(f"{a['role']}:{a['confirmation_state']}" for a in dec["actors"])
        typer.echo(f"{dec['id'][:12]}  [{dec['status']}]  {dec['decision']}  ({roles})")


@app.command("feedback-record")
def feedback_record(
    repository_id: str, comment: str, author_user_id: str,
    entity: str = typer.Option(None, "--entity"),
    revision: str = typer.Option(None, "--revision"),
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    container = _container(database_url, repo_root, secret)
    with container.database.connect() as conn:
        item = container.feedback.record(
            conn, repository_id, comment, author_user_id, None, revision, entity
        )
    typer.echo(item.id)


@app.command("workspace-create")
def workspace_create(
    repository_id: str, user_id: str, base_commit: str,
    patch_file: str = typer.Option(None, "--patch-file"),
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    container = _container(database_url, repo_root, secret)
    patch = Path(patch_file).read_text() if patch_file else ""
    overlay = container.workspace_service.create(user_id, repository_id, base_commit, patch)
    typer.echo(f"{overlay.id}  snapshot={overlay.snapshot_id}")


@app.command("dependencies")
def dependencies(
    repository_id: str, revision: str,
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    container = _container(database_url, repo_root, secret)
    result = container.dependency_service.analyze_revision(repository_id, revision)
    typer.echo(f"{result.package_count} packages from {', '.join(result.sources) or '(none)'}")


@app.command("resolve-dependencies")
def resolve_dependencies(
    repository_id: str, revision: str,
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    """Download dependency source and resolve project imports across packages."""
    container = _container(database_url, repo_root, secret)
    summary = container.dependency_resolution.resolve_revision(repository_id, revision)
    typer.echo(f"downloaded {summary.downloaded} packages, {summary.indexed_modules} modules")
    typer.echo(f"resolved {summary.resolved}, unresolved {summary.unresolved}")


@app.command("compare-revisions")
def compare_revisions(
    repository_id: str, base: str, head: str,
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    container = _container(database_url, repo_root, secret)
    result = container.revision_comparer.compare(repository_id, base, head)
    typer.echo(f"files changed: {len(result.changed_files)}")
    typer.echo(f"entities +{len(result.entities_added)} "
               f"-{len(result.entities_removed)} ~{len(result.entities_changed)}")
    typer.echo(f"commits: {len(result.commits)}  authors: {', '.join(result.authors)}")


@app.command("identity-list")
def identity_list(
    organization_id: str,
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    container = _container(database_url, repo_root, secret)
    with container.database.connect() as conn:
        identities = container.git_identities.list_identities(conn, organization_id)
    for ident in identities:
        owner = ident.verified_user_id or "(unclaimed)"
        typer.echo(f"{ident.email}  {ident.name}  commits={ident.commit_count}  -> {owner}")


@app.command("identity-harvest")
def identity_harvest(
    organization_id: str,
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    """Recompute Git identities from indexed commits and auto-map by email."""
    container = _container(database_url, repo_root, secret)
    with container.database.connect() as conn:
        count = container.git_identities.harvest(conn, organization_id)
        mapped = container.git_identities.auto_map_by_email(conn, organization_id)
    typer.echo(f"harvested {count} identities, auto-mapped {mapped}")


@app.command("identity-map")
def identity_map(
    organization_id: str, email: str, user_id: str,
    method: str = typer.Option("admin", "--method"),
    database_url: str = _DB, repo_root: str = _ROOT, secret: str = _SECRET,
) -> None:
    container = _container(database_url, repo_root, secret)
    with container.database.connect() as conn:
        container.git_identities.map_identity(conn, organization_id, email, user_id, method)
    typer.echo("mapped")


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
