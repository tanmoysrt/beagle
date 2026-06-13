# beagle

Local code-discovery engine for Python and Frappe projects. No LLM required.

`beagle` indexes a repo into a local SQLite graph, then answers questions about
symbols, callers, callees, hooks, jobs, DocTypes, lifecycle events, and the
exact source ranges to read before changing anything. Every fact is
deterministic and carries confidence + evidence.

See `design/` for architecture and `CLAUDE.md` for development rules.

## Setup

```bash
uv sync
uv run beagle index .        # build the index (.beagle/index.db)
uv run beagle status         # counts + last run
uv run pytest
```

## CLI

Run any command with `uv run beagle <command> --help`. Names resolve from a
symbol, a qualified name, or a full entity id (`python://module#Qual.name`,
`doctype://app/Name`). Ambiguous names print candidates.

```bash
uv run beagle search "site deployment"
uv run beagle resolve Site
uv run beagle show "python://app.module#Class.method"
uv run beagle callers deactivate
uv run beagle card "doctype://press/Site" --mermaid
uv run beagle lifecycle Site --event on_update
```

## MCP server (Claude Code)

Read-only server over stdio. It never indexes or mutates — index first with the
CLI, then start the server.

```bash
uv run beagle mcp            # serves the index found from the current dir
BEAGLE_ROOT=/path/to/repo uv run beagle mcp
```

Register in Claude Code (`.mcp.json` or `claude mcp add`):

```json
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

## Tools (MCP ↔ CLI)

Every MCP tool has a matching CLI command. Same engine, same results.

**Lookup**

| MCP tool | CLI | Purpose |
|---|---|---|
| `index_status` | `status` | Index counts and the last run. |
| `search` | `search` | Lexical (FTS) search over indexed source. |
| `resolve` | `resolve` | Name / qualified-name / id → candidate entities. |
| `show` | `show` | One entity's details and source range. |
| `read_source` | `read` | Exact source text for an entity (or `path:start-end`). |

**Graph**

| MCP tool | CLI | Purpose |
|---|---|---|
| `relations` | `relations` | All incoming + outgoing edges for an entity. |
| `callers` | `callers` | Who calls this entity. |
| `callees` | `callees` | What this entity calls. |
| `find_path` | `path` | Shortest call path between two entities. |
| `impact` | `impact` | What transitively depends on an entity. |

**Frappe data**

| MCP tool | CLI | Purpose |
|---|---|---|
| `uses_doctype` | `uses-doctype` | Code that reads/writes/creates/deletes a DocType. |
| `reads_field` | `reads-field` | Code reading a field (falls back to DocType-level). |
| `writes_field` | `writes-field` | Code writing a field. |
| `tests` | `tests` | Tests covering an entity. |

**Synthesis**

| MCP tool | CLI | Purpose |
|---|---|---|
| `context` | `context` | Intent-shaped, budget-bounded context bundle. |
| `investigate` | `investigate` | Issue text → ranked, evidence-backed code map. |
| `explain_function` | `explain` | Function summary + optional control-flow Mermaid. |
| `function_context` | `card` | Behaviour card: responsibility, guards, effects, lifecycle, failures (+ Mermaid). |

**Frappe lifecycle**

| MCP tool | CLI | Purpose |
|---|---|---|
| `lifecycle` | `lifecycle` | Standard document lifecycle events + handlers for a DocType. |
| `event_handlers` | `event-handlers` | Handlers for one (DocType, event), including custom events. |
| `trace` | `trace` | Operations → lifecycle events → handlers reached from a function. |

CLI-only: `index` (build the graph), `mcp` (run the server).

### Which to use

- Exact symbol → `resolve` then `show` / `relations`.
- "What does this function do?" → `function_context` (card); for branch
  structure use `explain`.
- Conceptual question → `context`; bug report or issue → `investigate`.
- "What runs on save?" → `lifecycle` (standard events) or `trace` (from a
  function); a single custom event → `event_handlers`.

Tools return stable entity ids — feed them back into the next call. Read only
the source ranges returned; fall back to Grep/Glob/Read when coverage is thin.
