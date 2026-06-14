<img src="assets/logo.svg" alt="beagle logo" width="72" align="left" />

# beagle

Local code-discovery for Python, Frappe, and their JS/TS/Vue frontends.
Deterministic, no LLM. Traces frontend calls to their backend handlers
(`frappe.call`, client ORM, frappe-ui resources → whitelisted methods & DocTypes).

<br clear="left" />

Indexes a repo into a local SQLite graph, then answers questions about symbols,
callers, DocTypes, hooks, jobs, and lifecycle events — every fact carrying
confidence, evidence, and the exact source range to read. Pairs with Claude Code
over MCP.

## Quickstart

```bash
uv sync
uv run beagle index .              # build .beagle/index.db
uv run beagle status               # counts + last run

uv run beagle search "deploy site"
uv run beagle card Site --mermaid  # what a function does + diagram
uv run beagle lifecycle Site       # events that fire on save/submit
```

Names resolve from a symbol, qualified name, or full id
(`python://module#Class.method`, `doctype://app/Name`); ambiguous names print
candidates. `uv run beagle --help` lists everything.

## Claude Code (MCP)

Read-only server over stdio — index with the CLI first, then:

```jsonc
// .mcp.json
{
  "mcpServers": {
    "beagle": {
      "command": "uv",
      "args": ["run", "beagle", "mcp"],
      "env": { "BEAGLE_ROOT": "/path/to/repo" }
    }
  }
}
```

## Tools

Every MCP tool is also a CLI command — same engine, same results.

| Area | MCP tool · CLI command |
|---|---|
| **Lookup** | `index_status`·`status` · `search` · `resolve` · `show` · `read_source`·`read` |
| **Graph** | `relations` · `callers` · `callees` · `find_path`·`path` · `impact` |
| **Frappe data** | `uses_doctype`·`uses-doctype` · `reads_field`·`reads-field` · `writes_field`·`writes-field` · `tests` |
| **Synthesis** | `context` · `investigate` · `explain_function`·`explain` · `function_context`·`card` |
| **Lifecycle** | `lifecycle` · `event_handlers`·`event-handlers` · `trace` |
| **Change memory** | `change_facts`·`change` · `entity_history`·`history` · `episode`·`episode show` |

CLI-only: `index`, `mcp`, and episode authoring (`episode new/decision/
alternative/supersede/followup/finalize/attach`) — the MCP server is read-only.

**Which to use** — exact symbol → `resolve` then `show`/`relations`. What a
function does → `card` (behaviour) or `explain` (control flow). Conceptual
question → `context`; a bug report → `investigate`. What runs on save →
`lifecycle` or `trace`; one custom event → `event-handlers`. Why an entity
changed → `history`; record the reasoning behind a change → `episode`.

Tools return stable ids — feed them into the next call. Read only the returned
ranges; fall back to Grep/Glob when coverage is thin.

## Shared service (teams)

Beyond the local engine, beagle ships a revision-aware **shared service**: Git
mirroring, per-commit indexing, dependency resolution, decision/feedback memory,
and JWT auth — with a local bridge and a read-only MCP for Claude Code. Run it
with Docker:

```bash
export BEAGLE_SERVICE_SECRET=$(openssl rand -hex 32)
docker compose up --build          # API on http://localhost:8000
```

See **[docs/guide/shared-service.md](docs/guide/shared-service.md)** for setup,
the bridge, MCP, CI, and the admin UI, and `beagle/service/README.md` for the
module map and full API reference.

---

See `design/` for architecture, `CLAUDE.md` for development rules.
