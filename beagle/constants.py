from pathlib import Path

SCHEMA_VERSION = 1  # bumped on breaking NDJSON/API changes
PROMPT_SET_VERSION = "v1"

# The most review units one change is split into.
MAX_UNITS = 6

# Per-level caps enforced by the merge pass. Not configurable by design.
P5_CAP = 1
P4_CAP = 2
P3_CAP = 3

DEFAULT_CONFIG_PATH = Path("/data/config.toml")
MIRROR_DIRNAME = "repo.git"

# Files above this size are never indexed or reviewed.
MAX_FILE_BYTES = 512 * 1024

# A review that has not finished by now is cut off and its partial results kept.
REVIEW_DEADLINE_SECONDS = 30 * 60

# Reviews cost money, so a failed one is reported rather than retried.
JOB_ATTEMPT_LIMITS = {"review": 1, "index": 3, "github_review": 1, "github_comment": 3}

# The call log holds whole prompts and responses, so it is trimmed rather than kept forever.
LLM_LOG_RETENTION_DAYS = 60

# Everything not matching these globs counts as application code, where security
# findings are forced to P0. Elsewhere the model's own severity stands.
NON_APP_PATTERNS = (
    "tests/**",
    "test/**",
    "**/tests/**",
    "**/test/**",
    "**/*_test.*",
    "**/test_*.py",
    "**/*.test.*",
    "**/*.spec.*",
    "**/*_spec.*",
    "fixtures/**",
    "**/fixtures/**",
    "testdata/**",
    "**/testdata/**",
    "scripts/**",
    "tools/**",
    "examples/**",
    "example/**",
    "**/examples/**",
    "docs/**",
    "doc/**",
    "**/docs/**",
    "benchmarks/**",
    "**/conftest.py",
)
