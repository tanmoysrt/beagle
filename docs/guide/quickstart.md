# Quickstart

This walks through indexing a repository and asking it a few questions. It
assumes you've completed [installation](./installation).

## 1. Build an index

Point `beagle index` at the repository you want to explore. It writes a SQLite
graph to `.beagle/index.db` inside that repository.

```bash
uv run beagle index .
```

```text
indexed 412, deleted 0, unchanged 0 (412 files)
db: /path/to/repo/.beagle/index.db
```

Re-running `index` is **incremental** — only changed files are re-parsed, and
facts owned by deleted files are removed. Use `--force` to reindex everything.

```bash
uv run beagle index . --force
```

## 2. Check status

```bash
uv run beagle status
```

```text
root: /path/to/repo
db:   /path/to/repo/.beagle/index.db
counts: entities=3120, edges=8044, files=412
last run: #3 ok (412 files)
```

## 3. Find something

Lexical search over indexed source:

```bash
uv run beagle search "deploy site"
```

Resolve a name to a concrete entity (prints candidates if ambiguous):

```bash
uv run beagle resolve "Site.deploy"
```

Names resolve from a bare symbol, a qualified name, or a full id such as
`python://press.press.doctype.site.site#Site.deploy` or `doctype://press/Site`.

## 4. Understand it

```bash
uv run beagle card Site.deploy --mermaid   # what the function does, + a diagram
uv run beagle explain Site.deploy          # control-flow walkthrough
uv run beagle relations Site.deploy        # incoming / outgoing edges
uv run beagle callers Site.deploy          # who calls it
```

## 5. Ask Frappe-specific questions

```bash
uv run beagle lifecycle Site               # events that fire on save/submit
uv run beagle uses-doctype Site            # code that reads/writes/creates Site
uv run beagle trace Site.deploy --mermaid  # document ops + lifecycle from a fn
```

## 6. Compile context for a question

```bash
uv run beagle context -q "How does site deployment work?" --intent understand
```

This returns a budget-bounded bundle of the most relevant entities with their
source excerpts, reasons, and confidence — the kind of thing you'd paste into a
review or hand to an assistant.

## Next steps

- The full [command reference](./commands).
- Wire it into [Claude Code over MCP](./mcp).
- Learn [how it works](./how-it-works) under the hood.

::: tip Tip
Every command accepts an entity **id** as well as a name. Commands print stable
ids — feed the id from one command straight into the next to avoid re-resolving
ambiguous names.
:::
