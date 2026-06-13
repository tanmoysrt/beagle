"""Command-line interface.

Thin presentation layer over the application services in ``Workspace`` and the
search/retrieval modules. It parses arguments, calls a service, and renders the
result. No parsing, resolution, or SQL lives here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from beagle.context import ContextCompiler
from beagle.search import SearchEngine
from beagle.search.graph import GraphService
from beagle.workspace import Workspace

app = typer.Typer(
    add_completion=False,
    help="beagle: local code-discovery for Python and Frappe projects.",
)


def _open(start: Optional[Path] = None) -> Workspace:
    return Workspace.locate(start or Path.cwd())


@app.command()
def index(
    path: Path = typer.Argument(Path("."), help="Repository or directory to index."),
    force: bool = typer.Option(False, "--force", help="Reindex every file."),
) -> None:
    """Index a repository into a local SQLite graph."""
    workspace = Workspace(path.resolve())
    summary = workspace.index(force=force)
    typer.echo(
        f"indexed {summary['indexed']}, deleted {summary['deleted']}, "
        f"unchanged {summary['unchanged']} ({summary['total_files']} files)"
    )
    typer.echo(f"db: {workspace.db_path}")
    workspace.close()


@app.command()
def status() -> None:
    """Show index counts and the last run."""
    workspace = _open()
    counts = workspace.repo.counts()
    run = workspace.repo.latest_run()
    typer.echo(f"root: {workspace.root}")
    typer.echo(f"db:   {workspace.db_path}")
    typer.echo("counts: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    if run:
        typer.echo(f"last run: #{run['id']} {run['status']} ({run['files_indexed']} files)")
    workspace.close()


@app.command()
def search(
    query: str = typer.Argument(..., help="Lexical query."),
    limit: int = typer.Option(10, "--limit", "-n"),
) -> None:
    """Lexical search over indexed source."""
    workspace = _open()
    results = SearchEngine(workspace.db).search(query, limit=limit)
    if not results:
        typer.echo("no matches")
    for r in results:
        loc = f"{r.owner_file}:{r.source_range.start_line}-{r.source_range.end_line}"
        ref = r.entity_id or loc
        typer.echo(f"{ref}")
        for line in r.snippet.splitlines():
            typer.echo(f"    {line}")
    workspace.close()


@app.command()
def read(
    target: str = typer.Argument(..., help="Entity id, or path:start-end, or path."),
) -> None:
    """Print the exact source for an entity or file range."""
    workspace = _open()
    relpath, start, end = _resolve_target(workspace, target)
    if relpath is None:
        typer.echo(f"not found: {target}")
        raise typer.Exit(code=1)
    typer.echo(workspace.read_range(relpath, start, end))
    workspace.close()


def _entity_label(workspace: Workspace, entity_id: Optional[str]) -> str:
    if not entity_id:
        return "<unresolved>"
    entity = workspace.repo.get_entity(entity_id)
    return entity.qualified_name if entity else entity_id


def _resolve_one(workspace: Workspace, ref: str) -> Optional[str]:
    """Resolve a name/id to a single entity id, printing candidates if ambiguous."""
    graph = GraphService(workspace.repo)
    matches = graph.resolve(ref)
    if not matches:
        typer.echo(f"no entity matches: {ref}")
        return None
    if len(matches) > 1 and matches[0].id != ref:
        typer.echo(f"ambiguous '{ref}', candidates:")
        for m in matches[:15]:
            typer.echo(f"  {m.id}")
        return None
    return matches[0].id


@app.command()
def resolve(name: str = typer.Argument(..., help="Symbol name, qualified name, or id.")) -> None:
    """Resolve a name to candidate entities."""
    workspace = _open()
    for entity in GraphService(workspace.repo).resolve(name):
        typer.echo(f"{entity.id}  [{entity.kind}]  {entity.owner_file}:{entity.source_range.start_line}")
    workspace.close()


@app.command()
def show(entity_id: str = typer.Argument(..., help="Entity id (or resolvable name).")) -> None:
    """Show an entity's details and source range."""
    workspace = _open()
    target = _resolve_one(workspace, entity_id)
    if target:
        entity = workspace.repo.get_entity(target)
        typer.echo(f"{entity.id}\nkind: {entity.kind}\nfile: {entity.owner_file}:"
                   f"{entity.source_range.start_line}-{entity.source_range.end_line}")
        if entity.signature:
            typer.echo(f"signature: {entity.signature}")
        if entity.docstring:
            typer.echo(f"doc: {entity.docstring.splitlines()[0]}")
    workspace.close()


