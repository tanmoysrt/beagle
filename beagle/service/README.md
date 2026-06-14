# Beagle shared service (design/15)

A revision-aware, multi-tenant code-intelligence service. This package is
independent of the local SQLite engine: it owns organizations, users, JWT
identity, Git repository mirrors, and the HTTP API.

**Implemented:** Phase A (JWT identity), Phase B (Git repository service),
Phase C (commit metadata indexing + search), Phase D (per-commit source
indexing), Phase G (Git identity mapping), Phase H (decision/feedback memory),
Phase I (compare revisions/branches, merge summary, read-only service MCP, CI
report, admin UI), Phase E (dependency parsing, registry download, hash
verification, archive-safe unpack, artifact caching, Python cross-package
resolution), and Phase F (local bridge: sync handshake, push-missing-commits,
dirty overlays, local-only mode — see `beagle/bridge/`). All design/15 phases
A–I are implemented; the one remaining sub-item is JS cross-package symbol edges
(JS dependency source is downloaded, verified, and indexed).

## Layout

| Module | Responsibility |
| --- | --- |
| `config.py` | Immutable deployment config (DB URL, repo root, JWT secret). |
| `db.py`, `schema.py` | Portable DB layer over SQLite (tests) and PostgreSQL (prod). |
| `models.py` | Dataclass views of records. |
| `permissions.py` | Permission vocabulary and checks. |
| `jwt_service.py` | Mint and validate signed HS256 tokens. |
| `identity.py` | Organizations, users, token records, repository access. |
| `sessions.py`, `audit.py` | MCP sessions and the audit log. |
| `repositories.py`, `repository_service.py` | Repository records + coordination with the mirror. |
| `git/commit_reader.py` | Parse reachable commit metadata from a bare repo. |
| `commit_store.py`, `commit_indexer.py` | Persist, search, and incrementally index commit metadata. |
| `git_identities.py` | Harvest Git identities and map them to verified users. |
| `snapshot_store.py`, `revision_indexer.py` | Per-commit immutable index snapshots (materialize tree + reuse the engine). |
| `revision_compare.py` | Compare revisions/branches and summarize merges (files, entities, commits, authors). |
| `decisions.py`, `feedback_store.py` | Change episodes, decisions + actors (roles/confirmation), feedback lifecycle. |
| `dependencies/`, `dependency_store.py`, `dependency_service.py` | Parse manifests/lockfiles, verify hashes, archive-safe unpack, dependency snapshots. |
| `dependencies/registry.py`, `artifact_cache.py`, `cross_resolve.py`, `dependency_resolution.py` | Download artifacts, index + cache by hash, resolve project imports to dependency symbols. |
| `workspaces.py`, `workspace_service.py` | Workspace overlays: base commit + local patch, indexed into a private snapshot. |
| `admin.py`, `admin_auth.py`, `api/admin_page.py` | Password-gated admin web UI: overview, users, repos, token generation. |
| `git/mirror.py` | Bare mirrors: init, fetch upstream, refs, integrity, `pre-receive` hook. |
| `git/refs.py` | Ref namespaces and push authorization. |
| `git/smart_http.py` | Authenticated `git http-backend` proxy. |
| `api/` | FastAPI app, routes, and the Git transport route. |
| `cli.py` | `beagle-service` administration CLI. |
| `container.py` | Composition root shared by the API and CLI. |

## Identity model

Code identity is `repository + commit`; a branch is a mutable pointer. The
service is the sole minter of JWTs (claims: `sub`, `org`, `repos`, `permissions`,
`iat`, `exp`, `jti`, `iss`). Tokens are revocable by `jti`. Validation verifies
signature, expiry, revocation, the user, and the organization, in that order.

Repository scoping and permissions are separate axes: a request is authorized
only when the token holds the required permission **and** names the target
repository slug.

## Git storage

Each registered repository is a bare mirror at `<repo-root>/<repository-id>.git`.
Upstream history is fetched into `refs/beagle/upstream/*` (canonical, trusted
only). Users push into their own `refs/beagle/users/<user-id>/*` and
`refs/beagle/workspaces/<user-id>/*` namespaces; a `pre-receive` hook rejects
anything else. Git objects move over Smart HTTP, never through the JSON API.

## Running

```bash
export BEAGLE_SERVICE_SECRET="<a long random secret>"      # token signing key
export BEAGLE_ADMIN_PASSWORD="<admin UI password>"         # enables /admin
export BEAGLE_DATABASE_URL="sqlite:///beagle-service.db"    # or postgresql://user:pass@host/beagle
export BEAGLE_REPO_ROOT="/var/lib/beagle/repositories"

beagle-service init-db
beagle-service serve --host 0.0.0.0 --port 8000 &

# Then manage everything from the web UI at http://localhost:8000/admin
# (sign in with BEAGLE_ADMIN_PASSWORD). The CLI below does the same headlessly.

# One team is the default — no organization to manage. `setup` creates the user
# and prints a full token (all permissions, all repositories).
beagle-service setup tanmoy --email t@example.com

REPO=$(beagle-service repo-register press "Press" --remote-url https://github.com/frappe/press)
beagle-service repo-sync "$REPO"
```

Finer-grained: `user-create`, `user-list`, `grant`, `token-mint`
(username or id), `token-revoke`. An additional organization is only needed for
multi-tenant installs (`org-create`, then pass `--org` to the commands above).

## HTTP API

