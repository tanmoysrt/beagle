"""Per-file extraction dispatch.

Given a discovered file and its text, produce the facts beagle stores:
entities, raw observations, and searchable chunks. Resolution turns
observations into edges in a later, cross-file pass.

Stage 1 only chunks text. Python and Frappe extractors plug in here as later
stages land, replacing the baseline chunker with entity-aligned output.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from beagle.extractors.chunker import chunk_text
from beagle.extractors.frappe import extract_doctype, is_doctype_json
from beagle.extractors.frappe.hooks import extract_hooks, is_hooks_file
from beagle.extractors.frappe.runtime import augment_runtime
from beagle.extractors.python import extract_python
from beagle.models import DiscoveredFile, Entity, Observation, TextChunk


@dataclass
class ExtractionResult:
    entities: list[Entity] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    chunks: list[TextChunk] = field(default_factory=list)


def extract_file(discovered: DiscoveredFile, text: str) -> ExtractionResult:
    result = ExtractionResult()
    if discovered.language == "python":
        _extract_python(discovered, text, result)
    elif discovered.language == "json" and is_doctype_json(text):
        _extract_doctype(discovered, text, result)
    if not result.chunks:
        result.chunks = chunk_text(discovered.relpath, text)
    return result


def _extract_doctype(discovered: DiscoveredFile, text: str, result: ExtractionResult) -> None:
    extraction = extract_doctype(discovered.relpath, text)
    result.entities = extraction.entities
    result.observations = extraction.observations
    result.chunks = extraction.chunks


def _extract_python(discovered: DiscoveredFile, text: str, result: ExtractionResult) -> None:
    extraction = extract_python(discovered.relpath, text, discovered.module)
    result.entities = extraction.entities
    result.observations = extraction.observations
    augment_runtime(discovered.relpath, result.entities, result.observations)
    if is_hooks_file(discovered.relpath):
        result.observations += extract_hooks(discovered.relpath, text, discovered.module)
    # Symbol chunks sharpen name search; window chunks keep full-text coverage
    # of bodies and module-level code that symbol chunks omit.
    result.chunks = extraction.chunks + chunk_text(discovered.relpath, text)
