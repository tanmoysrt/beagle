# 08 — Frappe Document Lifecycle Policy

## Goal

Teach Beagle the implicit lifecycle triggered by Frappe document operations.

Example:

```python
site = frappe.get_doc("Site", name)
site.status = "Active"
site.save()
```

Beagle should connect:

```text
caller
  → writes Site.status
  → saves Site
  → before_validate
  → validate
  → before_save
  → database update
  → on_update
  → on_change
```

Each event must then resolve to its effective controller and hook handlers.

## Source of truth

Use Frappe source, not only the documentation table, for exact ordering.

The lifecycle policy must be tied to a pinned Frappe commit. The `develop` branch is mutable.

Primary source:

- `frappe/model/document.py`
- `frappe/model/delete_doc.py`
- `frappe/model/base_document.py`

Documentation remains useful for public semantics, but source decides ordering and conditional behavior.

## Graph model

Do not flatten implicit framework dispatch into ordinary `CALLS`.

```text
Function
  SAVES_DOCTYPE
DocType
  TRIGGERS_EVENT
LifecycleEvent
  HANDLED_BY
Controller or hook function
```

Add operation relationships:

```text
INSERTS_DOCTYPE
SAVES_DOCTYPE
SUBMITS_DOCTYPE
CANCELS_DOCTYPE
UPDATES_AFTER_SUBMIT
DB_SETS_DOCTYPE
DELETES_DOCTYPE
DISCARDS_DOCTYPE
```

Synthetic event IDs:

```text
frappe-event://Site/before_validate
frappe-event://Site/validate
frappe-event://Site/on_update
frappe-event://Site/on_change
```

Every generated edge stores:

- operation source range;
- resolved DocType and evidence;
- lifecycle policy version;
- event order;
- confidence;
- applicable conditions.

## Standard operation policies

These sequences describe the standard `Document` implementation from the pinned source.

### New document: `insert()`

Business lifecycle:

```text
before_insert
naming
before_validate
validate
before_save
internal validation
database insert
after_insert
on_update
on_change
```

Important details:

- `before_insert` runs before naming.
- `after_insert` runs before the normal post-save events.
- `run_post_save_methods()` then emits `on_update` and finally `on_change`.
- A new/local document passed to `save()` routes to `insert()`.

Beagle may collapse internal validation and persistence steps in compact output, but event order must remain correct.

### Existing draft: `save()`

```text
before_validate
validate
before_save
internal validation
database update
on_update
on_change
```

The action is determined from the previous and current `docstatus`, not merely from the called method name.

### Submit: `submit()`

`submit()` sets submitted docstatus and delegates to `save()`.

```text
before_validate
validate
before_submit
internal validation
database update
on_update
on_submit
on_change
```

`on_update` occurs before `on_submit`.

### Cancel: `cancel()`

`cancel()` sets cancelled docstatus and delegates to `save()`.

```text
before_cancel
database update
on_cancel
back-link validation
on_change
```

Do not add `before_validate` or `validate` to the standard cancel path.

### Update after submit

When the old and new document remain submitted:

```text
before_update_after_submit
internal validation
validate_update_after_submit
database update
on_update_after_submit
on_change
```

Do not treat this as a normal draft save.

### `db_set()`

Source behavior:

```text
before_change
direct database field update
on_change
optional notify
optional commit
```

It does not run the normal validation/save lifecycle.

### Direct database operations

These must not trigger document lifecycle expansion:

```text
frappe.db.set_value(...)
frappe.db.delete(...)
doc.db_update()
doc.db_insert()
raw SQL
query builder update/delete
```

Model them as direct data writes unless source code explicitly calls an event afterward.

### Delete

The standard delete path is outside `Document.delete()` and delegates to `frappe.delete_doc`.

Relevant event order:

```text
on_trash
on_change
link checks and database deletion
after_delete
```

Conditions such as `ignore_on_trash` must be preserved when statically visible.

### Discard

The standard discard path includes a nested `db_set()`:

```text
before_discard
db_set(docstatus)
  → before_change
  → direct update
  → on_change
on_discard
```

Represent the nested operation rather than inventing a separate simplified order.

## Action detection

`save()` alone is insufficient to determine the lifecycle.

Use the document-status transition:

```text
Draft → Draft          save
Draft → Submitted      submit
Submitted → Submitted update_after_submit
Submitted → Cancelled  cancel
```

Invalid transitions should not produce confirmed lifecycle paths.

When the previous status is unknown, return candidate actions with lower confidence.

## Receiver DocType resolution

Use evidence in this order:

1. `frappe.get_doc("DocType", ...)`
2. `frappe.new_doc("DocType")`
3. dict with a literal `doctype`
4. controller class identity
5. typed or constructor assignment
6. resolved helper return type
7. data-flow candidate

Do not expand lifecycle when DocType confidence is below the configured threshold.

## Controller overrides

A custom controller may override:

```text
insert
save
_submit
submit
_cancel
cancel
delete
db_set
discard
run_before_save_methods
run_post_save_methods
run_method
```

Before applying the standard policy:

1. resolve the effective controller class;
2. check whether the operation is overridden;
3. inspect whether the override calls `super()`;
4. mark the standard lifecycle as conditional when the call chain is unclear;
5. do not claim standard events when an override clearly bypasses them.

This is essential for correctness.

## Child table behavior

Parent insert/save persists child rows using direct `db_insert()` or `db_update()`.

Therefore:

- child rows do not automatically receive their own full controller lifecycle;
- do not emit child `validate`, `on_update`, or `doc_events` solely because the parent is saved;
- parent controller methods may still explicitly call child methods;
- virtual DocTypes may implement different child behavior.

This must have dedicated regression tests.

## Single and virtual DocTypes

### Single DocType

The persistence primitive differs, but the surrounding standard lifecycle still applies.

### Virtual DocType

Virtual controllers may override persistence methods and child management.

Treat standard database stages as conditional. Prefer the effective controller implementation over the default policy.

## Ignore flags and early exits

Index statically visible flags that alter lifecycle behavior, especially:

```text
ignore_validate
in_print
ignore_children
ignore_children_type
```

Do not attempt to evaluate runtime flag values that cannot be determined.

Show conditional branches in traces when a flag may suppress events.

## CLI behavior

```bash
beagle lifecycle "Site"
beagle trace "activate_site" --framework-events
beagle explain "activate_site" --framework-events --mermaid
```

Output must distinguish:

```text
Explicit Python call
Framework lifecycle transition
Direct database write
Conditional or uncertain transition
```

## Implementation tasks

- [ ] Add document-operation observations.
- [ ] Resolve receiver DocTypes.
- [ ] Detect docstatus transitions.
- [ ] Create versioned operation policies.
- [ ] Add lifecycle-event entities.
- [ ] Generate ordered `TRIGGERS_EVENT` edges.
- [ ] Detect operation overrides and `super()` continuation.
- [ ] Handle nested `db_set()` in discard.
- [ ] Model delete through `frappe.delete_doc`.
- [ ] Prevent lifecycle expansion for direct DB writes.
- [ ] Prevent automatic child-row lifecycle expansion.
- [ ] Add Single and Virtual DocType handling.
- [ ] Add cycle and depth limits.

## Definition of done

Starting from a function that mutates and persists a known document, Beagle must accurately show:

- the persistence operation;
- the resolved DocType;
- the action derived from docstatus;
- ordered lifecycle events;
- direct versus framework-dispatched transitions;
- conditions and overrides;
- exact source evidence;
- no invented child-row lifecycle.
