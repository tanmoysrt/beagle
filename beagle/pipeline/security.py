from __future__ import annotations

from fnmatch import fnmatch
from pathlib import PurePosixPath

from ..config import Severity
from ..constants import NON_APP_PATTERNS
from .models import Finding


class SecurityClassifier:
    """Decides application code by path, then forces those findings to P0.

    The model's own severity is kept for calibration, and the classification
    is attached to the finding so the rule can be audited.
    """

    def __init__(self, extra_non_app: list[str] | None = None):
        self.patterns = list(NON_APP_PATTERNS) + list(extra_non_app or [])

    def apply(self, findings: list[Finding]) -> list[Finding]:
        for finding in findings:
            if not finding.is_security:
                continue
            finding.app_code = self.is_application_code(finding.file)
            finding.metadata["path_class"] = "application" if finding.app_code else "non-application"
            if finding.app_code and finding.severity is not Severity.P0:
                finding.metadata["severity_forced"] = finding.severity.value
                finding.severity = Severity.P0
        return findings

    def is_application_code(self, path: str) -> bool:
        normalized = PurePosixPath(path).as_posix()
        return not any(fnmatch(normalized, pattern) for pattern in self.patterns)
