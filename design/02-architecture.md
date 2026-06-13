# 02 — Architecture

## Stack

- Python 3.11+
- LibCST for Python parsing and source ranges
- SQLite for persistence
- SQLite FTS5 for lexical search
- `pathspec` for ignore rules
- Typer for CLI
- pytest for tests
- Python MCP SDK for Claude Code integration

## Flow

```text
Repository
   |
   +-- discovery and hashing
   |
   +-- Python extraction
   |     +-- symbols
   |     +-- imports
   |     +-- inheritance observations
   |     +-- assignments
   |     +-- calls
   |
   +-- Frappe extraction
   |     +-- DocTypes
   |     +-- fields
   |     +-- controllers
   |     +-- hooks
   |     +-- ORM operations
   |     +-- jobs
   |     +-- endpoints
   |     +-- tests
   |
   +-- resolution
   |     +-- lexical names
   |     +-- imports and aliases
   |     +-- inheritance
   |     +-- simple type propagation
   |     +-- dotted paths
   |     +-- Frappe conventions
   |
   +-- SQLite graph and FTS
   |
   +-- search, traversal, and context compilation
   |
   +-- CLI and MCP
```

## Separation of responsibilities

Keep these layers independent:

1. discovery
2. extraction
3. resolution
4. persistence
5. retrieval
6. rendering
7. MCP transport

The CLI and MCP server must call the same application services.

## Repository layout

```text
project_index/
├── cli.py
├── workspace.py
├── database/
├── models/
├── discovery/
├── extractors/
│   ├── python/
│   └── frappe/
├── resolution/
├── search/
├── context/
├── mcp/
└── benchmarks/
```

Keep tests in a separate `tests/` tree that mirrors the package.
