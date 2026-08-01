# Operation

## The databases

Beagle uses three SQLite files. Each file has a different task.

| File | Content | If you lose it |
| --- | --- | --- |
| `beagle.db` | The index, the findings, the feedback, the rules, the jobs | You lose the memory of the team. Make a backup of this file. |
| `vectors.db` | The embeddings | You can make it again. You pay the cost of the embeddings again. |
| `llm_log.db` | A record of each request to a model | You lose the record of the costs. |

All three files use the WAL mode. One process writes to them. Keep the volume on a local disk. Do not put the volume on a network file system.

Beagle applies the changes to the schema when it starts. If the database does not agree with the code, the server stops and shows the reason. The server does not try to repair the database.

## The record of requests

`llm_log.db` holds the full text of each prompt and each answer. This is necessary for the costs, for the calibration, and to find the reason for a bad finding.

Beagle removes the records that are more than 60 days old. Beagle does this work when it starts.

Give the same protection to this file that you give to the source code.

## Costs

Look at the costs:

```bash
curl localhost:8080/v1/stats -H "Authorization: Bearer <token>"
```

The `spend` field shows the total cost, the tokens, the rate of cache use, and the cost of each prompt.

Beagle controls the costs with these methods:

- **The cache.** The instructions, the description of the repository, the instruction files, and the rules do not change during a review. The model service keeps them in its cache. The second call and the calls after it are much less expensive.
- **The small model.** Beagle uses the small model to plan, to merge, and to write the summary.
- **The strong model only when necessary.** Beagle uses the strong model for a unit with a risk tag, and for the second check.
- **The limits.** `max_cost_usd` and `token_budget` stop a review.
- **The stored answers.** A question that Beagle asked before gives the stored answer at no cost. Refer to [reviews.md](reviews.md).

If the rate of cache use is 0 after several reviews, something changes the prompt at each call. `beagle doctor` shows a warning.

## When a service fails

**The embeddings service does not answer.** `beagle doctor` shows a failed `embeddings` test, because the test sends one small request. Beagle continues to review. The review uses the diff and the call graph, but it does not use similar code from the index. The summary shows `retrieval unavailable` and the confidence is lower. Beagle does not try the service again for 120 seconds.

**The model service does not answer.** The review stops. The event stream shows an `error` line. The job has the condition `failed`. Beagle does not try a review again, because a review costs money. Ask for the review again when the service operates.

**The model gives an answer that Beagle cannot read.** Beagle tries to repair the answer. If Beagle cannot repair it, the summary shows the condition in the `degraded` field. Beagle does not report an empty review as a good review.

**The cost limit or the time limit stops the review.** A review stops after 30 minutes.

## The jobs

The jobs are rows in `beagle.db`. The workers read them. There is no other service.

- Beagle tries a review one time. A review costs money, so Beagle does not do it again.
- Beagle tries an index three times.
- If the server stops during a job, the server examines the job when it starts again. An index continues. A review does not continue, because it can have results already.
- There is no method to stop a job. A job continues to the end.

Look at the jobs:

```bash
sqlite3 data/beagle.db "select id, kind, status, attempts, error from jobs order by id desc limit 10"
```

## Problems and repairs

**The server does not start and it shows a message about the dimensions.** The configuration and `vectors.db` do not agree. Put the old value in the configuration, or delete `vectors.db` and make the index again.

**The server does not start and it shows a message about a checksum.** The database has a change to the schema. This version of the code does not know that change. Use the correct version of the code.

**Beagle reports no findings and you expect findings.** Look at the `degraded` field in the summary. A problem with the answer of the model shows there. Then ask for the review again.

**Beagle does not report a finding that you expect.** Look at the `suppressed` field of the result. A member of the team can have dismissed the same finding before. The record shows who dismissed it and why.

**The reviews are too slow.** Decrease `max_parallel_reviews` if the model service limits your rate. Increase it if the machine is not busy.

**The costs are too high.** Look at the cost of each type of prompt in the statistics. The second check usually costs the most. Decrease `max_findings`, or make `min_severity` more strict, or decrease `max_cost_usd`.

## Backup

Make a backup of `/data`. The important file is `beagle.db`. You can make `vectors.db` again, but you pay for the embeddings again. You can remove `llm_log.db`.

Stop the server before you copy the files. If you cannot stop the server, use the backup command of SQLite.
