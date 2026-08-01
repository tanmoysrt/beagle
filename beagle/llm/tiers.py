from __future__ import annotations

from fnmatch import fnmatch

RISK_TAGS = ("auth", "payments", "crypto", "concurrency", "data_loss", "session")


def tier_for_unit(paths: list[str], risk_tags: list[str], deep_paths: list[str]) -> str:
    """A risky or configured-deep unit gets the reasoning model, the rest the general one."""
    if any(tag in RISK_TAGS for tag in risk_tags):
        return "reasoning"
    if any(matches_any(path, deep_paths) for path in paths):
        return "reasoning"
    return "general"


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch(path, pattern) for pattern in patterns)
