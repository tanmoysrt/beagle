# GitHub

Beagle can review pull requests and can learn from the replies of the team. The GitHub interface is optional. Without it, Beagle operates through the HTTP interface and the client.

## What you need

- A machine account, for example `beagle-bot`. Do not use a personal account.
- A token for that account. A fine-grained token needs **Contents: read** and **Pull requests: write** on the repository. A classic token needs the `repo` scope, or `public_repo` for a public repository.

Beagle does not push to the repository. It only reads the repository and writes comments. So the account does not need to be a collaborator on a public repository. But to close a thread when you say a finding is wrong, the account needs write permission.

Put the token in the configuration:

```toml
[github]
token = "github_pat_..."
repo  = "acme/api"
```

The interface starts when both keys have a value. To stop it, remove the token.

## Two modes

| Mode | What Beagle does | What you must do on GitHub |
| --- | --- | --- |
| `poll` (default) | Beagle asks GitHub for the open pull requests every 60 seconds | Nothing |
| `webhook` | GitHub tells Beagle immediately | Add one webhook |

Use `poll` first. It needs no setup and it is enough for most teams. Change to `webhook` if you want a review to start in one second instead of one minute.

### The webhook

Add a webhook to the repository:

- **Payload URL**: `https://your-server/v1/github/webhook`
- **Content type**: `application/json`
- **Secret**: the same text as `github.webhook_secret`
- **Events**: Pull requests, Issue comments, Pull request review comments

```toml
[github]
mode = "webhook"
webhook_secret = "a long random text"
```

Beagle refuses a request that has no correct signature. If you do not set `webhook_secret`, the endpoint returns 403. This prevents an open endpoint by accident.

## What starts a review

Beagle reviews a pull request when the head commit changes and all of these are true:

- The action is in `github.review_on`. The default is `opened` and `synchronize`.
- The pull request is not a draft.
- The pull request comes from the same repository, or `review_forks` is `true`.

Beagle records the head commit before the review starts. If the review fails, Beagle does not try again. A review costs money, so Beagle does not repeat one without a request. To ask again, write `@beagle review`.

The index always follows the base branch of the pull request. Beagle does not make an index for each pull request. Refer to [reviews.md](reviews.md).

## What Beagle writes

Beagle writes one pull request review. The review holds the summary, every line comment, and the state. So one review gives you one notification.

The summary starts with a confidence score out of 5. Then one sentence tells you if the change is safe to merge, or what to correct first. One or two sentences tell you why. A short list names the files that need a second look. There is no table and no list of counts.

The last line of the summary gives the commit that Beagle read: the short hash and the subject of the message. So you know which push the review speaks about.

Each line comment contains the level, the title, and the explanation. If the change is a replacement of the same lines, the comment also contains a GitHub suggestion block.

Beagle sets the state of the review:

| Verdict | State |
| --- | --- |
| `request_changes` | REQUEST_CHANGES |
| `comment` or `approve` | COMMENT |

Beagle never approves a pull request. A person approves.

### A second push

Beagle finds its own comments by a hidden marker in the text. The marker holds the fingerprint of the finding. So Beagle knows what it wrote before, even after a loss of the database.

On a second review of the same pull request:

- A finding that is still there: Beagle does not write again. The discussion stays.
- A finding that is gone: the new summary tells you that the author corrected it, or that Beagle withdrew it.
- A new finding: Beagle adds it to the new review.
- The state: Beagle sets it again with each review.

Each new review is one more notification. There is no notification for a comment that does not change.

### When you say a finding is wrong

Beagle answers in the thread, then it closes the thread. GitHub calls this "resolve conversation".

To close a thread, the account needs write permission on the repository. A read-only account can write comments, but GitHub refuses to let it close a thread. Beagle records that in the log and continues, so nothing else stops.

Beagle also writes the summary again, in the same place. The finding no longer counts, so the confidence score can go up and the verdict can change. You get no new notification for this, because Beagle changes the review it already wrote.

### A force push

A force push changes the head commit, so Beagle reviews the pull request again. Beagle gets the new head even if it is not a continuation of the old head.

What the review costs depends on the code, not on the commit:

- An amend or a rebase that keeps the same code gives the same diff. Beagle reuses each answer, the review costs nothing, and no comment changes.
- A force push that changes the code gives a different diff. Beagle reviews the units that changed. Refer to [reviews.md](reviews.md).

A force push can make GitHub mark a comment of Beagle as outdated. Beagle keeps that comment, because a new comment would lose the discussion in the thread.

GitHub accepts a comment only on a line that its own diff contains. Beagle reads that diff first and moves each other finding into the summary. Beagle loses no finding.

To get only the summary, set `post_style = "summary_only"`.

## What you can write

Write the name of the account, then what you want. The default name is `beagle`. Set `github.mention` to the name of your account, for example `beagle-app`.

When Beagle reads your comment, it puts a 👍 on that comment and a 👀 on the pull request. When the work is complete, the 👀 becomes a 👍. So you know that Beagle got the message and that it is busy. Beagle does not write a reply to tell you the same thing, because that would be one more notification.

There are two commands. The word must come first, after the name.

| Command | Result |
| --- | --- |
| `@beagle review` | Beagle reviews the pull request again |
| `@beagle explain` | Beagle gives more detail about the finding in this thread |

For everything else, write ordinary English. A small model reads your words and finds one of five intentions:

| What you say | What Beagle does |
| --- | --- |
| The finding is wrong, or does not apply | Records the error, closes the thread, and holds back findings like it |
| Not now, or not in this pull request | Drops this one instance, closes the thread, and learns nothing |
| A convention of your team | Records the convention and follows it |
| A question | Answers it |
| Anything else | Nothing |

So `@beagle that is wrong, the caller checks it first` teaches Beagle, and `@beagle we always do it this way here` becomes a rule. You do not need to remember a word for each one.

Write inside the thread of a finding to speak about that finding. Write a new comment to speak about the pull request.

A 👍 on a comment of Beagle counts as agreement. A 👎 counts as an error. A reaction has less weight than a reply, because it says less.

To see the conventions, the condition of the index, or the money that Beagle used, use the client: `beagle rules`, `beagle doctor`, `beagle stats`. The pull request is for the review, not for the operation of the server.

## Safety

- Beagle never writes to the repository. It writes comments and review states only. It makes no commit, no branch, and no tag.
- The text of a comment only selects an action from a fixed list. Beagle never executes it.
- The text of a comment never enters the review of this or any other pull request.
- Beagle ignores its own comments. Each comment that Beagle writes holds a marker, and Beagle does not answer a comment that holds one.
- Beagle does not review a pull request from a fork unless you set `review_forks = true`. A fork can contain any code.

## Costs

Each push to a pull request starts one review. On a busy repository this is the largest cost of Beagle. Three controls limit it:

- `review.max_cost_usd` stops one review.
- `review_on` can hold only `opened`. Then a push does not start a review, and a person writes `@beagle review` when the change is ready.
- `server.max_parallel_reviews` limits how many reviews operate together.

Use `beagle stats` to see the money that Beagle used.

## When something does not operate

Use `beagle doctor`. It shows a `github` check. The check gives the name of the repository and tells you if the repository is public or private. If the token cannot reach the repository, the check fails and gives the answer of GitHub.
