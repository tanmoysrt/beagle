# Beagle shared service (design/15)

A revision-aware, multi-tenant code-intelligence service. This package is
independent of the local SQLite engine: it owns organizations, users, JWT
identity, Git repository mirrors, and the HTTP API.

**Implemented:** Phase A (JWT identity), Phase B (Git repository service),
Phase C (commit metadata indexing + search), Phase D (per-commit source
indexing), Phase G (Git identity mapping), Phase H (decision/feedback memory),
and Phase I comparison (compare revisions/branches, merge summary). Phases E, F
and the Phase I consumer integrations (MCP/CI/admin UI) are staged in
`design/15` and not yet built.

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
export BEAGLE_SERVICE_SECRET="<a long random secret>"
export BEAGLE_DATABASE_URL="postgresql://user:pass@host/beagle"   # or sqlite:///beagle-service.db
export BEAGLE_REPO_ROOT="/var/lib/beagle/repositories"

beagle-service init-db
ORG=$(beagle-service org-create frappe "Frappe")
USER=$(beagle-service user-create "$ORG" tanmoy "Tanmoy" t@example.com)
REPO=$(beagle-service repo-register "$ORG" press "Press" --remote-url https://github.com/frappe/press)
beagle-service repo-sync "$REPO"
beagle-service grant "$USER" "$REPO" "source:read,repo:sync"
beagle-service token-mint "$USER" --repos press --permissions source:read,repo:sync
beagle-service serve --host 0.0.0.0 --port 8000
```

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

## Tests

```bash
uv run pytest tests/service/
```

Tests run on SQLite and use real `git` for mirror, hook, and end-to-end clone
coverage. No live PostgreSQL is required.