@app.command()
def relations(entity_id: str = typer.Argument(..., help="Entity id or name.")) -> None:
    """List incoming and outgoing edges for an entity."""
    workspace = _open()
    target = _resolve_one(workspace, entity_id)
    if target:
        rel = GraphService(workspace.repo).relations(target)
        typer.echo("outgoing:")
        for e in rel.outgoing:
            typer.echo(f"  -{e.relationship}-> {_entity_label(workspace, e.target_id)} ({e.confidence:.2f})")
        typer.echo("incoming:")
        for e in rel.incoming:
            typer.echo(f"  <-{e.relationship}- {_entity_label(workspace, e.source_id)} ({e.confidence:.2f})")
    workspace.close()


@app.command()
def callers(entity_id: str = typer.Argument(..., help="Entity id or name.")) -> None:
    """List callers of an entity."""
    _print_edges_side(entity_id, "callers")


@app.command()
def callees(entity_id: str = typer.Argument(..., help="Entity id or name.")) -> None:
    """List callees of an entity."""
    _print_edges_side(entity_id, "callees")


def _print_edges_side(ref: str, side: str) -> None:
    workspace = _open()
    target = _resolve_one(workspace, ref)
    if target:
        graph = GraphService(workspace.repo)
        edges = graph.callers(target) if side == "callers" else graph.callees(target)
        for e in edges:
            other = e.source_id if side == "callers" else e.target_id
            typer.echo(f"{_entity_label(workspace, other)}  ({e.relationship}, {e.confidence:.2f})  "
                       f"{e.owner_file}:{e.source_range.start_line}")
    workspace.close()


@app.command()
def path(
    source: str = typer.Argument(..., help="Start entity id or name."),
    target: str = typer.Argument(..., help="End entity id or name."),
) -> None:
    """Find a call path between two entities."""
    workspace = _open()
    src, dst = _resolve_one(workspace, source), _resolve_one(workspace, target)
    if src and dst:
        trail = GraphService(workspace.repo).path(src, dst)
        if trail:
            for step in trail:
                typer.echo(f"  {_entity_label(workspace, step)}")
        else:
            typer.echo("no call path found")
    workspace.close()


@app.command()
def impact(
    entity_id: str = typer.Argument(..., help="Entity id or name."),
    depth: int = typer.Option(3, "--depth"),
) -> None:
    """Show what transitively depends on an entity."""
    workspace = _open()
    target = _resolve_one(workspace, entity_id)
    if target:
        for node in GraphService(workspace.repo).impact(target, max_depth=depth):
            typer.echo(f"  [{node.distance}] {_entity_label(workspace, node.entity_id)} (via {node.via})")
    workspace.close()


@app.command(name="uses-doctype")
def uses_doctype(name: str = typer.Argument(..., help="DocType name or id.")) -> None:
    """List code that reads, writes, creates, or deletes a DocType."""
    workspace = _open()
    target = _resolve_one(workspace, name)
    if target:
        for e in GraphService(workspace.repo).uses_doctype(target):
            typer.echo(f"  {e.relationship}: {_entity_label(workspace, e.source_id)}  "
                       f"{e.owner_file}:{e.source_range.start_line}")
    workspace.close()


@app.command()
def tests(entity_id: str = typer.Argument(..., help="Entity id or name.")) -> None:
    """List tests covering an entity."""
    workspace = _open()
    target = _resolve_one(workspace, entity_id)
    if target:
        for e in GraphService(workspace.repo).tests(target):
            typer.echo(f"  {_entity_label(workspace, e.source_id)}  {e.owner_file}:{e.source_range.start_line}")
    workspace.close()


