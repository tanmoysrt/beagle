from __future__ import annotations

import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .constants import DEFAULT_CONFIG_PATH
from .errors import ConfigError

SECRET_KEYS = ("api_key", "token", "webhook_secret", "auth_tokens")


class Severity(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"
    P5 = "P5"

    @property
    def rank(self) -> int:
        """0 is most severe, 5 the least."""
        return int(self.value[1])

    def at_least(self, threshold: "Severity") -> bool:
        """True when this severity is as bad as, or worse than, the threshold."""
        return self.rank <= threshold.rank


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServerCfg(Section):
    port: int = 8080
    auth_tokens: list[str] = Field(default_factory=list)
    max_parallel_reviews: int = Field(default=5, ge=1, le=64)


class RepoCfg(Section):
    url: str
    default_base: str = "main"
    ignore: list[str] = Field(default_factory=list)


class LLMModels(Section):
    haiku: str
    sonnet: str
    opus: str


class LLMCfg(Section):
    base_url: str = "https://api.anthropic.com"
    api_key: str
    headers: dict[str, str] = Field(default_factory=dict)
    models: LLMModels


class EmbeddingsCfg(Section):
    base_url: str = "https://api.openai.com/v1"
    api_key: str
    model: str
    dims: int = Field(default=1024, ge=8, le=8192)
    batch_size: int = Field(default=128, ge=1, le=2048)
    headers: dict[str, str] = Field(default_factory=dict)


class GithubCfg(Section):
    token: str | None = None
    repo: str | None = None
    api_url: str = "https://api.github.com"
    mode: Literal["poll", "webhook"] = "poll"
    poll_interval_seconds: int = Field(default=60, ge=10)
    webhook_secret: str | None = None
    review_on: list[str] = Field(default_factory=lambda: ["opened", "synchronize"])
    review_forks: bool = False
    post_style: Literal["inline_plus_summary", "summary_only"] = "inline_plus_summary"

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.repo)


class ReviewCfg(Section):
    min_severity: Severity = Severity.P5
    fail_on: Severity = Severity.P1
    max_findings: int = Field(default=12, ge=1)
    categories: list[str] = Field(
        default_factory=lambda: [
            "bug",
            "security",
            "performance",
            "correctness",
            "style",
            "test_gap",
        ]
    )
    max_cost_usd: float = Field(default=2.50, gt=0)
    token_budget: int = Field(default=60000, gt=0)
    deep_paths: list[str] = Field(default_factory=list)


class ContextCfg(Section):
    instruction_files: Literal["auto", "off"] = "auto"
    instruction_files_extra: list[str] = Field(default_factory=list)
    instruction_files_budget: int = Field(default=4000, ge=0)


class PromptsCfg(Section):
    dir: str | None = None


class MemoryCfg(Section):
    suppress_similarity: float = Field(default=0.92, ge=0.0, le=1.0)
    downrank_similarity: float = Field(default=0.80, ge=0.0, le=1.0)
    suppress_similarity_security: float = Field(default=0.97, ge=0.0, le=1.0)


class Config(Section):
    server: ServerCfg = Field(default_factory=ServerCfg)
    repo: RepoCfg
    llm: LLMCfg
    embeddings: EmbeddingsCfg
    github: GithubCfg = Field(default_factory=GithubCfg)
    review: ReviewCfg = Field(default_factory=ReviewCfg)
    context: ContextCfg = Field(default_factory=ContextCfg)
    prompts: PromptsCfg = Field(default_factory=PromptsCfg)
    memory: MemoryCfg = Field(default_factory=MemoryCfg)

    @field_validator("memory")
    @classmethod
    def check_threshold_order(cls, memory: MemoryCfg) -> MemoryCfg:
        if memory.downrank_similarity > memory.suppress_similarity:
            raise ValueError("downrank_similarity must be <= suppress_similarity")
        return memory

    @property
    def github_enabled(self) -> bool:
        return self.github.enabled

    def repo_access_mode(self) -> str:
        """How the mirror will reach the remote, for doctor output."""
        if self.repo.url.startswith(("git@", "ssh://")):
            return "ssh (deploy key)"
        if self.github.token:
            return "https (PAT)"
        return "https (anonymous)"


class LoadedConfig:
    """A parsed config plus a record of which values the file actually set."""

    def __init__(self, config: Config, raw: dict[str, Any], path: Path):
        self.config = config
        self.raw = raw
        self.path = path
        self.explicit_keys = set(walk_keys(raw))

    def source_of(self, dotted_key: str) -> str:
        return str(self.path) if dotted_key in self.explicit_keys else "default"

    def effective(self, redact: bool = True) -> list[tuple[str, str, str]]:
        """Every resolved setting as (dotted key, rendered value, source)."""
        rows = []
        for key, value in walk_values(self.config.model_dump(mode="json")):
            rendered = redact_secret(key, value) if redact else repr(value)
            rows.append((key, rendered, self.source_of(key)))
        return rows


class ConfigProvider:
    """Holds the live config so callers never hang on to stale values."""

    def __init__(self, loaded: LoadedConfig):
        self.loaded = loaded

    @property
    def current(self) -> Config:
        return self.loaded.config



def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> LoadedConfig:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: invalid TOML: {exc}") from exc
    try:
        config = Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"{path}: {format_errors(exc)}") from exc
    return LoadedConfig(config, raw, path)


def walk_keys(raw: dict[str, Any], prefix: str = "") -> list[str]:
    keys = []
    for key, value in raw.items():
        dotted = f"{prefix}{key}"
        # headers is free-form, so it counts as one setting rather than many
        if isinstance(value, dict) and key != "headers":
            keys.extend(walk_keys(value, f"{dotted}."))
        else:
            keys.append(dotted)
    return keys


def walk_values(data: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    rows = []
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict) and key != "headers":
            rows.extend(walk_values(value, f"{dotted}."))
        else:
            rows.append((dotted, value))
    return rows


def redact_secret(dotted_key: str, value: Any) -> str:
    leaf = dotted_key.rsplit(".", 1)[-1]
    if leaf in SECRET_KEYS and value:
        if isinstance(value, list):
            return f"[{len(value)} token(s), redacted]"
        text = str(value)
        return f"{text[:6]}…{text[-4:]} (redacted)" if len(text) > 12 else "(redacted)"
    return repr(value)


def format_errors(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
        for err in exc.errors()
    )
