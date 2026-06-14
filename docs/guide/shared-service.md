# Shared service

Beyond the local engine, beagle ships a **shared, revision-aware service** for
teams (`design/15`). It mirrors private Git repositories, indexes commits once
and reuses them across branches, downloads and analyses exact dependencies, and
records decisions and feedback — all behind server-minted JWT auth.

The primary identity of code is `repository + commit`; a branch is just a
mutable pointer. The service lives in `beagle/service/`, the local client in
`beagle/bridge/`. Both are separate from the local SQLite engine.

There's no tenant or organization to manage — a single team is the default. The
recommended way to drive it is the **admin web UI**: everything (users, repos,
access) is point-and-click, and it hands each developer copy-paste setup. The
CLI is still there if you prefer it.

## 1 · Start the service

Pick one. Set an **admin password** — it gates the web UI.

::: code-group

```bash [Docker (team / Postgres)]
export BEAGLE_SERVICE_SECRET=$(openssl rand -hex 32)   # token signing key
export BEAGLE_ADMIN_PASSWORD="choose-a-strong-password"
docker compose up --build                              # http://localhost:8000
```

```bash [Local (SQLite)]
uv sync
export BEAGLE_SERVICE_SECRET=$(openssl rand -hex 32)
export BEAGLE_ADMIN_PASSWORD="choose-a-strong-password"
export BEAGLE_DATABASE_URL="sqlite:///$PWD/beagle-service.db"
export BEAGLE_REPO_ROOT="$PWD/beagle-repositories"
uv run beagle-service serve            # http://localhost:8000  (git must be on PATH)
```

:::

Add `BEAGLE_ADMIN_PASSWORD` under `service.environment` in `docker-compose.yml`
(or pass `-e`) so the container picks it up.

## 2 · Open the admin UI

Go to **`http://localhost:8000/admin`** and sign in with the admin password.
From there:

1. **Register a repository** — name, slug, and (optionally) a Git remote URL.
   With a URL it is mirrored and indexed on save; without one it waits for a
   developer to push from their machine.
2. **Add users** — one row each (username, optional email).
3. **Grant access** — pick a user and click *Generate setup*. The UI shows two
   copy-paste blocks for that user:
   - the **bridge** commands (`beagle-bridge login …`), and
   - a ready-made **`.mcp.json`** for Claude Code.

   The token it embeds is a credential — share it over a private channel.

The dashboard also shows live counts and each repository's commit/snapshot
totals. The page only ever holds the admin session in your browser; close the
tab and you're signed out.

> The admin UI is admin-only by design. It doesn't log developers in — it
> *generates* their setup. Each developer just pastes what they're given.

## 3 · Developer setup (from the UI's instructions)

A developer pastes the bridge block, then works normally:

```bash
export BEAGLE_SERVICE_URL=http://localhost:8000
beagle-bridge login --token <token from the admin UI>

# inside a checkout of the repo — the bridge auto-detects it:
beagle-bridge sync <repo-slug>
```

For Claude Code, they drop the generated `.mcp.json` into the project (see
[Use it from Claude Code](#use-it-from-claude-code-mcp)).

## Prefer the CLI?

Everything the UI does is also a CLI command. The one-shot path:

```bash
uv run beagle-service setup tanmoy --email tanmoy@example.com   # user + full token
REPO=$(uv run beagle-service repo-register press "Press" \
        --remote-url https://github.com/frappe/press)
uv run beagle-service repo-sync "$REPO"
```

`setup` prints a token with all permissions and all repositories — no org, no
separate grant. See [Users and tokens](#users-and-tokens) for the rest.

## Docker details

`docker compose up --build` runs the service with PostgreSQL. Check it:

```bash
curl http://localhost:8000/healthz     # {"status":"ok"}
```

Mirrors, snapshots, and downloaded artifacts persist in the `beagle-data`
volume; PostgreSQL data in `beagle-db`. Run any CLI command inside the container
if you skip the UI, e.g.:

```bash
docker compose exec service beagle-service setup tanmoy --email t@example.com
```

For a single-node image without Postgres, `docker build -t beagle-service . &&
docker run -p 8000:8000 -e BEAGLE_SERVICE_SECRET=... -e
BEAGLE_ADMIN_PASSWORD=... -v beagle-data:/data beagle-service` uses SQLite at
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
retrieval to the service with your token. Add it to the project's `.mcp.json`:

```json
{
  "mcpServers": {
    "beagle-service": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/beagle", "beagle-service-mcp"],
      "env": {
        "BEAGLE_SERVICE_URL": "http://localhost:8000",
        "BEAGLE_TOKEN": "<token from the admin UI>"
      }
    }
  }
}
```

The `uv run --project` form is used because `beagle-service-mcp` lives in
beagle's virtualenv and isn't on `PATH` by default. Point `/path/to/beagle` at
your install. If you installed beagle globally (`uv tool install`), you can
instead use `"command": "beagle-service-mcp"` with no `args`.

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

## Admin UI reference

The web UI at `http://localhost:8000/admin` is gated by `BEAGLE_ADMIN_PASSWORD`.
Signing in exchanges the password for a short-lived admin token
(`POST /v1/admin/login`) held only in your browser. It drives these endpoints
(all requiring the `admin:identity` scope):

| Action | Endpoint |
| --- | --- |
| Sign in | `POST /v1/admin/login` |
| Overview (counts, repos, audit) | `GET /v1/admin/overview` |
| Add / list users | `POST /v1/users`, `GET /v1/users` |
| Register / sync repo | `POST /v1/repositories`, `POST /v1/repositories/{id}/sync` |
| Generate a user's token | `POST /v1/admin/tokens` |

If `BEAGLE_ADMIN_PASSWORD` is unset, the UI login is disabled and you manage the
service with the CLI instead.

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
