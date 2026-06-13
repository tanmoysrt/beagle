# 10 — Lifecycle Validation, Versioning, and Benchmarks

## Goal

Prevent Beagle from encoding one approximate lifecycle forever.

Frappe lifecycle behavior changes between versions and can be altered by effective controllers, app order, flags, and site configuration.

The implementation must be source-backed, versioned, and benchmarked.

## Pin the framework source

Every benchmark repository must record:

```text
Frappe repository commit SHA
Frappe version
Press commit SHA
Python version
installed apps and order when available
```

Do not use the moving `develop` branch as a benchmark identity.

Store lifecycle policy metadata:

```json
{
  "framework": "frappe",
  "version": "detected version",
  "commit": "pinned SHA",
  "policy_version": 1
}
```

## Policy adapters

Create a small interface:

```python
class LifecyclePolicy:
    def events_for(self, operation, action, context):
        ...

    def supports(self, framework_version):
        ...
```

Start with one adapter for the pinned current Frappe source.

Do not build a large plugin framework. Add another adapter only when a real supported Frappe version differs.

## Source verification checklist

For every policy release, verify:

- `Document.insert`
- `Document.save` / `_save`
- action detection and docstatus transitions
- `run_before_save_methods`
- `run_post_save_methods`
- `submit` / `_submit`
- `cancel` / `_cancel`
- `db_set`
- `discard`
- `delete` and `frappe.delete_doc`
- `run_method`
- controller hook composition
- controller override and extension resolution
- child table persistence
- Single DocType behavior
- Virtual DocType behavior

Record the relevant source functions in benchmark metadata.

## Synthetic fixture matrix

### Standard operations

- [ ] new document `insert`
- [ ] new document `save` routing to insert
- [ ] existing draft save
- [ ] submit
- [ ] cancel
- [ ] update after submit
- [ ] `db_set`
- [ ] direct `frappe.db.set_value`
- [ ] direct `db_update`
- [ ] delete
- [ ] discard

### Handler dispatch

- [ ] controller-only event
- [ ] exact `doc_events`
- [ ] wildcard `doc_events`
- [ ] multiple handlers
- [ ] multiple apps with known order
- [ ] app order unavailable
- [ ] `override_doctype_class`
- [ ] multiple overrides
- [ ] `extend_doctype_class`
- [ ] extension calling `super`
- [ ] extension not calling `super`
- [ ] literal custom `run_method`

### Data-flow cases

- [ ] literal `get_doc` receiver
- [ ] `new_doc` receiver
- [ ] dict with literal `doctype`
- [ ] typed helper return
- [ ] ambiguous helper return
- [ ] unknown receiver
- [ ] nested save in an event handler
- [ ] lifecycle recursion cycle

### Special behavior

- [ ] child table insert through parent
- [ ] child table update through parent
- [ ] Single DocType save
- [ ] Virtual DocType override
- [ ] `ignore_validate`
- [ ] operation override with `super`
- [ ] operation override without `super`
- [ ] runtime Notification/Webhook/Server Script channel

## Critical negative tests

Beagle must not infer:

```text
child controller hooks from parent child-row persistence
normal save hooks from frappe.db.set_value
normal save hooks from db_update
known runtime handlers without site metadata
standard lifecycle after an override that bypasses super
one definitive MRO when installed-app order is unknown
```

These negative tests are as important as recall tests.

## Real repository benchmark

Select at least 30 manually verified flows from pinned Frappe and Press commits.

Each case should start from real application code:

```text
entry function
  → document mutation
  → persistence operation
  → lifecycle event
  → controller or hook handler
  → important downstream call or job
```

Include:

- common draft saves;
- submit/cancel flows;
- background jobs;
- controller extensions or overrides;
- wildcard hooks;
- nested document saves;
- direct database writes that must not expand.

## Gold-case format

```yaml
question: What runs when activate_site saves Site?
entry_entity: press.api.activate_site
expected:
  operations:
    - type: SAVES_DOCTYPE
      target: Site
  events:
    - before_validate
    - validate
    - before_save
    - on_update
    - on_change
  handlers:
    - press.press.doctype.site.site.Site.on_update
must_not_include:
  - child_row_on_update
  - direct_db_write_as_save
uncertainty:
  - site_runtime_handlers
```

Include exact source ranges and the pinned commit.

## Accuracy targets

```text
Persistence-operation precision               >= 98%
Persistence-operation recall                  >= 95%
Receiver DocType precision                    >= 96%
Receiver DocType recall                       >= 90%
Lifecycle-event precision                     >= 99%
Lifecycle-event recall                        >= 95%
Controller-handler precision                  >= 98%
doc_events handler precision                  >= 98%
Important transitive-edge recall              >= 88%
Incorrect high-confidence lifecycle paths     = 0
Stale lifecycle facts after update            = 0
```

## Performance targets

```text
Lifecycle lookup p95                          < 100 ms
Depth-2 framework trace p95                   < 500 ms
Lifecycle context compilation p95             < 1 second
Single changed hooks.py re-resolution         < 1 second
Single changed controller re-resolution       < 1 second
```

Measure before enforcing on large repositories.

## Mermaid validation

For selected traces, assert:

- every node maps to an entity or observation;
- every edge maps to explicit code or lifecycle policy;
- event order matches the policy;
- uncertain dispatch is visibly distinct;
- child lifecycle is not invented;
- graph limits do not remove the primary failure or state path.

Target:

```text
Invented diagram nodes or edges = 0
```

## Claude Code benchmark

Compare:

```text
Claude using Read/Grep/Glob
Claude using Beagle without framework expansion
Claude using Beagle with framework expansion
```

Record:

- correctness;
- source lines read;
- tool calls;
- input tokens;
- missed hooks;
- invented hooks;
- elapsed time.

Framework expansion succeeds when it improves lifecycle-answer correctness and reduces manual exploration without increasing unsupported claims.

## Regression workflow

When Frappe lifecycle source changes:

1. pin the new commit;
2. diff the verified source functions;
3. update the adapter;
4. update synthetic cases;
5. regenerate expected event sequences;
6. run real repository benchmarks;
7. publish the changed assumptions.

Never silently update lifecycle semantics.

## Definition of done

Lifecycle expansion is ready for Claude Code when:

- all operation policies are pinned and source-backed;
- exact and wildcard hooks resolve correctly;
- controller MRO is handled or marked uncertain;
- runtime-only handlers are honestly reported as unknown;
- critical negative tests pass;
- no high-confidence false lifecycle path exists;
- Mermaid output is fully evidence-backed.
