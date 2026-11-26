"""Bounded, serializable section memory for M30 composition planning."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Any, Iterable, Mapping, Sequence, TYPE_CHECKING

from reawarp.composition.phrases import MotifTransformation, TRANSFORMATIONS

if TYPE_CHECKING:
    from reawarp.score.model import Score

SECTION_MEMORY_SCHEMA_VERSION = 1
SECTION_MEMORY_FORMAT = "eli_lab_reawarp_section_memory"
SECTION_MEMORY_METADATA_KEY = "m30_section_memory"
SECTION_MEMORY_FINGERPRINT_KEY = "m30_section_memory_fingerprint"
DEFAULT_SECTION_MEMORY_CAPACITY = 12
MAX_SECTION_MEMORY_CAPACITY = 64

EXPECTATION_KINDS = frozenset({
    "motif_return", "resolution", "cadence", "handoff", "contrast", "other",
})


def _text(value: Any, field: str) -> str:
    result = str(value).strip()
    if not result:
        raise ValueError(f"{field} cannot be empty")
    return result


def _beat(value: Any, field: str) -> Fraction:
    try:
        if isinstance(value, bool):
            raise TypeError("boolean is not a beat value")
        result = value if isinstance(value, Fraction) else Fraction(str(value))
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{field} must be a valid rational beat value") from exc
    if result < 0:
        raise ValueError(f"{field} must be non-negative")
    return result


def _unit(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite value from zero to one")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a finite value from zero to one") from exc
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        raise ValueError(f"{field} must be a finite value from zero to one")
    return result


def _unique_texts(values: Iterable[Any], field: str) -> tuple[str, ...]:
    result = tuple(_text(item, field) for item in values)
    if len(result) != len(set(result)):
        raise ValueError(f"{field} values must be unique")
    return result


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class TrajectorySummary:
    """Compact, normalized summary of one section's energy or density curve."""

    sample_count: int
    start: float
    mean: float
    end: float
    minimum: float
    maximum: float
    standard_deviation: float = 0.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.sample_count, bool)
            or not isinstance(self.sample_count, int)
            or self.sample_count < 1
        ):
            raise ValueError("trajectory sample_count must be a positive integer")
        for name in ("start", "mean", "end", "minimum", "maximum"):
            object.__setattr__(self, name, _unit(getattr(self, name), f"trajectory {name}"))
        try:
            deviation = float(self.standard_deviation)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                "trajectory standard_deviation must be finite and non-negative"
            ) from exc
        if not math.isfinite(deviation) or deviation < 0.0 or deviation > 1.0:
            raise ValueError("trajectory standard_deviation must be finite and in [0, 1]")
        if self.minimum > self.maximum:
            raise ValueError("trajectory minimum cannot exceed maximum")
        if not (
            self.minimum <= self.start <= self.maximum
            and self.minimum <= self.mean <= self.maximum
            and self.minimum <= self.end <= self.maximum
        ):
            raise ValueError("trajectory samples and mean must lie within min/max")
        object.__setattr__(self, "standard_deviation", deviation)

    @classmethod
    def from_values(cls, values: Sequence[float]) -> "TrajectorySummary":
        """Summarize a finite sequence without retaining an unbounded raw curve."""
        if not values:
            raise ValueError("trajectory values cannot be empty")
        samples = tuple(_unit(value, "trajectory sample") for value in values)
        mean = math.fsum(samples) / len(samples)
        variance = math.fsum((value - mean) ** 2 for value in samples) / len(samples)
        return cls(
            sample_count=len(samples),
            start=samples[0],
            mean=mean,
            end=samples[-1],
            minimum=min(samples),
            maximum=max(samples),
            standard_deviation=math.sqrt(variance),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_count": self.sample_count,
            "start": self.start,
            "mean": self.mean,
            "end": self.end,
            "minimum": self.minimum,
            "maximum": self.maximum,
            "standard_deviation": self.standard_deviation,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TrajectorySummary":
        return cls(
            sample_count=data.get("sample_count", 0),
            start=data.get("start", 0.0),
            mean=data.get("mean", 0.0),
            end=data.get("end", 0.0),
            minimum=data.get("minimum", 0.0),
            maximum=data.get("maximum", 0.0),
            standard_deviation=data.get("standard_deviation", 0.0),
        )


@dataclass(frozen=True, slots=True)
class MemoryExpectation:
    """A named musical expectation opened by a section and not yet resolved."""

    expectation_id: str
    kind: str
    subject_id: str
    opened_at_beats: Fraction
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "expectation_id", _text(self.expectation_id, "expectation_id"))
        kind = _text(self.kind, "expectation kind")
        if kind not in EXPECTATION_KINDS:
            raise ValueError(f"unsupported expectation kind: {kind}")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "subject_id", _text(self.subject_id, "expectation subject_id"))
        object.__setattr__(self, "opened_at_beats", _beat(self.opened_at_beats, "expectation beat"))
        object.__setattr__(self, "description", str(self.description).strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "expectation_id": self.expectation_id,
            "kind": self.kind,
            "subject_id": self.subject_id,
            "opened_at_beats": str(self.opened_at_beats),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MemoryExpectation":
        return cls(
            expectation_id=str(data.get("expectation_id", "")),
            kind=str(data.get("kind", "")),
            subject_id=str(data.get("subject_id", "")),
            opened_at_beats=data.get("opened_at_beats", "0"),
            description=str(data.get("description", "")),
        )


@dataclass(frozen=True, slots=True)
class ReturnOpportunity:
    """An explicit invitation to recall a motif from an earlier section."""

    motif_id: str
    source_section_id: str
    reason: str = ""
    source_version: int | None = None
    transformation_ids: tuple[str, ...] = ()
    allowed_transformations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "motif_id", _text(self.motif_id, "return motif_id"))
        object.__setattr__(
            self, "source_section_id", _text(self.source_section_id, "return source_section_id")
        )
        object.__setattr__(self, "reason", str(self.reason).strip())
        if self.source_version is not None and (
            isinstance(self.source_version, bool)
            or not isinstance(self.source_version, int)
            or self.source_version < 1
        ):
            raise ValueError("return source_version must be a positive integer or None")
        object.__setattr__(
            self, "transformation_ids",
            _unique_texts(self.transformation_ids, "return transformation_id"),
        )
        allowed = _unique_texts(self.allowed_transformations, "allowed transformation")
        unknown = set(allowed) - TRANSFORMATIONS
        if unknown:
            raise ValueError("unsupported return transformations: " + ", ".join(sorted(unknown)))
        object.__setattr__(self, "allowed_transformations", allowed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "motif_id": self.motif_id,
            "source_section_id": self.source_section_id,
            "reason": self.reason,
            "source_version": self.source_version,
            "transformation_ids": list(self.transformation_ids),
            "allowed_transformations": list(self.allowed_transformations),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReturnOpportunity":
        return cls(
            motif_id=str(data.get("motif_id", "")),
            source_section_id=str(data.get("source_section_id", "")),
            reason=str(data.get("reason", "")),
            source_version=data.get("source_version"),
            transformation_ids=tuple(data.get("transformation_ids", ())),
            allowed_transformations=tuple(data.get("allowed_transformations", ())),
        )


@dataclass(frozen=True, slots=True)
class SectionState:
    """Immutable snapshot of a section's recent identity and musical trajectory."""

    section_id: str
    start_beats: Fraction
    end_beats: Fraction
    revision: int = 1
    phrase_ids: tuple[str, ...] = ()
    motif_ids: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    transformations: tuple[MotifTransformation, ...] = ()
    energy: TrajectorySummary | None = None
    density: TrajectorySummary | None = None
    unresolved_expectations: tuple[MemoryExpectation, ...] = ()
    resolved_expectation_ids: tuple[str, ...] = ()
    return_opportunities: tuple[ReturnOpportunity, ...] = ()
    rationale: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "section_id", _text(self.section_id, "section_id"))
        start = _beat(self.start_beats, "section start")
        end = _beat(self.end_beats, "section end")
        if end <= start:
            raise ValueError("section end must be greater than section start")
        object.__setattr__(self, "start_beats", start)
        object.__setattr__(self, "end_beats", end)
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 1
        ):
            raise ValueError("section revision must be a positive integer")
        for field_name in ("phrase_ids", "motif_ids", "roles"):
            object.__setattr__(
                self, field_name, _unique_texts(getattr(self, field_name), field_name)
            )
        transformations = tuple(
            item if isinstance(item, MotifTransformation)
            else MotifTransformation.from_dict(item)
            for item in self.transformations
        )
        if any(item.motif_id not in self.motif_ids for item in transformations):
            raise ValueError("section transformation history must reference a section motif")
        object.__setattr__(self, "transformations", transformations)
        for field_name in ("energy", "density"):
            value = getattr(self, field_name)
            if value is not None and not isinstance(value, TrajectorySummary):
                value = TrajectorySummary.from_dict(value)
            object.__setattr__(self, field_name, value)
        expectations = tuple(
            item if isinstance(item, MemoryExpectation) else MemoryExpectation.from_dict(item)
            for item in self.unresolved_expectations
        )
        expectation_ids = [item.expectation_id for item in expectations]
        if len(expectation_ids) != len(set(expectation_ids)):
            raise ValueError("section expectation IDs must be unique")
        if any(
            item.opened_at_beats < start or item.opened_at_beats > end
            for item in expectations
        ):
            raise ValueError("an expectation must open within its section")
        object.__setattr__(self, "unresolved_expectations", expectations)
        resolved = _unique_texts(self.resolved_expectation_ids, "resolved expectation_id")
        if set(resolved) & set(expectation_ids):
            raise ValueError("an expectation cannot be opened and resolved in the same section")
        object.__setattr__(self, "resolved_expectation_ids", resolved)
        opportunities = tuple(
            item if isinstance(item, ReturnOpportunity) else ReturnOpportunity.from_dict(item)
            for item in self.return_opportunities
        )
        if any(item.source_section_id != self.section_id for item in opportunities):
            raise ValueError("return opportunities must identify their owning source section")
        opportunity_ids = [item.motif_id for item in opportunities]
        if len(opportunity_ids) != len(set(opportunity_ids)):
            raise ValueError("a section may declare only one return opportunity per motif")
        object.__setattr__(self, "return_opportunities", opportunities)
        object.__setattr__(self, "rationale", str(self.rationale).strip())

    @property
    def duration_beats(self) -> Fraction:
        return self.end_beats - self.start_beats

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "start_beats": str(self.start_beats),
            "end_beats": str(self.end_beats),
            "revision": self.revision,
            "phrase_ids": list(self.phrase_ids),
            "motif_ids": list(self.motif_ids),
            "roles": list(self.roles),
            "transformations": [item.to_dict() for item in self.transformations],
            "energy": None if self.energy is None else self.energy.to_dict(),
            "density": None if self.density is None else self.density.to_dict(),
            "unresolved_expectations": [
                item.to_dict() for item in self.unresolved_expectations
            ],
            "resolved_expectation_ids": list(self.resolved_expectation_ids),
            "return_opportunities": [
                item.to_dict() for item in self.return_opportunities
            ],
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SectionState":
        return cls(
            section_id=str(data.get("section_id", "")),
            start_beats=data.get("start_beats", "0"),
            end_beats=data.get("end_beats", "0"),
            revision=data.get("revision", 1),
            phrase_ids=tuple(data.get("phrase_ids", ())),
            motif_ids=tuple(data.get("motif_ids", ())),
            roles=tuple(data.get("roles", ())),
            transformations=tuple(
                MotifTransformation.from_dict(item)
                for item in data.get("transformations", ())
            ),
            energy=(
                None if data.get("energy") is None
                else TrajectorySummary.from_dict(data["energy"])
            ),
            density=(
                None if data.get("density") is None
                else TrajectorySummary.from_dict(data["density"])
            ),
            unresolved_expectations=tuple(
                MemoryExpectation.from_dict(item)
                for item in data.get("unresolved_expectations", ())
            ),
            resolved_expectation_ids=tuple(data.get("resolved_expectation_ids", ())),
            return_opportunities=tuple(
                ReturnOpportunity.from_dict(item)
                for item in data.get("return_opportunities", ())
            ),
            rationale=str(data.get("rationale", "")),
        )


