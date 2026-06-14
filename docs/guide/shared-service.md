# Shared service

Beyond the local engine, beagle ships a **shared, revision-aware service** for
teams (`design/15`). It mirrors private Git repositories, indexes commits once
and reuses them across branches, downloads and analyses exact dependencies, and
records decisions and feedback — all behind server-minted JWT auth.

The primary identity of code is `repository + commit`; a branch is just a
mutable pointer. The service lives in `beagle/service/`, the local client in
`beagle/bridge/`. Both are separate from the local SQLite engine.

## Run it with Docker

The fastest way to get a working service with PostgreSQL:

```bash
# A signing secret is required (keep it safe; rotating it invalidates tokens).
export BEAGLE_SERVICE_SECRET=$(openssl rand -hex 32)

docker compose up --build
```

The API is now on `http://localhost:8000`. Health check:

```bash
curl http://localhost:8000/healthz      # {"status":"ok"}
```

Mirrors, per-commit snapshots, and downloaded dependency artifacts persist in
the `beagle-data` volume; PostgreSQL data in `beagle-db`.

### Run the image directly (SQLite)

For a single-node trial without Postgres:

```bash
docker build -t beagle-service .
docker run --rm -p 8000:8000 \
  -e BEAGLE_SERVICE_SECRET=$(openssl rand -hex 32) \
  -v beagle-data:/data \
  beagle-service
```

This uses SQLite at `/data/beagle-service.db`. Use Postgres (compose) for any
real deployment.

## Run it without Docker

```bash
uv sync
export BEAGLE_SERVICE_SECRET=$(openssl rand -hex 32)
export BEAGLE_DATABASE_URL="postgresql://user:pass@localhost/beagle"  # or sqlite:///beagle-service.db
export BEAGLE_REPO_ROOT="$PWD/beagle-repositories"

uv run beagle-service init-db
uv run beagle-service serve --host 0.0.0.0 --port 8000
```

`git` must be on `PATH` — the mirror and Git Smart HTTP shell out to it.

## First-run setup (admin)

Create an organization and a user, register a repository, sync it, grant
access, and mint a token. With Docker, prefix each command with
`docker compose exec service`:

```bash
ORG=$(beagle-service org-create frappe "Frappe")
beagle-service user-create "$ORG" tanmoy "Tanmoy" tanmoy@example.com

REPO=$(beagle-service repo-register "$ORG" press "Press" \
        --remote-url https://github.com/frappe/press)
beagle-service repo-sync "$REPO"          # mirror + index commit metadata + identities

# `grant` and `token-mint` accept a username or a user id.
beagle-service grant tanmoy "$REPO" "source:read,repo:sync"
beagle-service token-mint tanmoy --repos press \
  --permissions source:read,repo:sync,decision:write
```

The last command prints the JWT. It is the user's credential — store it with the
bridge, never in a repository. List users any time with
`beagle-service user-list "$ORG"`.

### Admin token

An *admin token* is just a JWT that carries the `admin:identity` scope; it
unlocks the admin overview and identity-mapping endpoints. Mint one with:

```bash
beagle-service token-mint tanmoy --permissions admin:identity
```

(`BEAGLE_SERVICE_SECRET` is **not** a token — it is the server's signing key.)

### Permissions

Tokens carry flat scopes plus a list of repository slugs they may touch:
`source:read`, `repo:register`, `repo:sync`, `workspace:create`,
`workspace:share`, `decision:read`, `decision:write`, `feedback:read`,
`feedback:write`, `admin:identity`. A request is authorized only when the token
holds the required scope **and** names the target repository.

## Use it from your machine (the bridge)

```bash
export BEAGLE_SERVICE_URL=http://localhost:8000
beagle-bridge login --token "<the JWT from token-mint>"   # stored 0600, never in the repo
beagle-bridge whoami

# In a checkout of the repository:
beagle-bridge sync press                  # push HEAD if missing, then index it
beagle-bridge sync press --upload-dirty   # also send uncommitted changes as an overlay
beagle-bridge sync press --local-only     # uploads nothing
```

`sync` is incremental: an already-synced commit and snapshot upload nothing.
Missing commits travel over Git Smart HTTP into your own ref namespace, never to
canonical upstream refs.

## Use it from Claude Code (MCP)

The bridge hosts a **read-only** MCP server that forwards revision-aware
retrieval to the service with your token. Register it in Claude Code:

```json
{
  "mcpServers": {
    "beagle-service": {
      "command": "beagle-service-mcp",
      "env": { "BEAGLE_SERVICE_URL": "http://localhost:8000" }
    }
  }
}
```

Tools: `current_user`, `list_repositories`, `commit_history`, `search_commits`,
`revision_search`, `compare_revisions`, `decision_history`, `feedback_history`,
`dependency_resolutions`. Every result is scoped to your token's permissions.

## Use it in CI

```bash
beagle-bridge ci press <base-sha> <head-sha> --json
```

Prints a comparison report — changed files, added/removed/changed entities, the
commit range, and the authors involved — suitable for a pull-request check.

## Dependencies across packages

Once a revision is synced you can resolve the project's imports to the exact
dependency versions that provide them (downloads + indexes the dependency
source, cached by artifact hash; no install scripts ever run):

```bash
beagle-service dependencies "$REPO" <sha>            # parse lockfiles -> pinned snapshot
beagle-service resolve-dependencies "$REPO" <sha>    # download + index + resolve imports
```

Python cross-package symbol resolution is complete (e.g. `press.Site` →
`frappe.Document`). JavaScript dependency source is downloaded and indexed;
JS symbol edges across packages are a follow-up.

## Admin overview

A read-only dashboard is served at `http://localhost:8000/admin`. Paste an
`admin:identity` token to see org counts, repositories with commit/snapshot
totals, and recent audit activity. The JSON behind it is
`GET /v1/admin/overview`.

## What the service does

| Area | Capability |
| --- | --- |
| Identity | server-minted JWTs, revocation, repository-scoped permissions, audit log |
| Git | bare mirrors, authenticated Smart HTTP, per-user push namespaces |
| History | full commit metadata, separate author/committer, trailers, message search |
| Revisions | immutable per-commit index snapshots, reused across branches |
| Comparison | changed files + entities, branch compare, merge summary |
| Identities | email-anchored Git identities mapped to users (never by name) |
| Decisions | role-typed actors (confirmed vs inferred), feedback lifecycle |
| Dependencies | lockfile parsing, verified download, safe unpack, cross-package resolution |
| Workspaces | local dirty changes layered over a base commit |

See `beagle/service/README.md` for the full module map and API reference.
