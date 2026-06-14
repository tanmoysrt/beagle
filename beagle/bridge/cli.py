"""Local bridge CLI (``beagle-bridge``).

Stores the developer token, authenticates against the shared service, and
synchronizes the current repository's HEAD with the minimum upload.
"""

from __future__ import annotations

import os
from pathlib import Path

import typer

from beagle.bridge.client import ServiceClient
from beagle.bridge.local_repo import LocalRepository
from beagle.bridge.session import BridgeSession
from beagle.bridge.token_store import TokenStore
from beagle.discovery import find_repo_root

app = typer.Typer(help="Beagle local bridge.", no_args_is_help=True)

_URL = typer.Option(None, "--service-url", envvar="BEAGLE_SERVICE_URL")


def _client(service_url: str | None) -> ServiceClient:
    url = service_url or os.environ.get("BEAGLE_SERVICE_URL")
    if not url:
        raise typer.BadParameter("service URL required (--service-url or BEAGLE_SERVICE_URL)")
    token = TokenStore().get()
    if not token:
        raise typer.BadParameter("no token stored; run 'beagle-bridge login' first")
    return ServiceClient(url, token)


@app.command()
def login(token: str = typer.Option(..., "--token", prompt=True, hide_input=True)) -> None:
    """Store the developer token locally (never in the repository)."""
    TokenStore().set(token)
    typer.echo("token stored")


@app.command()
def whoami(service_url: str = _URL) -> None:
    identity = _client(service_url).whoami()
    typer.echo(f"{identity['user']['username']} ({identity['user']['id']})")
    typer.echo(f"repositories: {', '.join(identity['repositories']) or '(none)'}")


@app.command()
def sync(
    repository_slug: str,
    service_url: str = _URL,
    local_only: bool = typer.Option(False, "--local-only"),
    upload_dirty: bool = typer.Option(False, "--upload-dirty",
                                      help="send uncommitted changes as a workspace overlay"),
) -> None:
    """Synchronize the current repository's HEAD with the service."""
    root = find_repo_root(Path.cwd())
    session = BridgeSession(_client(service_url), LocalRepository(root))
    outcome = session.ensure_head_synced(
        repository_slug, local_only=local_only, upload_dirty=upload_dirty
    )
    typer.echo(f"head {outcome.head[:12]} on {outcome.branch}")
    typer.echo(f"pushed={outcome.pushed} indexed={outcome.indexed} "
               f"dirty={outcome.dirty} local_only={outcome.local_only} "
               f"workspace={outcome.workspace_id or '-'}")


if __name__ == "__main__":
    app()
