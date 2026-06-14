# Installation

## Requirements

- **Python 3.11+** — use a standard (GIL) CPython build. The free-threaded build
  (e.g. `3.14t`) breaks the tree-sitter binding used for JS/TS/Vue parsing, so
  stick to a regular interpreter. 3.11 is the project baseline.
- **[uv](https://docs.astral.sh/uv/)** — used to manage the environment and run
  the tool. Install it with:

  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

No system services, databases, or API keys are required. beagle is fully local
and writes its index to a SQLite file inside the repository you point it at.

## Get the code

```bash
git clone https://github.com/tanmoysrt/beagle.git
cd beagle
```

## Install dependencies

```bash
uv sync
```

This creates a virtual environment and installs the runtime dependencies:

| Dependency | Purpose |
|---|---|
| `libcst` | Python parsing with exact source ranges |
| `tree-sitter` + `tree-sitter-language-pack` | JavaScript / TypeScript / Vue parsing |
| `pathspec` | `.gitignore`-style ignore rules during discovery |
| `typer` | the command-line interface |
| `mcp` | the read-only Model Context Protocol server |

## Verify

```bash
uv run beagle --help
```

You should see the list of commands. To run the test suite:

```bash
uv run pytest
```

## What gets installed

`uv sync` exposes three entry points (see `pyproject.toml`):

- `beagle` — the main CLI (`uv run beagle ...`).
- `beagle-mcp` — the MCP server entry point (also reachable as
  `uv run beagle mcp`).
- `beagle-bench` — the benchmark report runner.

You're ready to [build your first index](./quickstart).
