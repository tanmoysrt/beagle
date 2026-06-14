# Shared service

Beyond the local engine, beagle ships a **shared, revision-aware service** for
teams (`design/15`). It mirrors private Git repositories, indexes commits once
and reuses them across branches, downloads and analyses exact dependencies, and
records decisions and feedback — all behind server-minted JWT auth.

The primary identity of code is `repository + commit`; a branch is just a
mutable pointer. The service lives in `beagle/service/`, the local client in
`beagle/bridge/`. Both are separate from the local SQLite engine.

There's no tenant or organization to manage — a single team is the default. You
create a user, register repositories, and go.

## Quick start (local, SQLite)

The shortest path to a running service on your machine. `git` must be on `PATH`
(the mirror and Git Smart HTTP shell out to it).

```bash
uv sync

# The signing key for tokens. Set once; keep it (rotating invalidates tokens).
export BEAGLE_SERVICE_SECRET=$(openssl rand -hex 32)
export BEAGLE_DATABASE_URL="sqlite:///$PWD/beagle-service.db"
export BEAGLE_REPO_ROOT="$PWD/beagle-repositories"

# Start the API (creates tables on first run).
uv run beagle-service init-db
uv run beagle-service serve &           # http://localhost:8000
```

In another shell (same env vars), create yourself a user and a token:

```bash
uv run beagle-service setup tanmoy --email tanmoy@example.com
```

`setup` prints a token with all permissions — perfect for a solo local install.
That's the whole identity step; no org, no separate grant.

Then register and index a repository:

```bash
REPO=$(uv run beagle-service repo-register press "Press" \
        --remote-url https://github.com/frappe/press)
uv run beagle-service repo-sync "$REPO"   # mirror + index commit metadata + identities
```

Point your machine at it:

```bash
export BEAGLE_SERVICE_URL=http://localhost:8000
uv run beagle-bridge login --token "<token from setup>"
uv run beagle-bridge whoami
```

You're done — see [Use it from Claude Code](#use-it-from-claude-code-mcp) below.

## Run it with Docker (team / Postgres)

For a shared deployment, compose runs the service with PostgreSQL:

```bash
export BEAGLE_SERVICE_SECRET=$(openssl rand -hex 32)
docker compose up --build              # API on http://localhost:8000
```

```bash
curl http://localhost:8000/healthz     # {"status":"ok"}
```

Run admin commands inside the container, e.g.:

```bash
docker compose exec service beagle-service setup tanmoy --email t@example.com
```

Mirrors, snapshots, and downloaded artifacts persist in the `beagle-data`
volume; PostgreSQL data in `beagle-db`. For a single-node image without
Postgres, `docker build -t beagle-service . && docker run -p 8000:8000 -e
BEAGLE_SERVICE_SECRET=... -v beagle-data:/data beagle-service` uses SQLite at
`/data`.

## Users and tokens

`setup` covers the common case. The finer-grained commands are there when you
want them:

```bash
beagle-service user-create alice alice@example.com   # add another user
beagle-service user-list                             # id, username, email
beagle-service grant alice "$REPO" "source:read,repo:sync"
beagle-service token-mint alice --repos press --permissions source:read
beagle-service token-revoke <jti>                    # revoke a token
```

`grant` and `token-mint` accept a username or a user id. A token is the user's
credential — store it with the bridge, never in a repository.

### Admin token

An *admin token* is just a JWT carrying the `admin:identity` scope; it unlocks
the admin overview and identity-mapping endpoints. The token from `setup`
already has it; to mint a narrower one:

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
