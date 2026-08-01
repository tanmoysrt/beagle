class BeagleError(Exception):
    exit_code = 1


class ConfigError(BeagleError):
    """Malformed, missing, or contradictory configuration."""

    exit_code = 2


class MigrationError(BeagleError):
    """Schema drift the server refuses to guess about."""

    exit_code = 2


class RepoError(BeagleError):
    """Git operation failed: bad ref, unreachable remote, dirty mirror."""

    exit_code = 6


class ProviderError(BeagleError):
    """LLM or embedding endpoint failed after retries."""

    exit_code = 4

    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class GithubError(BeagleError):
    """GitHub refused a request or could not be reached."""

    exit_code = 4


class BudgetExceeded(BeagleError):
    """max_cost_usd or token_budget hit; partial results are flushed."""

    exit_code = 5
