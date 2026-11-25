"""Score-native phrase grammar and immutable phrase candidate lineage (M28)."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, replace
from fractions import Fraction
from typing import TYPE_CHECKING, Any, Mapping, Sequence

import numpy as np

from reawarp.core.random_streams import derive_seed

if TYPE_CHECKING:
    from reawarp.score.events import MusicalEvent
    from reawarp.score.model import Score

PHRASE_SCHEMA_VERSION = 1
PHRASE_FORMAT = "eli_lab_reawarp_phrase_plan"
PHRASE_FUNCTIONS = frozenset({
    "presentation", "continuation", "departure", "response", "suspension",
    "arrival", "interruption", "reprise", "exit",
})
PHRASE_STATES = frozenset({"open", "closed", "fragmentary"})
BOUNDARY_KINDS = frozenset({
    "phrase_start", "phrase_end", "arrival", "interruption", "silence",
    "pickup", "cut", "manual",
})
MOTIF_DIMENSIONS = (
    "pitch", "rhythm", "timbre", "envelope", "register", "sample",
    "spatial", "silence",
)
TRANSFORMATIONS = frozenset({
    "no_change", "transposition", "inversion", "retrograde", "augmentation",
    "diminution", "fragmentation", "extension", "truncation",
    "displacement", "re_orchestration", "resampling", "timbral_translation",
})
VARIATION_LADDER = {
    "subtle": ("no_change", "displacement", "re_orchestration"),
    "moderate": (
        "transposition", "augmentation", "diminution", "fragmentation",
        "extension", "truncation",
    ),
    "disruptive": (
        "inversion", "retrograde", "resampling", "timbral_translation",
    ),
}


def _json_copy(value: Any, field: str) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be finite JSON-compatible data") from exc


def _fraction(value: Any, field: str, *, positive: bool = False) -> Fraction:
    try:
        if isinstance(value, bool):
            raise TypeError("boolean is not a beat value")
        result = value if isinstance(value, Fraction) else Fraction(str(value))
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{field} must be a valid rational beat value") from exc
    if result < 0 or (positive and result <= 0):
        comparator = "positive" if positive else "non-negative"
        raise ValueError(f"{field} must be {comparator}")
    return result


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _score_fingerprint(score: Score) -> str:
    payload = score.to_dict()
    metadata = dict(payload.get("metadata", {}))
    metadata.pop("performance", None)
    metadata.pop("render_provenance", None)
    payload["metadata"] = metadata
    return _fingerprint(payload)


@dataclass(frozen=True, slots=True)
class PhraseBoundary:
    """A semantic event at an exact rational beat boundary."""

    at_beats: Fraction
    kind: str
    label: str = ""
    event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "at_beats", _fraction(self.at_beats, "boundary beat"))
        if self.kind not in BOUNDARY_KINDS:
            raise ValueError(f"unsupported phrase boundary kind: {self.kind}")
        ids = tuple(str(item).strip() for item in self.event_ids)
        if any(not item for item in ids) or len(ids) != len(set(ids)):
            raise ValueError("boundary event IDs must be unique non-empty strings")
        object.__setattr__(self, "event_ids", ids)
        object.__setattr__(self, "label", str(self.label).strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "at_beats": str(self.at_beats), "kind": self.kind,
            "label": self.label, "event_ids": list(self.event_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PhraseBoundary":
        return cls(
            at_beats=data.get("at_beats", "0"),
            kind=str(data.get("kind", "manual")),
            label=str(data.get("label", "")),
            event_ids=tuple(data.get("event_ids", ())),
        )


@dataclass(frozen=True, slots=True)
class PhraseSpan:
    """A phrase references canonical Score events; it is not a second scheduler."""

    phrase_id: str
    start_beats: Fraction
    end_beats: Fraction
    function: str
    state: str = "closed"
    motif_ids: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    internal_cycles: tuple[Fraction, ...] = ()
    boundaries: tuple[PhraseBoundary, ...] = ()
    event_ids: tuple[str, ...] = ()
    parent_section_id: str | None = None
    notes: str = ""
    custom_function: str | None = None

    def __post_init__(self) -> None:
        phrase_id = str(self.phrase_id).strip()
        if not phrase_id:
            raise ValueError("phrase_id cannot be empty")
        start = _fraction(self.start_beats, "phrase start")
        end = _fraction(self.end_beats, "phrase end")
        if end <= start:
            raise ValueError("phrase end must be greater than phrase start")
        function = str(self.function).strip()
        if function not in PHRASE_FUNCTIONS:
            if not self.custom_function or function != str(self.custom_function).strip():
                raise ValueError(
                    f"unsupported phrase function: {function}; use custom_function for extensions"
                )
        if self.state not in PHRASE_STATES:
            raise ValueError(f"phrase state must be one of {sorted(PHRASE_STATES)}")
        motif_ids = tuple(str(item).strip() for item in self.motif_ids)
        roles = tuple(str(item).strip() for item in self.roles)
        event_ids = tuple(str(item).strip() for item in self.event_ids)
        for name, values in (
            ("motif_ids", motif_ids), ("roles", roles), ("event_ids", event_ids),
        ):
            if any(not item for item in values) or len(values) != len(set(values)):
                raise ValueError(f"{name} must contain unique non-empty values")
        cycles = tuple(_fraction(item, "internal cycle", positive=True) for item in self.internal_cycles)
        if any(item >= end - start for item in cycles):
            raise ValueError("internal cycle lengths must be shorter than the phrase span")
        boundaries = tuple(
            item if isinstance(item, PhraseBoundary) else PhraseBoundary.from_dict(item)
            for item in self.boundaries
        )
        if any(item.at_beats < start or item.at_beats > end for item in boundaries):
            raise ValueError("phrase boundary falls outside its phrase span")
        if len({(item.at_beats, item.kind, item.label) for item in boundaries}) != len(boundaries):
            raise ValueError("phrase boundaries must be unique")
        if self.parent_section_id is not None:
            parent = str(self.parent_section_id).strip()
            if not parent:
                raise ValueError("parent_section_id must be non-empty or None")
            object.__setattr__(self, "parent_section_id", parent)
        custom = None if self.custom_function is None else str(self.custom_function).strip()
        if self.custom_function is not None and not custom:
            raise ValueError("custom_function must be non-empty")
        object.__setattr__(self, "custom_function", custom)
        object.__setattr__(self, "phrase_id", phrase_id)
        object.__setattr__(self, "start_beats", start)
        object.__setattr__(self, "end_beats", end)
        object.__setattr__(self, "motif_ids", motif_ids)
        object.__setattr__(self, "roles", roles)
        object.__setattr__(self, "event_ids", event_ids)
        object.__setattr__(self, "internal_cycles", cycles)
        object.__setattr__(self, "boundaries", tuple(sorted(
            boundaries, key=lambda item: (item.at_beats, item.kind, item.label)
        )))
        object.__setattr__(self, "notes", str(self.notes).strip())

    @property
    def duration_beats(self) -> Fraction:
        return self.end_beats - self.start_beats

    @property
    def is_silent(self) -> bool:
        return not self.event_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "phrase_id": self.phrase_id,
            "start_beats": str(self.start_beats),
            "end_beats": str(self.end_beats),
            "function": self.function,
            "state": self.state,
            "motif_ids": list(self.motif_ids),
            "roles": list(self.roles),
            "internal_cycles": [str(item) for item in self.internal_cycles],
            "boundaries": [item.to_dict() for item in self.boundaries],
            "event_ids": list(self.event_ids),
            "parent_section_id": self.parent_section_id,
            "notes": self.notes,
            "custom_function": self.custom_function,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PhraseSpan":
        return cls(
            phrase_id=str(data.get("phrase_id", "")),
            start_beats=data.get("start_beats", "0"),
            end_beats=data.get("end_beats", "1"),
            function=str(data.get("function", "continuation")),
            state=str(data.get("state", "closed")),
            motif_ids=tuple(data.get("motif_ids", ())),
            roles=tuple(data.get("roles", ())),
            internal_cycles=tuple(data.get("internal_cycles", ())),
            boundaries=tuple(PhraseBoundary.from_dict(x) for x in data.get("boundaries", ())),
            event_ids=tuple(data.get("event_ids", ())),
            parent_section_id=data.get("parent_section_id"),
            notes=str(data.get("notes", "")),
            custom_function=data.get("custom_function"),
        )


@dataclass(frozen=True, slots=True)
class MotifIdentity:
    """A named motif identity over inspectable musical feature dimensions."""

    motif_id: str
    version: int = 1
    dimensions: tuple[str, ...] = MOTIF_DIMENSIONS
    feature_references: Mapping[str, Any] | None = None
    description: str = ""

    def __post_init__(self) -> None:
        motif_id = str(self.motif_id).strip()
        if not motif_id:
            raise ValueError("motif_id cannot be empty")
        if isinstance(self.version, bool) or int(self.version) < 1:
            raise ValueError("motif version must be positive")
        dimensions = tuple(str(item) for item in self.dimensions)
        if not dimensions or len(dimensions) != len(set(dimensions)):
            raise ValueError("motif identity dimensions must be non-empty and unique")
        unknown = set(dimensions) - set(MOTIF_DIMENSIONS)
        if unknown:
            raise ValueError("unsupported motif dimensions: " + ", ".join(sorted(unknown)))
        refs = _json_copy(dict(self.feature_references or {}), "motif feature references")
        if set(refs) - set(dimensions):
            raise ValueError("feature references supplied for undeclared dimensions")
        object.__setattr__(self, "motif_id", motif_id)
        object.__setattr__(self, "version", int(self.version))
        object.__setattr__(self, "dimensions", dimensions)
        object.__setattr__(self, "feature_references", refs)
        object.__setattr__(self, "description", str(self.description).strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "motif_id": self.motif_id, "version": self.version,
            "dimensions": list(self.dimensions),
            "feature_references": _json_copy(dict(self.feature_references), "feature references"),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MotifIdentity":
        return cls(
            motif_id=str(data.get("motif_id", "")),
            version=int(data.get("version", 1)),
            dimensions=tuple(data.get("dimensions", MOTIF_DIMENSIONS)),
            feature_references=data.get("feature_references", {}),
            description=str(data.get("description", "")),
        )


@dataclass(frozen=True, slots=True)
class MotifTransformation:
    """A transformation with full identity and event-lineage provenance."""

    transformation_id: str
    motif_id: str
    source_version: int
    target_version: int
    operation: str
    changed_dimensions: tuple[str, ...]
    preserved_dimensions: tuple[str, ...]
    amount: Any = None
    seed: int | None = None
    source_event_ids: tuple[str, ...] = ()
    target_event_ids: tuple[str, ...] = ()
    implementation: str = "symbolic"
    notes: str = ""

    def __post_init__(self) -> None:
        for name in ("transformation_id", "motif_id", "operation", "implementation"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} cannot be empty")
        if self.operation not in TRANSFORMATIONS:
            raise ValueError(f"unsupported motif transformation: {self.operation}")
        if self.source_version < 1 or self.target_version <= self.source_version:
            raise ValueError("transformation versions must increase")
        changed = tuple(self.changed_dimensions)
        preserved = tuple(self.preserved_dimensions)
        if (
            len(changed) != len(set(changed)) or len(preserved) != len(set(preserved))
            or set(changed) & set(preserved)
            or set(changed) | set(preserved) != set(MOTIF_DIMENSIONS)
        ):
            raise ValueError("changed/preserved dimensions must partition all motif dimensions")
        if self.operation == "no_change" and changed:
            raise ValueError("no_change cannot declare changed dimensions")
        if self.seed is not None and (isinstance(self.seed, bool) or int(self.seed) < 0):
            raise ValueError("transformation seed must be a non-negative integer")
        object.__setattr__(self, "changed_dimensions", tuple(
            item for item in MOTIF_DIMENSIONS if item in changed
        ))
        object.__setattr__(self, "preserved_dimensions", tuple(
            item for item in MOTIF_DIMENSIONS if item in preserved
        ))
        object.__setattr__(self, "amount", _json_copy(self.amount, "transformation amount"))
        object.__setattr__(self, "source_event_ids", tuple(self.source_event_ids))
        object.__setattr__(self, "target_event_ids", tuple(self.target_event_ids))
        object.__setattr__(self, "notes", str(self.notes).strip())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MotifTransformation":
        return cls(**dict(data))


@dataclass(frozen=True, slots=True)
class MotifFamily:
    """Versioned motif family retaining identity for each predecessor/return."""

    family_id: str
    versions: tuple[MotifIdentity, ...]
    transformations: tuple[MotifTransformation, ...] = ()

    def __post_init__(self) -> None:
        family_id = str(self.family_id).strip()
        if not family_id:
            raise ValueError("motif family ID cannot be empty")
        versions = tuple(
            item if isinstance(item, MotifIdentity) else MotifIdentity.from_dict(item)
            for item in self.versions
        )
        transforms = tuple(
            item if isinstance(item, MotifTransformation)
            else MotifTransformation.from_dict(item)
            for item in self.transformations
        )
        if not versions or len({item.version for item in versions}) != len(versions):
            raise ValueError("motif family must contain unique versions")
        ordered = tuple(sorted(versions, key=lambda item: item.version))
        if tuple(item.version for item in ordered) != tuple(range(1, len(ordered) + 1)):
            raise ValueError("motif family versions must be contiguous from version one")
        by_version = {item.version for item in ordered}
        for transform in transforms:
            if transform.motif_id != family_id:
                raise ValueError("motif transformation belongs to another family")
            if transform.source_version not in by_version or transform.target_version not in by_version:
                raise ValueError("motif transformation references unknown family versions")
        object.__setattr__(self, "family_id", family_id)
        object.__setattr__(self, "versions", ordered)
        object.__setattr__(self, "transformations", transforms)

    @property
    def current(self) -> MotifIdentity:
        return self.versions[-1]

    def evolve(self, transformation: MotifTransformation) -> "MotifFamily":
        if transformation.motif_id != self.family_id:
            raise ValueError("transformation belongs to another motif family")
        if transformation.source_version != self.current.version:
            raise ValueError("transformation source is not the current motif version")
        if transformation.target_version != self.current.version + 1:
            raise ValueError("transformation must create the next motif version")
        identity = MotifIdentity(
            motif_id=self.family_id,
            version=transformation.target_version,
            dimensions=self.current.dimensions,
            feature_references=self.current.feature_references,
            description=self.current.description,
        )
        return MotifFamily(
            family_id=self.family_id,
            versions=self.versions + (identity,),
            transformations=self.transformations + (transformation,),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "versions": [item.to_dict() for item in self.versions],
            "transformations": [item.to_dict() for item in self.transformations],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MotifFamily":
        return cls(
            family_id=str(data.get("family_id", "")),
            versions=tuple(MotifIdentity.from_dict(x) for x in data.get("versions", ())),
            transformations=tuple(MotifTransformation.from_dict(x) for x in data.get("transformations", ())),
        )


@dataclass(frozen=True, slots=True)
class PhrasePlan:
    """Versioned phrase grammar attached to a canonical Score."""

    phrases: tuple[PhraseSpan, ...]
    motif_families: tuple[MotifFamily, ...] = ()
    schema_version: int = PHRASE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PHRASE_SCHEMA_VERSION:
            raise ValueError(f"unsupported phrase plan schema: {self.schema_version}")
        phrases = tuple(
            item if isinstance(item, PhraseSpan) else PhraseSpan.from_dict(item)
            for item in self.phrases
        )
        if len({item.phrase_id for item in phrases}) != len(phrases):
            raise ValueError("phrase IDs must be unique")
        families = tuple(
            item if isinstance(item, MotifFamily) else MotifFamily.from_dict(item)
            for item in self.motif_families
        )
        if len({item.family_id for item in families}) != len(families):
            raise ValueError("motif family IDs must be unique")
        family_ids = {item.family_id for item in families}
        unknown = {motif for item in phrases for motif in item.motif_ids} - family_ids
        if unknown:
            raise ValueError("phrase references unknown motif families: " + ", ".join(sorted(unknown)))
        object.__setattr__(self, "phrases", tuple(sorted(
            phrases, key=lambda item: (item.start_beats, item.end_beats, item.phrase_id)
        )))
        object.__setattr__(self, "motif_families", families)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": PHRASE_FORMAT, "schema_version": self.schema_version,
            "phrases": [item.to_dict() for item in self.phrases],
            "motif_families": [item.to_dict() for item in self.motif_families],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PhrasePlan":
        if data.get("format") != PHRASE_FORMAT:
            raise ValueError("not a Reawarp phrase plan")
        return cls(
            schema_version=int(data.get("schema_version", 0)),
            phrases=tuple(PhraseSpan.from_dict(x) for x in data.get("phrases", ())),
            motif_families=tuple(MotifFamily.from_dict(x) for x in data.get("motif_families", ())),
        )

    def validate_score(self, score: Score) -> None:
        by_id = {item.event_id: item for item in score.events}
        for phrase in self.phrases:
            missing = set(phrase.event_ids) - set(by_id)
            if missing:
                raise ValueError(
                    f"phrase {phrase.phrase_id!r} references missing Score event(s): "
                    + ", ".join(sorted(missing))
                )
            for event_id in phrase.event_ids:
                event = by_id[event_id]
                if event.onset_beats < phrase.start_beats or event.end_beats > phrase.end_beats:
                    raise ValueError(
                        f"event {event_id!r} falls outside phrase {phrase.phrase_id!r}"
                    )

    def attach_to_score(self, score: Score) -> Score:
        self.validate_score(score)
        metadata = copy.deepcopy(score.metadata)
        metadata["m28_phrase_plan"] = self.to_dict()
        metadata["m28_phrase_plan_fingerprint"] = _fingerprint(self.to_dict())
        return replace(score, metadata=metadata)

    @classmethod
    def from_score(cls, score: Score) -> "PhrasePlan":
        record = score.metadata.get("m28_phrase_plan")
        if not isinstance(record, dict):
            raise ValueError("Score does not contain an M28 phrase plan")
        plan = cls.from_dict(record)
        plan.validate_score(score)
        expected = score.metadata.get("m28_phrase_plan_fingerprint")
        if expected and expected != _fingerprint(plan.to_dict()):
            raise ValueError("M28 phrase plan fingerprint does not match its contents")
        return plan


@dataclass(frozen=True, slots=True)
class PhraseCandidate:
    candidate_id: str
    phrase_id: str
    index: int
    base_score_fingerprint: str
    base_phrase_fingerprint: str
    candidate_score: Score
    operation: str
    transformation: MotifTransformation
    seed_name: str
    seed: int
    source_event_ids: tuple[str, ...]
    target_event_ids: tuple[str, ...]
    config_delta: Mapping[str, Any]
    generator_version: str
    context_event_ids: Mapping[str, tuple[str, ...]]
    selection_note: str = ""

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.phrase_id or self.index < 1:
            raise ValueError("phrase candidate identity and index must be valid")
        if self.operation != self.transformation.operation:
            raise ValueError("candidate operation and transformation provenance differ")
        if self.seed < 0 or not self.seed_name or not self.generator_version:
            raise ValueError("candidate seed lineage and generator version are required")
        if not callable(getattr(self.candidate_score, "to_dict", None)):
            raise ValueError("candidate_score must provide Score serialization")
        object.__setattr__(self, "config_delta", _json_copy(dict(self.config_delta), "config delta"))
        object.__setattr__(self, "context_event_ids", {
            key: tuple(value) for key, value in dict(self.context_event_ids).items()
        })
        object.__setattr__(self, "selection_note", str(self.selection_note).strip())

    def to_dict(self, *, include_score: bool = False) -> dict[str, Any]:
        data = {
            "candidate_id": self.candidate_id,
            "phrase_id": self.phrase_id,
            "index": self.index,
            "base_score_fingerprint": self.base_score_fingerprint,
            "base_phrase_fingerprint": self.base_phrase_fingerprint,
            "operation": self.operation,
            "transformation": self.transformation.to_dict(),
            "seed_name": self.seed_name,
            "seed": self.seed,
            "source_event_ids": list(self.source_event_ids),
            "target_event_ids": list(self.target_event_ids),
            "config_delta": _json_copy(dict(self.config_delta), "config delta"),
            "generator_version": self.generator_version,
            "context_event_ids": {key: list(value) for key, value in self.context_event_ids.items()},
            "selection_note": self.selection_note,
        }
        if include_score:
            data["candidate_score"] = self.candidate_score.to_dict()
        return data


@dataclass(frozen=True, slots=True)
class PhraseCandidateBatch:
    batch_id: str
    phrase_id: str
    base_score_fingerprint: str
    base_phrase_fingerprint: str
    candidates: tuple[PhraseCandidate, ...]

    def __post_init__(self) -> None:
        if not self.batch_id or not self.phrase_id or not self.candidates:
            raise ValueError("phrase candidate batch requires identity and candidates")
        ids = [item.candidate_id for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("phrase candidate IDs must be unique")


@dataclass(frozen=True, slots=True)
class PhraseFreezeRecord:
    phrase_id: str
    candidate_id: str
    base_score_fingerprint: str
    frozen_score_fingerprint: str
    frozen_event_ids: tuple[str, ...]
    parent_candidate_id: str | None = None
    selection_note: str = ""
    generator_version: str = "reawarp-m28-phrase-v1"

    def __post_init__(self) -> None:
        for name in ("phrase_id", "candidate_id", "base_score_fingerprint", "frozen_score_fingerprint"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} cannot be empty")
        object.__setattr__(self, "frozen_event_ids", tuple(self.frozen_event_ids))
        object.__setattr__(self, "selection_note", str(self.selection_note).strip())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _event_id(source_id: str, seed: int, operation: str) -> str:
    return "m28-" + hashlib.sha256(
        f"{source_id}:{seed}:{operation}".encode("utf-8")
    ).hexdigest()[:20]


def _transform_events(
    events: Sequence[MusicalEvent],
    phrase: PhraseSpan,
    operation: str,
    seed: int,
    policy: str,
) -> tuple[tuple[MusicalEvent, ...], MotifTransformation]:
    source = tuple(events)
    if not source and operation != "no_change":
        raise ValueError("cannot transform an empty/silent phrase; only no_change is valid")
    pitches = [event.pitch for event in source if event.pitch is not None]
    pitch_axis = float(np.mean(pitches)) if pitches else 60.0
    changed_by_operation = {
        "no_change": (),
        "transposition": ("pitch", "register"),
        "inversion": ("pitch", "register"),
        "retrograde": ("rhythm",),
        "augmentation": ("rhythm", "envelope"),
        "diminution": ("rhythm", "envelope"),
        "fragmentation": ("rhythm", "silence"),
        "extension": ("rhythm", "silence"),
        "truncation": ("rhythm", "silence"),
        "displacement": ("rhythm",),
    }
    if operation not in changed_by_operation:
        raise ValueError(f"operation {operation!r} requires an unavailable M31 sound-object service")
    changed = changed_by_operation[operation]
    if policy == "one_principal_change" and operation not in changed_by_operation:
        raise ValueError("operation violates one-principal-change policy")
    rng = np.random.default_rng(seed)
    span = phrase.duration_beats
    output: list[MusicalEvent]
    if operation == "no_change":
        output = list(source)
    elif operation == "transposition":
        semitones = int(rng.choice(np.asarray([-7, -5, -2, 2, 5, 7])))
        output = [replace(
            event,
            pitch=None if event.pitch is None else event.pitch + semitones,
            frequency_hz=(
                None if event.frequency_hz is None
                else event.frequency_hz * (2.0 ** (semitones / 12.0))
            ),
            parameters={**event.parameters, "m28_transposition_semitones": semitones},
        ) for event in source]
    elif operation == "inversion":
        output = [replace(
            event,
            pitch=None if event.pitch is None else 2 * pitch_axis - event.pitch,
            parameters={**event.parameters, "m28_inversion_axis": pitch_axis},
        ) for event in source]
    elif operation == "retrograde":
        output = [replace(
            event,
            onset_beats=phrase.start_beats
            + span - (event.onset_beats - phrase.start_beats) - event.duration_beats,
        ) for event in reversed(source)]
    elif operation == "augmentation":
        # Expand the phrase's inter-onset distances to use its full span. The
        # last onset anchors the phrase end; note lengths are capped at that
        # boundary so the following phrase is never overwritten.
        offsets = [event.onset_beats - phrase.start_beats for event in source]
        last_offset = max(offsets, default=Fraction(0))
        scale = (
            phrase.duration_beats / last_offset
            if last_offset > 0 else Fraction(1)
        )
        output = []
        for event, offset in zip(source, offsets, strict=True):
            onset = phrase.start_beats + offset * scale
            room = phrase.end_beats - onset
            output.append(replace(
                event,
                onset_beats=onset,
                duration_beats=min(event.duration_beats * scale, room),
            ))
    elif operation == "diminution":
        # Compress phrase material into its first half.
        output = [replace(
            event,
            onset_beats=phrase.start_beats + (event.onset_beats - phrase.start_beats) / 2,
            duration_beats=event.duration_beats / 2,
        ) for event in source]
    elif operation == "fragmentation":
        output = [event for index, event in enumerate(source) if index % 2 == 0]
    elif operation == "extension":
        output = list(source)
        for event in source:
            onset = event.onset_beats + span / 2
            if onset + event.duration_beats <= phrase.end_beats:
                output.append(replace(
                    event,
                    event_id=_event_id(event.event_id, seed, "extension"),
                    onset_beats=onset,
                    parameters={**event.parameters, "m28_derived_from": event.event_id},
                ))
    elif operation == "truncation":
        midpoint = phrase.start_beats + span / 2
        output = [
            replace(event, duration_beats=min(event.duration_beats, midpoint - event.onset_beats))
            for event in source if event.onset_beats < midpoint
        ]
        output = [event for event in output if event.duration_beats > 0]
    else:  # displacement
        shift = Fraction(1, 2)
        output = [replace(
            event,
            onset_beats=phrase.start_beats
            + (event.onset_beats - phrase.start_beats + shift) % span,
        ) for event in source]

    output.sort(key=lambda item: (item.onset_beats, item.voice_id, item.event_id))
    for event in output:
        if event.onset_beats < phrase.start_beats or event.end_beats > phrase.end_beats:
            raise ValueError(
                f"{operation} moves event {event.event_id!r} outside phrase {phrase.phrase_id!r}"
            )
    target_ids = tuple(item.event_id for item in output)
    motif_id = phrase.motif_ids[0] if phrase.motif_ids else f"phrase:{phrase.phrase_id}"
    changed_set = set(changed)
    transformation = MotifTransformation(
        transformation_id=f"m28-transform-{_fingerprint([phrase.phrase_id, seed, operation])[:16]}",
        motif_id=motif_id,
        source_version=1,
        target_version=2,
        operation=operation,
        changed_dimensions=tuple(item for item in MOTIF_DIMENSIONS if item in changed_set),
        preserved_dimensions=tuple(item for item in MOTIF_DIMENSIONS if item not in changed_set),
        amount={"development_policy": policy},
        seed=seed,
        source_event_ids=tuple(item.event_id for item in source),
        target_event_ids=target_ids,
    )
    return tuple(output), transformation


def _phrase_for_score(score: Score, phrase_id: str) -> PhraseSpan:
    """Resolve a phrase using persisted freeze lineage when its original span changed."""
    plan = PhrasePlan.from_score(score)
    phrase = next((item for item in plan.phrases if item.phrase_id == phrase_id), None)
    if phrase is None:
        raise ValueError(f"unknown phrase ID: {phrase_id}")
    freeze = score.metadata.get("m28_phrase_freezes", {}).get(phrase_id)
    if freeze:
        target_ids = set(freeze.get("frozen_event_ids", ()))
        events = [event for event in score.events if event.event_id in target_ids]
        if events:
            phrase = replace(
                phrase,
                event_ids=tuple(event.event_id for event in events),
                start_beats=_fraction(freeze.get("phrase_start_beats", phrase.start_beats), "frozen phrase start"),
                end_beats=_fraction(freeze.get("phrase_end_beats", phrase.end_beats), "frozen phrase end"),
            )
    return phrase


def _context_ids(score: Score, phrase: PhraseSpan) -> dict[str, tuple[str, ...]]:
    return {
        "preceding": tuple(
            event.event_id for event in score.events if event.end_beats <= phrase.start_beats
        ),
        "following": tuple(
            event.event_id for event in score.events if event.onset_beats >= phrase.end_beats
        ),
    }


def build_phrase_candidate_batch(
    score: Score,
    phrase_id: str,
    *,
    count: int = 4,
    root_seed: int | str = 0,
    variation_ladder: str = "moderate",
    development_policy: str = "one_principal_change",
    operations: Sequence[str] | None = None,
    batch_id: str | None = None,
) -> "PhraseCandidateBatch":
    """Generate an offline, repeatable set of phrase alternatives from a frozen Score."""
    phrase = _phrase_for_score(score, phrase_id)
    if isinstance(count, bool) or not 1 <= int(count) <= 16:
        raise ValueError("phrase candidate count must be between 1 and 16")
    if variation_ladder not in VARIATION_LADDER:
        raise ValueError(f"unknown variation ladder: {variation_ladder}")
    if development_policy not in {"one_principal_change", "open"}:
        raise ValueError("development_policy must be one_principal_change or open")
    choices = tuple(operations or VARIATION_LADDER[variation_ladder])
    if not choices or any(item not in TRANSFORMATIONS for item in choices):
        raise ValueError("candidate operations must be supported transformation IDs")
    executable = {
        "no_change", "transposition", "inversion", "retrograde", "augmentation",
        "diminution", "fragmentation", "extension", "truncation", "displacement",
    }
    unavailable = set(choices) - executable
    if unavailable:
        raise ValueError(
            "operations require a dedicated M31 sound-object service: "
            + ", ".join(sorted(unavailable))
        )
    source_ids = set(phrase.event_ids)
    existing_freeze = score.metadata.get("m28_phrase_freezes", {}).get(phrase_id)
    if existing_freeze:
        source_ids = set(existing_freeze.get("frozen_event_ids", ()))
        phrase = replace(
            phrase, event_ids=tuple(
                event.event_id for event in score.events if event.event_id in source_ids
            ),
        )
    source_events = tuple(item for item in score.events if item.event_id in source_ids)
    source_provenance = score.metadata.get("m28_phrase_freezes", {}).get(phrase_id)
    if source_provenance:
        prior = source_provenance.get("transformation", {})
        parent_candidate_id = source_provenance.get("candidate_id")
    else:
        prior = {}
        parent_candidate_id = None
    base_phrase_fingerprint = _fingerprint({
        "phrase": phrase.to_dict(),
        "events": [item.to_dict() for item in source_events],
        "parent_candidate_id": parent_candidate_id,
    })
    base_score_fingerprint = _score_fingerprint(score)
    resolved_batch_id = batch_id or _fingerprint({
        "base": base_phrase_fingerprint,
        "score": base_score_fingerprint,
        "count": int(count),
        "seed": root_seed,
        "ladder": variation_ladder,
        "policy": development_policy,
        "operations": choices,
    })[:20]
    candidates: list[PhraseCandidate] = []
    for index in range(1, int(count) + 1):
        seed_name = f"m28:{phrase_id}:{resolved_batch_id}:candidate:{index}"
        seed = derive_seed(root_seed, seed_name)
        operation = choices[int(np.random.default_rng(seed).integers(0, len(choices)))]
        transformed, transformation = _transform_events(
            source_events, phrase, operation, seed, development_policy,
        )
        source_event_id_set = {item.event_id for item in source_events}
        outside = tuple(item for item in score.events if item.event_id not in source_event_id_set)
        transformed_ids = {item.event_id for item in transformed}
        if len(transformed_ids) != len(transformed):
            raise ValueError("candidate transformation produced duplicate event IDs")
        collision = transformed_ids & {item.event_id for item in outside}
        if collision:
            raise ValueError("candidate event IDs collide with unrelated Score events")
        candidate_score = replace(
            score,
            events=outside + transformed,
        )
        candidate_id = f"phrase-candidate-{index:02d}-{_fingerprint([base_phrase_fingerprint, seed_name, operation])[:10]}"
        if prior:
            transformation = replace(
                transformation,
                source_version=int(prior.get("transformation", {}).get("target_version", 2)),
                target_version=int(prior.get("transformation", {}).get("target_version", 2)) + 1,
                notes=f"branched from {parent_candidate_id}",
            )
        candidates.append(PhraseCandidate(
            candidate_id=candidate_id,
            phrase_id=phrase_id,
            index=index,
            base_score_fingerprint=base_score_fingerprint,
            base_phrase_fingerprint=base_phrase_fingerprint,
            candidate_score=candidate_score,
            operation=operation,
            transformation=transformation,
            seed_name=seed_name,
            seed=seed,
            source_event_ids=tuple(item.event_id for item in source_events),
            target_event_ids=tuple(item.event_id for item in transformed),
            config_delta={},
            generator_version="reawarp-m28-phrase-v1",
            context_event_ids=_context_ids(score, phrase),
        ))
    return PhraseCandidateBatch(
        batch_id=resolved_batch_id,
        phrase_id=phrase_id,
        base_score_fingerprint=base_score_fingerprint,
        base_phrase_fingerprint=base_phrase_fingerprint,
        candidates=tuple(candidates),
    )


def freeze_phrase_candidate(
    base_score: Score,
    candidate: PhraseCandidate,
    *,
    selection_note: str = "",
    parent_candidate_id: str | None = None,
) -> tuple[Score, dict[str, Any]]:
    """Freeze candidate events in the Score and retain reversible source lineage."""
    existing_freeze = base_score.metadata.get("m28_phrase_freezes", {}).get(candidate.phrase_id)
    if existing_freeze:
        raise ValueError("phrase is already frozen; restore its base before replacing it")
    if _score_fingerprint(base_score) != candidate.base_score_fingerprint:
        raise ValueError("candidate base Score is stale; regenerate against the current Score")
    source_ids = set(candidate.source_event_ids)
    target_events = tuple(
        item for item in candidate.candidate_score.events
        if item.event_id in set(candidate.target_event_ids)
    )
    base_unrelated = {
        item.event_id: item.to_dict() for item in base_score.events
        if item.event_id not in source_ids
    }
    candidate_unrelated = {
        item.event_id: item.to_dict() for item in candidate.candidate_score.events
        if item.event_id not in set(candidate.target_event_ids)
    }
    if base_unrelated != candidate_unrelated:
        raise ValueError("candidate modified events outside its frozen phrase")
    freezes = copy.deepcopy(base_score.metadata.get("m28_phrase_freezes", {}))
    prior = freezes.get(candidate.phrase_id)
    if prior:
        raise ValueError("phrase is already frozen; restore its base before replacing it")
    new_events = tuple(item for item in base_score.events if item.event_id not in source_ids) + target_events
    record = {
        "schema_version": 1,
        "phrase_id": candidate.phrase_id,
        "candidate_id": candidate.candidate_id,
        "parent_candidate_id": parent_candidate_id,
        "base_score_fingerprint": candidate.base_score_fingerprint,
        "frozen_event_ids": list(candidate.target_event_ids),
        "phrase_start_beats": str(
            next(item.start_beats for item in PhrasePlan.from_score(base_score).phrases
                 if item.phrase_id == candidate.phrase_id)
        ),
        "phrase_end_beats": str(
            next(item.end_beats for item in PhrasePlan.from_score(base_score).phrases
                 if item.phrase_id == candidate.phrase_id)
        ),
        "source_events": [
            item.to_dict() for item in base_score.events if item.event_id in source_ids
        ],
        "selection_note": str(selection_note).strip(),
        "generator_version": candidate.generator_version,
        "seed_name": candidate.seed_name,
        "seed": candidate.seed,
        "transformation": candidate.transformation.to_dict(),
        "candidate_event_fingerprint": _fingerprint([item.to_dict() for item in target_events]),
    }
    metadata = copy.deepcopy(base_score.metadata)
    phrase_plan = PhrasePlan.from_score(base_score)
    replaced_phrase = next(
        item for item in phrase_plan.phrases if item.phrase_id == candidate.phrase_id
    )
    updated_phrases = tuple(
        replace(item, event_ids=tuple(candidate.target_event_ids))
        if item.phrase_id == candidate.phrase_id else item
        for item in phrase_plan.phrases
    )
    updated_plan = PhrasePlan(
        phrases=updated_phrases,
        motif_families=phrase_plan.motif_families,
    )
    metadata["m28_phrase_plan"] = updated_plan.to_dict()
    metadata["m28_phrase_plan_fingerprint"] = _fingerprint(updated_plan.to_dict())
    freezes[candidate.phrase_id] = record
    metadata["m28_phrase_freezes"] = freezes
    frozen_score = replace(base_score, events=new_events, metadata=metadata)
    record["frozen_score_fingerprint"] = _score_fingerprint(frozen_score)
    freezes[candidate.phrase_id] = record
    frozen_score = replace(frozen_score, metadata={**metadata, "m28_phrase_freezes": freezes})
    return frozen_score, copy.deepcopy(record)


def restore_phrase_base(
    current_score: Score,
    phrase_id: str,
) -> Score:
    """Restore a frozen phrase's original source events without reverting other edits."""
    freezes = copy.deepcopy(current_score.metadata.get("m28_phrase_freezes", {}))
    record = freezes.get(phrase_id)
    if not isinstance(record, dict):
        raise ValueError(f"phrase {phrase_id!r} is not frozen")
    from reawarp.score.events import MusicalEvent

    source_events = tuple(MusicalEvent.from_dict(x) for x in record.get("source_events", ()))
    frozen_ids = set(record.get("frozen_event_ids", ()))
    remaining = [item for item in current_score.events if item.event_id not in frozen_ids]
    occupied = {item.event_id for item in remaining}
    if occupied & {item.event_id for item in source_events}:
        raise ValueError("restore would collide with an existing Score event ID")
    restored = tuple(remaining) + source_events
    freezes.pop(phrase_id, None)
    metadata = copy.deepcopy(current_score.metadata)
    phrase_plan = PhrasePlan.from_dict(metadata["m28_phrase_plan"])
    updated_phrases = tuple(
        replace(
            item,
            event_ids=tuple(
                event.event_id for event in source_events
            ),
        ) if item.phrase_id == phrase_id else item
        for item in phrase_plan.phrases
    )
    updated_plan = PhrasePlan(
        phrases=updated_phrases,
        motif_families=phrase_plan.motif_families,
    )
    metadata["m28_phrase_plan"] = updated_plan.to_dict()
    metadata["m28_phrase_plan_fingerprint"] = _fingerprint(updated_plan.to_dict())
    metadata["m28_phrase_freezes"] = freezes
    return replace(current_score, events=restored, metadata=metadata)