@app.command(name="reads-field")
def reads_field(field: str = typer.Argument(..., help="Field id or DocType.field name.")) -> None:
    """List code reading a field (ORM get_value field arg or self.<field> in conditions)."""
    workspace = _open()
    target = _resolve_field(workspace, field)
    if target is None:
        typer.echo(f"no field matches: {field}")
        workspace.close()
        return
    edges = workspace.repo.edges_to(target.id, ("READS_FIELD",))
    if edges:
        for e in edges:
            typer.echo(f"  {_entity_label(workspace, e.source_id)}  "
                       f"{e.owner_file}:{e.source_range.start_line}  ({e.confidence:.2f})")
    else:
        doctype_id = target.extra.get("doctype_id")
        typer.echo(f"# no field-level reads tracked; DocType-level access to {doctype_id}:")
        for e in workspace.repo.edges_to(doctype_id, ("READS_DOCTYPE",)):
            typer.echo(f"  {e.relationship}: {_entity_label(workspace, e.source_id)}  "
                       f"{e.owner_file}:{e.source_range.start_line}")
    workspace.close()


@app.command(name="writes-field")
def writes_field(field: str = typer.Argument(..., help="Field id or DocType.field name.")) -> None:
    """List code that writes a field (set_value or controller self.<field> =)."""
    workspace = _open()
    target = _resolve_field(workspace, field)
    if target is None:
        typer.echo(f"no field matches: {field}")
        workspace.close()
        return
    edges = workspace.repo.edges_to(target.id, ("WRITES_FIELD",))
    if not edges:
        typer.echo("# no field-level writes found")
    for e in edges:
        typer.echo(f"  {_entity_label(workspace, e.source_id)}  "
                   f"{e.owner_file}:{e.source_range.start_line}  ({e.confidence:.2f})")
    workspace.close()


def _resolve_field(workspace: Workspace, ref: str):
    if ref.startswith("doctype-field://"):
        return workspace.repo.get_entity(ref)
    for entity in workspace.repo.find_entities_by_name(ref):
        if entity.kind == "doctype_field":
            return entity
    return None


@app.command()
def context(
    query: str = typer.Option(..., "--query", "-q", help="The question."),
    intent: str = typer.Option("understand", "--intent",
                               help="locate | understand | change | debug | test | investigate"),
    max_tokens: int = typer.Option(6000, "--max-tokens"),
) -> None:
    """Compile an intent-shaped, budget-bounded context bundle."""
    workspace = _open()
    compiler = ContextCompiler(
        workspace.repo, GraphService(workspace.repo), SearchEngine(workspace.db),
        workspace.read_range,
    )
    bundle = compiler.compile(intent, query, max_tokens=max_tokens)
    typer.echo(f"# intent={bundle.intent} tokens={bundle.used_tokens}/{bundle.max_tokens} "
               f"items={len(bundle.items)}")
    for note in bundle.notes:
        typer.echo(f"# note: {note}")
    for item in bundle.items:
        typer.echo(f"\n## {item.qualified_name}  [{item.kind}]  ({item.confidence:.2f})")
        typer.echo(f"# {item.reason} — {item.path}:{item.start_line}-{item.end_line}")
        typer.echo(item.excerpt)
    workspace.close()


@app.command()
def investigate(
    query: Optional[str] = typer.Argument(None, help="Issue text."),
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Read issue from a file."),
    max_tokens: int = typer.Option(6000, "--max-tokens"),
    compact: bool = typer.Option(False, "--compact", help="Emit the structured JSON result."),
    include_source: bool = typer.Option(False, "--include-source", help="Append cited source."),
    mermaid: bool = typer.Option(False, "--mermaid", help="Append a compact Mermaid diagram."),
    show_query_terms: bool = typer.Option(False, "--show-query-terms"),
    show_scores: bool = typer.Option(False, "--show-scores"),
    show_paths: bool = typer.Option(False, "--show-paths"),
    show_unknowns: bool = typer.Option(False, "--show-unknowns"),
) -> None:
    """Turn an issue into an evidence-backed map of the relevant code."""
    from beagle.investigate import Investigator, render_investigation
    from beagle.lifecycle import LifecycleService

    text = file.read_text(encoding="utf-8") if file else query
    if not text:
        typer.echo("provide issue text or --file")
        raise typer.Exit(code=1)
    workspace = _open()
    graph = GraphService(workspace.repo)
    inv = Investigator(workspace.repo, graph, SearchEngine(workspace.db),
                       workspace.read_range, LifecycleService(workspace.repo, graph))
    report = inv.investigate(text, max_tokens=max_tokens)
    debug = {"terms": show_query_terms, "scores": show_scores,
             "paths": show_paths, "unknowns": show_unknowns}
    if compact:
        typer.echo(json.dumps(report.data, indent=2))
    else:
        _print_investigation(report, debug)
    if mermaid:
        typer.echo("\n```mermaid")
        typer.echo(render_investigation(report.data))
        typer.echo("```")
    if include_source:
        _print_cited_source(workspace, report)
    workspace.close()


