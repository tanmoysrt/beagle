# 09 — Frappe Event Dispatch Resolution

## Goal

Resolve what actually runs when Frappe calls:

```python
doc.run_method("on_update")
```

The result is broader than a single controller method.

For a known DocType and event, Beagle should discover:

1. effective controller method;
2. exact-DocType `doc_events` handlers;
3. wildcard `doc_events["*"]` handlers;
4. Notifications;
5. Webhooks;
6. Server Scripts;
7. calls, jobs, and document operations performed by those handlers.

## Dispatch model

Represent one event as a synthetic node:

```text
frappe-event://Site/on_update
```

Recommended edges:

```text
HANDLED_BY_CONTROLLER
HANDLED_BY_DOC_EVENT
HANDLED_BY_WILDCARD_DOC_EVENT
MAY_RUN_NOTIFICATION
MAY_RUN_WEBHOOK
MAY_RUN_SERVER_SCRIPT
```

Do not merge these into a single undifferentiated `CALLS` list.

## Static dispatch order

For standard `Document.run_method` behavior, preserve this order:

```text
effective controller method
exact-DocType doc_events handlers
wildcard doc_events handlers
Notifications
Webhooks
Server Scripts
```

Controller and `doc_events` handlers are composed before the runtime integrations are invoked.

The final answer should clearly separate:

```text
Repository-resolved handlers
Site/runtime-configured handlers
```

## Controller method resolution

Build the effective controller before resolving an event.

### Base controller

Start from the conventional DocType controller.

### `override_doctype_class`

The effective override depends on hooks resolution and installed-app order.

When multiple overrides exist:

- preserve all declarations;
- use known app order to identify the effective one;
- otherwise mark the chosen controller as unresolved;
- never silently pick one by file order.

### `extend_doctype_class`

Available in newer Frappe versions and applied on top of the base or overridden controller.

For app order:

```text
frappe, app1, app2
```

the effective MRO is shaped like:

```text
App2Mixin, App1Mixin, EffectiveBase
```

Method execution depends on each implementation calling `super()`.

Beagle must:

- build the effective MRO;
- find all implementations of the lifecycle method;
- trace `super()` continuation;
- stop when an implementation does not continue;
- show conditional MRO paths when app order is unknown.

## `doc_events` resolution

Support statically evaluable forms:

```python
doc_events = {
    "Site": {
        "on_update": "press.events.on_site_update",
    },
    "*": {
        "on_update": [
            "audit.events.record",
            "search.events.refresh",
        ],
    },
}
```

Extract:

- exact DocType;
- wildcard DocType;
- event name;
- one or multiple dotted targets;
- declaring app;
- declaring file and range;
- hooks resolution order.

Resolve targets without importing or executing `hooks.py`.

Unsupported dynamic expressions remain observations.

## Hook execution ordering

Hook values are collected from installed apps.

For one event, keep:

```text
controller
exact handlers in resolved app order
wildcard handlers in resolved app order
```

Do not assume alphabetical app order.

When installed-app order is unavailable:

- preserve declarations;
- mark exact ordering unknown;
- do not fabricate an effective sequence.

## Generic `run_method`

Index literal calls such as:

```python
doc.run_method("rebuild_cache")
doc.run_trigger("custom_event")
```

These can dispatch controller methods and hooks even when the name is not part of the standard CRUD lifecycle.

Create event nodes for literal custom method names.

Computed names remain unresolved observations.

## Runtime integrations

After controller and `doc_events`, Frappe can invoke runtime-configured behavior.

### Notifications

Repository-only indexing may discover Notification definitions exported as fixtures or JSON, but most are site records.

Model:

```text
MAY_RUN_NOTIFICATION
```

and resolve exact records only when site metadata is available.

### Webhooks

Handle the same way:

```text
MAY_RUN_WEBHOOK
```

### Server Scripts

Server Scripts can run for document events and are often site-specific.

Model:

```text
MAY_RUN_SERVER_SCRIPT
```

Do not execute scripts during indexing.

Without a site snapshot, report:

```text
Runtime dispatch channel exists; concrete handlers are unknown.
```

## Optional site metadata snapshot

A later read-only snapshot can provide:

- installed apps and order;
- Notification records;
- Webhook records;
- Server Scripts;
- custom DocTypes;
- custom fields and property setters.

Repository facts and site facts must retain separate provenance.

## Transitive exploration

After resolving handlers, continue through:

```text
CALLS
ENQUEUES
READS_DOCTYPE
WRITES_DOCTYPE
WRITES_FIELD
document lifecycle operations
```

Example:

```text
site.save()
  → Site.on_update event
  → exact doc_event handler
  → frappe.enqueue(...)
  → background function
  → Deployment.save()
  → Deployment.on_update event
```

Use cycle detection across event boundaries.

## Confidence

Suggested confidence:

```text
1.00 standard event emitted by confirmed operation policy
0.99 effective controller method with known MRO
0.98 static exact doc_events target
0.98 static wildcard target
0.90 controller/MRO result with incomplete app ordering
0.70 known runtime channel without concrete site record
```

Each handler edge includes:

- event source;
- dispatch category;
- hook declaration;
- app and app order;
- controller MRO evidence;
- confidence.

## CLI and MCP

```bash
beagle event-handlers "Site.on_update"
beagle lifecycle "Site" --event on_update
beagle trace "activate_site" --framework-events --depth 2
```

MCP tools:

```text
event_handlers(doctype, event)
lifecycle(doctype, event?)
trace(entity, framework_events=True, depth=2)
```

## Mermaid conventions

Use different edge styles:

```text
solid    explicit Python call
dashed   framework lifecycle dispatch
dotted   possible runtime-configured dispatch
```

Show handler categories rather than presenting every handler as a direct call from the original function.

## Implementation tasks

- [ ] Add event entities and dispatch edge types.
- [ ] Build effective controller resolution.
- [ ] Resolve overrides using installed-app order.
- [ ] Resolve extensions and MRO.
- [ ] Trace `super()` across lifecycle methods.
- [ ] Parse exact and wildcard `doc_events`.
- [ ] Preserve hook declaration order.
- [ ] Index literal `run_method` and `run_trigger`.
- [ ] Add runtime Notification/Webhook/Server Script channels.
- [ ] Add optional site-snapshot provider later.
- [ ] Continue transitive calls and jobs from handlers.
- [ ] Add framework-cycle prevention.
- [ ] Render dispatch categories separately.

## Definition of done

For a confirmed event, Beagle must show:

- the effective controller implementation chain;
- exact-DocType handlers;
- wildcard handlers;
- known order or explicit ordering uncertainty;
- possible runtime-configured integrations;
- downstream calls and jobs;
- source ranges and provenance;
- no imported or executed repository code.
