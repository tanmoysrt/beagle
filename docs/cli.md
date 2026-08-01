# Commands

There are two programs. Both have the name `beagle`. They are for two different people.

| Program | For | Installation |
| --- | --- | --- |
| The client, in `cli/` | A person who asks a server for a review | One file. Python 3.7 or newer, and nothing else. Refer to [cli/README.md](../cli/README.md). |
| The server package | A person who operates the server | The full package with all its dependencies |

**If you write code and you want a review, you need only the client.** Refer to [cli/README.md](../cli/README.md). This document describes the commands of the server package.

Do not install both on the same machine with the same name. The installation script of the client gives you a warning if it finds the other program.

## The commands of the server package

Each command needs the location of the configuration file:

```bash
beagle --config data/config.toml <command>
```

The default location is `/data/config.toml`. In the container you do not need the option.

These commands open the databases directly. They do not send requests to the server. Use them on the machine that holds the data.

## beagle serve

Start the HTTP server. The server reads the port from the configuration.

```bash
beagle serve
```

## beagle index

Make the index of the repository now. If you do not use this command, Beagle makes the index at the first review.

```bash
beagle index
beagle index --full
```

`--full` reads each file again. Use it if you think that the index is not correct.

The command writes a JSON report: the commit, the counts, the time, and the files that Beagle did not read.

## beagle review

Review a reference, or review a diff.

```bash
beagle review my-branch
beagle review my-branch --base main
beagle review --diff changes.patch
git diff main... | beagle review --diff -
```

Options:

| Option | Meaning |
| --- | --- |
| `--base` | The reference to compare against. The default is `repo.default_base`. |
| `--diff` | Read a diff from a file. Use `-` to read from the standard input. |
| `--format` | `pretty` (the default), `md`, or `json` |
| `--fresh` | Ask the models again. Do not use a stored answer. |

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | No finding is at the `fail_on` level or worse |
| 1 | One finding or more is at the `fail_on` level or worse |
| 2 | The configuration is not correct |
| 4 | The model service or the embeddings service failed |
| 6 | Git failed |

## beagle doctor

Show the condition of the system.

```bash
beagle doctor
```

The command shows:

- The version of the prompts, and the prompts that you changed
- The condition of the GitHub interface and the method of access to the repository
- Four tests: the copy of the repository, the index, the embeddings, and the cache of the model service. With GitHub on, a fifth test.
- Each configuration value and its source

Use this command first when something does not operate.

The embeddings test sends one very small request to the embeddings service. It compares the width of the answer with `embeddings.dims`. A wrong value then stops here, and not in the middle of an index.

## beagle eval

Compare Beagle against a set of examples with known answers.

```bash
beagle eval
beagle eval evals/golden.json --format json
```

Each example has a diff, the findings that Beagle must give, and the findings that Beagle must not give. The command writes these values:

- The number of examples that passed
- The recall
- The number of false positives
- The number of extra findings
- The cost

Use this command after you change a prompt or a limit. Then you can measure the change instead of a guess.

The exit code is 0 if all the examples passed. If one example failed, the exit code is 1.

**This command sends requests to the model service and it costs money.** Three examples cost about 0.07 US dollars.

## beagle guide

Write a short description of Beagle.

```bash
beagle guide
beagle guide config
```

The topics are `api`, `config`, `feedback`, and `comments`.

Give this text to a coding agent. Then the agent can use Beagle correctly.
