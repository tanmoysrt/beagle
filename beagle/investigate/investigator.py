"""Issue-driven discovery.

Turns an issue into an evidence-backed map: seed from exact symbols and lexical
search, scan a bounded candidate set for the signals design/07 calls strong
(numeric thresholds, counters, exceptions, external commands, state writes,
hook/job/endpoint relations), rank, and emit the fixed report sections. Every
cited entity carries a path and exact source range. It supplies evidence; it
does not decide the fix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from beagle.investigate.issue import IssueQuery, parse_issue
from beagle.models import Entity, Observation
from beagle.search.engine import SearchEngine
from beagle.search.graph import GraphService

_CODE_KINDS = ("function", "method", "test_function")
_SIGNAL_KINDS = ("comparison", "counter", "raise", "except", "call", "assignment")
_SUBPROCESS = {"subprocess.run", "subprocess.Popen", "subprocess.check_output",
               "subprocess.call", "subprocess.check_call", "os.system", "os.popen"}
_CANDIDATE_CAP = 40
_CITE_CAP = 25
# A first-arg string is a shell command only with these markers, not any phrase.
_SHELL_HINT = re.compile(r"(?:^|\s)(?:--?\w|/\w|sudo |bash |sh |\w+/\w)")


def _looks_like_shell_command(arg: str) -> bool:
    return bool(arg) and " " in arg and bool(_SHELL_HINT.search(arg))


@dataclass
class EntitySignals:
    terms_hit: set[str] = field(default_factory=set)
    thresholds: list[str] = field(default_factory=list)
    counters: list[str] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    status_writes: list[str] = field(default_factory=list)
    doctype_writes: set[str] = field(default_factory=set)
    doctype_reads: set[str] = field(default_factory=set)
    is_endpoint: bool = False
    driven_by_hook_or_job: bool = False
    tests: list[str] = field(default_factory=list)
    unresolved_calls: list[str] = field(default_factory=list)
    callees: list[str] = field(default_factory=list)


@dataclass
class Candidate:
    entity: Entity
    score: float
    reasons: list[str] = field(default_factory=list)
    signals: EntitySignals = field(default_factory=EntitySignals)


@dataclass
class ReportSection:
    title: str
    lines: list[str] = field(default_factory=list)


@dataclass
class InvestigationReport:
    query: IssueQuery
    sections: list[ReportSection] = field(default_factory=list)
    cited: list[tuple[str, str, int, int]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class Investigator:
    def __init__(self, repo, graph: GraphService, search: SearchEngine, reader):
        self.repo = repo
        self.graph = graph
        self.search = search
        self.reader = reader

    def investigate(self, text: str, max_tokens: int = 6000) -> InvestigationReport:
        query = parse_issue(text)
        seeds = self._seed(query)
        report = InvestigationReport(query=query)
        if not seeds:
            report.notes.append("no seeds; try including a symbol name, command, or error text")
            return report
        candidates = self._build_candidates(query, seeds)
        candidates.sort(key=lambda c: -c.score)
        cited = candidates[:_CITE_CAP]
        report.sections = self._sections(query, cited)
        report.cited = [
            (c.entity.id, c.entity.owner_file, c.entity.source_range.start_line,
             c.entity.source_range.end_line)
            for c in cited
        ]
        return report

    # --- seeding -------------------------------------------------------

    def _seed(self, query: IssueQuery) -> dict[str, tuple[float, list[str]]]:
        seeds: dict[str, tuple[float, list[str]]] = {}

        def bump(eid: str, amount: float, reason: str) -> None:
            score, reasons = seeds.get(eid, (0.0, []))
            seeds[eid] = (score + amount, [*reasons, reason])

        for ident in query.identifiers:
            for entity in self.graph.resolve(ident):
                bump(entity.id, 5.0, f"exact symbol match: {ident}")
        queries = [query.text, *query.identifiers]
        for q in queries:
            for result in self.search.search(q, limit=20, prefix=True):
                for eid in self._hit_entities(result):
                    bump(eid, 1.5, "lexical match")
        return seeds

    def _hit_entities(self, result) -> list[str]:
        if result.entity_id:
            return [result.entity_id]
        # A window chunk can match anywhere in its span, so seed every code
        # entity overlapping it rather than just the one at its first line.
        overlapping = self.repo.entities_overlapping(
            result.owner_file, result.source_range.start_line,
            result.source_range.end_line, _CODE_KINDS,
        )
        return [e.id for e in overlapping]

    # --- candidate scoring --------------------------------------------

    def _build_candidates(self, query, seeds) -> list[Candidate]:
        ranked = sorted(seeds.items(), key=lambda kv: -kv[1][0])[:_CANDIDATE_CAP]
        ids = [eid for eid, _ in ranked]
        obs_by_subject = self._observations_by_subject(ids)
        candidates: list[Candidate] = []
        for eid, (base, reasons) in ranked:
            entity = self.repo.get_entity(eid)
            if entity is None:
                continue
            signals = self._signals(entity, query, obs_by_subject.get(eid, []))
            score, extra = self._score(base, query, signals)
            candidates.append(Candidate(entity, score, [*reasons, *extra], signals))
        return candidates

    def _observations_by_subject(self, ids: list[str]) -> dict[str, list[Observation]]:
        grouped: dict[str, list[Observation]] = {}
        for obs in self.repo.observations_for_subjects(ids, _SIGNAL_KINDS):
            grouped.setdefault(obs.subject, []).append(obs)
        return grouped

    def _signals(self, entity: Entity, query, observations) -> EntitySignals:
        sig = EntitySignals()
        sig.terms_hit = self._terms_in_source(entity, query)
        self._scan_observations(sig, query, observations)
        self._scan_edges(sig, entity.id)
        return sig

    def _terms_in_source(self, entity: Entity, query) -> set[str]:
        try:
            source = self.reader(entity.owner_file, entity.source_range.start_line,
                                  entity.source_range.end_line).lower()
        except OSError:
            return set()
        hit = set()
        for term in query.terms | {i.lower() for i in query.identifiers}:
            if re.search(rf"\b{re.escape(term)}\b", source):
                hit.add(term)
        return hit

    def _scan_observations(self, sig, query, observations) -> None:
        for obs in observations:
            kind, data = obs.kind, obs.data
            if kind == "comparison" and data.get("value") in query.numbers:
                sig.thresholds.append(f"{data.get('left_code')} {data.get('op')} {data.get('value')}")
            elif kind == "counter":
                sig.counters.append(f"{data.get('target_code')} {data.get('op')}")
            elif kind in ("raise", "except"):
                self._note_exception(sig, query, kind, data)
            elif kind == "call":
                self._note_command(sig, data)
            elif kind == "assignment":
                target = data.get("target_code") or ""
                if target.endswith((".status", ".state")) or target in ("status", "state"):
                    sig.status_writes.append(target)

    def _note_exception(self, sig, query, kind, data) -> None:
        names = [data.get("exc")] if kind == "raise" else data.get("types", [])
        message = data.get("message") or ""
        blob = " ".join(str(n) for n in names if n) + " " + message
        sig.exceptions.append(blob.strip())

    def _note_command(self, sig, data) -> None:
        dotted = data.get("dotted")
        arg = data.get("first_arg") or ""
        if dotted in _SUBPROCESS:
            sig.commands.append(arg or data.get("func_code") or dotted)
        elif _looks_like_shell_command(arg):
            # only flag genuine command lines, not DocType names like "TLS Certificate"
            sig.commands.append(arg)

    def _scan_edges(self, sig, entity_id) -> None:
        sig.is_endpoint = bool(self.repo.edges_from(entity_id, ("EXPOSES_ENDPOINT",)))
        sig.driven_by_hook_or_job = bool(self.repo.edges_to(entity_id, ("INVOKES", "ENQUEUES")))
        for e in self.repo.edges_from(entity_id, ("WRITES_DOCTYPE", "CREATES_DOCTYPE", "DELETES_DOCTYPE")):
            if e.target_id:
                sig.doctype_writes.add(e.target_id)
        for e in self.repo.edges_from(entity_id, ("READS_DOCTYPE",)):
            if e.target_id:
                sig.doctype_reads.add(e.target_id)
        for e in self.repo.edges_from(entity_id, ("CALLS",)):
            (sig.callees if e.target_id else sig.unresolved_calls).append(
                e.target_id or e.target_hint or "?"
            )
        sig.tests = [e.source_id for e in self.graph.tests(entity_id)]

    def _score(self, base: float, query, sig: EntitySignals) -> tuple[float, list[str]]:
        score, reasons = base, []
        concepts = len(sig.terms_hit)
        if concepts:
            score += 1.5 * min(concepts, 4)
            if concepts >= 2:
                reasons.append(f"contains {concepts} issue concepts: {', '.join(sorted(sig.terms_hit))}")
        if sig.thresholds:
            score += 3.0
            reasons.append("numeric threshold: " + "; ".join(sig.thresholds))
        if sig.counters and sig.thresholds:
            score += 2.0
            reasons.append("counter + threshold (retry policy)")
        if sig.exceptions:
            score += 2.0
        if sig.commands:
            score += 2.0
            reasons.append("external command")
        if sig.is_endpoint or sig.driven_by_hook_or_job:
            score += 2.0
            reasons.append("entrypoint (endpoint/hook/job)")
        if sig.doctype_writes or sig.status_writes:
            score += 1.0
        if sig.tests:
            score += 1.0
        return score, reasons

    # --- sections ------------------------------------------------------

    def _sections(self, query, cited: list[Candidate]) -> list[ReportSection]:
        return [
            self._likely_area(cited),
            self._entrypoints(cited),
            self._workflow(cited),
            self._retry_conditions(cited),
            self._failure_handling(cited),
            self._state_changes(cited),
            self._external(cited),
            self._tests_section(cited),
            self._change_points(cited),
            self._unknowns(query, cited),
            self._source_ranges(cited),
        ]

    def _loc(self, c: Candidate) -> str:
        r = c.entity.source_range
        return f"{c.entity.qualified_name}  ({c.entity.owner_file}:{r.start_line}-{r.end_line})"

    def _likely_area(self, cited) -> ReportSection:
        section = ReportSection("Likely area")
        if cited:
            top = cited[0]
            module = top.entity.qualified_name.rsplit(".", 1)[0]
            section.lines.append(f"{module} — strongest seed: {self._loc(top)}")
        return section

    def _entrypoints(self, cited) -> ReportSection:
        section = ReportSection("Primary entrypoints")
        for c in cited:
            if c.signals.is_endpoint:
                section.lines.append(f"endpoint: {self._loc(c)}")
            elif c.signals.driven_by_hook_or_job:
                section.lines.append(f"hook/job handler: {self._loc(c)}")
        return section

    def _workflow(self, cited) -> ReportSection:
        section = ReportSection("Probable workflow")
        if not cited:
            return section
        start = next((c for c in cited if c.signals.is_endpoint or c.signals.driven_by_hook_or_job), cited[0])
        chain = self._callee_chain(start.entity.id)
        if chain:
            section.lines.append(" -> ".join(self._short(i) for i in chain))
        return section

    def _callee_chain(self, start: str, limit: int = 6) -> list[str]:
        chain, node, seen = [start], start, {start}
        while len(chain) < limit:
            nxt = next((e.target_id for e in self.graph.callees(node)
                        if e.target_id and e.target_id not in seen), None)
            if not nxt:
                break
            chain.append(nxt)
            seen.add(nxt)
            node = nxt
        return chain

    def _retry_conditions(self, cited) -> ReportSection:
        section = ReportSection("Retry and stop conditions")
        for c in cited:
            for t in c.signals.thresholds:
                section.lines.append(f"threshold: {t}  [{self._short(c.entity.id)}]")
            for ctr in c.signals.counters:
                section.lines.append(f"counter: {ctr}  [{self._short(c.entity.id)}]")
        return section

    def _failure_handling(self, cited) -> ReportSection:
        section = ReportSection("Failure handling")
        for c in cited:
            for exc in c.signals.exceptions:
                section.lines.append(f"{exc}  [{self._short(c.entity.id)}]")
        return section

    def _state_changes(self, cited) -> ReportSection:
        section = ReportSection("State and field changes")
        for c in cited:
            for w in c.signals.status_writes:
                section.lines.append(f"status write: {w}  [{self._short(c.entity.id)}]")
            for dt in sorted(c.signals.doctype_writes):
                section.lines.append(f"writes DocType: {dt}  [{self._short(c.entity.id)}]")
        return section

    def _external(self, cited) -> ReportSection:
        section = ReportSection("External systems and commands")
        for c in cited:
            for cmd in c.signals.commands:
                section.lines.append(f"{cmd}  [{self._short(c.entity.id)}]")
        return section

    def _tests_section(self, cited) -> ReportSection:
        section = ReportSection("Related tests")
        seen = set()
        for c in cited:
            for t in c.signals.tests:
                if t not in seen:
                    seen.add(t)
                    section.lines.append(self._short(t))
        return section

    def _change_points(self, cited) -> ReportSection:
        section = ReportSection("Likely change points")
        for c in cited:
            s = c.signals
            if s.thresholds or s.counters or s.status_writes:
                section.lines.append(self._loc(c))
        return section

    def _unknowns(self, query, cited) -> ReportSection:
        section = ReportSection("Unknowns")
        if not any(c.signals.thresholds for c in cited) and query.numbers:
            section.lines.append(f"no numeric threshold matched {sorted(query.numbers)} statically")
        unresolved = {u for c in cited for u in c.signals.unresolved_calls}
        if unresolved:
            section.lines.append("unresolved calls (dynamic/external): "
                                 + ", ".join(sorted(unresolved)[:8]))
        return section

    def _source_ranges(self, cited) -> ReportSection:
        section = ReportSection("Source ranges")
        for c in cited:
            r = c.entity.source_range
            section.lines.append(f"{c.entity.id}  {c.entity.owner_file}:{r.start_line}-{r.end_line}")
        return section

    def _short(self, entity_id: str) -> str:
        entity = self.repo.get_entity(entity_id)
        return entity.qualified_name if entity else entity_id
