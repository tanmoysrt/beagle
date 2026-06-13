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

## Stage 5: Frappe runtime semantics — DONE

Hooks:

- [x] `doc_events`
- [x] `scheduler_events`
- [x] `override_doctype_class`
- [x] `extend_doctype_class` (EXTENDS_CONTROLLER)
- [x] `override_whitelisted_methods` (OVERRIDES)
- [x] permission hooks (`has_permission`, `permission_query_conditions`) (PERMISSION_CHECK)

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
- [~] `reads-field` — DocType-granular (field-level reads not extracted)
- [x] `writes-field` — field-level via WRITES_FIELD (set_value field arg + controller self.<field>)
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

## Design 08 — Frappe document lifecycle policy — DONE

- [x] Add document-operation observations (reuse call obs + receiver resolution).
- [x] Resolve receiver DocTypes (literal get_doc/new_doc + controller self).
- [~] Detect docstatus transitions — action derived from operation method;
      true draft↔submitted transitions need runtime state (reported, not guessed).
- [x] Create versioned operation policies (FrappeLifecyclePolicy, pinned commit).
- [~] Lifecycle-event entities — synthetic IDs generated at query time, not stored
      rows (keeps the index to deterministic facts).
- [x] Generate ordered events (policy.events_for) + operation edges.
- [~] Detect operation overrides and `super()` continuation — override of an op
      method is flagged "standard lifecycle conditional"; full super-trace is partial.
- [x] Handle nested `db_set()` in discard (policy sequence).
- [x] Model delete through `frappe.delete_doc`.
- [x] Prevent lifecycle expansion for direct DB writes (set_value/db.delete).
- [x] Prevent automatic child-row lifecycle expansion (negative-tested).
- [~] Single/Virtual DocType handling — standard policy applies; virtual override
      treated as conditional via the override note.
- [x] Cycle and depth limits (trace).

## Design 09 — Frappe event dispatch resolution — DONE

- [x] Event nodes + differentiated dispatch categories (controller/exact/wildcard/runtime).
- [x] Effective controller resolution.
- [~] Overrides via installed-app order — multiple overrides preserved + marked
      uncertain (app order unknown from repo alone), never silently picked.
- [x] Extensions and MRO (extend_doctype_class mixins first).
- [~] `super()` continuation across lifecycle methods — partial.
- [x] Exact and wildcard `doc_events`.
- [~] Hook declaration order — preserved; cross-app order marked unknown.
- [x] Literal `run_method` (RUNS_EVENT).
- [x] Runtime Notification/Webhook/Server Script channels (reported unknown).
- [ ] Optional site-snapshot provider (deferred).
- [x] Continue transitive calls/jobs/operations from handlers.
- [x] Framework-cycle prevention.
- [x] Render dispatch categories separately (Mermaid solid/dashed/dotted).

CLI: `lifecycle`, `event-handlers`, `trace`, `explain --framework-events`.
MCP: `event_handlers`, `lifecycle`, `trace`.

## Design 10 — Lifecycle validation, versioning, benchmarks — PARTIAL

- [x] Pinned framework source (commit in POLICY_META) + policy metadata.
- [x] Policy adapter interface (LifecyclePolicy) with one Frappe adapter.
- [x] Source verification of the key Document functions (done before coding).
- [x] Synthetic fixture matrix essentials + critical negative tests
      (no child lifecycle, db_set ≠ save, set_value ≠ operation, override uncertain).
- [ ] Full 30+ manually-verified real-repo lifecycle gold cases with accuracy
      gates — seeded/validated on press by hand; formal gold set not yet authored.

## Design 11 — Issue investigation and context compilation — DONE (benchmarks partial)

Most of the pipeline shipped in Stage 7 (`investigate`) and Stage 9 (context).
This design added the remaining pieces:

- [x] Deterministic query term expansion (curated synonyms + plural/singular),
      kept separate from concept terms so a derived word never outranks an
      exact match (`investigate/issue.py`, `IssueQuery.expansions`).
- [x] Framework-lifecycle section: implicit Frappe lifecycle expanded for
      resolved document operations on cited candidates (LifecycleService wired
      into `Investigator`; omitted gracefully when no service is supplied).
- [x] Structured result (§12): `primary_workflows`, `conditions`,
      `state_changes`, `external_boundaries`, `framework_events`, `tests`,
      `change_points`, `unknowns`, `sources` (with score + reasons).
- [x] Compact / source / mermaid output modes; deterministic node-capped
      `investigate/mermaid.py` (solid call, dashed lifecycle/boundary).
- [x] CLI flags: `--compact`, `--include-source`, `--mermaid`,
      `--show-query-terms`, `--show-scores`, `--show-paths`, `--show-unknowns`.
- [x] MCP `investigate(query, max_tokens, include_source, include_mermaid)` —
      compact structured result by default (§17).
- [x] `investigate` context-compiler intent (§11).
- [~] Path-type labels and multiple-workflow ranking — single ranked workflow
      with a reason; per-hop path-type labelling is partial.
- [~] Category token budgets (§11 percentages) — investigate uses a cite cap,
      not per-category budget rebalancing.
- [ ] §19 synthetic ranking-benchmark matrix and §20 20+ real gold issues
      (TLS verified by hand; formal labelled corpus + accuracy gates not authored).