def _print_investigation(report, debug: dict) -> None:
    if debug["terms"]:
        q = report.query
        typer.echo(f"# terms={sorted(q.terms)} ids={sorted(q.identifiers)} "
                   f"numbers={sorted(q.numbers)} expansions={sorted(q.expansions)}")
    for note in report.notes:
        typer.echo(f"# note: {note}")
    if any(debug[k] for k in ("scores", "paths", "unknowns")):
        _print_debug(report, debug)
        return
    for section in report.sections:
        typer.echo(f"\n## {section.title}")
        for line in section.lines or ["(none found)"]:
            typer.echo(f"  {line}")


def _print_debug(report, debug: dict) -> None:
    if debug["scores"]:
        typer.echo("\n## Scores")
        for src in report.data["sources"]:
            typer.echo(f"  {src['score']:>6}  {src['name']}  — {'; '.join(src['reasons'])}")
    if debug["paths"]:
        typer.echo("\n## Paths")
        for wf in report.data["primary_workflows"]:
            steps = " -> ".join(f"{s['name']} [{s['via']}]" for s in wf["steps"])
            typer.echo(f"  #{wf.get('rank', 1)} ({wf['reason']}) {steps}")
    if debug["unknowns"]:
        typer.echo("\n## Unknowns")
        for line in report.data["unknowns"] or ["(none)"]:
            typer.echo(f"  {line}")


def _print_cited_source(workspace, report) -> None:
    typer.echo("\n## Cited source")
    for entity_id, path, start, end in report.cited:
        typer.echo(f"\n# {entity_id}  {path}:{start}-{end}")
        try:
            typer.echo(workspace.read_range(path, start, end))
        except OSError:
            typer.echo("# (source unavailable)")


@app.command()
def explain(
    entity_id: str = typer.Argument(..., help="Function/method id or name."),
    mermaid: bool = typer.Option(False, "--mermaid", help="Include a Mermaid flowchart."),
    expand_calls: int = typer.Option(0, "--expand-calls", help="Inline N resolved callees."),
    framework_events: bool = typer.Option(False, "--framework-events",
                                          help="Append Frappe lifecycle trace."),
) -> None:
    """Explain a function: summary plus an optional deterministic Mermaid flow."""
    from beagle.explain import Explainer

    workspace = _open()
    explainer = Explainer(workspace.repo, GraphService(workspace.repo), workspace.read_range)
    result = explainer.explain(entity_id, include_mermaid=mermaid, expand_calls=expand_calls)
    if result.entity is None:
        typer.echo(f"not a single function: {entity_id}")
        for c in result.candidates:
            typer.echo(f"  {c}")
        workspace.close()
        raise typer.Exit(code=1)
    for line in result.summary:
        typer.echo(line)
    if result.mermaid:
        typer.echo("\n```mermaid")
        typer.echo(result.mermaid)
        typer.echo("```")
        typer.echo("\n# node sources")
        for nid, path, line in result.node_sources:
            typer.echo(f"  {nid}: {path}:{line}")
    if framework_events:
        _render_framework_events(workspace, result.entity.id)
    workspace.close()


def _render_framework_events(workspace, entity_id: str) -> None:
    from beagle.lifecycle import LifecycleService

    graph = LifecycleService(workspace.repo, GraphService(workspace.repo)).trace(entity_id, depth=1)
    typer.echo("\n# framework events")
    if graph is None or not graph.edges:
        typer.echo("  (no document operations detected)")
        return
    for src, dst, cat in graph.edges:
        s = graph.nodes.get(src, (src, ""))[0]
        d = graph.nodes.get(dst, (dst, ""))[0]
        typer.echo(f"  {s}  --{cat}-->  {d}")


