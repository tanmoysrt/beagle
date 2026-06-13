"""Render a FunctionContext as compact text or a JSON-friendly dict.

Compact is the default (design/12 progressive disclosure): identity and
responsibility first, then only the non-empty behaviour sections in importance
order, trimmed to a token budget. Uncertainty is never hidden — the unknowns
section is emitted even under a tight budget.
"""

from __future__ import annotations

from beagle.card.model import FunctionContext

_CHARS_PER_TOKEN = 4


def as_dict(card: FunctionContext) -> dict:
    if card.candidates:
        return {"candidates": card.candidates}
    i, r = card.identity, card.responsibility
    return {
        "identity": {"entity_id": i.entity_id, "qualified_name": i.qualified_name,
                     "kind": i.kind, "path": i.path, "start_line": i.start_line,
                     "end_line": i.end_line, "signature": i.signature,
                     "decorators": i.decorators, "docstring": i.docstring},
        "responsibility": {"action": r.action, "subject": r.subject, "summary": r.summary,
                           "evidence": r.evidence, "confidence": r.confidence},
        "entrypoints": [{"kind": e.kind, "detail": e.detail, "entity_id": e.entity_id}
                        for e in card.entrypoints],
        "guards": [{"kind": g.kind, "text": g.text, "line": g.line} for g in card.guards],
        "reads": [_effect(e) for e in card.reads],
        "writes": [_effect(e) for e in card.writes],
        "calls": [{"name": c.name, "category": c.category, "resolved": c.resolved,
                   "line": c.line} for c in card.calls],
        "lifecycle": [{"operation": p.operation, "doctype": p.doctype,
                       "events": p.events, "handlers": p.handlers} for p in card.lifecycle],
        "jobs": [_effect(e) for e in card.jobs],
        "external_boundaries": [{"kind": b.kind, "detail": b.detail, "line": b.line}
                                for b in card.external_boundaries],
        "failures": [{"kind": f.kind, "detail": f.detail, "line": f.line} for f in card.failures],
        "callers": [_related(e) for e in card.callers],
        "tests": [_related(e) for e in card.tests],
        "unknowns": card.unknowns,
    }


def _effect(e) -> dict:
    return {"kind": e.kind, "target": e.target, "line": e.line, "certainty": e.certainty}


def _related(e) -> dict:
    return {"entity_id": e.entity_id, "name": e.name, "kind": e.kind}


def render(card: FunctionContext, max_tokens: int = 1500) -> list[str]:
    if card.candidates:
        return ["not a single function; candidates:", *(f"  {c}" for c in card.candidates)]
    lines = _header(card)
    budget = max_tokens - _tokens(lines)
    for title, body in _sections(card):
        if not body:
            continue
        block = [f"\n{title}", *(f"  {b}" for b in body)]
        if title != "Unknowns" and _tokens(block) > budget:
            lines.append(f"\n{title}: ({len(body)} items omitted for budget)")
            continue
        lines += block
        budget -= _tokens(block)
    return lines


def _header(card: FunctionContext) -> list[str]:
    i, r = card.identity, card.responsibility
    head = [f"{i.qualified_name}  [{i.kind}]  ({i.path}:{i.start_line}-{i.end_line})"]
    if i.signature:
        head.append(f"signature: {i.signature}")
    head.append(f"responsibility: {r.summary}  (confidence {r.confidence})")
    if r.evidence:
        head.append(f"  evidence: {'; '.join(r.evidence)}")
    return head


def _sections(card: FunctionContext) -> list[tuple[str, list[str]]]:
    return [
        ("Entrypoints", [f"{e.kind}: {e.detail}" for e in card.entrypoints]),
        ("Guards", [f"{g.kind}: {g.text}" for g in card.guards]),
        ("State changes", [f"{w.kind}: {w.target}" + _flag(w) for w in card.writes]),
        ("Reads", [f"{e.kind}: {e.target}" + _flag(e) for e in card.reads]),
        ("Important calls", [f"{c.category}: {c.name}" + ("" if c.resolved else " (unresolved)")
                             for c in card.calls]),
        ("Implicit Frappe lifecycle", [f"{p.operation} {p.doctype}: " + " -> ".join(p.events)
                                       for p in card.lifecycle]),
        ("Background jobs", [f"enqueue: {j.target}" for j in card.jobs]),
        ("External systems", [f"{b.kind}: {b.detail}" for b in card.external_boundaries]),
        ("Failure paths", [f"{f.kind}: {f.detail}" for f in card.failures]),
        ("Callers", [c.name for c in card.callers]),
        ("Tests", [t.name for t in card.tests]),
        ("Unknowns", list(card.unknowns)),
    ]


def _flag(effect) -> str:
    return " (unconfirmed)" if effect.certainty == "unconfirmed" else ""


def _tokens(lines: list[str]) -> int:
    return sum(len(line) for line in lines) // _CHARS_PER_TOKEN + 1
