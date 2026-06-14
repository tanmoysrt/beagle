# How it works

beagle turns a repository into a queryable graph in a fixed sequence of stages.
Each stage has one job and hands its output to the next. The guiding principle:
**raw observations are kept separate from resolved conclusions**, and nothing
uncertain is ever recorded as certain.

```text
Repository
   │
   ▼
discovery & hashing  ──►  extraction  ──►  resolution  ──►  SQLite graph + FTS
                              │                                     │
              (Python · Frappe · JS/TS/Vue)              search · traversal · synthesis
                                                                    │
                                                              CLI  &  MCP
```

## 1. Discovery & hashing

beagle walks the repository, applies `.gitignore`-style ignore rules (via
`pathspec`), and hashes every candidate file. On a re-index it compares hashes:
unchanged files are skipped, changed files are re-parsed, and files that
disappeared have **all** their facts deleted in a single transaction. This is
what makes incremental indexing safe — the index can never drift into holding
facts for code that no longer exists.

## 2. Extraction

Extraction parses source into **entities** (definitions) and **observations**
(raw, un-interpreted facts). It never resolves anything yet, and it never
executes repository code — `hooks.py` and other modules are read, not run.

**Python** is parsed with [LibCST](https://libcst.readthedocs.io/), which
preserves exact source ranges. beagle extracts modules, classes, functions,
methods, imports, inheritance observations, assignments, and call sites.

**Frappe** extraction layers framework knowledge on top: DocTypes and their
fields (from DocType JSON), controllers, `hooks.py` entries, ORM/document
operations, background jobs, whitelisted endpoints, and tests.

**JavaScript / TypeScript / Vue** is parsed with
[tree-sitter](https://tree-sitter.github.io/) (via `tree-sitter-language-pack`).
beagle extracts modules (one per file), classes, functions, methods, top-level
arrow-function consts, ES imports, `extends` clauses, and — crucially —
**frontend API call sites** (`frappe.call`, the client ORM, frappe-ui
resources). For `.vue` single-file components it locates the `<script>` /
`<script setup>` block and parses its body with line offsets preserved, so
ranges still point at the right lines in the original file.

The tree-sitter binding has an unusual API; it is quarantined in a single
adapter module so the rest of the codebase sees a clean node interface.

## 3. Resolution

Resolution reads the stored observations and produces **resolved edges** —
confident statements about how entities relate. Because observations are stored
separately, resolution can be improved later without re-parsing any files.

Resolvers handle, among others:

- lexical name matching;
- imports and aliases;
- inheritance and method overrides;
- simple type propagation and dotted-path resolution;
- Frappe conventions (controllers, `doc_events`, hooks dispatch);
- **frontend → backend**: a JS call site to a backend whitelisted
  method/endpoint becomes a `CALLS_BACKEND` edge; a JS call site to a DocType
  through the client ORM or a frappe-ui resource becomes a `QUERIES_DOCTYPE`
  edge.

Every resolved edge records its **confidence**, the **resolver** (and version),
the **evidence**, the **source range**, the **owner file**, and the originating
observation. Ambiguous relationships are preserved as ambiguous. There is no
`CALLS_PROBABLE` relationship — uncertainty lives in the confidence value, not in
invented relationship names.

::: warning Conservative by design
beagle prefers a missing edge over a wrong one. Where Frappe semantics are
genuinely uncertain (for example, dynamically dispatched runtime handlers), it
records a hint rather than a confirmed edge.
:::

## 4. Persistence: the SQLite graph

Everything lands in a single SQLite database (`.beagle/index.db`) with foreign
keys enforced. The core tables are `files`, `entities`, `observations`, `edges`,
`text_chunks`, `index_runs`, and `schema_versions`. Lexical search is backed by
SQLite's FTS5 over the indexed text chunks.

Entity **ids are stable**: they are keyed by structure (e.g. dotted module path
for Python), not by line number, so an entity keeps its id when its code moves up
or down a file. That stability is what lets you feed an id from one command into
the next, and what lets change-tracking compare across commits. See the
[data model](./data-model) for the full picture.

## 5. Retrieval & synthesis

On top of the graph sit the query services:

- **search** — lexical FTS lookup;
- **traversal** — relations, callers/callees, paths, impact;
- **synthesis** — context bundles, investigation reports, function context
  cards, control-flow explanations, and Mermaid diagrams;
- **lifecycle** — Frappe document events and their resolved handlers;
- **change memory** — what changed, and the human-authored reasoning behind it.

All synthesis is deterministic and citation-backed: every claim points at a
source range you can open. There is no model generating prose; the engine
assembles facts.

## 6. Two front ends, one engine

The **CLI** and the **MCP server** are thin presentation layers over the same
application services. Anything the CLI can answer, the MCP server can answer
identically — the MCP server is simply the read-only subset, exposed to Claude
Code over stdio. This is a hard rule in the project: the CLI and MCP must call
the same services, so they can never disagree.

## Change memory (temporal)

Beyond the structural graph, beagle records **change facts** and **episodes**.

Change facts are deterministic: given a commit, a `base..head` range, or the
working tree, beagle computes which entities were added/changed/removed, a patch
id, and an entity fingerprint. This uses entity ids, so a change is attributed to
`Site.deploy` rather than "lines 120–160 of site.py".

Episodes are the opposite — they are **authored, never inferred**. A developer
records the problem, the goal, the decision taken, the alternatives rejected and
why, and links the episode to affected entities. `beagle history <entity>` then
answers *why* a piece of code is the way it is, combining the deterministic
changes with the human reasoning. beagle never fabricates this narrative; if no
one wrote it, the history is empty.

## What it deliberately does not do

- It does not run an LLM in the engine — results are deterministic and
  reproducible.
- It does not execute repository code while indexing, ever.
- It does not yet resolve the JS-internal call graph or cross-file JS imports —
  those observations are stored, but the edges are staged for a later stage.
- It is not a PR reviewer, a GitHub integration, an embeddings/vector system, or
  a hosted multi-repo service. Those are explicit non-goals.
