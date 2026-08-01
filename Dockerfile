FROM python:3.13-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE healthcheck.py ./
COPY beagle ./beagle
RUN pip install --no-cache-dir .

# config.toml, the three databases, the bare mirror and any prompt overrides
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD ["python", "/app/healthcheck.py"]

CMD ["beagle", "serve"]
