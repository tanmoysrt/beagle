# 06 — Claude Code (MCP)

## MCP tools

Expose (24 tools). Foundational lookup/graph/Frappe-data tools:

```text
index_status
search
resolve
show
relations
callers
callees
find_path
uses_doctype
reads_field
writes_field
tests
impact
read_source
```

Synthesis and lifecycle tools (added by later stages):

```text
context
investigate
explain_function
function_context
event_handlers
lifecycle
trace
```

Temporal memory tools (design/13, read-only; authoring is CLI-only):

```text
change_facts
entity_history
episode
```

`callers`/`callees`/`tests`/`uses_doctype` are intentional filtered views of
`relations` (high-frequency queries, less noise). `event_handlers` resolves an
arbitrary event; `lifecycle` enumerates the standard policy events. Each tool
maps 1:1 to a CLI command — see README.

Keep results compact and return stable entity IDs for follow-up calls.

Do not expose arbitrary SQL.

## Claude Code guidance

Claude should:

1. start with `context` for conceptual questions;
2. use `resolve` and `relations` for exact symbols;
3. read only returned source ranges;
4. treat low-confidence edges as hypotheses;
5. fall back to normal Grep/Glob/Read when coverage is missing.

The index supplements normal tools. It must not block them.

## LLM flow (Claude only)

```text
Question
   |
   +-- classify intent
   +-- select likely entities
   +-- request deterministic retrieval
   +-- inspect evidence
   +-- request more retrieval if needed
   +-- produce a concise cited explanation
```

Claude — through the CLI or the MCP server — is the only LLM layer. There is no
bundled local model (Stage 11 dropped). The model, whichever it is, must not:

- parse the repository instead of the indexer;
- mutate the graph;
- invent relationships;
- answer without source-backed evidence;
- receive entire files when exact ranges are available.
