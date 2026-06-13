# 13 — Temporal Decision and Change Memory

## Goal

Make Beagle remember why code changed, not only what the repository looks like now.

For every meaningful change, Beagle should be able to answer:

```text
What problem were we solving?
What did we discuss?
What decision was made?
Why was this approach chosen?
Which alternatives were rejected?
What changed in the code?
Which commits implemented it?
Which symbols, DocTypes, fields, hooks, and tests were affected?
What remains unresolved?
Was the decision later superseded?
```

This memory must remain connected to the exact code changes and commit history.

The goal is not to archive every conversation forever.

The goal is to preserve compact, useful engineering context that can help Claude and developers understand future changes.

---

## Problem

Git records:

```text
commits
authors
timestamps
messages
diffs
```

Git usually does not preserve:

```text
the original problem
important constraints
the reasoning behind the approach
alternatives considered
why alternatives were rejected
conversation context
expected behavior
known risks
follow-up work
```

Claude sessions may contain this information, but raw transcripts are:

- large;
- noisy;
- difficult to search;
- tied to one tool;
- potentially sensitive;
- disconnected from the final commit;
- hard to use after rebases or squashes.

Commit messages may contain some reasoning, but they are often too short and may describe only one implementation step.

A single decision may produce several commits.

Several conversations may contribute to one change.

One conversation may discuss multiple unrelated changes.

Beagle therefore needs a first-class temporal model that connects:

```text
conversation
decision
change episode
diff
commit
code entities
tests
future decisions
```

---

## Core principle

Keep three kinds of information separate:

```text
Deterministic code facts
Generated decision summaries
Raw conversation provenance
```

### Deterministic code facts

Calculated by Beagle:

```text
base commit
head commit
commits
changed files
diff hunks
changed entities
added or removed symbols
signature changes
DocType changes
field changes
hook changes
relationship changes
test changes
```

These facts must never depend on an LLM summary.

### Generated decision summaries

Produced from the conversation and deterministic diff evidence:

```text
problem
goal
constraints
decision
rationale
alternatives
risks
follow-ups
```

These summaries are editable and must be labelled as generated or human-confirmed.

### Raw conversation provenance

Stored locally by default:

```text
session ID
transcript path
transcript hash
timestamps
starting commit
ending commit
tool name
```

Raw transcripts should not be committed automatically.

---

## Main concept: Change Episode

The primary unit is a:

```text
ChangeEpisode
```

A change episode represents one coherent problem and its implementation.

It may contain:

```text
one or more conversations
one or more commits
one or more decisions
one or more rejected alternatives
one or more test runs
uncommitted work
follow-up work
```

Example:

```yaml
id: episode-tls-renewal-delayed-retry

title: Retry old TLS certificate renewal failures

problem:
  Certificate renewal permanently stops after five failed attempts.

goal:
  Retry temporary failures after a cooldown without retrying permanent
  failures forever.

constraints:
  - Keep the existing maximum-attempt protection.
  - Do not retry known permanent failures.
  - Preserve existing scheduler behavior.

decision:
  Allow a new retry after a cooldown when the last failure is classified
  as temporary.

rationale:
  DNS and external service failures may recover without user action.

alternatives:
  - option: Remove the maximum attempt limit.
    status: rejected
    reason: Permanent failures could retry forever.

  - option: Reset attempts every day.
    status: rejected
    reason: Time alone does not distinguish temporary and permanent errors.

base_commit: abc123
head_commit: fed789

commits:
  - def456
  - fed789

affected_entities:
  - Certificate.renew
  - retry_failed_certificates
  - Certificate.renewal_attempts

tests:
  - delayed retry after maximum attempts
  - permanent failures remain stopped
```

---

## Why episode instead of commit

A commit is an implementation artifact.

A decision often spans:

```text
investigation commit
implementation commit
test commit
cleanup commit
fixup commit
```

A change episode should therefore have:

```text
base commit
head commit
ordered commit list
optional working-tree snapshots
```

Each commit can reference the same episode.

This supports:

- incremental implementation;
- fixup commits;
- squashed histories;
- rebases;
- several Claude sessions;
- one issue discussed over multiple days.

---

## Data model

## ChangeEpisode

```text
id
title
status
created_at
updated_at
base_commit
head_commit
branch
repository_id
summary
problem
goal
outcome
confidence
provenance
```

Suggested statuses:

```text
draft
active
implemented
abandoned
superseded
```

## Session

