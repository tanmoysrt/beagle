# 03 — Data Model

## Three layers

Store:

```text
entities
observations
resolved edges
```

Observations are raw parser facts. Resolution may be improved later without reparsing files.

## Initial entities

```text
repository
file
module
class
function
method
test_class
test_function
doctype
doctype_field
hook
background_job
endpoint
```

## Initial relationships

```text
DEFINES
IMPORTS
INHERITS
OVERRIDES
CALLS
REFERENCES
TESTS
HAS_CONTROLLER
HAS_FIELD
LINKS_TO
CONTAINS_CHILD
INVOKES
ENQUEUES
EXPOSES_ENDPOINT
READS_DOCTYPE
CREATES_DOCTYPE
WRITES_DOCTYPE
DELETES_DOCTYPE
READS_FIELD
WRITES_FIELD
```

Do not create names such as `CALLS_PROBABLE`. Use `CALLS` with confidence and evidence.

## Stable IDs

Examples:

```text
python://press.press.doctype.site.site#Site
python://press.press.doctype.site.site#Site.deploy
doctype://press/Site
doctype-field://press/Site#status
endpoint://press.api.deploy
```

Do not include line numbers in stable IDs.

## Required edge metadata

Every edge stores:

- source and target IDs;
- relationship;
- confidence;
- resolver and resolver version;
- observation ID;
- owner file;
- source range;
- evidence JSON.

## SQLite tables

Start with:

```text
files
entities
observations
edges
text_chunks
index_runs
schema_versions
```

Enable foreign keys for every connection.

Changing or deleting a file must remove all facts owned by that file in one transaction.
