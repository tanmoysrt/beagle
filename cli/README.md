# Beagle client

This is the client. It sends requests to a Beagle server. It is one file, it uses only the Python standard library, and it needs no installation of the server.

You need Python 3.7 or newer. You need nothing else: no virtual environment, no `pip install`, no packages. Copy the file, make it executable, and run it.

Use this client if you want to ask a server for a review. Use the server package only if you operate the server.

## Installation

```bash
curl -fsSL https://raw.githubusercontent.com/tanmoysrt/beagle/main/cli/install.sh | bash
```

The script copies one file to `~/.local/bin/beagle`.

You can also get only this directory:

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/tanmoysrt/beagle
cd beagle
git sparse-checkout set cli
./cli/install.sh
```

Or copy the file yourself. There is nothing else to do:

```bash
curl -fsSL https://raw.githubusercontent.com/tanmoysrt/beagle/main/cli/beagle \
    -o ~/.local/bin/beagle && chmod +x ~/.local/bin/beagle
```

## First use

```bash
beagle login https://beagle.internal:8080 --token <token> --author alice
```

The client keeps the address and the token in `~/.beagle/settings.json`. The file has the permissions 600. The client keeps no other data.

If you have more than one server, the client reads the remote of your Git repository. The client then selects the correct server. Use `--server <name>` to select a server yourself.

## Commands

| Command | Task |
| --- | --- |
| `beagle login <url>` | Save the address of a server |
| `beagle review [ref]` | Review a branch. The default is the current branch. |
| `beagle review 482` | Review pull request 482 and write the result to GitHub |
| `beagle review --diff -` | Review a diff from the standard input |
| `beagle review --fresh` | Review again from the start, with no stored answer |
| `beagle findings <id>` | Show the result of a review |
| `beagle feedback <id> <action> [reason]` | Teach Beagle about a finding |
| `beagle rules` | Show the conventions of the team |
| `beagle rules add "..."` | Add a convention |
| `beagle rules rm R3` | Remove a convention |
| `beagle stats` | Show counts, costs, and calibration |
| `beagle status` | Show the condition of the server and the index |
| `beagle doctor` | Show the configuration of the server |
| `beagle guide [topic]` | Show this table, then the guide of the server |
| `beagle servers` | List the servers that you saved |

## Output

The client writes text with colour when it writes to a terminal. In all other conditions the client writes JSON, one object for each line. Use `--json` to get JSON in a terminal too.

This makes the client correct in a pipeline without more options:

```bash
beagle review > findings.ndjson
```

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | No finding is at P0 or P1 |
| 1 | One finding or more is at P0 or P1 |
| 2 | The command or the settings are not correct |
| 4 | The server did not answer, or it answered with an error |
| 6 | This directory is not a git repository |

## Use with a coding agent

```bash
beagle guide > AGENT_NOTES.md
```

The server makes this text from its own command table, its own routes, and its own configuration model. The text cannot become different from the software.