def branch_phrase_candidate(
    frozen_score: Score,
    phrase_id: str,
    *,
    branch_seed: int | str,
    count: int = 4,
    batch_id: str | None = None,
) -> PhraseCandidateBatch:
    """Branch from the currently frozen phrase while retaining its ancestry."""
    record = frozen_score.metadata.get("m28_phrase_freezes", {}).get(phrase_id)
    if not isinstance(record, dict):
        raise ValueError("branch source phrase is not frozen")
    return build_phrase_candidate_batch(
        frozen_score, phrase_id, count=count, root_seed=branch_seed,
        variation_ladder="moderate",
        batch_id=batch_id or f"branch-{record['candidate_id']}-{_fingerprint(branch_seed)[:8]}",
    )


def continue_evolving(
    score: Score,
    phrase_id: str,
    *,
    root_seed: int | str,
    count: int = 4,
    batch_id: str | None = None,
) -> PhraseCandidateBatch:
    """Continue generating from the current phrase; frozen phrases fail closed."""
    if phrase_id in score.metadata.get("m28_phrase_freezes", {}):
        raise ValueError("phrase is frozen; branch from it or restore its source material")
    return build_phrase_candidate_batch(
        score, phrase_id, count=count, root_seed=root_seed, batch_id=batch_id,
    )


