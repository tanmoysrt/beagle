from __future__ import annotations

from ..config import Config, Section
from ..constants import P4_CAP, P5_CAP, SCHEMA_VERSION
from ..pipeline.schemas import SEVERITIES

TOPICS = ("api", "config", "feedback", "comments")

def guide_text(topic: str | None = None) -> str:
    """Built from the live registries, so it cannot drift from the code."""
    sections = {
        "api": api_section,
        "config": config_section,
        "feedback": feedback_section,
        "comments": comments_section,
    }
    if topic in sections:
        return sections[topic]()
    return "\n\n".join([header()] + [build() for build in sections.values()])


def header() -> str:
    return (
        f"# Beagle guide (schema version {SCHEMA_VERSION})\n\n"
        "Beagle reviews a diff and returns findings graded P0 (must not merge) to P5 (nit).\n"
        f"Severity levels: {', '.join(SEVERITIES)}. Security findings in application code are "
        "always P0 and are exempt from the finding caps.\n"
        f"At most {P5_CAP} P5 and {P4_CAP} P4 findings survive the merge pass."
    )


def api_section() -> str:
    from .routes import ReviewBody, router

    lines = ["## API", "", "All routes need `Authorization: Bearer <token>` unless noted.", ""]
    lines += ["| method | path | purpose |", "| --- | --- | --- |"]
    for route in router.routes:
        methods = ",".join(sorted(route.methods - {"HEAD", "OPTIONS"}))
        summary = (route.endpoint.__doc__ or route.name.replace("_", " ")).strip().splitlines()[0]
        lines.append(f"| {methods} | `{route.path}` | {summary} |")
    fields = ", ".join(f"{name}?" for name in ReviewBody.model_fields)
    lines += [
        "",
        f"`POST /v1/reviews` accepts `{{{fields}}}` and returns 202 with a `review_id`. "
        "Stream progress from `/v1/reviews/{id}/stream` as NDJSON; every line carries `event` "
        "and `schema_version`. Re-using a `review_id` replaces its findings. Sending `pr` "
        "reviews that GitHub pull request and posts the result back to it.",
    ]
    return "\n".join(lines)


def config_section() -> str:
    lines = [
        "## Configuration",
        "",
        "One file, `/data/config.toml`. No environment variables and no CLI flags.",
        "",
        "| key | type | default |",
        "| --- | --- | --- |",
    ]
    lines += describe_model(Config, "")
    return "\n".join(lines)


def describe_model(model: type[Section], prefix: str) -> list[str]:
    rows = []
    for name, field in model.model_fields.items():
        annotation = field.annotation
        key = f"{prefix}{name}"
        if isinstance(annotation, type) and issubclass(annotation, Section):
            rows.extend(describe_model(annotation, f"{key}."))
            continue
        rows.append(f"| `{key}` | {type_name(annotation)} | {default_of(field)} |")
    return rows


def type_name(annotation) -> str:
    return getattr(annotation, "__name__", str(annotation).replace("typing.", ""))


def default_of(field) -> str:
    if field.is_required():
        return "**required**"
    if field.default_factory is not None:
        return f"`{field.default_factory()}`"
    return f"`{field.default}`"


def feedback_section() -> str:
    return "\n".join(
        [
            "## Feedback",
            "",
            "`POST /v1/findings/{id}/feedback` with `{action, reason?, author?, weight?}`.",
            "",
            "- `accept` — the finding was right",
            "- `false_positive` — wrong or not applicable; teaches suppression memory",
            "- `dismiss` — not now, this instance only",
            "- `style_rule` — the reason states a team convention to follow",
            "",
            "Feedback is keyed by fingerprint, so it survives re-reviews of the same issue.",
        ]
    )


def comments_section() -> str:
    from ..github.comments import COMMAND_HELP

    lines = [
        "## Pull request comments",
        "",
        "With GitHub enabled, reply to Beagle in a pull request. Anything else is ignored.",
        "",
        "| command | meaning |",
        "| --- | --- |",
    ]
    lines += [f"| `{command}` | {meaning} |" for command, meaning in COMMAND_HELP]
    lines += [
        "",
        "Free wording works too: a reply is classified into false positive, style rule, "
        "question or ignore. A reply inside a finding thread applies to that finding; a "
        "top-level comment applies to the pull request.",
    ]
    return "\n".join(lines)

