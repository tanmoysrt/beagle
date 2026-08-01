from __future__ import annotations

from fnmatch import fnmatch

RISK_TAGS = ("auth", "payments", "crypto", "concurrency", "data_loss", "session")


def tier_for_unit(paths: list[str], risk_tags: list[str], deep_paths: list[str]) -> str:
    """Deep or risky units get the strongest model; everything else the default."""
    if any(tag in RISK_TAGS for tag in risk_tags):
        return "opus"
    if any(matches_any(path, deep_paths) for path in paths):
        return "opus"
    return "sonnet"


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch(path, pattern) for pattern in patterns)