All routes require `Authorization: Bearer <jwt>` (writes are rejected without it).

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/v1/me` | any valid token |
| GET | `/v1/repositories` | any valid token |
| POST | `/v1/repositories` | `repo:register` |
| GET | `/v1/repositories/{id}` | repo scope |
| POST | `/v1/repositories/{id}/sync` | `repo:sync` + repo scope |
| GET | `/v1/repositories/{id}/commits` | `source:read` + repo scope |
| GET | `/v1/repositories/{id}/commits/search?q=` | `source:read` + repo scope |
| GET | `/v1/repositories/{id}/commits/{sha}` | `source:read` + repo scope |
| POST | `/v1/repositories/{id}/revisions/{rev}/index` | `repo:sync` + repo scope |
| GET | `/v1/repositories/{id}/revisions/{rev}` | `source:read` + repo scope |
| GET | `/v1/repositories/{id}/revisions/{rev}/search?q=` | `source:read` + repo scope |
| GET | `/v1/repositories/{id}/snapshots` | `source:read` + repo scope |
| GET | `/v1/repositories/{id}/sync-status?head=` | `source:read` + repo scope |
| POST | `/v1/repositories/{id}/revisions/{rev}/dependencies` | `repo:sync` + repo scope |
| GET | `/v1/repositories/{id}/revisions/{rev}/dependencies` | `source:read` + repo scope |
| GET | `/v1/repositories/{id}/dependencies/search?q=` | `source:read` + repo scope |
| POST | `/v1/repositories/{id}/revisions/{rev}/dependencies/resolve` | `repo:sync` + repo scope |
| GET | `/v1/repositories/{id}/revisions/{rev}/dependencies/resolutions` | `source:read` + repo scope |
| POST | `/v1/repositories/{id}/workspaces` | `workspace:create` + repo scope |
| POST/GET | `/v1/workspaces/{wid}[/search]` | owner (or shared, for read) |
| POST | `/v1/workspaces/{wid}/share` | `workspace:share`, owner |
| DELETE | `/v1/workspaces/{wid}` | owner (or `admin:identity`) |
| GET | `/v1/repositories/{id}/compare?base=&head=` | `source:read` + repo scope |
| GET | `/v1/repositories/{id}/compare-branches?target=&source=` | `source:read` + repo scope |
| GET | `/v1/repositories/{id}/merge-summary/{rev}` | `source:read` + repo scope |
| POST | `/v1/repositories/{id}/episodes` | `decision:write` + repo scope |
| POST | `/v1/episodes/{eid}/decisions` | `decision:write` + repo scope |
| POST | `/v1/decisions/{did}/actors[/{aid}/confirm]` | `decision:write` |
| GET | `/v1/repositories/{id}/decisions?entity=` | `decision:read` + repo scope |
| POST | `/v1/repositories/{id}/feedback` | `feedback:write` + repo scope |
| POST | `/v1/feedback/{fid}/status` | `feedback:write` |
| GET | `/v1/repositories/{id}/feedback?entity=` | `feedback:read` + repo scope |
| POST | `/v1/sessions/{id}/summary` | session owner (or `admin:identity`) |
| POST | `/v1/admin/login` | admin password (`BEAGLE_ADMIN_PASSWORD`) |
| GET | `/v1/admin/overview` | `admin:identity` |
| POST/GET | `/v1/users` | `admin:identity` |
| POST | `/v1/admin/tokens` | `admin:identity` |
| GET | `/admin` | password-gated web UI |
| GET | `/v1/identities` | `admin:identity` |
| GET | `/v1/me/identities` | any valid token |
| POST | `/v1/identities/map` | `admin:identity` |
| POST | `/v1/identities/claim` | self (or `admin:identity` to override) |
| POST | `/v1/sessions` | any valid token |
| POST | `/v1/sessions/{id}/end` | owner (or `admin:identity`) |
| GET/POST | `/git/{repository-id}.git/...` | `source:read` (fetch) / `repo:sync`/`workspace:create` (push) |

Fetch a Beagle ref with the token, e.g.:

```bash
git -c http.extraHeader="Authorization: Bearer $TOKEN" \
    fetch http://host:8000/git/$REPO.git refs/beagle/upstream/heads/main
```

## Local bridge

The client-side bridge lives in `beagle/bridge/` (`beagle-bridge` CLI). It stores
the token locally (never in the repo), discovers the working repository, and
synchronizes the current HEAD with the minimum upload:

```bash
export BEAGLE_SERVICE_URL="http://localhost:8000"
beagle-bridge login --token "<jwt>"
beagle-bridge whoami
beagle-bridge sync press                # push missing HEAD + index if needed
beagle-bridge sync press --local-only   # uploads nothing
```

The handshake calls `sync-status`; an already-synced commit and snapshot upload
nothing. Missing commits are pushed over Git Smart HTTP into the user's own ref
namespace, then indexed.

The bridge also hosts the consumer integrations (Phase I):

```bash
beagle-bridge ci press <base> <head> --json   # CI comparison report
beagle-service-mcp                             # read-only MCP for Claude Code
```

`beagle-service-mcp` exposes revision-aware retrieval (current_user,
commit_history, search_commits, revision_search, compare_revisions,
decision_history, feedback_history, dependency_resolutions), each forwarding to
the service with the stored token. In a project's `.mcp.json`, launch it via
`uv run --project /path/to/beagle beagle-service-mcp` (the script is in beagle's
venv, not on `PATH`). The admin UI is at `/admin`.

## Tests

```bash
uv run pytest tests/service/
```

Tests run on SQLite and use real `git` for mirror, hook, and end-to-end clone
coverage. No live PostgreSQL is required.