@app.command()
def card(
    entity_id: str = typer.Argument(..., help="Function/method id or name."),
    compact: bool = typer.Option(False, "--compact", help="Emit the structured JSON card."),
    mermaid: bool = typer.Option(False, "--mermaid", help="Append a compact behaviour diagram."),
    max_tokens: int = typer.Option(1500, "--max-tokens", help="Budget for the text card."),
) -> None:
    """Build a Function Context Card: evidence-backed responsibility and behaviour."""
    from beagle.card import ContextCardBuilder, as_dict, render, render_card_mermaid
    from beagle.lifecycle import LifecycleService

    workspace = _open()
    graph = GraphService(workspace.repo)
    builder = ContextCardBuilder(workspace.repo, graph, workspace.read_range,
                                 LifecycleService(workspace.repo, graph))
    result = builder.build(entity_id)
    if result is None:
        typer.echo(f"no entity matches: {entity_id}")
        workspace.close()
        raise typer.Exit(code=1)
    if compact:
        typer.echo(json.dumps(as_dict(result), indent=2))
    else:
        for line in render(result, max_tokens=max_tokens):
            typer.echo(line)
    if mermaid and not result.candidates:
        typer.echo("\n```mermaid")
        typer.echo(render_card_mermaid(result))
        typer.echo("```")
    workspace.close()


@app.command()
def lifecycle(
    doctype: str = typer.Argument(..., help="DocType name or id."),
    event: Optional[str] = typer.Option(None, "--event", help="Restrict to one event."),
) -> None:
    """Show standard document lifecycle events and their handlers for a DocType."""
    from beagle.lifecycle import LifecycleService

    workspace = _open()
    report = LifecycleService(workspace.repo, GraphService(workspace.repo)).lifecycle(doctype, event)
    if report is None:
        typer.echo(f"no DocType matches: {doctype}")
        workspace.close()
        raise typer.Exit(code=1)
    typer.echo(f"# {report.doctype_id}  policy={report.policy['framework']} "
               f"{report.policy['version']} v{report.policy['policy_version']}")
    for op in report.operations:
        typer.echo(f"\n## {op.relationship}")
        if op.override_note:
            typer.echo(f"  ! {op.override_note}")
        for ev in op.events:
            _render_event(workspace, ev)
    for note in report.notes:
        typer.echo(f"# note: {note}")
    workspace.close()


def _render_event(workspace, ev) -> None:
    flags = []
    if ev.event.conditional:
        flags.append(f"conditional: {ev.event.note}")
    tag = f"  [{ev.event.category}]" + (f"  ({'; '.join(flags)})" if flags else "")
    typer.echo(f"  {ev.event.order}. {ev.event.name}{tag}")
    if ev.dispatch:
        _render_dispatch(workspace, ev.dispatch, indent="      ")


def _render_dispatch(workspace, dispatch, indent="  ") -> None:
    if dispatch.controller:
        typer.echo(f"{indent}controller: {_entity_label(workspace, dispatch.controller.target_id)} "
                   f"({dispatch.controller.confidence:.2f})")
    for h in dispatch.exact:
        typer.echo(f"{indent}doc_event: {h.target_id or h.hint} ({h.confidence:.2f})")
    for h in dispatch.wildcard:
        typer.echo(f"{indent}wildcard doc_event: {h.target_id or h.hint}")
    for h in dispatch.runtime:
        typer.echo(f"{indent}runtime?: {h.hint}")
    for note in dispatch.notes:
        typer.echo(f"{indent}# {note}")


@app.command(name="event-handlers")
def event_handlers(
    target: str = typer.Argument(..., help='"DocType.event" or DocType with --event.'),
    event: Optional[str] = typer.Option(None, "--event"),
) -> None:
    """Resolve what runs for a (DocType, event): controller, doc_events, runtime."""
    from beagle.lifecycle import LifecycleService

    doctype, ev = (target.rsplit(".", 1) if event is None and "." in target else (target, event))
    if not ev:
        typer.echo("provide an event: 'DocType.event' or --event")
        raise typer.Exit(code=1)
    workspace = _open()
    dispatch = LifecycleService(workspace.repo, GraphService(workspace.repo)).event_handlers(doctype, ev)
    if dispatch is None:
        typer.echo(f"no DocType matches: {doctype}")
        workspace.close()
        raise typer.Exit(code=1)
    typer.echo(f"# {dispatch.doctype_id} :: {dispatch.event}")
    _render_dispatch(workspace, dispatch)
    workspace.close()


