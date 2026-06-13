# 05 — Benchmark Plan

## Fixtures

Maintain:

- small synthetic Python/Frappe fixtures;
- pinned commits of `frappe` and `press`;
- at least 50 manually verified real questions.

Question groups:

```text
10 symbol and import
10 caller and callee
10 DocType and field
10 hook, job, and endpoint
10 end-to-end understanding
```

Each gold case records:

- expected entities;
- expected edges;
- expected source ranges;
- must-include context;
- must-not-include noise.

## Structural targets

```text
Symbol precision                       >= 99%
Symbol recall                          >= 98%
Import-resolution precision            >= 97%
Import-resolution recall               >= 93%
Direct-call precision                  >= 92%
Direct-call recall                     >= 82%
Frappe relationship precision          >= 97%
Frappe relationship recall             >= 90%
Stale facts after incremental update   = 0
```

## Retrieval targets

```text
Exact symbol resolution                >= 98%
Relevant result in top 5               >= 95%
Must-include context recall            >= 90%
Irrelevant context ratio               <= 20%
```

## Performance targets

```text
Exact lookup p95                       < 50 ms
Graph relation query p95               < 100 ms
FTS query p95                          < 150 ms
Context compilation p95                < 1 second
Single-file incremental update         < 1 second
```

Set cold-index targets after measuring the first implementation.

## Claude benchmark

Compare:

1. Claude Code using Read/Grep/Glob only
2. Claude Code using `project-index`
3. optional local LLM using `project-index`

Record:

- answer correctness;
- unsupported claims;
- tool calls;
- files opened;
- source lines read;
- input tokens;
- elapsed time.

Target at least 50% fewer input tokens without reducing correctness.
