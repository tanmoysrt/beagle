# Reviews

## How to ask for a review

Send the name of a branch:

```bash
curl -X POST localhost:8080/v1/reviews \
  -H "Authorization: Bearer <token>" \
  -H "content-type: application/json" \
  -d '{"head": "my-branch"}'
```

The server returns a `review_id` immediately. The review operates in the background.

You can also send a diff. Use this method if the code is not on the server yet. The diff is a string in the `diff` field of the JSON body:

```bash
git diff main... | jq -Rs '{diff: .}' | curl -X POST localhost:8080/v1/reviews \
  -H "Authorization: Bearer <token>" \
  -H "content-type: application/json" \
  --data-binary @-
```

If you send a diff, Beagle has less context. Beagle can read only the lines in the diff, and the code that the index contains. The summary shows a lower value for the confidence.

With the GitHub interface on, send a pull request number. Beagle gets the code from GitHub and writes the result to the pull request:

```bash
curl -X POST localhost:8080/v1/reviews \
  -H "Authorization: Bearer <token>" \
  -H "content-type: application/json" \
  -d '{"pr": 482}'
```

Beagle also starts this review by itself. Refer to [github.md](github.md).

## The steps of a review

1. **Fetch and index.** Beagle gets the new commits. Beagle reads only the files that changed.
2. **Select the files.** Beagle removes the files that the rules ignore.
3. **Plan.** The small model puts the files into units. One unit is one logical change.
4. **Find the risk.** Beagle reads the call graph. Beagle gives a risk tag to a unit that is near one of these subjects: authentication, sessions, cryptography, payments, deletion of data, or concurrency. A unit with a risk tag uses the strong model.
5. **Scan for secrets.** A local scan reads the new lines. This scan uses patterns and entropy. It does not use a model and it does not cost money.
6. **Collect the context.** Beagle collects four items for each unit. First the diff. Then the related symbols from the call graph. Then the other files that still name what the diff removes. Then similar code from the index. The third item is a text search of the whole tree, so it finds a caller in a different language. A Vue component can call a Python route by its address. Such a call has no entry in the call graph, but the search finds it. Beagle stops when the token budget is full. The summary shows the parts that did not fit.
7. **Review.** The model reads each unit and returns findings.
8. **Merge.** The small model puts the same finding from different units together. Beagle then applies the limits.
9. **Classify the security findings.** Refer to "Security findings" below.
10. **Apply the memory.** Beagle hides the findings that the team dismissed before. Refer to [memory.md](memory.md).
11. **Check again.** A second model examines each security finding, and each P0 or P1 finding with a low confidence. The strong model checks a security or P0 finding; the usual model checks the others. The model can agree, correct, or refuse the finding.
12. **Write the summary.** Beagle keeps the result and closes the event stream.

## Reviews of almost the same change

A person who works on a change asks for a review many times. Beagle does not pay for the same question twice.

Each call to a model is identified by everything the model sees: the prompt, the diff of the unit, the related code, and the conventions of the team. Beagle keeps the answer to each call. If the same call occurs again, Beagle gives the stored answer. The call costs no money and no time.

The effect in a usual sequence of work:

| Condition | Result |
| --- | --- |
| The same change again | No model call at all |
| One file of four changed | Beagle reviews the unit that contains that file. The other units keep their findings. |
| A different prompt, model, or rule | Beagle asks the model again, because the question is different |

Measured on a change to four files, with two units:

- The same change again: 0.349 US dollars becomes 0.000.
- One of the four files changed: 0.349 US dollars becomes 0.218.

To review again from the start, use `--fresh` or send `"fresh": true`. Use this if you think that an answer was bad.

Beagle keeps the answers for 60 days, with the record of the calls.

## Which files Beagle reads

Beagle uses these rules in this sequence. The first rule that agrees is the result.

1. **`.gitignore`.** A file that Git ignores is not in the copy. Beagle cannot see it.
2. **`.beagleignore`.** Put this file in the root of the repository. It uses the same format as `.gitignore`. Use it for files that Git keeps but a reviewer does not need, for example lock files and generated code.
3. **`[repo].ignore`.** These patterns are in the configuration.
4. **Size and type.** Beagle does not read these files: a binary file, an empty file, or a file of more than 512 KB.

The summary shows each file that Beagle did not read, and the reason.

## Security findings

A security finding in application code is always P0. The pipeline sets this level after the model answers. The model cannot make the level lower.

Beagle decides what application code is. Beagle uses the path, not the opinion of the model. These paths are **not** application code:

- `tests/` and `test/`
- Files with a name such as `*_test.py` or `*.spec.ts`
- `fixtures/` and `testdata/`
- `scripts/` and `tools/`
- `examples/` and `docs/`

In these paths, the level of the model stays. A weak key in a test is not the same problem as a weak key in the login page.

Each security finding shows its classification. You can see why Beagle gave the level.

Security findings are also an exception to three limits:

- The `min_severity` limit does not remove them.
- The `max_findings` limit does not remove them.
- The P4 and P5 limits do not apply to them.

The strong model always examines a security finding a second time.

## How Beagle stays short

Too many findings make a reviewer useless. Beagle uses these controls:

- The model gets instructions to report only what a strong engineer reports. If the model is not sure, the model does not report.
- The model must not report a problem that a linter finds. Examples are the sequence of imports and the type of quotation mark.
- The model must judge the change, not the file. Behaviour from before the change is outside the scope.
- The same problem in 6 places is 1 finding with 6 locations.
- One review contains 2 P5 findings at the most, and 3 P4 findings at the most.
- One review contains 12 findings at the most. The summary counts the rest.
- The memory hides the findings that the team dismissed before.

## The event stream

Read the events while the review operates:

```bash
curl -N localhost:8080/v1/reviews/<review_id>/stream \
  -H "Authorization: Bearer <token>"
```

Each line is one JSON object. Each line has an `event` field, a `seq` field, and a `schema_version` field.

| Event | Meaning |
| --- | --- |
| `review_started` | The review started |
| `unit_started` | A unit started |
| `unit_complete` | A unit is complete |
| `finding` | A finding is in the result |
| `finding_suppressed` | The memory hid a finding |
| `review_complete` | The review is complete. This is the last line. |
| `superseded` | A newer review replaced this one. This is the last line. |
| `error` | The review stopped. This is the last line. |

You can read the stream before the review starts, during the review, or after the review. You get the same sequence in all three conditions.

## The result

Get the result:

```bash
curl localhost:8080/v1/reviews/<review_id> -H "Authorization: Bearer <token>"
```

Get a report for a human:

```bash
curl "localhost:8080/v1/reviews/<review_id>/report?format=md" \
  -H "Authorization: Bearer <token>"
```

The summary contains these items:

- A verdict, a confidence value, and a coverage value
- The count of the findings at each level
- The instruction files that Beagle used
- The cost of the review
- A list of the degraded conditions

If you send the same `review_id` again, the new result replaces the old result. The feedback stays, because the feedback uses the fingerprint of the finding.
