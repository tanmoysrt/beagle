# 04 — Implementation Plan

Status legend: `[x]` done · `[~]` partial (note follows) · `[ ]` not started.

## Stage 1: foundation — DONE

- [x] Create package, CLI, and test skeleton.
- [x] Add SQLite migrations.
- [x] Implement repository-root detection.
- [x] Implement gitignore-aware discovery.
- [x] Add file hashing.
- [x] Handle added, changed, renamed, and deleted files.
- [x] Add symbol-scoped source chunks and FTS5.
- [x] Implement `index`, `status`, `search`, and `read`.

## Stage 2: Python extraction — DONE (literals/returns handled differently)

Using LibCST, extract:

- [x] modules;
- [x] classes;
- [x] functions and methods;
- [x] nested functions;
- [x] signatures;
- [x] decorators;
- [x] docstrings;
- [x] imports and aliases;
- [x] inheritance expressions;
- [x] assignments and calls;
- [~] string and numeric literals — string args captured on calls (`first_arg`);
      numeric literals captured inside comparisons; no standalone literal table;
- [x] comparisons and branch conditions (`comparison` observations);
- [x] exception handlers, raises (`except`/`raise` observations);
      [~] returns are reconstructed on demand by the flow builder, not indexed;
- [x] subprocess and shell-command calls — detected from call observations
      (dotted/`first_arg`) in investigate and the flow builder;
- [x] test classes and methods.

Stable qualified names and exact source ranges: [x].

## Stage 3: Python resolution — DONE

- [x] same lexical scope (via constructor/annotated assignment propagation);
- [x] same module;
- [x] imported names and aliases;
- [x] explicit class references;
- [x] `self.method()` and `cls.method()`;
- [x] `super().method()`;
- [x] inherited methods;
- [x] simple constructor and annotated assignments; plus `Foo().bar()` chains;
- [x] dotted Python paths.
- [x] Preserve unresolved and ambiguous calls (target_id NULL + hint).

## Stage 4: Frappe schema — DONE

- [x] Discover apps and DocType JSON files.
- [x] Create DocType and field entities.
- [x] Resolve Link fields.
- [x] Resolve Table and Table MultiSelect fields.
- [x] Preserve Dynamic Link observations.
- [x] Associate controller modules and classes.
- [x] Associate conventional test modules.

## Stage 5: Frappe runtime semantics — MOSTLY DONE

Hooks:

- [x] `doc_events`
- [x] `scheduler_events`
- [x] `override_doctype_class`
- [ ] `extend_doctype_class`
- [ ] `override_whitelisted_methods`
- [ ] permission hooks (`has_permission`, `permission_query_conditions`)

APIs:

- [x] `frappe.get_doc`
- [x] `frappe.new_doc`
- [x] `frappe.get_all`
- [x] `frappe.get_list`
- [x] `frappe.get_value`
- [x] `frappe.db.get_value`
- [x] `frappe.db.get_all`
- [x] `frappe.db.set_value`
- [x] `frappe.delete_doc`
- [x] `frappe.db.delete`
- [x] `frappe.enqueue`
- [x] `frappe.enqueue_doc`
- [x] `@frappe.whitelist`
- [x] known status and counter writes (status/state assignments + `counter` observations,
      surfaced by investigate)

## Stage 6: graph exploration — DONE

- [x] `resolve`
- [x] `show`
- [x] `relations`
- [x] `callers`
- [x] `callees`
- [x] `path`
- [x] `uses-doctype`
- [~] `reads-field` — DocType-granular (field-level access not yet extracted)
- [~] `writes-field` — DocType-granular
- [x] `tests`
- [x] `impact`

## Stage 7: issue-driven discovery — DONE

```bash
beagle investigate "TLS certificate renewal stops after 5 attempts"
beagle investigate --file issue.md
```

- [x] preserve exact phrases, identifiers, and numbers;
- [x] search names, source, literals, comments, exceptions, and commands (FTS prefix);
- [x] rank initial symbol and DocType seeds;
- [x] expand callers, callees, hooks, jobs, fields, and tests;
- [x] prioritize retry counters, thresholds, status writes, exceptions, and external commands;
- [x] reconstruct probable workflows;
- [x] return important files and exact ranges;
- [x] separate confirmed facts from likely candidates (resolved edges vs lexical reasons);
- [x] report missing evidence and unanswered questions (Unknowns section).

Output sections all implemented (Likely area … Source ranges).

## Stage 8: function explanation and Mermaid — DONE

```bash
beagle explain "Site.deploy"
beagle explain "Site.deploy" --mermaid
beagle explain "Site.deploy" --mermaid --expand-calls 1
```

- [x] build a simplified flow from branches, loops, calls, returns, and exceptions;
- [x] include Frappe reads, writes, and enqueued jobs;
- [x] optionally expand selected resolved callees;
- [x] limit diagrams to the most important 15–20 nodes (node cap);
- [x] map every node to source evidence (node→path:line);
- [x] render deterministic Mermaid flowcharts;
- [ ] allow an optional local LLM to shorten labels only (deferred to Stage 11).

## Stage 9: context compiler — DONE

- [x] `locate`
- [x] `understand`
- [~] `investigate` — implemented as a dedicated command/service (Stage 7), not a
      context-compiler intent;
- [x] `change`
- [x] `debug`
- [x] `test`

Returns entities, inclusion reasons, confidence, paths, ranges, and excerpts: [x].

## Stage 10: MCP — DONE

- [x] Read-only MCP server (17 tools) over all retrieval services, including
      `investigate` and `explain_function`. Every tool calls a tested service.

## Stage 11: optional local LLM — NOT STARTED (out of scope until benchmarks gate it)

- [ ] intent classification, query expansion, retrieval planning, candidate
      ranking, concise explanations, shortening Mermaid labels.
- The model must not create authoritative graph facts or diagram edges.
