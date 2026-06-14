# Beagle shared service — container image.
#
# Builds the service and its dependencies with uv, on a slim Python base that
# also carries `git` (the mirror and Smart-HTTP transport shell out to it).
# Runs the FastAPI service via uvicorn through the `beagle-service` CLI.

FROM python:3.11-slim AS base

# git is required at runtime: bare mirrors, fetch, and `git http-backend`.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# uv for fast, reproducible installs.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (cached unless the lock or manifest changes).
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

# Then the project itself.
COPY beagle ./beagle
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    BEAGLE_DATABASE_URL="sqlite:////data/beagle-service.db" \
    BEAGLE_REPO_ROOT="/data/repositories"

# Persist mirrors, snapshots, and (in SQLite mode) the database.
VOLUME ["/data"]
EXPOSE 8000

# BEAGLE_SERVICE_SECRET must be provided at run time.
CMD ["sh", "-c", "beagle-service init-db && beagle-service serve --host 0.0.0.0 --port 8000"]
