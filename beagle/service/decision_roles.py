"""Vocabulary for decision and feedback memory (design/15 §16, §18).

Decision roles are kept distinct from Git commit roles: a person who authored a
commit is not, by that fact, the decision owner. Confirmation state separates
inferred attribution from explicitly confirmed attribution.
"""

from __future__ import annotations

from beagle.service.errors import ValidationError

SPEAKER = "speaker"
PROPOSER = "proposer"
DECISION_OWNER = "decision_owner"
APPROVER = "approver"
REVIEWER = "reviewer"
IMPLEMENTER = "implementer"
SUMMARY_EDITOR = "summary_editor"

ROLES = frozenset(
    {SPEAKER, PROPOSER, DECISION_OWNER, APPROVER, REVIEWER, IMPLEMENTER, SUMMARY_EDITOR}
)

INFERRED = "inferred"
CONFIRMED = "confirmed"
REJECTED = "rejected"
CONFIRMATION_STATES = frozenset({INFERRED, CONFIRMED, REJECTED})

DECISION_STATUSES = frozenset({"open", "accepted", "rejected", "superseded"})

# Feedback lifecycle (design §18).
FEEDBACK_STATES = frozenset(
    {"received", "accepted", "implemented", "rejected", "superseded"}
)


def validate_role(role: str) -> str:
    if role not in ROLES:
        raise ValidationError(f"unknown decision role: {role}")
    return role


def validate_confirmation(state: str) -> str:
    if state not in CONFIRMATION_STATES:
        raise ValidationError(f"unknown confirmation state: {state}")
    return state


def validate_feedback_state(state: str) -> str:
    if state not in FEEDBACK_STATES:
        raise ValidationError(f"unknown feedback state: {state}")
    return state
