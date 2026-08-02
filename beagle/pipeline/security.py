from __future__ import annotations

from fnmatch import fnmatch
from pathlib import PurePosixPath

from ..constants import NON_APP_PATTERNS
from .models import Finding


class SecurityClassifier:
    """Marks a security finding as application code or not, and nothing more.

    Forcing every one of them to P0 put 45 percent of reviews at 1 out of 5,
    which taught readers to ignore the number. The reviewer rates a security
    fault on the same scale as any other, and the level it gives is the level
    that stands. What the classification still buys: a security finding is
    never dropped by the severity floor, never capped, and always checked
    a second time.
    """

    def __init__(self, extra_non_app: list[str] | None = None):
        self.patterns = list(NON_APP_PATTERNS) + list(extra_non_app or [])

    def apply(self, findings: list[Finding]) -> list[Finding]:
        for finding in findings:
            if not finding.is_security:
                continue
            finding.app_code = self.is_application_code(finding.file)
            finding.metadata["path_class"] = "application" if finding.app_code else "non-application"
        return findings

    def is_application_code(self, path: str) -> bool:
        normalized = PurePosixPath(path).as_posix()
        return not any(fnmatch(normalized, pattern) for pattern in self.patterns)
