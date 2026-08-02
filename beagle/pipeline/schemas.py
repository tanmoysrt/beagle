from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("beagle.schemas")

SEVERITIES = ["P0", "P1", "P2", "P3", "P4", "P5"]

LOCATION = {
    "type": "object",
    "properties": {
        "file": {"type": "string"},
        "line_start": {"type": "integer"},
        "line_end": {"type": "integer"},
    },
    "required": ["file"],
    "additionalProperties": False,
}


def finding_schema(categories: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "file": {"type": "string", "description": "Repository-relative path"},
            "line_start": {
                "type": "integer",
                "description": "The line in the file after the change that the finding is "
                "about. Count from the +++ side of the diff, not the file on disk.",
            },
            "line_end": {"type": "integer"},
            "category": {"type": "string", "enum": categories},
            "severity": {"type": "string", "enum": SEVERITIES},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "title": {
                "type": "string",
                "description": "Three to six words in Title Case naming the defect, "
                "e.g. 'Setup Failure Reports Success'",
            },
            "body": {
                "type": "string",
                "description": "One to three sentences: the input or state, what goes "
                "wrong, and the consequence. No preamble, no restatement of the code.",
            },
            "suggested_patch": {
                "type": "string",
                "description": "Replacement code for the cited lines, when the fix is a line edit",
            },
            "locations": {
                "type": "array",
                "items": LOCATION,
                "description": "Every place this same issue occurs",
            },
        },
        "required": [
            "file", "line_start", "category", "severity", "confidence", "title", "body",
        ],
        "additionalProperties": False,
    }


def report_findings_schema(categories: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "findings": {"type": "array", "items": finding_schema(categories)},
        },
        "required": ["findings"],
        "additionalProperties": False,
    }


PLAN_UNITS_SCHEMA = {
    "type": "object",
    "properties": {
        "units": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "paths": {"type": "array", "items": {"type": "string"}},
                    "risk_tags": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "auth",
                                "payments",
                                "crypto",
                                "concurrency",
                                "data_loss",
                                "session",
                                "blast_radius",
                            ],
                        },
                    },
                    "rationale": {"type": "string"},
                },
                "required": ["title", "paths"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["units"],
    "additionalProperties": False,
}

SUBMIT_CONTEXT_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "description": "The code the reviewer needs, as line ranges. Never the code itself.",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Repository-relative path"},
                    "start_line": {"type": "integer"},
                    "end_line": {"type": "integer"},
                    "why": {
                        "type": "string",
                        "description": "One line: what the reviewer should notice here",
                    },
                },
                "required": ["path", "start_line", "end_line", "why"],
                "additionalProperties": False,
            },
        },
        "notes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "What you learned that is not code: a commit message, a name "
            "nothing calls, a pattern the rest of the repository follows.",
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["confirm", "revise", "reject"]},
        "severity": {"type": "string", "enum": SEVERITIES},
        "body": {
            "type": "string",
            "description": "The corrected finding as the author reads it, not your "
            "reasoning about it. Omit unless the wording itself needs changing.",
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string", "description": "Why, for Beagle's log. Never shown."},
    },
    "required": ["verdict"],
    "additionalProperties": False,
}

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {
            "type": "string",
            "description": "One sentence: merge it, or the one thing to fix first",
        },
        "reasoning": {
            "type": "string",
            "description": "One or two sentences of specific technical justification",
        },
        "attention": {
            "type": "array",
            "items": {"type": "string"},
            "description": "`path: what needs attention there`, at most two entries. Use a colon, never a dash.",
        },
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["description", "reasoning"],
    "additionalProperties": False,
}

COMMENT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {
            "type": "string",
            "enum": ["false_positive", "dismiss", "style_rule", "question", "ignore"],
        },
        "rule": {"type": "string", "description": "For style_rule, the convention as one sentence"},
        "reason": {"type": "string", "description": "A short paraphrase of what the author said"},
    },
    "required": ["intent"],
    "additionalProperties": False,
}


def parse_loose(text: str) -> Any | None:
    """Parse a list that may carry trailing junk, such as an extra closing brace."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    end = text.rfind("]")
    if end == -1:
        return None
    try:
        salvaged = json.loads(text[: end + 1])
    except json.JSONDecodeError:
        return None
    log.warning("recovered a %d character list from a malformed tool result", len(text))
    return salvaged


def read_entries(data: dict[str, Any], key: str) -> tuple[list[dict], str | None]:
    """Read a list of objects from a tool result, reporting anything unusable.

    A model sometimes hands back the whole list as a JSON string. Iterating that
    yields one character per entry, so it is parsed rather than walked, and what
    still cannot be read is reported instead of being dropped in silence.
    """
    entries = data.get(key)
    if isinstance(entries, str):
        entries = parse_loose(entries)
        if entries is None:
            log.warning("%s came back as text that is not json", key)
            return [], f"the model returned {key} as unparseable text"
    if entries is None:
        return [], None
    if not isinstance(entries, list):
        return [], f"the model returned {key} as {type(entries).__name__}, not a list"

    usable = [item for item in entries if isinstance(item, dict)]
    if entries and not usable:
        return [], f"none of the {len(entries)} {key} entries were readable"
    if len(usable) != len(entries):
        return usable, f"{len(entries) - len(usable)} of {len(entries)} {key} entries were unreadable"
    return usable, None


OUTPUT_INSTRUCTIONS = {
    "reviewer": (
        "Return your findings by calling the `report_findings` tool exactly once, "
        "with one entry per finding, worst first. Never answer in prose."
    ),
    "plan": "Return the units by calling the `plan_units` tool exactly once.",
    "dedup": (
        "Return the final merged list by calling the `report_findings` tool exactly once."
    ),
    "verify": "Return your verdict by calling the `verify_finding` tool exactly once.",
    "comment_classifier": (
        "Return the intent by calling the `classify_comment` tool exactly once."
    ),
    "summary": "Return the summary by calling the `write_summary` tool exactly once.",
    "investigator": (
        "Hand over the context by calling the `submit_context` tool exactly once. "
        "Never answer in prose."
    ),
}
