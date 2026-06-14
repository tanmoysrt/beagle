# Claude Code (MCP)

beagle ships a **read-only** MCP (Model Context Protocol) server. It exposes the
same engine the CLI uses, so Claude Code can resolve symbols, traverse the graph,
and read exact source ranges instead of grepping the whole repository.

## Prerequisites

Index the repository with the CLI first — the MCP server only reads the existing
`.beagle/index.db`, it does not build it.

```bash
uv run beagle index .
```

## Configure

Add a `.mcp.json` at the root of the project you want Claude Code to explore:

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

`BEAGLE_ROOT` tells the server which indexed repository to serve. Point it at the
repository whose `.beagle/index.db` you built above.

::: tip Keep the index fresh
The server reads whatever is in `.beagle/index.db`. After significant code
changes, re-run `uv run beagle index .` so Claude sees current facts. Indexing is
incremental, so this is cheap.
:::

## What Claude gets

Every MCP tool corresponds to a CLI command — same engine, same results. The
read-only surface:

| Area | MCP tools |
|---|---|
| **Lookup** | `index_status`, `search`, `resolve`, `show`, `read_source` |
| **Graph** | `relations`, `callers`, `callees`, `find_path`, `impact` |
| **Frappe data** | `uses_doctype`, `reads_field`, `writes_field`, `tests` |
| **Synthesis** | `context`, `investigate`, `explain_function`, `function_context` |
| **Lifecycle** | `lifecycle`, `event_handlers`, `trace` |
| **Change memory** | `change_facts`, `entity_history`, `episode` |

Indexing (`index`), running the server (`mcp`), and episode *authoring* are
CLI-only — the MCP server never writes.

## Which tool for which question

| You want to… | Use |
|---|---|
| Pin an exact symbol | `resolve` then `show` / `relations` |
| Know what a function does | `function_context` (behaviour) or `explain_function` (control flow) |
| Answer a conceptual question | `context` |
| Trace a bug report | `investigate` |
| Know what runs on save | `lifecycle` or `trace` (one event → `event_handlers`) |
| Know why an entity changed | `entity_history` |

Tools return stable ids — feed them into the next call. Claude should read only
the returned ranges, and fall back to its own Grep/Glob when coverage is thin.
