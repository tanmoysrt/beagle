from pathlib import Path

SCHEMA_VERSION = 1  # bumped on breaking NDJSON/API changes
PROMPT_SET_VERSION = "v1"

# Per-level caps enforced by the merge pass. Not configurable by design.
P5_CAP = 2
P4_CAP = 3

DEFAULT_CONFIG_PATH = Path("/data/config.toml")
DEFAULT_DATA_DIR = Path("/data")
MIRROR_DIRNAME = "repo.git"

# Files above this size are never indexed or reviewed.
MAX_FILE_BYTES = 512 * 1024

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