@app.command()
def trace(
    entity_id: str = typer.Argument(..., help="Function/method id or name."),
    framework_events: bool = typer.Option(True, "--framework-events/--no-framework-events"),
    depth: int = typer.Option(2, "--depth"),
    mermaid: bool = typer.Option(False, "--mermaid"),
) -> None:
    """Trace document operations, lifecycle events, and handlers from a function."""
    from beagle.lifecycle import LifecycleService
    from beagle.lifecycle.mermaid import render as render_trace

    workspace = _open()
    graph = LifecycleService(workspace.repo, GraphService(workspace.repo)).trace(entity_id, depth=depth)
    if graph is None:
        typer.echo(f"not a single function: {entity_id}")
        workspace.close()
        raise typer.Exit(code=1)
    for src, dst, cat in graph.edges:
        s = graph.nodes.get(src, (src, ""))[0]
        d = graph.nodes.get(dst, (dst, ""))[0]
        typer.echo(f"  {s}  --{cat}-->  {d}")
    for note in graph.notes:
        typer.echo(f"# note: {note}")
    if mermaid:
        typer.echo("\n```mermaid")
        typer.echo(render_trace(graph))
        typer.echo("```")
    workspace.close()


def _temporal(workspace: Workspace):
    from beagle.temporal import TemporalRepository, TemporalService

    return TemporalService(workspace.root, workspace.repo,
                           TemporalRepository(workspace.db))


@app.command()
def change(
    spec: Optional[str] = typer.Argument(None, help="Commit, 'base..head', or omit for working tree."),
    episode: Optional[str] = typer.Option(None, "--episode", "-e", help="Record against this episode."),
    note: bool = typer.Option(False, "--note", help="Attach a git note to the head commit."),
    as_json: bool = typer.Option(False, "--json", help="Emit the structured report."),
) -> None:
    """Deterministic change facts: commits, changed entities, patch id."""
    workspace = _open()
    service = _temporal(workspace)
    report = service.analyze(spec)
    if episode:
        service.record(report, episode_id=episode, write_note=note)
    if as_json:
        typer.echo(json.dumps(_change_json(report), indent=2))
    else:
        _print_change(workspace, report, episode)
    workspace.close()


def _change_json(report) -> dict:
    cs = report.changeset
    return {
        "base_commit": report.base_commit, "head_commit": report.head_commit,
        "commits": [c.commit_sha for c in report.commits],
        "entity_changes": [
            {"change_type": c.change_type, "entity": c.entity_after or c.entity_before,
             "path": c.path_after or c.path_before, "confidence": c.confidence}
            for c in report.entity_changes
        ],
        "patch_id": cs.patch_id if cs else None,
        "entity_fingerprint": cs.entity_fingerprint if cs else None,
        "notes": report.notes,
    }


def _print_change(workspace, report, episode: Optional[str]) -> None:
    typer.echo(f"# {report.base_commit or '(root)'}..{report.head_commit or '(working tree)'}")
    for note in report.notes:
        typer.echo(f"# note: {note}")
    for c in report.commits:
        typer.echo(f"  commit {c.commit_sha[:10]}  {c.message}")
    for c in report.entity_changes:
        label = _entity_label(workspace, c.entity_after or c.entity_before) \
            if (c.entity_after or c.entity_before) else (c.path_after or c.path_before)
        typer.echo(f"  {c.change_type:<18} {label}  ({c.confidence:.2f})")
    if report.changeset:
        typer.echo(f"# patch_id={report.changeset.patch_id} "
                   f"fingerprint={report.changeset.entity_fingerprint}")
    if episode:
        typer.echo(f"# recorded against {episode}")


