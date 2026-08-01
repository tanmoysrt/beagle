# HTTP interface

All the paths start with `/v1`. All the requests need this header:

```
Authorization: Bearer <token>
```

Three paths do not need the header: `/v1/healthz`, `/v1/guide`, and `/v1/github/webhook`. The webhook path does not need a token because GitHub signs each request, and Beagle checks the signature.

## Reviews

### POST /v1/reviews

Start a review. The server answers immediately with code 202.

Body:

| Field | Necessary | Meaning |
| --- | --- | --- |
| `review_id` | no | Your identifier. If you send the same identifier again, the new result replaces the old result. |
| `base` | no | The reference to compare against. The default is `repo.default_base`. |
| `head` | no | The reference to review |
| `diff` | no | A unified diff. Use this field if the code is not on the server. |
| `author` | no | The person who asked for the review |
| `pr` | no | A pull request number. Beagle gets the code from GitHub and writes the result to the pull request. |
| `fresh` | no | Ask the models again instead of using a stored answer |

With `pr`, the identifier is always `pr-<number>` and the other fields are not used. If the GitHub interface is off, the answer is 409.

Answer: `{"review_id": "...", "job_id": 3, "schema_version": 1}`

### GET /v1/reviews/{review_id}/stream

Read the events. The answer is NDJSON. One line is one event. Refer to [reviews.md](reviews.md) for the list of events.

### GET /v1/reviews/{review_id}

Get the result. The answer contains `summary`, `findings`, and `suppressed`.

### GET /v1/reviews/{review_id}/report?format=md

Get a report for a human. Use `format=md` for Markdown. Use `format=json` for the same data as `GET /v1/reviews/{review_id}`.

## Feedback

### POST /v1/findings/{finding_id}/feedback

Give feedback about one finding. Refer to [memory.md](memory.md).

Body:

| Field | Necessary | Meaning |
| --- | --- | --- |
| `action` | yes | `accept`, `false_positive`, `dismiss`, or `style_rule` |
| `reason` | no | Why. Necessary for a security finding. |
| `author` | no | The person |
| `weight` | no | The default is 1.0 |

### POST /v1/feedback/batch

Give feedback about many findings. The body is a list. Each item has a `finding_id` field and the fields above. The answer counts the items that Beagle accepted.

## Rules

### GET /v1/rules

Get the rules that are active.

### POST /v1/rules

Add a rule. Body: `{"body": "...", "author": "..."}`.

### DELETE /v1/rules/{rule_id}

Make a rule inactive. Beagle keeps the record.

## The index

### POST /v1/index/rebuild

Make the index again. Add `?full=true` to read each file. The server answers with code 202.

### GET /v1/index/status

Get the condition of the index: the commit, the progress, the counts, and the number of blocks that have no embedding.

## Information

### GET /v1/stats

Get these values:

- The counts of the reviews and the findings
- The rate of false positives for each category
- The money spent, and the rate of cache use
- The counts of the index

### GET /v1/doctor

Get the configuration with the source of each value, the condition of each part, and the identifier of each prompt.

### GET /v1/schema

Get the version of the interface, the version of the prompts, and the list of events.

### GET /v1/healthz

Get the condition of the server. This path does not need a token.

### GET /v1/guide

Get a short description of the interface. The text is Markdown. Add `?topic=api`, `?topic=config`, `?topic=feedback`, or `?topic=comments` for one part. This path does not need a token.

The server describes its own interface only. It does not describe a client, because it does not know which client you use. The client describes itself.

Give this text to a coding agent. Then the agent can use Beagle correctly.

## GitHub

### POST /v1/github/webhook

Receive an event from GitHub.

| Answer | Cause |
| --- | --- |
| 404 | The GitHub interface is off |
| 403 | `github.webhook_secret` has no value |
| 401 | The header `X-Hub-Signature-256` does not agree with the body |

Beagle acts on three events: `pull_request`, `issue_comment`, and `pull_request_review_comment`. Beagle answers 200 to each other event and does nothing. Refer to [github.md](github.md).

## Rules of the interface

- Each line of the event stream has a `schema_version` field. If Beagle makes a change that is not compatible, the number increases.
- Each line of the event stream is correct JSON. If the review stops, the last line is `{"event": "error", ...}`.
- A review can stop because of the cost limit or the time limit. The summary then shows the condition in the `degraded` field.
