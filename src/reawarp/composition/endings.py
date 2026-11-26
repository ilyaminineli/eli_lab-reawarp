"""M30 ending plans and deterministic EndingDirector.

Ending plans are canonical Score annotations. They describe an explicit final
musical action without rendering fades, deleting events, or introducing a
parallel scheduler. Marker events are silent; a later workflow must explicitly
consume a directive and preserve its provenance.
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Any, Iterable, Mapping

from reawarp.composition.phrases import TRANSFORMATIONS
from reawarp.composition.section_memory import (
    SECTION_MEMORY_METADATA_KEY,
    SectionMemory,
    section_memory_from_score,
)
from reawarp.score.events import MusicalEvent
from reawarp.score.model import Score
from reawarp.score.time import as_fraction

ENDING_SCHEMA_VERSION = 1
ENDING_FORMAT = "eli_lab_reawarp_ending_plan"
ENDING_STRATEGIES = frozenset({
    "delayed_return", "transformed_reprise", "interrupted_cadence",
    "residue", "dissolve", "hard_stop",
})
_ENDING_METADATA_KEY = "m30_ending_plans"
_ENDING_FINGERPRINT_KEY = "m30_ending_plan_fingerprint"
_ENDING_MARKER_KEY = "m30_ending_marker"
_ENDING_VOICE_ID = "ending_director"


def _text(value: Any, name: str) -> str:
    result = str(value).strip()
    if not result:
        raise ValueError(f"{name} cannot be empty")
    return result


def _beat(value: Any, name: str) -> Fraction:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a non-negative rational beat")
    try:
        result = as_fraction(value)
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{name} must be a non-negative rational beat") from exc
    if result < 0:
        raise ValueError(f"{name} must be a non-negative rational beat")
    return result


def _unique_texts(values: Iterable[Any], name: str) -> tuple[str, ...]:
    result = tuple(_text(item, name) for item in values)
    if len(result) != len(set(result)):
        raise ValueError(f"{name} values must be unique")
    return result


def _json_object(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    try:
        return json.loads(json.dumps(
            dict(value), sort_keys=True, ensure_ascii=False, allow_nan=False
        ))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain finite JSON-compatible values") from exc


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class EndingPlan:
    """Versioned, explicit final action with exact Score-beat boundaries."""

    ending_id: str
    strategy: str
    start_beats: Fraction
    end_beats: Fraction
    motif_id: str | None = None
    source_section_id: str | None = None
    transformation_ids: tuple[str, ...] = ()
    expectation_id: str | None = None
    retained_material_ids: tuple[str, ...] = ()
    participating_roles: tuple[str, ...] = ()
    seed_name: str = "m30.ending"
    seed: int = 0
    rationale: str = ""
    parameters: Mapping[str, Any] | None = None
    schema_version: int = ENDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != ENDING_SCHEMA_VERSION:
            raise ValueError(f"unsupported M30 ending schema version: {self.schema_version}")
        object.__setattr__(self, "ending_id", _text(self.ending_id, "ending_id"))
        object.__setattr__(self, "seed_name", _text(self.seed_name, "ending seed_name"))
        strategy = str(self.strategy).strip()
        if strategy not in ENDING_STRATEGIES:
            raise ValueError(
                f"unsupported ending strategy: {strategy}; "
                f"expected one of {', '.join(sorted(ENDING_STRATEGIES))}"
            )
        object.__setattr__(self, "strategy", strategy)

        start = _beat(self.start_beats, "ending start")
        end = _beat(self.end_beats, "ending end")
        if strategy == "hard_stop":
            if end != start:
                raise ValueError("hard_stop must commit at one exact beat")
        elif end <= start:
            raise ValueError("ending end must be greater than ending start")
        object.__setattr__(self, "start_beats", start)
        object.__setattr__(self, "end_beats", end)

        motif_id = None if self.motif_id is None else _text(self.motif_id, "ending motif_id")
        source_section_id = (
            None if self.source_section_id is None
            else _text(self.source_section_id, "ending source_section_id")
        )
        expectation_id = (
            None if self.expectation_id is None
            else _text(self.expectation_id, "ending expectation_id")
        )
        transformations = _unique_texts(self.transformation_ids, "ending transformation")
        unknown = set(transformations) - TRANSFORMATIONS
        if unknown:
            raise ValueError("unsupported ending transformations: " + ", ".join(sorted(unknown)))
        retained = _unique_texts(self.retained_material_ids, "retained material ID")
        roles = _unique_texts(self.participating_roles, "participating role")

        if strategy in {"delayed_return", "transformed_reprise"}:
            if motif_id is None or source_section_id is None:
                raise ValueError(f"{strategy} requires a motif and its source section")
        if strategy == "delayed_return" and transformations:
            raise ValueError("delayed_return cannot declare reprise transformations")
        if strategy == "transformed_reprise" and not transformations:
            raise ValueError("transformed_reprise requires at least one explicit transformation")
        if strategy == "interrupted_cadence" and expectation_id is None:
            raise ValueError("interrupted_cadence requires an unresolved expectation ID")
        if strategy != "interrupted_cadence" and expectation_id is not None:
            raise ValueError("expectation_id is only valid for interrupted_cadence")
        if strategy == "residue" and not retained:
            raise ValueError("residue requires at least one retained material identity")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("ending seed must be a non-negative integer")

        object.__setattr__(self, "motif_id", motif_id)
        object.__setattr__(self, "source_section_id", source_section_id)
        object.__setattr__(self, "expectation_id", expectation_id)
        object.__setattr__(self, "transformation_ids", transformations)
        object.__setattr__(self, "retained_material_ids", retained)
        object.__setattr__(self, "participating_roles", roles)
        object.__setattr__(self, "parameters", _json_object(
            {} if self.parameters is None else self.parameters, "ending parameters"
        ))
        object.__setattr__(self, "rationale", str(self.rationale).strip())

    @property
    def duration_beats(self) -> Fraction:
        return self.end_beats - self.start_beats

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": ENDING_FORMAT,
            "schema_version": self.schema_version,
            "ending_id": self.ending_id,
            "strategy": self.strategy,
            "start_beats": str(self.start_beats),
            "end_beats": str(self.end_beats),
            "motif_id": self.motif_id,
            "source_section_id": self.source_section_id,
            "transformation_ids": list(self.transformation_ids),
            "expectation_id": self.expectation_id,
            "retained_material_ids": list(self.retained_material_ids),
            "participating_roles": list(self.participating_roles),
            "seed_name": self.seed_name,
            "seed": self.seed,
            "rationale": self.rationale,
            "parameters": _json_object(self.parameters or {}, "ending parameters"),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EndingPlan":
        if data.get("format") != ENDING_FORMAT:
            raise ValueError("not a Reawarp ending plan")
        return cls(
            schema_version=data.get("schema_version", 0),
            ending_id=str(data.get("ending_id", "")),
            strategy=str(data.get("strategy", "")),
            start_beats=data.get("start_beats", "0"),
            end_beats=data.get("end_beats", "0"),
            motif_id=data.get("motif_id"),
            source_section_id=data.get("source_section_id"),
            transformation_ids=tuple(data.get("transformation_ids", ())),
            expectation_id=data.get("expectation_id"),
            retained_material_ids=tuple(data.get("retained_material_ids", ())),
            participating_roles=tuple(data.get("participating_roles", ())),
            seed_name=str(data.get("seed_name", "m30.ending")),
            seed=data.get("seed", 0),
            rationale=str(data.get("rationale", "")),
            parameters=data.get("parameters", {}),
        )


class EndingDirector:
    """Create endings from explicit intent and recent SectionMemory.

    The director never chooses a strategy or seed implicitly. It resolves a
    caller-selected ending against open return/expectation records so a return
    is not proposed after its opportunity has already been consumed.
    """

    @staticmethod
    def propose(
        memory: SectionMemory | Mapping[str, Any],
        *,
        ending_id: str,
        strategy: str,
        start_beats: Any,
        end_beats: Any | None = None,
        motif_id: str | None = None,
        transformation_ids: Iterable[str] = (),
        expectation_id: str | None = None,
        retained_material_ids: Iterable[str] = (),
        participating_roles: Iterable[str] = (),
        seed_name: str = "m30.ending",
        seed: int = 0,
        rationale: str = "",
        parameters: Mapping[str, Any] | None = None,
    ) -> EndingPlan:
        """Build a validated plan without adding randomness or editing the Score."""
        recent = (
            memory if isinstance(memory, SectionMemory)
            else SectionMemory.from_dict(memory)
        )
        normalized_strategy = str(strategy).strip()
        source_section_id = None

        if normalized_strategy in {"delayed_return", "transformed_reprise"}:
            if motif_id is None:
                raise ValueError(f"{normalized_strategy} requires a motif_id")
            last_use = recent.last_used_motif(motif_id)
            if last_use is None:
                raise ValueError(f"ending motif is absent from recent section memory: {motif_id}")
            opportunity = next(
                (item for item in recent.return_opportunities if item.motif_id == motif_id),
                None,
            )
            if opportunity is None:
                raise ValueError(f"no open return opportunity remains for motif: {motif_id}")
            transformations = tuple(transformation_ids)
            if normalized_strategy == "delayed_return" and transformations:
                raise ValueError("delayed_return cannot declare reprise transformations")
            allowed = set(opportunity.allowed_transformations)
            if allowed and not set(transformations).issubset(allowed):
                raise ValueError("ending transformation is not permitted by the return opportunity")
            source_section_id = opportunity.source_section_id
        else:
            transformations = tuple(transformation_ids)

        if normalized_strategy == "interrupted_cadence":
            if expectation_id is None:
                raise ValueError("interrupted_cadence requires an expectation_id")
            expectation = next(
                (item for item in recent.unresolved_expectations
                 if item.expectation_id == expectation_id),
                None,
            )
            if expectation is None:
                raise ValueError(
                    f"interrupted cadence requires an unresolved expectation: {expectation_id}"
                )
            source_section_id = next(
                (
                    state.section_id for state in reversed(recent.states)
                    if any(
                        item.expectation_id == expectation_id
                        for item in state.unresolved_expectations
                    )
                ),
                None,
            )

        start = _beat(start_beats, "ending start")
        if end_beats is None:
            if normalized_strategy != "hard_stop":
                raise ValueError("end_beats is required for every non-hard-stop ending")
            end = start
        else:
            end = _beat(end_beats, "ending end")

        return EndingPlan(
            ending_id=ending_id,
            strategy=normalized_strategy,
            start_beats=start,
            end_beats=end,
            motif_id=motif_id,
            source_section_id=source_section_id,
            transformation_ids=transformations,
            expectation_id=expectation_id,
            retained_material_ids=tuple(retained_material_ids),
            participating_roles=tuple(participating_roles),
            seed_name=seed_name,
            seed=seed,
            rationale=rationale,
            parameters={} if parameters is None else parameters,
        )


def _ending_marker_event_id(ending_id: str, phase: str) -> str:
    digest = hashlib.sha256(
        f"reawarp:m30:ending:{ending_id}:{phase}".encode("utf-8")
    ).hexdigest()[:24]
    return f"m30-ending-{digest}"


def ending_marker_events(plan: EndingPlan) -> tuple[MusicalEvent, ...]:
    """Compile one ending into silent, deterministic Score marker events."""
    phases = ("commit",) if plan.strategy == "hard_stop" else ("start", "complete")
    result: list[MusicalEvent] = []
    for phase in phases:
        beat = plan.start_beats if phase != "complete" else plan.end_beats
        payload = {
            "format": ENDING_FORMAT,
            "schema_version": ENDING_SCHEMA_VERSION,
            "ending_id": plan.ending_id,
            "strategy": plan.strategy,
            "phase": phase,
            "at_beats": str(beat),
            "start_beats": str(plan.start_beats),
            "end_beats": str(plan.end_beats),
            "atomic_directive": phase in {"start", "commit"},
            "motif_id": plan.motif_id,
            "source_section_id": plan.source_section_id,
            "transformation_ids": list(plan.transformation_ids),
            "expectation_id": plan.expectation_id,
            "retained_material_ids": list(plan.retained_material_ids),
            "participating_roles": list(plan.participating_roles),
            "seed_name": plan.seed_name,
            "seed": plan.seed,
            "rationale": plan.rationale,
            "parameters": _json_object(plan.parameters or {}, "ending parameters"),
        }
        result.append(MusicalEvent(
            event_id=_ending_marker_event_id(plan.ending_id, phase),
            voice_id=_ENDING_VOICE_ID,
            onset_beats=beat,
            duration_beats=Fraction(0),
            kind="marker",
            velocity=0.0,
            articulation="marker",
            parameters={_ENDING_MARKER_KEY: payload},
            tags=("m30_ending", f"m30_ending:{plan.strategy}", f"m30_ending_phase:{phase}"),
        ))
    return tuple(result)


def _validate_ending_memory(score: Score, plans: Iterable[EndingPlan]) -> None:
    if SECTION_MEMORY_METADATA_KEY not in score.metadata:
        return
    memory = section_memory_from_score(score)
    opportunities = {item.motif_id: item for item in memory.return_opportunities}
    expectations = {item.expectation_id for item in memory.unresolved_expectations}
    for plan in plans:
        if plan.strategy in {"delayed_return", "transformed_reprise"}:
            opportunity = opportunities.get(plan.motif_id or "")
            if opportunity is None:
                raise ValueError(
                    f"ending references a closed or unknown motif return: {plan.motif_id}"
                )
            if opportunity.source_section_id != plan.source_section_id:
                raise ValueError("ending return source section does not match SectionMemory")
            allowed = set(opportunity.allowed_transformations)
            if allowed and not set(plan.transformation_ids).issubset(allowed):
                raise ValueError("ending transformation is not permitted by SectionMemory")
        if plan.strategy == "interrupted_cadence" and plan.expectation_id not in expectations:
            raise ValueError(
                "interrupted cadence references an expectation that is no longer unresolved"
            )


def compile_ending_plans(
    score: Score,
    plans: Iterable[EndingPlan],
    *,
    replace_existing: bool = True,
) -> Score:
    """Attach ending plans and silent markers to a canonical Score.

    Recompiling the same plan is idempotent. Replacing a plan owns only its
    generated markers and leaves all musical events, M20/M28 plans, transition
    markers, automation and SectionMemory intact.
    """
    if not isinstance(score, Score):
        raise TypeError("score must be a reawarp Score")
    incoming = tuple(
        item if isinstance(item, EndingPlan) else EndingPlan.from_dict(item)
        for item in plans
    )
    if not incoming:
        return score
    incoming_ids = [item.ending_id for item in incoming]
    if len(incoming_ids) != len(set(incoming_ids)):
        raise ValueError("ending plan IDs must be unique within one compilation batch")

    records = score.metadata.get(_ENDING_METADATA_KEY, [])
    if not isinstance(records, list):
        raise ValueError("Score m30_ending_plans metadata must be an array")
    existing = tuple(EndingPlan.from_dict(item) for item in records)
    existing_by_id = {item.ending_id: item for item in existing}
    collision = set(incoming_ids) & set(existing_by_id)
    if collision and not replace_existing:
        raise ValueError("ending plan already exists: " + ", ".join(sorted(collision)))
    _validate_ending_memory(score, incoming)

    merged_by_id = dict(existing_by_id)
    merged_by_id.update({item.ending_id: item for item in incoming})
    merged = tuple(sorted(
        merged_by_id.values(),
        key=lambda item: (item.start_beats, item.end_beats, item.ending_id),
    ))
    old_marker_ids = {
        event.event_id
        for plan in existing
        for event in ending_marker_events(plan)
    }
    source_events = [event for event in score.events if event.event_id not in old_marker_ids]
    source_ids = {event.event_id for event in source_events}
    generated: list[MusicalEvent] = []
    for plan in merged:
        for event in ending_marker_events(plan):
            if event.event_id in source_ids:
                raise ValueError(
                    f"ending marker ID collides with existing Score event: {event.event_id}"
                )
            generated.append(event)

    metadata = copy.deepcopy(score.metadata)
    metadata[_ENDING_METADATA_KEY] = [item.to_dict() for item in merged]
    metadata[_ENDING_FINGERPRINT_KEY] = _fingerprint(metadata[_ENDING_METADATA_KEY])
    return replace(score, events=tuple((*source_events, *generated)), metadata=metadata)


def ending_plans_from_score(score: Score) -> tuple[EndingPlan, ...]:
    """Read ending provenance and verify its fingerprint and canonical markers."""
    records = score.metadata.get(_ENDING_METADATA_KEY, [])
    if not isinstance(records, list):
        raise ValueError("Score m30_ending_plans metadata must be an array")
    plans = tuple(EndingPlan.from_dict(item) for item in records)
    ids = [item.ending_id for item in plans]
    if len(ids) != len(set(ids)):
        raise ValueError("Score contains duplicate M30 ending plan IDs")
    if plans:
        expected = score.metadata.get(_ENDING_FINGERPRINT_KEY)
        actual = _fingerprint([item.to_dict() for item in plans])
        if expected != actual:
            raise ValueError("M30 ending plan fingerprint does not match its contents")
    by_id = {event.event_id: event for event in score.events}
    for plan in plans:
        for expected_marker in ending_marker_events(plan):
            actual_marker = by_id.get(expected_marker.event_id)
            if actual_marker != expected_marker:
                raise ValueError(
                    "M30 ending marker is missing or does not match its plan: "
                    f"{plan.ending_id}/{expected_marker.tags[-1]}"
                )
    return plans


__all__ = [
    "ENDING_FORMAT", "ENDING_SCHEMA_VERSION", "ENDING_STRATEGIES",
    "EndingDirector", "EndingPlan", "compile_ending_plans",
    "ending_marker_events", "ending_plans_from_score",
]
