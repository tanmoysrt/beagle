# Configuration

Beagle reads one file: `/data/config.toml`. There are no environment variables and there are no command options that change the configuration.

The server reads the file one time, when it starts. If you change the file, you must start the server again.

To see each value and its source, use this command:

```bash
beagle --config data/config.toml doctor
```

## server

| Key | Default | Meaning |
| --- | --- | --- |
| `port` | `8080` | The port of the HTTP interface |
| `auth_tokens` | `[]` | The bearer tokens. Give one token to each consumer. You can remove one token and keep the others. |
| `max_parallel_reviews` | `5` | The number of workers. This number also limits the rate of requests to the model service. |

If `auth_tokens` is empty, the server accepts all requests. Use an empty list only on your own machine.

## repo

| Key | Default | Meaning |
| --- | --- | --- |
| `url` | none. You must give a value. | The location of the repository. Use an HTTPS URL, an SSH URL, or a local path. |
| `default_base` | `"main"` | The branch that Beagle compares against |
| `ignore` | `[]` | More patterns to ignore. Refer to [reviews.md](reviews.md). |

Beagle can read a public repository without a key. For a private repository, use one of these two methods:

- Give an SSH URL and attach a deploy key to the container.
- Give an HTTPS URL and a GitHub token.

## llm

| Key | Default | Meaning |
| --- | --- | --- |
| `base_url` | `"https://api.anthropic.com"` | The address of the model service |
| `api_key` | none. You must give a value. | The key |
| `headers` | `{}` | More headers. Beagle adds these headers to each request. |
| `models.reasoning` | `"claude-opus-5"` | The model that reviews the code, and that makes the second check of a security or P0 finding |
| `models.general` | `"claude-sonnet-5"` | The model for every other call: the plan, the merge, the summary, and a reply to a comment |

The service must accept the Anthropic message format at `/v1/messages`. It must also accept tool use.

Any gateway that gives this format works, so you can use an open model. This pair costs much less through OpenRouter:

```toml
[llm]
base_url = "https://openrouter.ai/api"
api_key = "PASTE-OPENROUTER-KEY"
[llm.models]
reasoning = "z-ai/glm-5.2"
general = "deepseek/deepseek-v4-flash-0731"
```

Use `moonshotai/kimi-k2.6` if you prefer Moonshot. Do not use `moonshotai/kimi-k2.7-code`: it cannot turn reasoning off, so it uses the whole token budget on thought and returns no findings.

## embeddings

| Key | Default | Meaning |
| --- | --- | --- |
| `base_url` | `"https://openrouter.ai/api/v1"` | The address of the embeddings service |
| `api_key` | none. You must give a value. | The key |
| `model` | `"text-embedding-3-large"` | The name of the embeddings model |
| `dims` | `1024` | The number of dimensions of each vector |
| `batch_size` | `128` | The number of blocks in one request |
| `headers` | `{}` | More headers |

The service must accept the OpenAI format at `/v1/embeddings`.

Do not change `dims` after the first index. The server refuses to start if the value does not agree with the database. To change the value, delete `vectors.db` and make the index again.

## review

| Key | Default | Meaning |
| --- | --- | --- |
| `min_severity` | `"P5"` | Beagle does not report a finding below this level. Security findings are an exception. |
| `fail_on` | `"P1"` | If a finding has this level or a worse level, the verdict is `request_changes`. |
| `max_findings` | `8` | The largest number of findings in one review |
| `categories` | bug, security, performance, correctness, style, test_gap | The categories that the model can use |
| `max_cost_usd` | `2.50` | Beagle stops the review at this cost |
| `token_budget` | `60000` | Beagle stops the review at this number of tokens |

Beagle limits P3 findings to 3, P4 findings to 2, and P5 findings to 1 in one review. A `test_gap` finding never goes above P4, so a missing test is a nit and cannot stop a merge. These limits are in the code. You cannot change them with the configuration.

## context

| Key | Default | Meaning |
| --- | --- | --- |
| `instruction_files` | `"auto"` | Set `"off"` to stop the search for instruction files |
| `instruction_files_extra` | `[]` | More files to include, for example `["docs/style.md"]` |
| `instruction_files_budget` | `4000` | The largest number of tokens for these files |

## prompts

| Key | Default | Meaning |
| --- | --- | --- |
| `dir` | none | A directory that contains your prompt files. Refer to [prompts.md](prompts.md). |

## memory

| Key | Default | Meaning |
| --- | --- | --- |
| `suppress_similarity` | `0.92` | Beagle hides a finding at this score or a higher score |
| `downrank_similarity` | `0.80` | Beagle decreases the confidence at this score |
| `suppress_similarity_security` | `0.97` | The score for a security finding. It is higher, because a mistake here is more dangerous. |

`downrank_similarity` must not be more than `suppress_similarity`. The server refuses to start if it is more.

## github

| Key | Default | Meaning |
| --- | --- | --- |
| `token` | none | A fine-grained token with Contents: read and Pull requests: write |
| `repo` | none | The repository, as `owner/name` |
| `api_url` | `"https://api.github.com"` | Change this for GitHub Enterprise |
| `mention` | `"beagle"` | The name of the account, without the `@`. People write to this name. |
| `mode` | `"poll"` | `poll` needs no setup. `webhook` is faster. |
| `poll_interval_seconds` | `60` | The time between two questions to GitHub |
| `webhook_secret` | none | The secret of the webhook. Necessary for `webhook`. |
| `review_on` | `["opened", "synchronize"]` | The actions that start a review |
| `review_forks` | `false` | Review a pull request from a fork |
| `post_style` | `"inline_plus_summary"` | Use `"summary_only"` for one comment only |

The interface starts when `token` and `repo` both have a value. Without them, the server ignores this section and `/v1/github/webhook` returns 404. Refer to [github.md](github.md).

## Secrets

The keys are in the file as plain text. This is the design. The container gives service to one repository and one team. Protect the file with the permissions of the file and with the access control of the volume. Give a different bearer token to each consumer, and remove a token if it becomes known.
