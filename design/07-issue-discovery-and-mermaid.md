# 07 — Issue Discovery and Mermaid Explanations

## Purpose

Users usually start with an issue, not a symbol:

```text
TLS Certificate renewal can fail due to DNS validation,
rate limits, or Certbot problems. After 5 attempts we stop.
After a long delay, some failures may be safe to retry.
```

Beagle must turn this into an evidence-backed map of the relevant code.

## Operations

```bash
beagle investigate --file issue.md
beagle investigate "certificate renewal stops after 5 attempts"
beagle explain "Certificate.renew" --mermaid
```

MCP:

```text
investigate(query, max_tokens?, include_diagram?)
explain_function(entity, include_mermaid?, expand_calls?)
```

## Investigation pipeline

```text
Issue text
   |
   +-- preserve exact phrases and numbers
   +-- derive a small search-term set
   |
   +-- FTS over symbols and symbol-scoped source
   +-- search literals, exceptions, commands, and DocType metadata
   |
   +-- select top seed entities
   |
   +-- expand callers, callees, hooks, jobs, fields, and tests
   |
   +-- detect counters, comparisons, status writes, exceptions, and commands
   |
   +-- rank probable workflows
   |
   +-- compile exact source ranges
   +-- optionally render Mermaid
```

## Ranking

Strong signals:

1. exact symbol or qualified-name match;
2. exact phrase or command match;
3. numeric threshold near a matching concept;
4. exception or error-message match;
5. one function containing several issue concepts;
6. Frappe hook, scheduled job, or endpoint relation;
7. state-field read or write;
8. graph proximity to a strong seed;
9. relevant tests.

Generic words such as `retry`, `error`, and `status` must not dominate ranking alone.

## TLS issue acceptance shape

After manually verifying the pinned Press commit, Beagle should return:

```text
Likely area
  certificate renewal workflow

Primary entrypoints
  scheduler or retry job
  certificate renewal controller method

Retry policy
  attempt counter increment
  maximum-attempt check
  reset or bypass behavior
  whether elapsed time is considered

Failure handling
  DNS validation failures
  rate-limit failures
  Certbot or subprocess failures
  persisted status and error fields

External boundary
  Certbot command or wrapper
  exit-code, stdout, and stderr handling

Related code
  callers
  jobs
  DocType fields
  tests
  exact ranges

Likely change points
  retry-eligibility decision
  scheduling condition
  attempt-reset policy
  delayed-retry tests

Unknowns
  behavior that cannot be confirmed statically
```

Beagle supplies evidence for designing the fix. It does not decide the retry policy.

## Mermaid rendering

Render compact, business-relevant flowcharts.

Rules:

- use deterministic topology;
- mark uncertain edges;
- keep labels short;
- cap diagrams at 15–20 nodes;
- map every node to a path and source range;
- omit low-value implementation details;
- emphasize branches, state changes, jobs, external calls, returns, and failures.

A local LLM may shorten labels or summarize evidence. It may not invent workflow steps, conditions, or edges.

