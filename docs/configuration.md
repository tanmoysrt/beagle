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
| `reasoning.model` | `"claude-sonnet-5"` | The model that reviews the code, and that makes the second check of a security or P0 finding |
| `general.model` | `"claude-haiku-4-5"` | The model for every other call: the plan, the merge, the summary, and a reply to a comment |
| `reasoning.extra_body` | `{}` | More fields for the request body of that model. Beagle sends them and does not read them. |
| `general.extra_body` | `{}` | The same, for the other model |

The service must accept the Anthropic message format at `/v1/messages`, and it must accept tool use. The reviewer is nothing without tool calls.

### Keep one review on one provider

The reviewer sends the same conversation again on each turn, and it grows. The service reads almost all of it from its cache. A cached read costs a fraction of the price. This holds only while the same provider answers each turn. A gateway that sends one turn to a different provider reads the whole conversation again at full price.

In one measurement, 10 percent of the turns went to a provider with no cache. Those turns were 76 percent of all the input that Beagle paid full price for.

There is a second reason to hold one provider. On OpenRouter, 19 providers serve `z-ai/glm-5.2`, some at fp4 and some at fp8. Two turns of one review can go to two providers with different arithmetic. Then the reviewer is not one reader of the code, and a repeated review is not a repeated measurement.

Use `extra_body` to hold the review on one provider. Set it on the model, not on the whole `[llm]` section. The two models are rarely the same vendor. A provider that serves one of them does not serve the other:

```toml
[llm.reasoning]
model = "z-ai/glm-5.2"
[llm.reasoning.extra_body.provider]
order = ["z-ai"]
allow_fallbacks = false
quantizations = ["fp8"]
```

To see the effect, compare `tokens_cached` with `tokens_in` in `llm_log.db`. Inside one review the share climbs above 95 percent. A turn near 0 percent is a turn that changed provider.

### Which model to give to `reasoning`

Beagle has a test set of 56 known problems. They come from the reviews that a commercial tool left on 33 pull requests. Each model read the same code with the same prompt. This is one measurement of one repository. Read it as a guide, not as a law.

| Model | Found | Cost | Cost for each problem found |
| --- | --- | --- | --- |
| `claude-sonnet-5` | 38 of 56 | $1.09 | $0.029 |
| `claude-opus-5` | 36 of 56 | $2.78 | $0.077 |
| `z-ai/glm-5.2` | 30 of 56 | $0.19 | $0.006 |
| `mistralai/mistral-large-2512` | 27 of 56 | $0.14 | $0.005 |
| `claude-haiku-4-5` | 26 of 56 | $0.46 | $0.018 |
| `moonshotai/kimi-k2.6` | 20 of 56 | $0.26 | $0.013 |
| `google/gemini-3-flash-preview` | 20 of 56 | $0.15 | $0.008 |

Two results are important. `claude-opus-5` found less than `claude-sonnet-5` and costs 2.5 times more, so it is not the model to use. And `z-ai/glm-5.2` found 79 percent as many problems for 18 percent of the cost.

Any gateway that gives the Anthropic format works, so you can use an open model:

```toml
[llm]
base_url = "https://openrouter.ai/api"
api_key = "PASTE-OPENROUTER-KEY"
[llm.reasoning]
model = "z-ai/glm-5.2"
[llm.general]
model = "deepseek/deepseek-v4-flash-0731"
```

Do not use `moonshotai/kimi-k2.7-code`: it cannot turn reasoning off, so it uses the whole token budget on thought and returns no findings. Do not use `qwen/qwen3-coder-plus`: it returns an empty list for each request.

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
| `agent_mode` | `true` | The reviewer reads the repository with tools. Set `false` to give it context that Beagle collects first. |
| `max_steps` | `12` | The largest number of tool calls for one unit |
| `max_input_tokens` | `80000` | The reviewer of one unit stops and reports when its conversation reaches this size |

In agent mode the reviewer has seven tools:

- `read_file` reads a file, or a range of lines in it.
- `read_symbol` reads the body of a function or a class by name.
- `find_callers` and `find_callees` list what calls a symbol, and what it calls.
- `search_code` finds code with a related meaning.
- `grep` finds an exact string in the tree.
- `git_history` shows the commits that touched a file or a name.

A usual unit uses 3 to 10 tool calls. `max_steps` and `max_input_tokens` control one unit. `max_cost_usd` controls the whole review. In agent mode `token_budget` only stops a review that runs away.

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
