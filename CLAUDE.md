# CLAUDE.md

## Purpose

This repository builds `project-index`, a local code-discovery engine for Python and Frappe projects.

Read the relevant files in `design/` before implementing or changing architecture.

## Development rules

- Use Python 3.11+.
- Prefer simple, explicit code over clever or highly generalized code.
- Follow object-oriented design where it improves separation of responsibilities.
- Give every class one clear responsibility.
- Prefer composition over inheritance.
- Avoid deep inheritance trees.
- Keep functions and methods at 30 lines or fewer whenever practical.
- Split long functions into well-named private helpers.
- Do not create meaningless wrappers only to satisfy the line limit.
- Keep control flow shallow.
- Prefer early returns over deeply nested conditions.
- Use descriptive names.
- Avoid abbreviations unless they are standard Python or Frappe terms.
- Keep public interfaces small and explicit.
- Keep parsing, resolution, persistence, retrieval, and presentation separate.
- Do not mix database access, graph resolution, and output rendering in one method.
- Prefer standard-library features before adding dependencies.
- Do not add abstractions until at least two concrete use cases need them.
- Avoid plugin systems, registries, factories, and dependency-injection frameworks unless required by a demonstrated need.
- Do not optimize before benchmarks show a bottleneck.

## Scope discipline

Current scope:

- Python source
- Frappe DocType JSON
- `hooks.py`
- common Frappe ORM and document operations
- background jobs
- whitelisted methods
- Python tests
- CLI
- read-only MCP server for Claude Code
- JavaScript, TypeScript, and Vue structural extraction (entities, imports, `extends`)
- frontend → backend resolution: JS/Vue call sites to backend methods and DocTypes (see `design/14`)
- shared multi-tenant service: JWT identity, Git mirroring, commit metadata, identity mapping,
  per-commit source indexing (see `design/15`, Phases A–D, G–I)
  - organizations, users, server-minted JWTs, repository-scoped permissions, MCP sessions, audit log
  - bare Git mirrors, authenticated Smart HTTP, ref namespaces with per-user push scoping
  - Tier-0 commit metadata: full messages, separate author/committer identities + timezones, parent
    graph, trailers, signature status, diff stats, and message search
  - Git identities anchored on email (never name similarity): harvested from authors/committers/
    co-author trailers, mapped to users by verified email / admin / explicit claim; unclaimed by default
  - revision indexing: materialize a commit tree (no checkout/execution) and reuse the local index
    engine into immutable per-commit snapshots; reused across branches, survive force-push;
    revision-scoped entity search
  - revision comparison: changed files + entity add/remove/change (signature-aware) + commit range +
    authors; branch comparison around the merge base; merge summary against the merge result tree
  - decision/feedback memory: change episodes, decisions with role-typed actors (confirmed vs inferred
    attribution; never derived from commit authorship), feedback lifecycle, history by entity, redacted
    session summaries
  - lives in `beagle/service/` (separate from the local SQLite engine); FastAPI + PostgreSQL (SQLite for tests)

Current non-goals:

- JS-internal call-graph and import resolution (facts stored, edges staged — see `design/14`)
- PR review
- GitHub integration
- embeddings
- vector databases
- conversation ingestion
- long-term memory
- web UI
- service Phases E, F (dependency analysis, local bridge) and the Phase I consumer integrations
  (MCP/CI/admin UI) — staged in `design/15`, not yet built

Do not introduce non-goal features unless the design files are intentionally updated first.

## Correctness rules

- Deterministic indexed facts are the source of truth.
- Store raw observations separately from resolved edges.
- Preserve ambiguous or unresolved observations.
- Never silently convert an uncertain relationship into a confirmed fact.
- Every resolved edge must include confidence, resolver, evidence, source range, and owner file.
- Entity IDs must remain stable when source lines move.
- Incremental indexing must not leave stale facts.
- Never execute repository Python files while indexing them.
- Never execute `hooks.py`.
- Prefer conservative Frappe semantics over speculative inference.

## Workflow

For every task:

1. Read the relevant design file.
2. Inspect existing code before proposing an abstraction.
3. Work on one small task at a time.
4. Keep the patch narrowly scoped.
5. Add or update tests with every behavior change.
6. Run targeted tests first.
7. Run the relevant benchmark when extraction, resolution, ranking, or context behavior changes.
8. Explain known false positives and false negatives.
9. Update design files only when behavior or architecture intentionally changes.

Do not skip to MCP integration before the same operation works through the CLI.

## Communication

Keep responses concise and practical.

Include:

- what changed;
- why it changed;
- important limitations;
- commands needed to test or use it.

Do not:

- repeat the task;
- explain obvious code line by line;
- provide long background sections when a short explanation is enough.

State uncertainty directly.

Add external references when a decision depends on library, Python, SQLite, MCP, or Frappe behavior. Prefer official documentation and primary sources.

## Tests and commands

Use:

```bash
uv sync
uv run project-index --help
uv run pytest
```

Run narrower suites during development, for example:

```bash
uv run pytest tests/extractors/python/
uv run pytest tests/extractors/frappe/
uv run pytest tests/resolution/
```

Do not invent commands that are not configured in `pyproject.toml`.

## Completion standard

A task is complete only when:

- behavior is implemented;
- tests pass;
- no stale indexed facts are introduced;
- public output is inspectable;
- confidence and evidence are preserved;
- the relevant benchmark does not regress unexpectedly.