def phrase_context_events(score: Score, phrase_id: str) -> dict[str, tuple[MusicalEvent, ...]]:
    """Return solo, predecessor-plus-candidate, and candidate-plus-successor event sets."""
    plan = PhrasePlan.from_score(score)
    phrases = list(plan.phrases)
    index = next((i for i, item in enumerate(phrases) if item.phrase_id == phrase_id), None)
    if index is None:
        raise ValueError(f"unknown phrase ID: {phrase_id}")
    phrase = _phrase_for_score(score, phrase_id)
    by_id = {event.event_id: event for event in score.events}
    solo = tuple(by_id[item] for item in phrase.event_ids)
    predecessor_start = phrases[index - 1].start_beats if index > 0 else phrase.start_beats
    successor_end = phrases[index + 1].end_beats if index + 1 < len(phrases) else phrase.end_beats
    return {
        "solo": solo,
        "after_predecessor": tuple(
            event for event in score.events
            if predecessor_start <= event.onset_beats < phrase.end_beats
        ),
        "before_successor": tuple(
            event for event in score.events
            if phrase.start_beats <= event.onset_beats < successor_end
        ),
    }


__all__ = [
    "BOUNDARY_KINDS", "MOTIF_DIMENSIONS", "PHRASE_FORMAT", "PHRASE_FUNCTIONS",
    "PHRASE_SCHEMA_VERSION", "PHRASE_STATES", "TRANSFORMATIONS", "VARIATION_LADDER",
    "MotifFamily", "MotifIdentity", "MotifTransformation", "PhraseBoundary",
    "PhraseCandidate", "PhraseCandidateBatch", "PhrasePlan", "PhraseSpan",
    "branch_phrase_candidate", "build_phrase_candidate_batch", "continue_evolving",
    "freeze_phrase_candidate", "phrase_context_events", "restore_phrase_base",
]
