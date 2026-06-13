"""Secret redaction for shared summaries (design/13 privacy section).

Conservative, pattern-based scrubbing applied before a summary leaves local
storage. It removes obvious credentials rather than attempting to understand
content; when unsure it redacts. Raw transcripts are never stored or shared by
this module — only already-summarized text passes through.
"""

from __future__ import annotations

import re

# token=value / "api_key": "..." / Authorization: Bearer xxx / long hex+base64.
_PATTERNS = [
    re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key|access[_-]?key"
               r"|client[_-]?secret|private[_-]?key)\b\s*[:=]\s*\S+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"),          # long base64-ish blobs
    re.compile(r"\b(?:sk|pk|ghp|gho|xox[baprs])[-_][A-Za-z0-9]{16,}\b"),  # keys
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
               re.DOTALL),
]

_PLACEHOLDER = "[REDACTED]"


def redact(text: str) -> str:
    """Replace credential-looking spans with a placeholder."""
    if not text:
        return text
    out = text
    for pattern in _PATTERNS:
        out = pattern.sub(_PLACEHOLDER, out)
    return out


def contains_secret(text: str) -> bool:
    return bool(text) and any(p.search(text) for p in _PATTERNS)
