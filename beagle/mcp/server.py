"""Read-only MCP server exposing beagle's retrieval operations.

Thin transport layer: each tool forwards to ``BeagleTools``, which is the same
service the CLI uses. No SQL, parsing, or graph logic lives here. The server is
read-only — it never indexes or mutates the graph, and it exposes no arbitrary
SQL (design/06).
"""

from __future__ import annotations

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from beagle.mcp.tools import BeagleTools
from beagle.workspace import Workspace


def build_server(workspace: Workspace) -> FastMCP:
    tools = BeagleTools(workspace)
    mcp = FastMCP(
        "beagle",
        instructions=(
            "Local code-discovery for Python/Frappe repos. Start with `context` "
            "for conceptual questions, `resolve`+`relations` for exact symbols. "
            "Read only the returned source ranges. Treat low-confidence edges as "
            "hypotheses and fall back to Grep/Glob/Read when coverage is missing."
        ),
    )

    mcp.add_tool(tools.index_status, description="Index counts and the last run.")
    mcp.add_tool(tools.search, description="Lexical (FTS) search over indexed source.")
    mcp.add_tool(tools.resolve, description="Resolve a name/qualified-name/id to entities.")
    mcp.add_tool(tools.show, description="Show one entity's details and source range.")
    mcp.add_tool(tools.relations, description="Incoming and outgoing edges for an entity.")
    mcp.add_tool(tools.callers, description="Callers of an entity.")
    mcp.add_tool(tools.callees, description="Callees of an entity.")
    mcp.add_tool(tools.find_path, description="Shortest call path between two entities.")
    mcp.add_tool(tools.uses_doctype, description="Code that reads/writes/creates/deletes a DocType.")
    mcp.add_tool(tools.reads_field, description="Code reading a field's DocType (DocType-granular).")
    mcp.add_tool(tools.writes_field, description="Code writing a field's DocType (DocType-granular).")
    mcp.add_tool(tools.tests, description="Tests covering an entity.")
    mcp.add_tool(tools.impact, description="Entities that transitively depend on an entity.")
    mcp.add_tool(tools.context, description="Compile an intent-shaped, budget-bounded context bundle.")
    mcp.add_tool(tools.investigate, description="Turn an issue into an evidence-backed map of relevant code.")
    mcp.add_tool(tools.explain_function, description="Explain a function; optional deterministic Mermaid flow.")
    mcp.add_tool(tools.event_handlers, description="Resolve controller/doc_events/runtime handlers for a DocType event.")
    mcp.add_tool(tools.lifecycle, description="Standard document lifecycle events and handlers for a DocType.")
    mcp.add_tool(tools.trace, description="Trace operations, lifecycle events, and handlers from a function.")
    mcp.add_tool(tools.read_source, description="Exact source for an entity.")
    return mcp


def main() -> None:
    root = Path(os.environ.get("BEAGLE_ROOT", "."))
    workspace = Workspace.locate(root)
    build_server(workspace).run()


if __name__ == "__main__":
    main()