```text
id
tool
started_at
ended_at
working_directory
start_commit
end_commit
transcript_path
transcript_hash
summary
redaction_status
```

## Decision

```text
id
episode_id
statement
rationale
status
confidence
created_at
superseded_by
source_session_ids
```

Decision statuses:

```text
proposed
accepted
rejected
superseded
unknown
```

## Alternative

```text
id
episode_id
description
status
rejection_reason
source_session_ids
```

## ChangeSet

```text
id
episode_id
base_commit
head_commit
patch_id
entity_fingerprint
summary
```

## CommitRecord

```text
commit_sha
episode_id
parent_shas
message
author
timestamp
patch_id
```

## EntityChange

```text
episode_id
entity_before
entity_after
change_type
path_before
path_after
diff_ranges
confidence
```

Change types:

```text
added
removed
modified
renamed
moved
signature_changed
behavior_changed
relationship_changed
unknown
```

## TestResult

```text
id
episode_id
command
status
started_at
finished_at
output_summary
source_session_id
```

## FollowUp

```text
id
episode_id
description
status
priority
related_entities
```

## Provenance

Every non-deterministic memory item must record:

```text
source type
source session
source message range
generation method
human confirmation state
created time
```

---

## Relationships

Add:

```text
Session DISCUSSED Decision
Session CONTRIBUTED_TO ChangeEpisode
Decision MOTIVATED ChangeSet
Decision AFFECTS Entity
Decision REJECTED Alternative
Decision SUPERSEDES Decision
ChangeEpisode IMPLEMENTED_BY Commit
ChangeEpisode CHANGED Entity
ChangeSet CHANGED Entity
TestResult VALIDATES ChangeSet
FollowUp CONTINUES ChangeEpisode
```

Temporal queries should operate over these relationships.

---

## Capture lifecycle

## Session start

Record:

```text
session ID
tool name
working directory
current branch
HEAD commit
dirty state
timestamp
transcript reference when available
```

Do not copy the full transcript into shared storage.

## During the session

Capture lightweight milestones:

```text
user problem statement
accepted plan
important decisions
rejected alternatives
files changed
tests run
commits created
```

Do not persist every shell command or tool response.

## Before a commit

Create or update a draft episode:

```text
current problem
active decisions
working-tree diff
changed entities
tests run
```

If no episode is active, Beagle may suggest creating one.

Do not block commits.

## After a commit

Update deterministic facts:

```text
commit SHA
parent SHA
diff
patch ID
changed files
changed entities
relationship changes
test changes
```

Attach the commit to the active episode when confidence is high.

Otherwise, keep it unassigned for later review.

## Session end

Create a compact session summary:

```text
what was discussed
what was decided
what was implemented
what remains uncommitted
what remains unresolved
```

Link it to the active episode.

Keep the raw transcript reference local.

## Episode finalization

An episode may be finalized when:

```text
the intended behavior is implemented
relevant tests pass
the commit range is known
the summary is complete
```

Finalization should not require perfect certainty.

Unknowns and follow-ups are valid final content.

---

## Conversation summarization

The summary should be structured, not one long paragraph.

Suggested sections:

```text
Problem
Goal
Constraints
Decision
Rationale
Alternatives considered
Implementation summary
Behavior before
Behavior after
Tests
Risks
Follow-ups
Unresolved questions
```

## Summary rules

- Prefer the user's stated reasoning over inferred reasoning.
- Preserve rejected alternatives.
- Keep implementation details linked to deterministic diff facts.
- Do not claim a decision was accepted unless the conversation supports it.
- Label inferred rationale separately.
- Avoid repeating complete code or tool output.
- Do not include secrets.
- Keep the shared summary concise.

## Human confirmation

Support:

```text
generated
reviewed
edited
confirmed
```

Confirmed summaries should rank higher during future retrieval.

---

## Diff and entity mapping

Beagle must map a Git diff to repository entities.

For each hunk:

1. resolve the enclosing entity before the change;
2. resolve the enclosing entity after the change;
3. classify the change;
4. map related graph changes;
5. attach exact diff ranges.

## Entity-level changes

Detect:

```text
function added or removed
signature changed
decorator changed
guard changed
field write changed
call added or removed
hook target changed
DocType field changed
lifecycle relationship changed
test added or changed
```

## Before and after behavior

Create deterministic summaries such as:

```text
Before:
  Renewal stopped permanently after five attempts.

After:
  Temporary failures may retry after a cooldown.
```

Only generate this when the changed conditions and effects are sufficiently clear.

Otherwise return:

```text
Behavioral difference requires source review.
```

