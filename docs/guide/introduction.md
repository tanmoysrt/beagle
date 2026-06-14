# What is beagle?

**beagle** is a local code-discovery engine for Python and
[Frappe](https://frappeframework.com/) projects, including their JavaScript,
TypeScript, and Vue frontends.

It reads a repository, extracts structural facts, resolves the relationships
between them, and stores everything in a local SQLite graph. You then query that
graph from the command line — or from [Claude Code](./mcp) over MCP — to answer
the questions you actually have about a codebase:

- How does this feature work?
- Where is this symbol defined, and who calls it?
- Which hooks, jobs, DocTypes, fields, and tests are related to it?
- When the user clicks a button in the frontend, which backend method runs?
- What runs when a document is saved or submitted?
- What source should I read before changing this?

## What makes it different

**It is deterministic.** The engine ships no model and calls no LLM. Every
answer comes from parsing and rule-based resolution, so results are repeatable
and explainable. Claude Code is an optional consumer that sits *on top* of the
engine; it is never in the engine's hot path.

**It is evidence-first.** beagle separates raw parser observations from resolved
edges. Every resolved relationship carries its **confidence**, the **resolver**
that produced it, the **evidence** behind it, the **source range** to read, and
the **owner file**. Uncertain relationships stay uncertain — beagle never
silently promotes a guess into a confirmed fact.

**It understands Frappe.** Generic Python tooling sees functions and classes.
beagle additionally sees DocTypes, fields, controllers, `hooks.py` event
dispatch, background jobs, whitelisted endpoints, and the document lifecycle.

**It is full-stack.** Frappe apps span a Python backend and a JS/TS/Vue
frontend. beagle traces frontend call sites (`frappe.call`, the client ORM,
frappe-ui resources) to the backend methods and DocTypes they hit, so the
frontend and backend show up as one connected graph.

## Scope

In scope today:

- Python source, plus Frappe DocType JSON, `hooks.py`, ORM/document operations,
  background jobs, whitelisted methods, and Python tests.
- JavaScript / TypeScript / Vue structural extraction (entities, imports,
  `extends`).
- Frontend → backend resolution: JS/Vue call sites to backend methods and
  DocTypes.
- A CLI and a read-only MCP server.

Not in scope (by design): the JS-internal call graph (facts are stored, edges
are staged), PR review, GitHub integration, embeddings, vector databases, and
any hosted/multi-repository service.

## Who it's for

Developers working in large Python/Frappe codebases who want fast, precise
discovery — and anyone pairing with Claude Code who wants the assistant to read
the *right* few hundred lines instead of grepping the whole tree.

Next: [Installation](./installation) → [Quickstart](./quickstart).
