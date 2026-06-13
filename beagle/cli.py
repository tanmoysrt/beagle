"""Command-line interface.

Thin presentation layer over the application services in ``Workspace`` and the
search/retrieval modules. It parses arguments, calls a service, and renders the
result. No parsing, resolution, or SQL lives here.
"""

from __future__ import annotations

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
    """List code reading the DocType that owns a field (doctype-granular)."""
    _field_access(field, ("READS_DOCTYPE",))


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


def _field_access(ref: str, relationships: tuple[str, ...]) -> None:
    workspace = _open()
    field = _resolve_field(workspace, ref)
    if field is None:
        typer.echo(f"no field matches: {ref}")
        workspace.close()
        return
    doctype_id = field.extra.get("doctype_id")
    typer.echo(f"# field-level reads not tracked; showing DocType-level access to {doctype_id}")
    for e in workspace.repo.edges_to(doctype_id, relationships):
        typer.echo(f"  {e.relationship}: {_entity_label(workspace, e.source_id)}  "
                   f"{e.owner_file}:{e.source_range.start_line}")
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
                               help="locate | understand | change | debug | test"),
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
) -> None:
    """Turn an issue into an evidence-backed map of the relevant code."""
    from beagle.investigate import Investigator

    text = file.read_text(encoding="utf-8") if file else query
    if not text:
        typer.echo("provide issue text or --file")
        raise typer.Exit(code=1)
    workspace = _open()
    inv = Investigator(workspace.repo, GraphService(workspace.repo),
                       SearchEngine(workspace.db), workspace.read_range)
    report = inv.investigate(text, max_tokens=max_tokens)
    for note in report.notes:
        typer.echo(f"# note: {note}")
    for section in report.sections:
        typer.echo(f"\n## {section.title}")
        for line in section.lines or ["(none found)"]:
            typer.echo(f"  {line}")
    workspace.close()


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
