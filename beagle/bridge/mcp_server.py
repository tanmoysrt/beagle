"""Read-only MCP server bridging Claude Code to the shared service (Phase I).

Exposes the service's revision-aware retrieval over MCP. Every tool forwards to
the shared service through :class:`ServiceClient` with the developer's JWT, so
all results are scoped to the authenticated user and the repository permissions
on their token. The server is read-only — it never mutates the service.

Configuration (environment):
    BEAGLE_SERVICE_URL   the shared service base URL
    BEAGLE_TOKEN         the developer JWT (or stored via `beagle-bridge login`)
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from beagle.bridge.client import ServiceClient
from beagle.bridge.token_store import TokenStore


def build_server(client: ServiceClient) -> FastMCP:
    mcp = FastMCP(
        "beagle-service",
        instructions=(
            "Revision-aware code intelligence from the shared Beagle service. "
            "Every operation is scoped to a repository and a commit. Use "
            "current_user to confirm identity and scopes, commit_history / "
            "search_commits for history, revision_search to find entities at a "
            "commit, compare_revisions for what changed, and decision_history / "
            "feedback_history for why. Results reflect your token's permissions."
        ),
    )

    def current_user() -> dict:
        """The authenticated user, repository scopes, and permissions."""
        return client.whoami()

    def list_repositories() -> list[dict]:
        """Repositories visible to the authenticated user."""
        return client.list_repositories()

    def commit_history(repository_id: str, limit: int = 20) -> list[dict]:
        """Recent commits for a repository (newest first)."""
        return client.commit_history(repository_id, limit)

    def search_commits(repository_id: str, query: str) -> list[dict]:
        """Search commit subjects, bodies, identities, and trailers."""
        return client.search_commits(repository_id, query)

    def revision_search(repository_id: str, revision: str, query: str) -> list[dict]:
        """Search entities (functions, classes, modules) at an exact commit."""
        return client.revision_search(repository_id, revision, query)

    def compare_revisions(repository_id: str, base: str, head: str) -> dict:
        """Changed files, entities, commits, and authors between two revisions."""
        return client.compare(repository_id, base, head)

    def decision_history(repository_id: str, entity: str = "") -> list[dict]:
        """Recorded decisions for a repository, optionally filtered by entity id."""
        return client.decision_history(repository_id, entity or None)

    def feedback_history(repository_id: str, entity: str = "") -> list[dict]:
        """Recorded feedback for a repository, optionally filtered by entity id."""
        return client.feedback_history(repository_id, entity or None)

    def dependency_resolutions(repository_id: str, revision: str) -> list[dict]:
        """Project imports resolved to exact dependency versions at a revision."""
        return client.dependency_resolutions(repository_id, revision)

    for func in (
        current_user, list_repositories, commit_history, search_commits,
        revision_search, compare_revisions, decision_history, feedback_history,
        dependency_resolutions,
    ):
        mcp.add_tool(func, description=(func.__doc__ or "").strip())
    return mcp


def main() -> None:
    url = os.environ.get("BEAGLE_SERVICE_URL")
    if not url:
        raise SystemExit("BEAGLE_SERVICE_URL is required")
    token = TokenStore().get()
    if not token:
        raise SystemExit("no token; run 'beagle-bridge login' first")
    build_server(ServiceClient(url, token)).run()


if __name__ == "__main__":
    main()
