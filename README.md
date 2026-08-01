# Beagle

Beagle is an AI code reviewer. It reads a diff and it writes findings. One server gives service to one repository.

Beagle keeps an index of the code and a memory of the feedback of the team. It gives a level from P0 to P5 to each finding. It reports few findings, because a reviewer that reports too much is not useful.

## How you use it

| Way | What Beagle does | Document |
| --- | --- | --- |
| Pull requests | Beagle reviews each push and writes comments. A person answers with `@beagle ...`. | [docs/github.md](docs/github.md) |
| Terminal, or CI | You ask for a review of a branch or of a diff. The client writes JSON in a pipeline. | [cli/README.md](cli/README.md) |

You do not call the HTTP interface yourself. The client and the GitHub interface do it for you.

## The client

The client is one file. It needs Python 3.7 and nothing else.

```bash
curl -fsSL https://raw.githubusercontent.com/tanmoysrt/beagle/main/cli/install.sh | bash
beagle login https://beagle.internal:8080 --token <token> --author you
beagle review
```

Refer to [cli/README.md](cli/README.md) for each command, the exit codes, and the use in CI.

## The server

Write the configuration first:

```bash
mkdir -p data
curl -fsSL https://raw.githubusercontent.com/tanmoysrt/beagle/main/data/config.example.toml -o data/config.toml
chmod 600 data/config.toml
```

Write your two API keys and the URL of your repository in that file. Then start the container:

```bash
docker run -d --name beagle -p 8080:8080 -v "$PWD/data:/data" ghcr.io/tanmoysrt/beagle
```

Refer to [docs/install.md](docs/install.md) for the other procedures. Refer to [docs/configuration.md](docs/configuration.md) for each key.

## Documentation

[docs/README.md](docs/README.md) lists all the documents. [docs/architecture.md](docs/architecture.md) shows the parts, the folders, and the flows.

## License

MIT. Refer to [LICENSE](LICENSE).
