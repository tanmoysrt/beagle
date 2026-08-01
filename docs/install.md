# Installation

This document is for the server. If you want to ask a server for a review, you do not need the server. Install the client instead. The client is one file and it has no dependencies. Refer to [cli/README.md](../cli/README.md).

## Before you start

You must have these items:

- Docker, or Python 3.11 or a later version
- Git
- An API key for a model service that accepts the Anthropic message format
- An API key for a service that accepts the OpenAI embeddings format

One key can do both tasks. OpenRouter gives both interfaces with one key.

## Procedure with the script

This is the fastest procedure for one machine.

```bash
git clone https://github.com/tanmoysrt/beagle
cd beagle
./install.sh
```

The script does these tasks:

1. It finds a Python of version 3.11 or newer.
2. It makes a virtual environment in `~/.local/share/beagle/venv`.
3. It installs Beagle in that environment.
4. It writes a launcher to `~/.local/bin/beagle`.
5. It makes `data/config.toml` from the example, if the file does not exist.

You can change the locations with these variables:

| Variable | Default |
| --- | --- |
| `BEAGLE_PREFIX` | `~/.local/share/beagle` |
| `BEAGLE_BIN_DIR` | `~/.local/bin` |
| `BEAGLE_DATA_DIR` | `./data` |

To remove Beagle, delete the two directories. The script tells you the names.

You can also run the script without a clone. Then the script gets the source itself:

```bash
curl -fsSL https://raw.githubusercontent.com/tanmoysrt/beagle/main/install.sh | bash
```

Read a script before you send it to a shell. This is good practice for all scripts, not only this one.

## Procedure with Docker

1. Make a copy of the example configuration file.

   ```bash
   cp data/config.example.toml data/config.toml
   ```

2. Open `data/config.toml`. Write your two API keys in the file. Write the URL of your repository.

3. Set the permissions of the file. The file contains secrets.

   ```bash
   chmod 600 data/config.toml
   ```

4. Build the image.

   ```bash
   docker build -t beagle .
   ```

5. Start the container.

   ```bash
   docker run -d --name beagle -p 8080:8080 -v "$PWD/data:/data" beagle
   ```

6. Make sure that the server operates.

   ```bash
   curl localhost:8080/v1/healthz
   ```

The server returns `{"ok":true,...}`.

## Procedure without Docker

1. Make a virtual environment and install the package.

   ```bash
   python -m venv .venv
   .venv/bin/pip install -e .
   ```

2. Make the configuration file. Refer to step 1 to step 3 of the Docker procedure.

3. Make the index of the repository.

   ```bash
   .venv/bin/beagle --config data/config.toml index
   ```

4. Start the server.

   ```bash
   .venv/bin/beagle --config data/config.toml serve
   ```

## The data directory

The container keeps all data in `/data`. Attach this directory to a volume. The directory holds these items:

| Item | Content |
| --- | --- |
| `config.toml` | The configuration and the secrets |
| `repo.git` | The bare clone of the repository |
| `beagle.db` | The index, the findings, the feedback, and the jobs |
| `vectors.db` | The embeddings |
| `llm_log.db` | A record of each request to a model |
| `prompts/` | Your prompt files, if you use them |

The databases contain code and prompts. Give the same protection to a backup of this directory that you give to the source code.

## First index

The first index of a large repository takes minutes. The first index also costs money, because Beagle makes an embedding of each block of code. Later indexes are much less expensive, because Beagle reads only the files that changed.

To see the condition of the index, use this command:

```bash
curl -H "Authorization: Bearer <token>" localhost:8080/v1/index/status
```

If you ask for a review before the index is complete, the job waits.
