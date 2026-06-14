# Architecture

This page is the structural companion to [How it works](./how-it-works). It
covers the stack, the layering, and where things live in the codebase.

## Stack

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | Standard (GIL) build. The free-threaded build breaks the tree-sitter binding. |
| Python parsing | [LibCST](https://libcst.readthedocs.io/) | Exact source ranges. |
| JS/TS/Vue parsing | [tree-sitter](https://tree-sitter.github.io/) via `tree-sitter-language-pack` | Prebuilt `javascript`, `typescript`, `tsx`, `vue` grammars. |
| Persistence | SQLite | Single file at `.beagle/index.db`, foreign keys enforced. |
| Lexical search | SQLite FTS5 | Over indexed text chunks. |
| Ignore rules | `pathspec` | `.gitignore`-style matching during discovery. |
| CLI | [Typer](https://typer.tiangolo.com/) | |
| Claude Code | Python MCP SDK | Read-only server over stdio. |
| Tests | pytest | |

beagle keeps to the standard library wherever practical and adds a dependency
only when a concrete, demonstrated need justifies it.

## Layered design

The codebase is split into independent layers. Data flows down; the layers below
never import the ones above.

```text
1. discovery     find & hash files (pathspec ignore rules)
2. extraction    parse → entities + raw observations  (no resolution, no exec)
3. resolution    observations → resolved edges (confidence + evidence)
4. persistence   SQLite graph + FTS5
5. retrieval     search · traversal · synthesis · lifecycle · change memory
6. rendering     human/structured output
7. MCP transport read-only server over stdio
```

Two rules hold this together:

1. **Parsing, resolution, persistence, retrieval, and presentation stay
   separate.** No method mixes database access, graph resolution, and output
   rendering.
2. **The CLI and the MCP server call the same application services.** Neither
   has logic the other lacks; the MCP server is the read-only subset of the same
   engine.

## Repository layout

```text
beagle/
├── cli.py            # Typer command surface (thin; calls services)
├── workspace.py      # opens a repo, owns the index lifecycle & db handle
├── discovery/        # file discovery & hashing
├── extractors/       # parsing → entities + observations
│   ├── python/       #   LibCST-based Python extraction
│   ├── frappe/       #   DocTypes, hooks, ORM ops, jobs, endpoints, runtime
│   └── javascript/   #   tree-sitter JS/TS/Vue; binding adapter; frappe_api
├── resolution/       # observations → resolved edges (per-resolver modules)
├── database/         # connection, migrations, repository (data access)
├── models/           # entity/edge/record dataclasses
├── search/           # FTS engine + graph traversal service
├── context/          # intent-shaped context compilation
├── investigate/      # issue → evidence map
├── card/             # function context cards (+ mermaid, classify)
├── explain/          # control-flow explanations (+ flow, mermaid)
├── lifecycle/        # Frappe document lifecycle policy, dispatch, trace
├── temporal/         # change facts, episodes, git, redaction
├── mcp/              # read-only MCP server + tool definitions
└── benchmarks/       # fixtures, gold sets, metrics, report runner
```

Tests live in a separate `tests/` tree that mirrors the package
(`tests/extractors/python/`, `tests/resolution/`, and so on).

### Notable boundaries

- **`workspace.py`** is the single entry point for opening a repository: it owns
  the database connection, the index lifecycle (`index`, incremental updates,
  deletion), and source-range reads. Both front ends go through it.
- **`database/repository.py`** is the only place that talks SQL. Higher layers
  ask the repository for entities and edges; they don't write queries.
- **`extractors/javascript/binding.py`** quarantines the non-standard
  tree-sitter API. If the binding is ever swapped, only that file changes.
- **`resolution/`** is split per concern (`symbols`, `calls`, `frappe`,
  `javascript`, `operations`, `builder`) so each resolver is independently
  testable and versioned.

## Correctness invariants

These are enforced across the architecture, not just by convention:

- Deterministic indexed facts are the source of truth; raw observations are
  stored separately from resolved edges.
- Every resolved edge carries confidence, resolver (+ version), evidence, source
  range, and owner file.
- Entity ids are stable when source lines move (keyed by structure, not line).
- Incremental indexing leaves no stale facts — changing or deleting a file
  removes everything that file owned, atomically.
- Repository Python is never executed during indexing; `hooks.py` is never
  executed.
- Frappe semantics are read conservatively — a hint over a wrong confirmed edge.

## Benchmarks

The `benchmarks/` package holds fixtures, gold sets, metrics, and a report
runner (`uv run beagle-bench`). Extraction, resolution, ranking, and context
behaviour are expected to be checked against benchmarks when they change, so
regressions are caught rather than discovered later.

## Design records

The authoritative, evolving design lives in the repository's `design/` directory
(numbered `01`–`14`), covering the product overview, architecture, data model,
implementation and benchmark plans, the Frappe lifecycle and event-dispatch
policies, issue investigation, function context cards, temporal/change memory,
and the JavaScript/TypeScript/Vue stage. Read the relevant design file before
changing architecture.
