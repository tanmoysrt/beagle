# Command reference

Every command runs through `uv run beagle <command>`. Run `uv run beagle --help`
for the authoritative list, or `uv run beagle <command> --help` for a single
command's options.

A note on **names**: most commands accept a bare symbol (`Site.deploy`), a
qualified name, or a full stable id (`python://...#Site.deploy`,
`doctype://app/Site`). If a name is ambiguous, beagle prints the candidate ids
instead of guessing — pass one back in.

## Indexing

### `index`

```bash
uv run beagle index [PATH] [--force]
```

Index a repository into `.beagle/index.db`. Incremental by default; `--force`
reparses every file. Deleting or changing a file removes its facts in one
transaction, so the index never carries stale data.

### `status`

```bash
uv run beagle status
```

Print the index location, entity/edge/file counts, and the last run.

## Lookup

| Command | What it does |
|---|---|
| `search "<query>" [-n N]` | Lexical (FTS5) search over indexed source. |
| `resolve <name>` | List candidate entities for a name/id. |
| `show <entity>` | Show an entity's kind, file, range, signature, docstring. |
| `read <target>` | Print exact source for an entity id, `path:start-end`, or file. |

```bash
uv run beagle search "background job retry" -n 5
uv run beagle resolve "Site.deploy"
uv run beagle show doctype://press/Site
uv run beagle read "press/press/doctype/site/site.py:120-160"
```

## Graph traversal

| Command | What it does |
|---|---|
| `relations <entity>` | Incoming and outgoing edges, with relationship + confidence. |
| `callers <entity>` | Who calls this entity. |
| `callees <entity>` | What this entity calls. |
| `path <source> <target>` | A call path between two entities, if one exists. |
| `impact <entity> [--depth N]` | What transitively depends on this entity. |

```bash
uv run beagle relations Site.deploy
uv run beagle path deploy_site AgentRequest.execute
uv run beagle impact Site.deploy --depth 3
```

## Frappe data

| Command | What it does |
|---|---|
| `uses-doctype <name>` | Code that reads / writes / creates / deletes a DocType. |
| `reads-field <field>` | Code reading a field (falls back to DocType-level reads). |
| `writes-field <field>` | Code writing a field (`set_value` or `self.<field> =`). |
| `tests <entity>` | Tests covering an entity. |

```bash
uv run beagle uses-doctype Site
uv run beagle reads-field "Site.status"
uv run beagle tests Site.deploy
```

## Synthesis

These compose multiple facts into something readable.

### `context`

```bash
uv run beagle context -q "<question>" [--intent ...] [--max-tokens N]
```

Compile an intent-shaped, budget-bounded bundle of the most relevant entities,
each with an excerpt, a reason, and confidence. Intents: `locate`, `understand`,
`change`, `debug`, `test`, `investigate`.

### `investigate`

```bash
uv run beagle investigate "<issue text>" [--file F] [--mermaid] [--include-source] [--compact]
```

Turn a bug report or issue into an evidence-backed map of the relevant code:
ranked sources, primary workflows, and unknowns. `--compact` emits the
structured JSON; debug flags (`--show-scores`, `--show-paths`, `--show-unknowns`,
`--show-query-terms`) expose the reasoning.

### `card` (function context card)

```bash
uv run beagle card <function> [--mermaid] [--compact] [--max-tokens N]
```

An evidence-backed summary of a function's responsibility and behaviour.
`--mermaid` appends a compact behaviour diagram.

### `explain`

```bash
uv run beagle explain <function> [--mermaid] [--expand-calls N] [--framework-events]
```

A control-flow walkthrough. `--mermaid` renders a deterministic flowchart with
node→source mapping; `--expand-calls` inlines resolved callees;
`--framework-events` appends the Frappe lifecycle trace.

## Lifecycle (Frappe documents)

| Command | What it does |
|---|---|
| `lifecycle <DocType> [--event E]` | Standard lifecycle events and their handlers for a DocType. |
| `event-handlers "<DocType.event>"` | What runs for one `(DocType, event)`: controller, `doc_events`, runtime. |
| `trace <function> [--depth N] [--mermaid]` | Document operations, lifecycle events, and handlers reachable from a function. |

```bash
uv run beagle lifecycle Site
uv run beagle event-handlers "Site.on_update"
uv run beagle trace Site.deploy --mermaid
```

## Change memory (temporal)

Deterministic facts about *what* changed, plus optional human-authored
**episodes** recording *why*.

| Command | What it does |
|---|---|
| `change [SPEC] [--episode E] [--note] [--json]` | Change facts for a commit, `base..head`, or the working tree. |
| `history <entity> [--json]` | Why an entity changed: episodes, decisions, recorded changes. |
| `episode ...` | Author episodes (see below). |

```bash
uv run beagle change HEAD~3..HEAD
uv run beagle history Site.deploy
```

### Episode authoring (CLI-only)

Episodes are written, never inferred. Subcommands:

```bash
uv run beagle episode new "Retry flaky deploys" --problem "..." --goal "..."
uv run beagle episode decision <id> "Use exponential backoff"
uv run beagle episode alternative <id> "Fixed delay" --rejected-because "..."
uv run beagle episode supersede <id> <decision> "New decision"
uv run beagle episode followup <id> "Add metrics"
uv run beagle episode attach <id> <entity>
uv run beagle episode finalize <id>
uv run beagle episode list [--status S]
uv run beagle episode show <id>
```

See [How it works → Change memory](./how-it-works#change-memory-temporal) for the
model behind this.

## MCP server

```bash
uv run beagle mcp
```

Start the read-only MCP server over stdio. See
[Claude Code (MCP)](./mcp) for configuration. Every MCP tool maps to one of the
CLI commands above — same engine, same results.
