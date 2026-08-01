from __future__ import annotations

import math
import re
from dataclasses import dataclass

from ..config import Severity
from ..pipeline.models import Finding
from ..repo.diff import FileDiff

ENTROPY_THRESHOLD = 4.2
MIN_ENTROPY_LENGTH = 24


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern


RULES = [
    Rule("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    Rule("AWS secret key", re.compile(r"(?i)aws[_-]?secret[_-]?access[_-]?key\W{0,3}([A-Za-z0-9/+=]{40})")),
    Rule("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b")),
    Rule("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{60,}\b")),
    Rule("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    Rule("OpenAI API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}\b")),
    Rule("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    Rule("Stripe secret key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    Rule("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    Rule("Twilio key", re.compile(r"\bSK[0-9a-fA-F]{32}\b")),
    Rule("SendGrid key", re.compile(r"\bSG\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\b")),
    Rule("private key block", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
    Rule("JSON web token", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    Rule(
        "database connection string",
        re.compile(r"(?i)\b(?:postgres|postgresql|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:@/]+:[^\s:@/]+@"),
    ),
    Rule(
        "hardcoded credential",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret|password|passwd|token|access[_-]?key)\b\s*[:=]\s*"
            r"[\"']([^\"'\s]{12,})[\"']"
        ),
    ),
]

PLACEHOLDERS = re.compile(
    r"(?i)(example|placeholder|dummy|redacted|changeme|your[_-]?key|xxx+|\.\.\.|<[^>]+>|"
    r"\$\{[^}]+\}|os\.environ|process\.env|getenv)"
)


class SecretScanner:
    """Regex and entropy pass over added lines. Costs nothing and always runs."""

    def scan(self, diffs: list[FileDiff]) -> list[Finding]:
        findings = []
        for file_diff in diffs:
            for line_number, text in file_diff.added_lines:
                hit = self.match_line(text)
                if hit:
                    findings.append(self.finding_for(file_diff.path, line_number, text, hit))
        return dedupe(findings)

    def match_line(self, text: str) -> str | None:
        if PLACEHOLDERS.search(text):
            return None
        for rule in RULES:
            if rule.pattern.search(text):
                return rule.name
        return "high-entropy string" if self.entropy_hit(text) else None

    def entropy_hit(self, text: str) -> bool:
        for token in re.findall(r"[A-Za-z0-9+/=_\-]{%d,}" % MIN_ENTROPY_LENGTH, text):
            if not looks_assigned(text):
                continue
            if shannon_entropy(token) >= ENTROPY_THRESHOLD:
                return True
        return False

    def finding_for(self, path: str, line: int, text: str, rule_name: str) -> Finding:
        return Finding(
            file=path,
            line_start=line,
            line_end=line,
            category="security",
            severity=Severity.P0,
            model_severity=Severity.P0,
            confidence=0.95,
            title=f"Possible {rule_name} committed in {path}",
            body=(
                f"A {rule_name} appears on line {line}. Secrets in version control must be "
                "treated as compromised: rotate the credential, remove it from the diff, and "
                "load it from configuration or a secret store instead.\n\n"
                f"Matched line (redacted): `{redact(text)}`"
            ),
            unit="secret-scan",
            metadata={"detector": "secret_scan", "rule": rule_name},
        )


def dedupe(findings: list[Finding]) -> list[Finding]:
    """The same secret pattern in one file is one finding listing every line."""
    grouped: dict[tuple[str, str], Finding] = {}
    for finding in findings:
        key = (finding.file, str(finding.metadata.get("rule")))
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = finding
        else:
            existing.locations.extend(finding.locations)
    return list(grouped.values())


def looks_assigned(text: str) -> bool:
    """Entropy alone flags hashes and base64 data; require it to look like a value."""
    return bool(re.search(r"[:=]\s*[\"']?[A-Za-z0-9+/=_\-]{%d,}" % MIN_ENTROPY_LENGTH, text))


def shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = {char: text.count(char) for char in set(text)}
    length = len(text)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def redact(text: str) -> str:
    stripped = text.strip()
    if len(stripped) <= 24:
        return re.sub(r"[A-Za-z0-9+/=_\-]{8,}", "***", stripped)
    return re.sub(r"[A-Za-z0-9+/=_\-]{8,}", "***", stripped[:120]) + "…"
