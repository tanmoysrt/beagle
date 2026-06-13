"""Synthesize Frappe runtime entities from extracted Python facts.

Runs right after Python extraction, on the same file, so the entities it adds
(endpoints, background jobs) are owned by that file and recreated cleanly on
reindex. It only adds entities and observations; the resolver turns the
observations into EXPOSES_ENDPOINT / ENQUEUES / INVOKES edges.
"""

from __future__ import annotations

from beagle.extractors.frappe.naming import endpoint_id, job_id
from beagle.models import Entity, Observation, SourceRange

_ENQUEUE_FUNCS = ("frappe.enqueue", "frappe.enqueue_doc")


def augment_runtime(relpath: str, entities: list[Entity], observations: list[Observation]) -> None:
    """Append endpoint and background-job entities/observations in place."""
    _add_endpoints(relpath, entities, observations)
    _add_jobs(relpath, entities, observations)


def _add_endpoints(relpath, entities, observations) -> None:
    new_entities: list[Entity] = []
    for entity in entities:
        if entity.kind not in ("function", "method") or not _is_whitelisted(entity):
            continue
        eid = endpoint_id(entity.qualified_name)
        new_entities.append(
            Entity(
                id=eid,
                kind="endpoint",
                name=entity.name,
                qualified_name=entity.qualified_name,
                owner_file=relpath,
                source_range=entity.source_range,
                extra={"handler": entity.id, "decorators": entity.extra.get("decorators", [])},
            )
        )
        observations.append(
            Observation(
                kind="frappe_endpoint",
                owner_file=relpath,
                subject=entity.id,
                source_range=entity.source_range,
                data={"endpoint_id": eid},
            )
        )
    entities.extend(new_entities)


def _is_whitelisted(entity: Entity) -> bool:
    return any("whitelist" in d for d in entity.extra.get("decorators", []))


def _add_jobs(relpath, entities, observations) -> None:
    jobs: dict[str, Entity] = {}
    job_obs: list[Observation] = []
    for obs in list(observations):
        if obs.kind != "call" or obs.data.get("dotted") not in _ENQUEUE_FUNCS:
            continue
        target = obs.data.get("first_arg")
        if not target or "." not in target:
            continue
        jid = job_id(target)
        jobs.setdefault(jid, _job_entity(jid, target, relpath))
        job_obs.append(
            Observation(
                kind="frappe_enqueue",
                owner_file=relpath,
                subject=obs.subject,
                source_range=obs.source_range,
                data={"job_id": jid, "target": target},
            )
        )
    entities.extend(jobs.values())
    observations.extend(job_obs)


def _job_entity(jid: str, target: str, relpath: str) -> Entity:
    return Entity(
        id=jid,
        kind="background_job",
        name=target.rsplit(".", 1)[-1],
        qualified_name=target,
        owner_file=relpath,
        source_range=SourceRange(1, 0, 1, 0),
        extra={"target": target},
    )
