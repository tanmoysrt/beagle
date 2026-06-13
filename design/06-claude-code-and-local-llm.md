# 06 — Claude Code (MCP)

## MCP tools

Expose:

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
context
read_source
```

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