---

## Git attachment

The Git repository should remain usable without Beagle.

Use a dedicated Git notes ref for commit-linked metadata:

```text
refs/notes/beagle-decisions
```

Each note may contain:

```json
{
  "episode_id": "episode-tls-renewal-delayed-retry",
  "summary_hash": "sha256:...",
  "base_commit": "abc123",
  "head_commit": "fed789"
}
```

The complete episode may be stored:

```text
in Beagle SQLite
in a dedicated Git ref
or in small repository files
```

The first implementation should use:

```text
SQLite for active local state
Git notes for commit attachment
optional exported Markdown or JSON for sharing
```

Do not rewrite commit messages automatically.

Optional commit trailers may be supported later.

---

## Rebase, squash, and history rewrite

Commit SHAs are not stable across rebases.

Store additional identity:

```text
patch ID
changed entity fingerprint
base tree fingerprint
episode ID
```

## Patch ID

Use a normalized diff fingerprint to reconnect equivalent commits.

## Entity fingerprint

Build from:

```text
changed stable entity IDs
change types
relative paths
important relationship changes
```

## Recovery strategy

After a rebase:

1. find exact commit-note matches;
2. match patch IDs;
3. match entity fingerprints;
4. compare base and head trees;
5. ask for confirmation when several matches exist.

Never silently attach an episode to a low-confidence commit match.

---

## Storage and sharing

## Local storage

Keep:

```text
raw transcript references
draft summaries
unconfirmed decisions
intermediate session events
working-tree snapshots
```

## Shared storage

Share:

```text
confirmed episode summary
decisions and rationale
alternatives
commit mapping
affected entities
tests
risks
follow-ups
```

Do not share raw transcripts by default.

## Export formats

Support:

```text
Markdown
JSON
Git notes
```

A repository may later maintain:

```text
decisions/
  2026/
    episode-tls-renewal-delayed-retry.md
```

This should remain optional.

---

## Privacy and redaction

Conversation and tool output may contain:

```text
tokens
passwords
API keys
customer data
internal URLs
personal information
large logs
```

Before storing shared summaries:

- redact secrets;
- exclude large logs;
- exclude unrelated messages;
- exclude credentials and environment values;
- preserve only necessary technical context.

Store:

```text
redaction status
redaction rules version
```

Never commit raw Claude transcripts automatically.

---

## Retrieval

Beagle should answer:

```text
Why was this function changed?

What decisions affected this DocType?

What changed between these commits and why?

Which alternatives were rejected?

What was discussed before this hook was introduced?

Which decision introduced this field?

Was this decision later superseded?

Which tests were expected for this behavior?

Show previous attempts to solve this problem.
```

## Entity history

For an entity, retrieve:

```text
episodes
decisions
commits
behavioral changes
tests
follow-ups
superseding decisions
```

## Change-range history

For a commit range:

```text
deterministic diff summary
related episodes
decision rationale
affected entities
tests
unknowns
```

## Issue investigation integration

When Claude investigates or changes an entity, Beagle should include:

```text
Relevant prior decisions
Known constraints
Rejected alternatives
Previous failures
Expected tests
Open follow-ups
```

Keep this section compact and ranked.

---

## Temporal ranking

Rank historical context using:

```text
entity overlap
relationship overlap
query relevance
recency
decision confirmation state
supersession state
commit ancestry
same issue or episode
```

Penalize:

```text
superseded decisions
abandoned episodes
weakly matched rebased commits
unconfirmed generated summaries
```

Do not hide superseded decisions.

Label them clearly.

---

## Superseding decisions

A later decision may replace an earlier one.

Represent:

```text
Decision B SUPERSEDES Decision A
```

Retrieve:

```text
current decision
superseded history
reason for supersession
commit where behavior changed
```

Do not delete older decisions.

They explain historical code and earlier commits.

---

## Claude integration

Claude remains the reasoning layer.

Beagle should provide:

```text
deterministic diff facts
compact conversation summary
confirmed decisions
rejected alternatives
source and commit references
```

Claude may:

- draft episode summaries;
- classify statements as decisions or alternatives;
- connect conversation points to diff facts;
- propose follow-ups.

Claude must not:

- alter deterministic diff facts;
- silently mark a generated decision as confirmed;
- invent rationale;
- expose raw private transcript content;
- attach an episode to a commit without evidence.

---

## Optional workflow

A practical workflow may be:

```text
1. Start Claude session.
2. Beagle records start commit and session reference.
3. Discuss and implement the change.
4. Beagle tracks changed entities and tests.
5. Commit one or more times.
6. Beagle generates a draft episode.
7. Claude or the developer edits the summary.
8. Finalize the episode.
9. Attach Git notes to the commits.
10. Future Beagle queries retrieve the decision.
```

The workflow must remain optional and non-blocking.

---

## Implementation phases

## Phase A — deterministic Git change model

- [ ] Read repository and branch state.
- [ ] Record base and head commits.
- [ ] Parse commit ranges and working-tree diffs.
- [ ] Generate patch IDs.
- [ ] Map hunks to Beagle entities.
- [ ] Detect added, removed, moved, and modified entities.
- [ ] Detect relationship changes.
- [ ] Detect DocType, hook, lifecycle, and test changes.
- [ ] Store exact diff ranges.

## Phase B — change episode schema

- [ ] Add ChangeEpisode.
- [ ] Add Session.
- [ ] Add Decision.
- [ ] Add Alternative.
- [ ] Add ChangeSet.
- [ ] Add CommitRecord.
- [ ] Add EntityChange.
- [ ] Add TestResult.
- [ ] Add FollowUp.
- [ ] Add provenance and confirmation states.

## Phase C — session capture

- [ ] Record session start.
- [ ] Record transcript reference and hash when available.
- [ ] Record start and end commit.
- [ ] Capture user problem statements.
- [ ] Capture accepted plans and important decisions.
- [ ] Record tests and commits.
- [ ] Create a compact session-end summary.
- [ ] Keep raw transcripts local.

## Phase D — episode drafting

- [ ] Group related sessions and commits.
- [ ] Generate structured problem and goal.
- [ ] Extract accepted decisions.
- [ ] Extract rejected alternatives.
- [ ] Attach deterministic diff facts.
- [ ] Attach tests and follow-ups.
- [ ] Report uncertainty.
- [ ] Support human editing and confirmation.

## Phase E — Git notes

- [ ] Create the Beagle notes ref.
- [ ] Attach episode pointers to commits.
- [ ] Read and index existing Beagle notes.
- [ ] Export compact note payloads.
- [ ] Keep note updates idempotent.
- [ ] Do not alter commit messages.

## Phase F — history rewrite recovery

- [ ] Store patch IDs.
- [ ] Store entity fingerprints.
- [ ] Match episodes after rebases.
- [ ] Match episodes after squashes.
- [ ] Report ambiguous matches.
- [ ] Require confirmation for weak matches.

## Phase G — temporal retrieval

- [ ] Retrieve decisions by entity.
- [ ] Retrieve decisions by commit range.
- [ ] Retrieve alternatives.
- [ ] Retrieve behavior before and after.
- [ ] Retrieve expected tests.
- [ ] Retrieve follow-ups.
- [ ] Retrieve superseding decisions.
- [ ] Rank historical context.

## Phase H — context integration

- [ ] Add relevant decisions to function context cards.
- [ ] Add prior decisions to issue investigation.
- [ ] Add historical constraints to change context.
- [ ] Respect token budgets.
- [ ] Clearly label generated and confirmed memory.
- [ ] Avoid returning raw transcripts.

---

## Synthetic test cases

Create cases for:

1. one session and one commit;
2. one session and several commits;
3. several sessions and one episode;
4. unrelated changes in one session;
5. rejected alternative;
6. abandoned episode;
7. superseding decision;
8. uncommitted work;
9. rebase with same patch;
10. squash of several commits;
11. entity renamed during the episode;
12. raw transcript unavailable;
13. generated summary edited by human;
14. secret redaction;
15. episode linked to tests.

---

## Real repository benchmarks

Select at least 20 historical changes from Frappe or Press where reasoning can be manually reconstructed from:

```text
issue
conversation
commit message
diff
tests
documentation
```

For every case, record:

```text
expected problem
expected decision
expected rationale
expected alternatives
expected commits
expected affected entities
expected tests
expected follow-ups
```

Include changes spanning multiple commits.

---

## Accuracy targets

```text
Changed-file precision                    = 100%
Changed-entity precision                  >= 98%
Changed-entity recall                     >= 95%
Commit-to-episode precision               >= 98%
Decision extraction precision             >= 90%
Rejected-alternative precision            >= 90%
Test association precision                >= 95%
Incorrect confirmed decision              = 0
Secret leakage in shared summary          = 0
```

Generated summaries may have lower recall, but unsupported statements must remain clearly marked or excluded.

---

## Retrieval targets