@app.command()
def history(
    entity_id: str = typer.Argument(..., help="Entity id or name."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Why an entity changed: episodes, decisions, and recorded changes."""
    workspace = _open()
    result = _temporal(workspace).entity_history(entity_id)
    if "error" in result:
        typer.echo(result["error"])
        workspace.close()
        raise typer.Exit(code=1)
    if as_json:
        typer.echo(json.dumps(_history_json(result), indent=2))
    else:
        _print_history(result)
    workspace.close()


def _history_json(result: dict) -> dict:
    return {
        "entity_id": result["entity_id"],
        "episodes": [e.id for e in result["episodes"]],
        "decisions": [{"statement": d.statement, "status": d.status,
                       "confirmation": d.confirmation} for d in result["decisions"]],
        "changes": [{"change_type": c.change_type, "commit": c.commit_sha}
                    for c in result["changes"]],
    }


def _print_history(result: dict) -> None:
    typer.echo(f"# {result['entity_id']}")
    if not (result["episodes"] or result["decisions"] or result["changes"]):
        typer.echo("  (no recorded history)")
        return
    for ep in result["episodes"]:
        typer.echo(f"  episode {ep.id} [{ep.status}] — {ep.title}")
    for d in result["decisions"]:
        flag = "" if d.status != "superseded" else " (superseded)"
        typer.echo(f"  decision [{d.status}/{d.confirmation}]{flag}: {d.statement}")
    for c in result["changes"]:
        where = f" in {c.commit_sha[:10]}" if c.commit_sha else ""
        typer.echo(f"  change {c.change_type}{where}")


episode_app = typer.Typer(add_completion=False, help="Create and manage change episodes.")
app.add_typer(episode_app, name="episode")


@episode_app.command("new")
def episode_new(
    title: str = typer.Argument(...),
    problem: Optional[str] = typer.Option(None, "--problem"),
    goal: Optional[str] = typer.Option(None, "--goal"),
    status: str = typer.Option("draft", "--status"),
) -> None:
    """Create a change episode."""
    workspace = _open()
    ep = _temporal(workspace).new_episode(title, problem, goal, status)
    typer.echo(ep.id)
    workspace.close()


@episode_app.command("list")
def episode_list(status: Optional[str] = typer.Option(None, "--status")) -> None:
    """List change episodes."""
    workspace = _open()
    from beagle.temporal import TemporalRepository

    for ep in TemporalRepository(workspace.db).list_episodes(status):
        typer.echo(f"{ep.id}  [{ep.status}]  {ep.title}")
    workspace.close()


@episode_app.command("show")
def episode_show(
    episode_id: str = typer.Argument(...),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show an episode with its decisions, alternatives, commits, and changes."""
    workspace = _open()
    bundle = _temporal(workspace).episode_bundle(episode_id)
    if bundle is None:
        typer.echo(f"no episode: {episode_id}")
        workspace.close()
        raise typer.Exit(code=1)
    typer.echo(json.dumps(_episode_json(bundle), indent=2) if as_json
               else _episode_text(bundle))
    workspace.close()


def _episode_json(bundle: dict) -> dict:
    ep = bundle["episode"]
    return {
        "id": ep.id, "title": ep.title, "status": ep.status,
        "problem": ep.problem, "goal": ep.goal, "outcome": ep.outcome,
        "base_commit": ep.base_commit, "head_commit": ep.head_commit,
        "decisions": [{"id": d.id, "statement": d.statement, "status": d.status,
                       "rationale": d.rationale, "superseded_by": d.superseded_by,
                       "confirmation": d.confirmation} for d in bundle["decisions"]],
        "alternatives": [{"description": a.description, "reason": a.rejection_reason}
                         for a in bundle["alternatives"]],
        "commits": [c.commit_sha for c in bundle["commits"]],
        "changes": [{"change_type": c.change_type, "entity": c.entity_after or c.entity_before}
                    for c in bundle["changes"]],
        "followups": [{"description": f.description, "status": f.status}
                      for f in bundle["followups"]],
    }


def _episode_text(bundle: dict) -> str:
    ep = bundle["episode"]
    lines = [f"# {ep.id} [{ep.status}] — {ep.title}"]
    for label, value in (("problem", ep.problem), ("goal", ep.goal), ("outcome", ep.outcome)):
        if value:
            lines.append(f"{label}: {value}")
    for d in bundle["decisions"]:
        sup = f" -> {d.superseded_by}" if d.superseded_by else ""
        lines.append(f"decision [{d.status}/{d.confirmation}]{sup}: {d.statement}")
    for a in bundle["alternatives"]:
        lines.append(f"rejected: {a.description}" + (f" — {a.rejection_reason}" if a.rejection_reason else ""))
    for c in bundle["commits"]:
        lines.append(f"commit {c.commit_sha[:10]}")
    for f in bundle["followups"]:
        lines.append(f"follow-up [{f.status}]: {f.description}")
    return "\n".join(lines)


@episode_app.command("decision")
def episode_decision(
    episode_id: str = typer.Argument(...),
    statement: str = typer.Argument(...),
    rationale: Optional[str] = typer.Option(None, "--rationale"),
    status: str = typer.Option("accepted", "--status"),
) -> None:
    """Record an accepted (or proposed/rejected) decision."""
    workspace = _open()
    d = _temporal(workspace).add_decision(episode_id, statement, rationale, status)
    typer.echo(d.id)
    workspace.close()


@episode_app.command("supersede")
def episode_supersede(
    episode_id: str = typer.Argument(...),
    old_decision: str = typer.Argument(..., help="Decision id being replaced."),
    statement: str = typer.Argument(...),
    rationale: Optional[str] = typer.Option(None, "--rationale"),
) -> None:
    """Replace an earlier decision; the old one is kept and labelled superseded."""
    workspace = _open()
    d = _temporal(workspace).supersede_decision(old_decision, episode_id, statement, rationale)
    typer.echo(d.id)
    workspace.close()


@episode_app.command("alternative")
def episode_alternative(
    episode_id: str = typer.Argument(...),
    description: str = typer.Argument(...),
    reason: Optional[str] = typer.Option(None, "--reason"),
) -> None:
    """Record a rejected alternative."""
    workspace = _open()
    a = _temporal(workspace).add_alternative(episode_id, description, reason)
    typer.echo(a.id)
    workspace.close()


@episode_app.command("followup")
def episode_followup(
    episode_id: str = typer.Argument(...),
    description: str = typer.Argument(...),
    priority: str = typer.Option("normal", "--priority"),
) -> None:
    """Record follow-up work."""
    workspace = _open()
    f = _temporal(workspace).add_followup(episode_id, description, priority)
    typer.echo(f.id)
    workspace.close()


@episode_app.command("finalize")
def episode_finalize(
    episode_id: str = typer.Argument(...),
    status: str = typer.Option("implemented", "--status"),
    outcome: Optional[str] = typer.Option(None, "--outcome"),
) -> None:
    """Finalize an episode (implemented | abandoned | superseded)."""
    workspace = _open()
    ep = _temporal(workspace).finalize_episode(episode_id, status, outcome)
    if ep is None:
        typer.echo(f"no episode: {episode_id}")
        workspace.close()
        raise typer.Exit(code=1)
    typer.echo(f"{ep.id} -> {ep.status}")
    workspace.close()


@episode_app.command("attach")
def episode_attach(
    episode_id: str = typer.Argument(...),
    commit: str = typer.Argument(...),
    note: bool = typer.Option(True, "--note/--no-note", help="Write a git note."),
) -> None:
    """Attach a commit's changes to an episode (and optionally a git note)."""
    workspace = _open()
    counts = _temporal(workspace).attach_commit(commit, episode_id, write_note=note)
    typer.echo(f"recorded {counts['entity_changes']} entity changes from {commit[:10]}")
    workspace.close()


@app.command()
def mcp() -> None:
    """Run the read-only MCP server over stdio for Claude Code."""
    import os

    from beagle.mcp.server import build_server

    root = os.environ.get("BEAGLE_ROOT")
    workspace = _open(Path(root) if root else None)
    build_server(workspace).run()


def _resolve_target(workspace: Workspace, target: str) -> tuple[Optional[str], int, int]:
    """Map a CLI target to (relpath, start_line, end_line)."""
    if "://" in target:
        entity = workspace.repo.get_entity(target)
        if entity is None:
            return None, 0, 0
        return entity.owner_file, entity.source_range.start_line, entity.source_range.end_line
    if ":" in target:
        path, _, span = target.rpartition(":")
        lo, _, hi = span.partition("-")
        if lo.isdigit():
            return path, int(lo), int(hi) if hi.isdigit() else int(lo)
    full = (workspace.root / target)
    if full.is_file():
        line_count = len(full.read_text(encoding="utf-8", errors="replace").splitlines())
        return target, 1, line_count
    return None, 0, 0


if __name__ == "__main__":
    app()
