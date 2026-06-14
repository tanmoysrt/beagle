# Data model

beagle stores everything in one SQLite database (`.beagle/index.db`). The model
has three conceptual layers and a small set of tables.

## Three layers

```text
entities         definitions in the code (stable identity)
observations     raw parser facts (un-interpreted)
resolved edges   confident relationships (confidence + evidence)
```

Keeping observations separate from edges means resolution can be improved later
**without re-parsing files** — re-run resolution over the stored observations.
It also means an uncertain observation is never lost just because no resolver was
confident enough to turn it into an edge.

## Entities

The entity kinds beagle records:

```text
repository   file        module
class        function    method
test_class   test_function
doctype      doctype_field
hook         background_job   endpoint
```

(JS/TS/Vue add their own structural entities — modules, classes, functions,
methods — under the same scheme.)

## Relationships

Resolved edges use a fixed vocabulary:

```text
DEFINES     IMPORTS     INHERITS    OVERRIDES
CALLS       REFERENCES  TESTS
HAS_CONTROLLER  HAS_FIELD  LINKS_TO  CONTAINS_CHILD
INVOKES     ENQUEUES    EXPOSES_ENDPOINT
READS_DOCTYPE  CREATES_DOCTYPE  WRITES_DOCTYPE  DELETES_DOCTYPE
READS_FIELD    WRITES_FIELD
```

Plus the frontend → backend edges from the JS/TS/Vue stage: `CALLS_BACKEND` and
`QUERIES_DOCTYPE`.

There is intentionally no `CALLS_PROBABLE` or similar. Uncertainty is expressed
by the **confidence** value on a `CALLS` edge, not by inventing a second
relationship name.

## Stable ids

Ids are keyed by structure, not by line number, so they survive code moving
around in a file:

```text
python://press.press.doctype.site.site#Site
python://press.press.doctype.site.site#Site.deploy
doctype://press/Site
doctype-field://press/Site#status
endpoint://press.api.deploy
```

Because ids are stable, you can feed an id from one command into the next, and
change-tracking can attribute a diff to `Site.deploy` rather than to a line
range.

## Edge metadata

Every resolved edge stores:

- source and target ids;
- the relationship;
- **confidence**;
- the **resolver** and resolver version;
- the originating observation id;
- the **owner file**;
- the **source range**;
- an **evidence** JSON blob.

This is what lets every answer be traced back to the exact lines that justify it.

## Tables

```text
files            entities         observations
edges            text_chunks      index_runs
schema_versions
```

Foreign keys are enabled on every connection. Lexical search runs over
`text_chunks` via SQLite FTS5. Changing or deleting a file removes **all** facts
owned by that file in a single transaction, which is the foundation of safe
incremental indexing.

---

For how these tables get populated and queried, see
[How it works](./how-it-works) and [Architecture](./architecture).