```text
Relevant decision in top 3                >= 90%
Relevant episode recall                   >= 90%
Superseded decision correctly labelled    = 100%
Commit-range explanation usefulness       >= 4/5
Irrelevant historical context             <= 20%
```

---

## Performance targets

```text
Single commit analysis p95                < 1 second
Small commit-range analysis p95           < 3 seconds
Entity-history lookup p95                 < 200 ms
Episode lookup p95                        < 100 ms
Git-note read/write                       < 500 ms
```

Measure before enforcing on large histories.

---

## Risks

## Hallucinated rationale

A generated summary may claim reasoning not present in the conversation.

Mitigation:

- attach source messages;
- separate stated and inferred rationale;
- require confirmation for authoritative memory.

## Wrong episode grouping

Several unrelated changes may be grouped together.

Mitigation:

- use entity overlap, commit timing, conversation topics, and explicit user confirmation;
- support splitting episodes.

## Rebase mismatch

An episode may attach to the wrong rewritten commit.

Mitigation:

- patch IDs;
- entity fingerprints;
- confidence thresholds;
- manual confirmation.

## Sensitive transcript data

Raw sessions may contain secrets or customer information.

Mitigation:

- local-only transcript references;
- redacted summaries;
- no automatic transcript commits.

## Memory noise

Too many trivial records reduce usefulness.

Mitigation:

- record meaningful decisions, not every code edit;
- rank by entity relevance and confirmation;
- support archival and supersession.

## Summary drift

A summary may become outdated after later commits.

Mitigation:

- tie summaries to base/head commits;
- create follow-up or superseding episodes;
- never mutate historical decisions silently.

---

## Definition of done

This plan is complete when Beagle can:

- record a change episode across one or more Claude sessions;
- calculate the exact code and graph changes;
- preserve the problem, decision, rationale, alternatives, and tests;
- attach the episode to one or more commits;
- recover links after common rebases or squashes;
- keep raw transcripts local and shared summaries redacted;
- show why an entity changed;
- show what changed between commits and why;
- retrieve prior decisions when Claude investigates or modifies related code;
- distinguish deterministic facts, generated summaries, and confirmed decisions.

The result should let a future developer understand both the implementation history and the reasoning that produced it.

---

## Implementation status

Deterministic spine implemented in `beagle/temporal/` (CLI-first, no LLM in the
engine). Schema is migration v2; temporal tables are **not** keyed on
`owner_file`, so reindexing never purges history.

- **Phase A — deterministic git change model — DONE.** `git.py` (read-only git
  wrapper, never executes repo Python), `changes.py` (unified-diff parser →
  entity mapping via the index; rename and signature-change detection; patch id;
  entity fingerprint). When the analyzed head differs from the indexed tree,
  changes are reported at path level with a note rather than guessed.
- **Phase B — schema — DONE.** `migrations.py` v2 + `models.py` + `repository.py`
  (TemporalRepository) for episodes, sessions, decisions, alternatives,
  changesets, commits, entity_changes, test_results, follow-ups, with
  provenance + confirmation states.
- **Phase C — session capture — DEFERRED.** Session rows + schema exist; the
  live capture loop needs Claude Code session hooks (out of engine scope).
- **Phase D — episode drafting — PARTIAL.** Manual authoring via
  `beagle episode` (decision/alternative/followup/supersede/finalize), stored
  with confirmation state and secret redaction. Auto-drafting a summary from a
  transcript is Claude's job; the engine stores, never generates rationale.
- **Phase E — git notes — DONE.** `notes.py` attaches compact episode pointers
  under `refs/notes/beagle-decisions`; idempotent; commit messages untouched.
- **Phase F — history-rewrite recovery — PARTIAL.** patch id + entity
  fingerprint stored; matchers by patch id then fingerprint. Tree-compare and
  ambiguous-match confirmation flow deferred.
- **Phase G — temporal retrieval — DONE.** `entity_history`, `episode_bundle`,
  `explain_range`; ranking penalizes superseded/abandoned but never hides them.
- **Phase H — context integration — DEFERRED.** Wiring temporal memory into
  function context cards and issue investigation is the next step.

CLI: `beagle change [SPEC]`, `beagle history ENTITY`, `beagle episode …`.
MCP (read-only): `change_facts`, `entity_history`, `episode` (authoring stays
CLI-only because the MCP server is read-only). Tests in `tests/temporal/`.

Real-repo 20-case benchmark deferred — needs human-reconstructed gold, not
fabricated (correctness rule).
