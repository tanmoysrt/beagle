# 14 — JavaScript, TypeScript, and Vue

## Why this exists

Frappe apps are full-stack. The Python backend is only half the story: Desk
client scripts, portal pages, and Vue/frappe-ui frontends call into the backend
through a small set of well-known APIs. A code-discovery engine that stops at
`.py` cannot answer the question developers ask most often about a Frappe app:

> *When the user clicks this button, which backend method runs?*

This stage moves JavaScript, TypeScript, and Vue from non-goal to in-scope and
makes that question answerable as a resolved graph edge.

## Scope of this stage

In scope:

- `.js`, `.jsx`, `.ts`, `.tsx`, `.vue` discovery.
- Structural entities: modules (one per file), classes, functions, methods,
  and top-level arrow-function consts.
- Raw observations: ES imports, `extends` clauses, and **frontend API calls**.
- Vue single-file components: the `<script>` / `<script setup>` block is
  located and its JS/TS body is parsed with line offsets preserved.
- Resolution of **frontend → backend** relationships:
  - `CALLS_BACKEND` — a JS call site to a backend whitelisted method/endpoint.
  - `QUERIES_DOCTYPE` — a JS call site to a DocType through the client ORM or a
    frappe-ui list/document resource.

Explicitly staged for later (facts are stored, edges are not yet built):

- JS-internal call graph (JS function → JS function).
- JS-internal import/`extends` resolution across files.
- Type-driven receiver inference (TS types).
- `<template>` event-handler extraction.

Storing the observations now keeps the door open without inventing confirmed
facts (see *Correctness*).

## Parser

We use `tree-sitter` via `tree-sitter-language-pack`, which ships prebuilt
`javascript`, `typescript`, `tsx`, and `vue` grammars. This is the first parser
dependency beyond LibCST; it is justified by a demonstrated need (two concrete
use cases: entity discovery and frontend→backend tracing) per the
no-abstraction-without-two-uses rule.

The bundled binding exposes a non-standard, Rust-backed API (`node.kind` not
`node.type`; `root_node()`, `start_position()`, `byte_range()` are methods;
nodes carry no `.text`). All of that is quarantined in
`extractors/javascript/binding.py` so the rest of the codebase sees a small,
clean node interface. If the binding is ever swapped, only that file changes.

> Environment note: tree-sitter's C/Rust extension misbehaves under the
> free-threaded CPython build (3.14t) — node attributes degrade. Development and
> CI must run on a standard (GIL) interpreter; 3.11 is the project baseline.

## Entity identity

Python entities are keyed by dotted module path because that is how Python
imports work. JavaScript module identity is the **file path**, so JS ids are
path-based and carry a language scheme:

```
module:  js://app/public/js/site.js
class:   js://app/public/js/site.js#SiteController
method:  js://app/public/js/site.js#SiteController.refresh
function:js://app/public/js/site.js#save_site
```

Vue components keep the `.vue` path; their script entities live under the same
file id. As with Python, ids never contain line numbers, so they survive edits
that move code within a file.

## Observations

Emitted with a `js_` prefix so the Python resolver never consumes them:

- `js_import` — `{style, module, names}` for `import x from "m"` /
  `import {a as b} from "./m"`.
- `js_inheritance` — `{base_name}` for `class X extends Base`.
- `js_api_call` — the load-bearing one. `{api, target_kind, method, doctype,
  url, args}` where `target_kind` is `method` or `doctype`. Covers:

| Call shape                                            | target_kind | captured |
|-------------------------------------------------------|-------------|----------|
| `frappe.call({method: "app.api.run"})`                | method      | method   |
| `frappe.xcall("app.api.run")`                         | method      | method   |
| `frm.call("refresh")` / `frm.call({method})`          | method      | method (controller-local hint) |
| frappe-ui `call("app.api.run", args)`                 | method      | method   |
| `createResource({url: "app.api.run"})`                | method      | url      |
| `frappe.db.get_list("ToDo", …)` and the `db.*` family | doctype     | doctype  |
| `createListResource({doctype: "ToDo"})`               | doctype     | doctype  |
| `createDocumentResource({doctype: "ToDo", name})`     | doctype     | doctype  |

`method`/`url`/`doctype` are recorded only when they are **string literals**.
A computed method name is preserved as an unresolved observation, never guessed.

## Resolution

`resolution/javascript.py` runs as one more pass inside `resolve_workspace`,
after the symbol table and Frappe DocType map are built, so it sees backend
entities from every file.

- `method`/`url` (dotted) → `SymbolTable.resolve_absolute(dotted)` → the Python
  function entity (the whitelisted handler). Falls back to the `endpoint`
  entity by qualified name. Resolved → `CALLS_BACKEND`, confidence 0.9.
- `doctype` (name) → DocType-by-name map → `QUERIES_DOCTYPE`, confidence 0.9.
- Anything unresolved is emitted with `target_id=None` and a `target_hint`, the
  same contract every other resolver follows.

`frm.call("refresh")` names a method on the *current form's* DocType, which is
not known from the call site alone; it is kept as an unresolved
`CALLS_BACKEND` with the bare method name as hint. Resolving it would require
binding the file to its DocType (a `.js` next to a `doctype.json`), which is a
natural follow-up.

## Correctness

This stage obeys the same rules as the rest of the engine:

- Deterministic facts only. A backend edge is built only from a string-literal
  method/doctype.
- Observations are stored even when they cannot be resolved; nothing uncertain
  is upgraded to a confirmed fact.
- Entity ids are stable across in-file moves.
- The parser never executes the file under analysis.

### Known false positives / negatives

- **FN:** computed method names (`frappe.call({method: x})`), methods built by
  string concatenation, and `frm.call` against an unknown DocType are not
  resolved.
- **FN:** REST-style `url` paths (`/api/resource/ToDo`) are not yet decoded to a
  DocType.
- **FP risk:** a dotted string that coincides with a Python function path but is
  not actually whitelisted resolves to that function. Confidence is 0.9, not
  1.0, to reflect that the whitelist is not re-checked at the call site.

## CLI / MCP

No new surface. The new entities are searchable through the existing entity and
FTS search; the new edges traverse through the existing graph queries, so
`CALLS_BACKEND` / `QUERIES_DOCTYPE` appear in callers/neighbours output for free.
