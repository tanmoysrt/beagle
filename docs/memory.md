# Memory

The memory is the part that makes Beagle better with time. When one person dismisses a finding, Beagle hides the same finding in the reviews of all the other people.

The memory has three parts: suppression, rules, and calibration. All three parts use the database of the server. All the team members share them.

## Feedback

Send feedback about a finding:

```bash
curl -X POST localhost:8080/v1/findings/<finding_id>/feedback \
  -H "Authorization: Bearer <token>" \
  -H "content-type: application/json" \
  -d '{"action": "false_positive", "reason": "the db layer does the hashing", "author": "alice"}'
```

| Action | Meaning |
| --- | --- |
| `accept` | The finding is correct |
| `false_positive` | The finding is wrong or it does not apply here |
| `dismiss` | Do not show this instance again, but do not learn from it |
| `style_rule` | The reason contains a convention. Beagle makes a rule from it and hides this instance. |

The last three actions hide the finding. Only `false_positive` and `dismiss` teach the suppression memory below.

You can also give feedback from a pull request comment. Refer to [github.md](github.md).

Always write a `reason`. The reason is necessary for a security finding. The reason also helps the other members of the team.

Always write an `author`. Beagle counts the different people. Refer to "Calibration" below.

## Suppression

Beagle keeps an embedding of each finding. When a review makes a new finding, Beagle compares it with the findings that the team dismissed.

Beagle uses two methods:

1. **The fingerprint.** If the new finding has the same fingerprint as a dismissed finding, Beagle hides it. The fingerprint uses the file, the category, and the title. The fingerprint does not use the line numbers, because line numbers move. This method is exact and it costs nothing.
2. **The embedding.** If the fingerprints are different, Beagle compares the two embeddings. The finding must have the same category. Beagle hides the finding at a score of 0.92 or more. Beagle decreases the confidence at a score of 0.80 or more.

These are typical scores:

| Comparison | Score | Result |
| --- | --- | --- |
| The same finding again | 1.00 | Beagle hides it |
| The same problem in different words | 0.92 | Beagle hides it |
| A related problem in different words | 0.90 | Beagle decreases the confidence |
| A different problem in the same file | 0.55 | Beagle keeps it |
| A different category, same words | no match | Beagle keeps it |

Two conditions protect against too much suppression:

- The category must be the same.
- Beagle keeps a record of each suppression. The record shows the score, the finding that caused it, and the person who dismissed that finding.

Get the suppressed findings of a review from the `suppressed` field of the result.

## Security findings need more

A security finding has two more conditions:

- The score must be 0.97 or more.
- The dismissal must have a reason.

If a person dismisses a security finding and gives no reason, Beagle continues to report it. This behaviour is correct. A security finding that disappears without an explanation is a danger.

## Rules

A rule is a convention of the team. Beagle puts the rules in each review prompt.

Add a rule:

```bash
curl -X POST localhost:8080/v1/rules \
  -H "Authorization: Bearer <token>" \
  -H "content-type: application/json" \
  -d '{"body": "Use the db helper for all queries.", "author": "alice"}'
```

Look at the rules:

```bash
curl localhost:8080/v1/rules -H "Authorization: Bearer <token>"
```

Remove a rule:

```bash
curl -X DELETE localhost:8080/v1/rules/R1 -H "Authorization: Bearer <token>"
```

The small model makes one short block from all the rules. Beagle does this work one time, and does it again only when the rules change. The block goes in the part of the prompt that the model service keeps in its cache. The block is almost free.

The rules have more authority than the opinion of the model. The instruction files of the repository also have more authority than the opinion of the model.

## Calibration

Beagle compares the confidence that the model gives with the feedback of the team. If a category collects many `false_positive` actions, Beagle decreases the confidence of the new findings in that category.

Two conditions control this correction:

- A category needs 5 events. Below 5, Beagle changes nothing.
- The correction cannot decrease the confidence more than one half. One bad week cannot make a category silent.

Beagle counts the different people. Feedback from 5 people has more weight than feedback from 1 person 5 times.

Look at the calibration in the statistics:

```bash
curl localhost:8080/v1/stats -H "Authorization: Bearer <token>"
```

The `calibration` field shows the rate of false positives and the correction for each category.
