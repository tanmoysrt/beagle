# Beagle

Beagle is an AI code reviewer. It reads a diff and it writes findings. One server gives service to one repository.

Beagle keeps an index of the code and a memory of the feedback of the team. It gives a level from P0 to P5 to each finding. It reports few findings, because a reviewer that reports too much is not useful.

Full documentation is in [docs/](docs/README.md).

## If you only want reviews

You do not need the server. The client is one file. It needs Python 3.7 or newer, and nothing else.

```bash
curl -fsSL https://raw.githubusercontent.com/tanmoysrt/beagle/main/cli/install.sh | bash
beagle login https://beagle.internal:8080 --token <token> --author you
beagle review
```

Refer to [cli/README.md](cli/README.md). The remainder of this page is for the person who operates the server.

## Start the server

```bash
git clone https://github.com/tanmoysrt/beagle
cd beagle
./install.sh
```

Write your two API keys in `data/config.toml`. Then use these commands:

```bash
beagle --config data/config.toml doctor
beagle --config data/config.toml index
beagle --config data/config.toml review my-branch
```

You can also use a container:

```bash
docker build -t beagle .
docker run -p 8080:8080 -v "$PWD/data:/data" beagle
```

Refer to [docs/install.md](docs/install.md).

## Ask for a review

```bash
curl -X POST localhost:8080/v1/reviews \
  -H "Authorization: Bearer <token>" \
  -H "content-type: application/json" \
  -d '{"head": "my-branch"}'

curl -N localhost:8080/v1/reviews/<review_id>/stream \
  -H "Authorization: Bearer <token>"
```

The stream is NDJSON. One line is one event. Refer to [docs/reviews.md](docs/reviews.md).

## For coding agents

```bash
beagle guide > AGENT_NOTES.md
```

Beagle makes this text from its own routes and its own configuration model. The text cannot become different from the software.
