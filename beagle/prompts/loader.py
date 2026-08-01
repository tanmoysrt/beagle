from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from ..config import Severity
from ..constants import P4_CAP, P5_CAP, PROMPT_SET_VERSION
from ..errors import ConfigError

DEFAULTS_DIR = Path(__file__).parent / "defaults"
SLOT = re.compile(r"\{\{(\w+)\}\}")

PROMPT_NAMES = (
    "reviewer",
    "plan",
    "dedup",
    "verify",
    "comment_classifier",
    "explain",
    "distill",
    "summary",
)

# Slots an override must keep, or the pipeline loses its output contract.
REQUIRED_SLOTS = {
    "reviewer": {"output_instructions", "severity_scale"},
    "plan": {"output_instructions"},
    "dedup": {"output_instructions"},
    "verify": {"output_instructions", "severity_scale"},
    "comment_classifier": {"output_instructions"},
    "explain": set(),
    "summary": {"output_instructions"},
    "distill": set(),
}

SEVERITY_SCALE = """SEVERITY SCALE — use these levels exactly:
P0  Must not merge. Real breakage or exposure.
    security vulnerability in app code, data loss, crash on main path, secret in code
P1  Should fix before merge. Likely bug or serious gap.
    logic error, race condition, unhandled error path, caller broken by an API change
P2  Should fix soon. Real problem, not immediately damaging.
    performance issue on a hot path, fragile pattern likely to break
P3  Worth fixing, author's call on timing.
    misleading naming on public surface, moderate readability or structure issue
P4  Minor improvement.
    small refactor opportunity, non-critical edge-case hardening, any missing test
P5  Nit or polish. Reported sparingly.
    minor style preference, tiny readability tweak"""


@dataclass(frozen=True)
class Prompt:
    name: str
    body: str
    source: str
    digest: str

    def render(self, values: dict[str, str]) -> str:
        text = self.body
        for slot, value in values.items():
            text = text.replace("{{" + slot + "}}", value)
        return SLOT.sub("", text).strip()


class PromptSet:
    """The packaged prompts plus operator overrides: `name.md` replaces a prompt,
    `name.append.md` is added after the built-in."""

    def __init__(self, override_dir: Path | str | None = None):
        self.override_dir = Path(override_dir) if override_dir else None
        self.prompts = {name: self.load(name) for name in PROMPT_NAMES}
        self.validate()

    def get(self, name: str) -> Prompt:
        if name not in self.prompts:
            raise ConfigError(f"unknown prompt: {name}")
        return self.prompts[name]

    def load(self, name: str) -> Prompt:
        body = (DEFAULTS_DIR / f"{name}.md").read_text(encoding="utf-8")
        source = "built-in"
        if self.override_dir:
            replacement = self.override_dir / f"{name}.md"
            addition = self.override_dir / f"{name}.append.md"
            if replacement.is_file():
                body = replacement.read_text(encoding="utf-8")
                source = f"replaced by {replacement}"
            if addition.is_file():
                body = f"{body.rstrip()}\n\n{addition.read_text(encoding='utf-8').strip()}\n"
                source = "built-in + append" if source == "built-in" else f"{source} + append"
        return Prompt(name, body, source, hashlib.sha256(body.encode()).hexdigest()[:16])

    def validate(self) -> None:
        """Fail at startup, never mid-review."""
        problems = []
        for name, prompt in self.prompts.items():
            present = set(SLOT.findall(prompt.body))
            missing = REQUIRED_SLOTS[name] - present
            if missing:
                problems.append(f"{name}.md is missing required slot(s): {', '.join(sorted(missing))}")
        if problems:
            raise ConfigError("; ".join(problems))

    def report(self) -> list[dict[str, str]]:
        return [
            {"name": name, "source": prompt.source, "digest": prompt.digest}
            for name, prompt in sorted(self.prompts.items())
        ]

    def version(self) -> str:
        combined = "".join(self.prompts[name].digest for name in PROMPT_NAMES)
        return f"{PROMPT_SET_VERSION}-{hashlib.sha256(combined.encode()).hexdigest()[:8]}"


def reviewer_values(
    repo_overview: str, instruction_files: str, conventions: str, output_instructions: str
) -> dict[str, str]:
    return {
        "severity_scale": SEVERITY_SCALE,
        "repo_overview": repo_overview,
        "instruction_files": instruction_files,
        "conventions": conventions,
        "output_instructions": output_instructions,
    }


def plan_values(max_units: int, output_instructions: str) -> dict[str, str]:
    return {
        "max_units": str(max_units),
        "output_instructions": output_instructions,
    }


def dedup_values(output_instructions: str) -> dict[str, str]:
    return {
        "p5_cap": str(P5_CAP),
        "p4_cap": str(P4_CAP),
        "output_instructions": output_instructions,
    }


def verify_values(output_instructions: str) -> dict[str, str]:
    return {"severity_scale": SEVERITY_SCALE, "output_instructions": output_instructions}


def summary_values(fail_on: Severity, output_instructions: str) -> dict[str, str]:
    return {"fail_on": fail_on.value, "output_instructions": output_instructions}
