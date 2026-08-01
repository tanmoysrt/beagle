from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from ..storage.dao import IndexStore
from .symbols import ParsedFile

TS_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".vue")


@dataclass(frozen=True)
class ResolvedEdge:
    src_symbol_id: int
    dst_symbol_id: int | None
    dst_name: str
    kind: str
    resolution: str
    line: int


class GraphBuilder:
    """Turns call sites into graph edges.

    Resolution is deliberately cheap: same file first, then files this one
    imports, then a unique repo-wide name. Anything ambiguous stays a text edge,
    which still tells us something about blast radius.
    """

    def __init__(self, store: IndexStore):
        self.store = store

    def edges_for(self, parsed: ParsedFile, symbol_ids: dict[str, int]) -> list[ResolvedEdge]:
        references = [ref for ref in parsed.references if ref.source_symbol is not None]
        if not references:
            return []

        candidates = self.candidates_by_name({ref.name for ref in references})
        imported = self.imported_paths(parsed)
        local_names = {symbol.name: symbol for symbol in parsed.symbols}

        edges = []
        for reference in references:
            source_key = symbol_key(parsed.path, reference.source_symbol)
            src_id = symbol_ids.get(source_key)
            if src_id is None:
                continue
            target, resolution = self.pick_target(
                reference.name, parsed.path, candidates, imported, local_names, symbol_ids
            )
            edges.append(
                ResolvedEdge(src_id, target, reference.name, "call", resolution, reference.line)
            )
        return edges

    def pick_target(
        self,
        name: str,
        path: str,
        candidates: dict[str, list[dict]],
        imported: set[str],
        local_names: dict,
        symbol_ids: dict[str, int],
    ) -> tuple[int | None, str]:
        local = local_names.get(name)
        if local is not None:
            local_id = symbol_ids.get(symbol_key(path, local))
            if local_id is not None:
                return local_id, "local"

        matches = candidates.get(name, [])
        from_imports = [match for match in matches if match["path"] in imported]
        if len(from_imports) == 1:
            return from_imports[0]["id"], "import"
        if len(matches) == 1:
            return matches[0]["id"], "global"
        return None, "text"

    def repair_unresolved(self) -> int:
        """Second pass for callees that had not been indexed yet when their caller was.

        Only unambiguous repo-wide names are linked; the rest stay text edges.
        """
        pending = self.store.unresolved_edges()
        if not pending:
            return 0
        candidates = self.candidates_by_name({name for _, name in pending})
        updates = []
        for edge_id, name in pending:
            matches = candidates.get(name, [])
            if len(matches) == 1:
                updates.append((matches[0]["id"], "global", edge_id))
        self.store.resolve_edges(updates)
        return len(updates)

    def candidates_by_name(self, names: set[str]) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = {}
        for row in self.store.symbols_by_name(sorted(names)):
            grouped.setdefault(row["name"], []).append(row)
        return grouped

    def imported_paths(self, parsed: ParsedFile) -> set[str]:
        known = self.store.known_paths()
        resolved = set()
        for record in parsed.imports:
            target = resolve_module(parsed.path, record.module, known)
            if target:
                resolved.add(target)
        return resolved


def resolve_module(importer: str, module: str, known_paths: set[str]) -> str | None:
    """Best-effort module path resolution, good enough to disambiguate names."""
    for candidate in module_candidates(importer, module):
        if candidate in known_paths:
            return candidate
    return None


def module_candidates(importer: str, module: str) -> list[str]:
    directory = PurePosixPath(importer).parent
    candidates: list[str] = []

    if module.startswith("."):
        if module.startswith("./") or module.startswith("../"):
            base = (directory / module).as_posix()
            base = normalize(base)
            candidates.extend(with_extensions(base))
        else:  # python relative import, e.g. .storage.db
            trimmed = module.lstrip(".")
            base = (directory / trimmed.replace(".", "/")).as_posix()
            candidates.extend([f"{base}.py", f"{base}/__init__.py"])
        return candidates

    if module.startswith("@/") or module.startswith("~/"):
        stem = module[2:]
        candidates.extend(with_extensions(f"src/{stem}"))
        candidates.extend(with_extensions(stem))
        return candidates

    dotted = module.replace(".", "/")
    candidates.extend([f"{dotted}.py", f"{dotted}/__init__.py"])
    candidates.extend(with_extensions(module))
    # go imports carry a repo prefix, so try the tail of the path too
    tail = module.rsplit("/", 1)[-1]
    candidates.append(f"{tail}.go")
    return candidates


def with_extensions(base: str) -> list[str]:
    paths = [base] if PurePosixPath(base).suffix else []
    paths.extend(f"{base}{extension}" for extension in TS_EXTENSIONS)
    paths.extend(f"{base}/index{extension}" for extension in TS_EXTENSIONS)
    return paths


def normalize(path: str) -> str:
    parts: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == ".." and parts and parts[-1] != "..":
            parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


def symbol_key(path: str, symbol) -> str:
    return f"{path}::{symbol.qualified_name}@{symbol.start_byte}"
