"""Extract Frappe DocType schema from ``*.json`` definition files.

Produces a ``doctype`` entity and one ``doctype_field`` entity per field, plus
observations the resolver turns into LINKS_TO / CONTAINS_CHILD / HAS_CONTROLLER
/ TESTS edges. Dynamic Link fields are recorded as observations but never
resolved to a single target, since their target is data-driven.
"""

from __future__ import annotations

import json
import posixpath
from dataclasses import dataclass, field as dc_field

from beagle.extractors.frappe.naming import (
    app_of,
    controller_class_name,
    doctype_id,
    field_id,
)
from beagle.models import Entity, Observation, SourceRange, TextChunk

_LINK_TYPES = {"Link"}
_TABLE_TYPES = {"Table", "Table MultiSelect"}
_DYNAMIC_TYPES = {"Dynamic Link"}


@dataclass
class FrappeExtraction:
    entities: list[Entity] = dc_field(default_factory=list)
    observations: list[Observation] = dc_field(default_factory=list)
    chunks: list[TextChunk] = dc_field(default_factory=list)


def is_doctype_json(text: str) -> bool:
    """Cheap check before full parse: only DocType definition files qualify."""
    return '"doctype"' in text and '"DocType"' in text


def extract_doctype(relpath: str, text: str) -> FrappeExtraction:
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return FrappeExtraction()
    if not isinstance(obj, dict) or obj.get("doctype") != "DocType" or not obj.get("name"):
        return FrappeExtraction()

    out = FrappeExtraction()
    app = app_of(relpath)
    name = obj["name"]
    dt_id = doctype_id(app, name)
    span = SourceRange(1, 0, max(len(text.splitlines()), 1), 0)
    out.entities.append(_doctype_entity(dt_id, app, name, obj, relpath, span))
    _extract_fields(out, dt_id, app, name, obj, relpath, span)
    _add_controller_obs(out, dt_id, relpath, name)
    out.chunks.append(_doctype_chunk(dt_id, app, name, obj, relpath, span))
    return out


def _doctype_entity(dt_id, app, name, obj, relpath, span) -> Entity:
    return Entity(
        id=dt_id,
        kind="doctype",
        name=name,
        qualified_name=f"{app}/{name}",
        owner_file=relpath,
        source_range=span,
        extra={
            "app": app,
            "module": obj.get("module"),
            "istable": obj.get("istable", 0),
            "issingle": obj.get("issingle", 0),
            "autoname": obj.get("autoname"),
        },
    )


def _extract_fields(out, dt_id, app, name, obj, relpath, span) -> None:
    for fld in obj.get("fields", []):
        fieldname = fld.get("fieldname")
        if not fieldname:
            continue
        fid = field_id(app, name, fieldname)
        out.entities.append(_field_entity(fid, dt_id, app, name, fld, relpath, span))
        out.observations.append(_field_observation(dt_id, fid, fieldname, fld, relpath, span))


def _field_entity(fid, dt_id, app, name, fld, relpath, span) -> Entity:
    return Entity(
        id=fid,
        kind="doctype_field",
        name=fld["fieldname"],
        qualified_name=f"{app}/{name}.{fld['fieldname']}",
        owner_file=relpath,
        source_range=span,
        extra={
            "doctype_id": dt_id,
            "fieldtype": fld.get("fieldtype"),
            "label": fld.get("label"),
            "options": fld.get("options"),
        },
    )


def _field_observation(dt_id, fid, fieldname, fld, relpath, span) -> Observation:
    fieldtype = fld.get("fieldtype")
    return Observation(
        kind="doctype_field",
        owner_file=relpath,
        subject=dt_id,
        source_range=span,
        data={
            "field_id": fid,
            "fieldname": fieldname,
            "fieldtype": fieldtype,
            "options": fld.get("options"),
            "is_link": fieldtype in _LINK_TYPES,
            "is_table": fieldtype in _TABLE_TYPES,
            "is_dynamic": fieldtype in _DYNAMIC_TYPES,
        },
    )


def _add_controller_obs(out, dt_id, relpath, name) -> None:
    controller_relpath = relpath[:-5] + ".py" if relpath.endswith(".json") else relpath
    test_relpath = posixpath.join(
        posixpath.dirname(relpath), "test_" + posixpath.basename(controller_relpath)
    )
    out.observations.append(
        Observation(
            kind="frappe_controller",
            owner_file=relpath,
            subject=dt_id,
            source_range=SourceRange(1, 0, 1, 0),
            data={
                "controller_relpath": controller_relpath,
                "test_relpath": test_relpath,
                "class_name": controller_class_name(name),
            },
        )
    )


def _doctype_chunk(dt_id, app, name, obj, relpath, span) -> TextChunk:
    field_names = [f.get("fieldname", "") for f in obj.get("fields", [])]
    labels = [f.get("label", "") for f in obj.get("fields", []) if f.get("label")]
    content = "\n".join([f"DocType {name}", app, obj.get("module") or "", *field_names, *labels])
    return TextChunk(
        owner_file=relpath,
        entity_id=dt_id,
        kind="doctype",
        content=content,
        source_range=span,
    )
