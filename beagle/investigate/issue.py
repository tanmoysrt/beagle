"""Parse free-text issues into search material.

Preserves exact identifiers and numbers (design/07: "preserve exact phrases and
numbers"), and derives a small term set with generic words removed so words like
``retry``/``error``/``status`` cannot dominate ranking on their own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]+")

# Words too generic to score on their own — present in almost any code path.
GENERIC = {
    "the", "and", "for", "with", "that", "this", "after", "some", "due", "can",
    "may", "stop", "stops", "fail", "fails", "failure", "failures", "error",
    "errors", "retry", "retries", "status", "state", "code", "codes", "value",
    "values", "data", "run", "runs", "check", "checks", "issue", "problem",
    "problems", "safe", "long", "delay", "attempt", "attempts", "time", "times",
}


# Small, deterministic domain variants (design/11 §3: "Keep expansion small. Do
# not generate dozens of speculative synonyms"). Only well-known Frappe/ops terms.
_SYNONYMS = {
    "renewal": {"renew", "renewed"},
    "renew": {"renewal", "renewed"},
    "certbot": {"certbot", "letsencrypt"},
    "scheduler": {"scheduled", "schedule"},
    "scheduled": {"scheduler", "schedule"},
    "expiry": {"expired", "expire", "expiration"},
    "expire": {"expiry", "expired", "expiration"},
    "validation": {"validate", "invalid"},
}


@dataclass
class IssueQuery:
    text: str
    identifiers: set[str] = field(default_factory=set)
    numbers: set[str] = field(default_factory=set)
    terms: set[str] = field(default_factory=set)
    expansions: set[str] = field(default_factory=set)

    @property
    def all_search_terms(self) -> list[str]:
        return sorted(self.identifiers | self.terms | self.numbers | self.expansions)


def _looks_like_identifier(token: str) -> bool:
    if "." in token or "_" in token:
        return True
    return any(c.isupper() for c in token[1:])  # CamelCase


def _variants(term: str) -> set[str]:
    """Deterministic plural/singular + curated synonym variants for one term."""
    out = set(_SYNONYMS.get(term, set()))
    if term.endswith("s") and len(term) > 3:
        out.add(term[:-1])
    else:
        out.add(term + "s")
    return {v for v in out if len(v) > 2 and v != term}


def parse_issue(text: str) -> IssueQuery:
    query = IssueQuery(text=text.strip())
    for token in _IDENTIFIER.findall(text):
        if _looks_like_identifier(token):
            query.identifiers.add(token)
    query.numbers = set(_NUMBER.findall(text))
    for word in _WORD.findall(text):
        low = word.lower()
        if low not in GENERIC and word not in query.identifiers:
            query.terms.add(low)
    # Expand only off concept terms; keep variants separate so concept-count
    # scoring stays anchored on the words the user actually wrote.
    for term in query.terms:
        query.expansions |= _variants(term)
    query.expansions -= query.terms
    return query