@dataclass(frozen=True, slots=True)
class SectionMemory:
    """A bounded, immutable window over recent sections—not a second timeline."""

    states: tuple[SectionState, ...] = ()
    capacity: int = DEFAULT_SECTION_MEMORY_CAPACITY
    schema_version: int = SECTION_MEMORY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SECTION_MEMORY_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported section memory schema version: {self.schema_version}"
            )
        if (
            isinstance(self.capacity, bool)
            or not isinstance(self.capacity, int)
            or not 1 <= self.capacity <= MAX_SECTION_MEMORY_CAPACITY
        ):
            raise ValueError(
                f"section memory capacity must be between 1 and {MAX_SECTION_MEMORY_CAPACITY}"
            )
        states = tuple(
            item if isinstance(item, SectionState) else SectionState.from_dict(item)
            for item in self.states
        )
        if len(states) > self.capacity:
            raise ValueError("section memory contains more states than its capacity")
        ids = [item.section_id for item in states]
        if len(ids) != len(set(ids)):
            raise ValueError("section memory section IDs must be unique")
        previous: SectionState | None = None
        expectation_ids: set[str] = set()
        for state in states:
            if previous is not None and state.start_beats < previous.end_beats:
                raise ValueError("section memory states must be chronological and non-overlapping")
            opened = {item.expectation_id for item in state.unresolved_expectations}
            if expectation_ids & opened:
                raise ValueError("expectation IDs must be unique within the memory window")
            expectation_ids.update(opened)
            previous = state
        object.__setattr__(self, "states", states)

    def append(self, state: SectionState) -> "SectionMemory":
        """Append one state, revise only the newest state, and evict oldest overflow.

        Re-recording an identical state is idempotent. Revising an existing
        section is allowed only for the newest section, with unchanged beat
        bounds and a strictly increasing revision number.
        """
        if not isinstance(state, SectionState):
            state = SectionState.from_dict(state)
        existing_index = next(
            (index for index, item in enumerate(self.states)
             if item.section_id == state.section_id),
            None,
        )
        if existing_index is not None:
            existing = self.states[existing_index]
            if existing == state:
                return self
            if existing_index != len(self.states) - 1:
                raise ValueError("only the newest section may be revised in memory")
            if (
                state.start_beats != existing.start_beats
                or state.end_beats != existing.end_beats
            ):
                raise ValueError("a section revision cannot change its beat boundaries")
            if state.revision <= existing.revision:
                raise ValueError("a section revision must have a higher revision number")
            return replace(self, states=self.states[:-1] + (state,))
        if self.states and state.start_beats < self.states[-1].end_beats:
            raise ValueError("new section must follow the most recent section")
        return replace(self, states=(self.states + (state,))[-self.capacity:])

    record = append

    @property
    def latest(self) -> SectionState | None:
        return self.states[-1] if self.states else None

    def previous_section(self, section_id: str | None = None) -> SectionState | None:
        """Return the latest state, or the state immediately before a given section."""
        if not self.states:
            return None
        if section_id is None:
            return self.states[-1]
        target = _text(section_id, "section_id")
        index = next(
            (position for position, item in enumerate(self.states)
             if item.section_id == target),
            None,
        )
        if index is None:
            raise KeyError(f"unknown section in memory: {target}")
        return self.states[index - 1] if index > 0 else None

    def last_used_motif(self, motif_id: str) -> SectionState | None:
        target = _text(motif_id, "motif_id")
        return next(
            (state for state in reversed(self.states) if target in state.motif_ids),
            None,
        )

    def last_used_role(self, role_id: str) -> SectionState | None:
        target = _text(role_id, "role_id")
        return next(
            (state for state in reversed(self.states) if target in state.roles),
            None,
        )

    def recurrence_count(self, motif_id: str, *, within: int | None = None) -> int:
        target = _text(motif_id, "motif_id")
        if within is not None and (
            isinstance(within, bool) or not isinstance(within, int) or within < 1
        ):
            raise ValueError("within must be a positive integer or None")
        states = self.states if within is None else self.states[-within:]
        return sum(target in state.motif_ids for state in states)

    def transformation_history(
        self, motif_id: str | None = None
    ) -> tuple[MotifTransformation, ...]:
        target = None if motif_id is None else _text(motif_id, "motif_id")
        return tuple(
            transform
            for state in self.states
            for transform in state.transformations
            if target is None or transform.motif_id == target
        )

    @property
    def unresolved_expectations(self) -> tuple[MemoryExpectation, ...]:
        active: dict[str, MemoryExpectation] = {}
        for state in self.states:
            for expectation_id in state.resolved_expectation_ids:
                active.pop(expectation_id, None)
            for expectation in state.unresolved_expectations:
                active[expectation.expectation_id] = expectation
        return tuple(active.values())

    @property
    def return_opportunities(self) -> tuple[ReturnOpportunity, ...]:
        active: dict[str, ReturnOpportunity] = {}
        for state in self.states:
            for motif_id in state.motif_ids:
                active.pop(motif_id, None)
            for opportunity in state.return_opportunities:
                active[opportunity.motif_id] = opportunity
        return tuple(active.values())

    def validate_score(self, score: "Score") -> None:
        """Validate referenced phrase spans against M28 or M20 Score provenance."""
        phrase_lookup: dict[str, tuple[Fraction, Fraction, str | None]] = {}
        phrase_plan = score.metadata.get("m28_phrase_plan")
        if isinstance(phrase_plan, dict):
            from reawarp.composition.phrases import PhrasePlan

            plan = PhrasePlan.from_score(score)
            phrase_lookup = {
                item.phrase_id: (item.start_beats, item.end_beats, item.parent_section_id)
                for item in plan.phrases
            }
        elif score.orchestration_plan is not None:
            from reawarp.score.orchestration_intent import OrchestrationPlan

            plan = OrchestrationPlan.from_dict(score.orchestration_plan)
            phrase_lookup = {
                item.phrase_id: (item.start_beats, item.end_beats, item.section_id)
                for item in plan.phrases
            }
        for state in self.states:
            for phrase_id in state.phrase_ids:
                phrase = phrase_lookup.get(phrase_id)
                if phrase is None:
                    raise ValueError(
                        f"section {state.section_id!r} references unknown Score phrase: {phrase_id}"
                    )
                start, end, parent_section_id = phrase
                if start < state.start_beats or end > state.end_beats:
                    raise ValueError(
                        f"phrase {phrase_id!r} falls outside section {state.section_id!r}"
                    )
                if parent_section_id is not None and parent_section_id != state.section_id:
                    raise ValueError(
                        f"phrase {phrase_id!r} belongs to section {parent_section_id!r}, "
                        f"not {state.section_id!r}"
                    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": SECTION_MEMORY_FORMAT,
            "schema_version": self.schema_version,
            "capacity": self.capacity,
            "states": [item.to_dict() for item in self.states],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SectionMemory":
        if data.get("format") != SECTION_MEMORY_FORMAT:
            raise ValueError("not a Reawarp section memory")
        return cls(
            schema_version=data.get("schema_version", 0),
            capacity=data.get("capacity", DEFAULT_SECTION_MEMORY_CAPACITY),
            states=tuple(
                SectionState.from_dict(item) for item in data.get("states", ())
            ),
        )

    def attach_to_score(
        self, score: "Score", *, replace_existing: bool = True
    ) -> "Score":
        return attach_section_memory(score, self, replace_existing=replace_existing)


def attach_section_memory(
    score: "Score",
    memory: SectionMemory,
    *,
    replace_existing: bool = True,
) -> "Score":
    """Attach bounded memory to Score provenance without changing musical events."""
    from reawarp.score.model import Score

    if not isinstance(score, Score):
        raise TypeError("score must be a reawarp Score")
    if not isinstance(memory, SectionMemory):
        memory = SectionMemory.from_dict(memory)
    memory.validate_score(score)
    if SECTION_MEMORY_METADATA_KEY in score.metadata and not replace_existing:
        raise ValueError("Score already contains M30 section memory")
    metadata = copy.deepcopy(score.metadata)
    record = memory.to_dict()
    metadata[SECTION_MEMORY_METADATA_KEY] = record
    metadata[SECTION_MEMORY_FINGERPRINT_KEY] = _fingerprint(record)
    return replace(score, metadata=metadata)


def section_memory_from_score(score: "Score") -> SectionMemory:
    """Read and verify the M30 section-memory snapshot from a Score."""
    from reawarp.score.model import Score

    if not isinstance(score, Score):
        raise TypeError("score must be a reawarp Score")
    record = score.metadata.get(SECTION_MEMORY_METADATA_KEY)
    if not isinstance(record, dict):
        raise ValueError("Score does not contain M30 section memory")
    memory = SectionMemory.from_dict(record)
    expected = score.metadata.get(SECTION_MEMORY_FINGERPRINT_KEY)
    if expected and expected != _fingerprint(memory.to_dict()):
        raise ValueError("M30 section memory fingerprint does not match its contents")
    memory.validate_score(score)
    return memory


__all__ = [
    "DEFAULT_SECTION_MEMORY_CAPACITY",
    "EXPECTATION_KINDS",
    "MAX_SECTION_MEMORY_CAPACITY",
    "SECTION_MEMORY_FORMAT",
    "SECTION_MEMORY_SCHEMA_VERSION",
    "MemoryExpectation",
    "ReturnOpportunity",
    "SectionMemory",
    "SectionState",
    "TrajectorySummary",
    "attach_section_memory",
    "section_memory_from_score",
]
