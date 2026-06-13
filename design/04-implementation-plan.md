# 04 — Implementation Plan

Status legend: `[x]` done · `[~]` partial (note follows) · `[ ]` not started ·
`[n/a]` permanent honest-unknown by design (a runtime/install fact the repo
cannot know; reported as uncertain, never guessed).

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
- [x] `reads-field` — field-level via READS_FIELD (ORM get_value field arg +
      self.<field> in numeric comparisons); falls back to DocType-level when no
      field-level read is captured. Plain assignment-RHS reads are not tracked.
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
- [x] render deterministic Mermaid flowcharts.

## Stage 9: context compiler — DONE

- [x] `locate`
- [x] `understand`
- [x] `investigate` — both a dedicated command/service (Stage 7) and a
      context-compiler intent (design/11 §11);
- [x] `change`
- [x] `debug`
- [x] `test`

Returns entities, inclusion reasons, confidence, paths, ranges, and excerpts: [x].

## Stage 10: MCP — DONE

- [x] Read-only MCP server (17 tools) over all retrieval services, including
      `investigate` and `explain_function`. Every tool calls a tested service.

## Stage 11: optional local LLM — DROPPED

Removed from scope. Claude (via the CLI consumer and the MCP server) is the only
LLM layer; Beagle ships no bundled local model. Intent classification, query
expansion, ranking, and label shortening are Claude's job. The engine stays
fully deterministic and never depends on a model to produce graph facts or
diagram edges.

## Design 08 — Frappe document lifecycle policy — DONE

- [x] Add document-operation observations (reuse call obs + receiver resolution).
- [x] Resolve receiver DocTypes (literal get_doc/new_doc + controller self).
- [n/a] Detect docstatus transitions — action derived from operation method.
      True draft↔submitted transitions are a runtime fact (depend on the row's
      current docstatus); permanent honest-unknown, reported not guessed.
- [x] Create versioned operation policies (FrappeLifecyclePolicy, pinned commit).
- [~] Lifecycle-event entities — synthetic IDs generated at query time, not stored
      rows (keeps the index to deterministic facts).
- [x] Generate ordered events (policy.events_for) + operation edges.
- [x] Detect operation overrides and `super()` continuation — override of an op
      method is flagged "standard lifecycle conditional"; the trace continues into
      the next controller-MRO method when the effective method actually calls
      `super().<event>()` (source-backed; see design/09 entry).
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
- [n/a] Overrides via installed-app order — permanent honest-unknown: install
      order is a bench/site fact, not in the repo. Multiple overrides are
      preserved and marked uncertain, never silently picked.
- [x] Extensions and MRO (extend_doctype_class mixins first).
- [x] `super()` continuation across lifecycle methods — `EventDispatcher.controller_chain`
      yields the ordered MRO methods (Frappe-injected extend/override order a
      pure-Python base walk can't see); the trace adds a continuation edge to the
      next method only when the earlier one actually calls `super().<event>()`.
- [x] Exact and wildcard `doc_events`.
- [~] Hook declaration order — preserved; cross-app order marked unknown.
- [x] Literal `run_method` (RUNS_EVENT).
- [x] Runtime Notification/Webhook/Server Script channels (reported unknown).
- [n/a] Site-snapshot provider — permanent honest-unknown by design. Runtime
      Notification/Webhook/Server Script handlers live in a site DB, not the
      repo; reported as existing-but-unknown rather than guessed.
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
- [x] Path-type labels — each workflow hop carries its type (`call`,
      `job dispatch`, `lifecycle: <op>`); rendered as Mermaid edge labels.
- [~] Multiple-workflow ranking — still a single ranked workflow with a reason.
- [~] Category token budgets (§11 percentages) — investigate uses a cite cap,
      not per-category budget rebalancing.
- [ ] §19 synthetic ranking-benchmark matrix and §20 20+ real gold issues
      (TLS verified by hand; formal labelled corpus + accuracy gates not authored).
