# Beagle

Beagle reads a pull request and tells you what is wrong with it.

One server gives service to one repository. Beagle keeps an index of the code, so it sees the callers of what you change, in every language. It keeps a memory of what your team told it, so it does not raise the same wrong finding twice.

Beagle reports few findings. A reviewer that says too much gets ignored.

## What you get

Beagle writes one comment with the summary and changes that same comment from then on. It writes one line comment for each finding. So a round of review gives you one notification.

```
### Confidence Score: 3/5

Safe to merge; the validation change is consistent and covered by new tests.

The new validators add the empty check and the private address check in one
place, and the tests exercise both paths.

pilot/config/llm.py: confirm the empty base check accepts a real empty default

Reviewed up to `726a88c` fix: harden the setup wizard and the install script
```

Each finding has a level from P0 (do not merge) to P5 (nit). Each one also holds a block you can copy into your own coding tool.

## Talk to it

Write the name of the account, then what you want.

| You write | Beagle does |
| --- | --- |
| `@beagle review` | Reads the pull request again |
| `@beagle explain` | Gives more detail about the finding in this thread |
| Anything else, in your own words | Reads your words and learns from them |

There is no other command to remember. Tell it that a finding is wrong and it holds back findings like it, and closes the thread. Tell it a convention of your team and it follows the convention.

## Use it in a terminal

The client is one file. It needs Python 3.7 and nothing else.

```bash
curl -fsSL https://raw.githubusercontent.com/tanmoysrt/beagle/main/cli/install.sh | bash
beagle login https://beagle.internal:8080 --token <token> --author you
beagle review
```

Refer to [cli/README.md](cli/README.md) for each command, the exit codes, and the use in CI.

## Run the server

```bash
mkdir -p data
curl -fsSL https://raw.githubusercontent.com/tanmoysrt/beagle/main/data/config.example.toml -o data/config.toml
chmod 600 data/config.toml
```

Put two API keys and the address of your repository in that file. Then start the container:

```bash
docker run -d --name beagle -p 8080:8080 -v "$PWD/data:/data" ghcr.io/tanmoysrt/beagle
```

Beagle needs two models. The example file gives an open pair that costs about one sixth of Claude and finds almost as much. [docs/configuration.md](docs/configuration.md) has the measurement and each key.

## Documents

| Document | Content |
| --- | --- |
| [docs/github.md](docs/github.md) | Pull requests: what Beagle writes, and what you can write |
| [docs/install.md](docs/install.md) | How to install the server |
| [docs/configuration.md](docs/configuration.md) | Each key, and which models to use |
| [docs/architecture.md](docs/architecture.md) | The parts, the folders, and the flows |
| [docs/README.md](docs/README.md) | All the documents |

## License

MIT. Refer to [LICENSE](LICENSE).
