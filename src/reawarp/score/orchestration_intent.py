"""Versioned, Score-native perceptual orchestration intent (M20).

The model describes musical relationships and attention; it does not schedule
playback or claim to measure artistic quality. Musical time remains rational.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Iterable, Sequence

from reawarp.score.time import Beat, as_fraction

PLAN_FORMAT = "eli_lab_reawarp_orchestration_plan"
PLAN_SCHEMA_VERSION = 3

PHRASE_FUNCTIONS = frozenset(
    {
        "proposition",
        "establishment",
        "development",
        "contrast",
        "suspension",
        "transition",
        "return",
        "residue",
        "coda",
    }
)
RELATION_KINDS = frozenset(
    {
        "unison",
        "reinforcement",
        "doubling",
        "complement",
        "interlock",
        "call_response",
        "antiphonal",
        "counterpoint",
        "convergence",
    }
)
ATTENTION_DEPTHS = frozenset({"foreground", "midground", "background", "absence"})
ATTENTION_ROLES = frozenset(
    {
        "unassigned",
        "anchor",
        "low_frequency_foundation",
        "primary_rhythm",
        "counter_rhythm",
        "motif",
        "harmonic_field",
        "texture",
        "transition",
        "spatial_bed",
    }
)
TRANSITION_GESTURES = frozenset(
    {
        "pickup",
        "fill",
        "riser",
        "subtraction",
        "hard_cut",
        "reverse_swell",
        "register_shift",
        "echo_handoff",
        "rhythmic_collapse",
        "silence_gate",
        "fragment_reassembly",
        "false_cadence",
        "silence",
        "collapse",
        "return",
        "residue",
        "open_ending",
        "closed_ending",
    }
)


def _text(value: Any, field: str) -> str:
    result = str(value).strip()
    if not result:
        raise ValueError(f"{field} must be non-empty")
    return result


def _time(value: Any, field: str, *, allow_negative: bool = False) -> Beat:
    result = as_fraction(value)
    if not allow_negative and result < 0:
        raise ValueError(f"{field} cannot be negative")
    return result


@dataclass(frozen=True, slots=True)
class PhraseSpan:
    phrase_id: str
    start_beats: Beat
    end_beats: Beat
    function: str = "development"
    section_id: str = "main"
    overlap_group: str | None = None
    allow_overlap: bool = False
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "phrase_id", _text(self.phrase_id, "phrase_id"))
        start = _time(self.start_beats, "phrase start")
        end = _time(self.end_beats, "phrase end")
        if end <= start:
            raise ValueError("phrase end must be after phrase start")
        if self.function not in PHRASE_FUNCTIONS:
            raise ValueError(f"unsupported phrase function: {self.function}")
        object.__setattr__(self, "start_beats", start)
        object.__setattr__(self, "end_beats", end)
        object.__setattr__(self, "section_id", _text(self.section_id, "section_id"))
        if self.overlap_group is not None:
            object.__setattr__(
                self, "overlap_group", _text(self.overlap_group, "overlap_group")
            )
        object.__setattr__(self, "tags", tuple(str(item) for item in self.tags))

    @property
    def duration_beats(self) -> Beat:
        return self.end_beats - self.start_beats

    def to_dict(self) -> dict[str, Any]:
        return {
            "phrase_id": self.phrase_id,
            "start_beats": str(self.start_beats),
            "end_beats": str(self.end_beats),
            "function": self.function,
            "section_id": self.section_id,
            "overlap_group": self.overlap_group,
            "allow_overlap": self.allow_overlap,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PhraseSpan":
        return cls(**{**data, "tags": tuple(data.get("tags", ()))})


@dataclass(frozen=True, slots=True)
class CycleSpec:
    cycle_id: str
    role: str
    length_beats: Beat
    phase_beats: Beat = Fraction(0)
    start_beats: Beat = Fraction(0)
    end_beats: Beat | None = None
    anchor_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "cycle_id", _text(self.cycle_id, "cycle_id"))
        object.__setattr__(self, "role", _text(self.role, "role"))
        length = _time(self.length_beats, "cycle length")
        if length <= 0:
            raise ValueError("cycle length must be positive")
        object.__setattr__(self, "length_beats", length)
        object.__setattr__(self, "phase_beats", _time(self.phase_beats, "cycle phase"))
        object.__setattr__(self, "start_beats", _time(self.start_beats, "cycle start"))
        if self.end_beats is not None:
            end = _time(self.end_beats, "cycle end")
            if end <= self.start_beats:
                raise ValueError("cycle end must be after cycle start")
            object.__setattr__(self, "end_beats", end)
        if self.anchor_id is not None:
            object.__setattr__(self, "anchor_id", _text(self.anchor_id, "anchor_id"))

    @property
    def normalized_phase(self) -> Beat:
        return self.phase_beats % self.length_beats

    def onset_beats(
        self,
        *,
        until: Beat | int | str,
        from_beat: Beat | int | str | None = None,
    ) -> tuple[Beat, ...]:
        """Enumerate exact cycle-grid onsets in the half-open interval [start, stop)."""
        stop = _time(until, "until")
        start = self.start_beats if from_beat is None else _time(from_beat, "from_beat")
        if self.end_beats is not None:
            stop = min(stop, self.end_beats)
        if stop <= start:
            return ()
        origin = self.start_beats + self.normalized_phase
        index = max(0, (start - origin) // self.length_beats)
        onset = origin + index * self.length_beats
        while onset < start:
            onset += self.length_beats
        result: list[Beat] = []
        while onset < stop:
            result.append(onset)
            onset += self.length_beats
        return tuple(result)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "role": self.role,
            "length_beats": str(self.length_beats),
            "phase_beats": str(self.phase_beats),
            "start_beats": str(self.start_beats),
            "end_beats": None if self.end_beats is None else str(self.end_beats),
            "anchor_id": self.anchor_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CycleSpec":
        return cls(**data)


@dataclass(frozen=True, slots=True)
class RoleRelationship:
    relationship_id: str
    source_role: str
    target_role: str
    kind: str
    start_beats: Beat = Fraction(0)
    end_beats: Beat | None = None
    offset_beats: Beat = Fraction(0)
    response_gap_beats: Beat = Fraction(0)
    transition_intent: str | None = None

    def __post_init__(self) -> None:
        for name in ("relationship_id", "source_role", "target_role"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.source_role == self.target_role:
            raise ValueError("a role relationship requires two distinct roles")
        if self.kind not in RELATION_KINDS:
            raise ValueError(f"unsupported role relationship: {self.kind}")
        object.__setattr__(
            self, "start_beats", _time(self.start_beats, "relationship start")
        )
        object.__setattr__(
            self,
            "offset_beats",
            _time(self.offset_beats, "relationship offset", allow_negative=True),
        )
        object.__setattr__(
            self, "response_gap_beats", _time(self.response_gap_beats, "response gap")
        )
        if self.end_beats is not None:
            end = _time(self.end_beats, "relationship end")
            if end <= self.start_beats:
                raise ValueError("relationship end must be after start")
            object.__setattr__(self, "end_beats", end)
        if self.transition_intent is not None:
            object.__setattr__(
                self, "transition_intent", str(self.transition_intent).strip() or None
            )

    def target_onsets(
        self, source_onsets: Iterable[Beat | int | str]
    ) -> tuple[Beat, ...]:
        """Apply a deterministic timing grammar to one role's onset sequence."""
        source = tuple(sorted(as_fraction(value) for value in source_onsets))
        if self.kind in {"unison", "reinforcement", "doubling"}:
            mapped = source
        elif self.kind in {"complement", "interlock", "counterpoint"}:
            mapped = tuple(value + self.offset_beats for value in source)
        elif self.kind in {"call_response", "antiphonal"}:
            mapped = tuple(value + self.response_gap_beats for value in source)
        else:
            if self.end_beats is None:
                raise ValueError("convergence requires an end_beats boundary")
            duration = self.end_beats - self.start_beats
            mapped = tuple(
                value
                + self.offset_beats
                * (
                    1
                    - min(
                        Fraction(1),
                        max(Fraction(0), (value - self.start_beats) / duration),
                    )
                )
                for value in source
            )
        return tuple(
            value
            for value in mapped
            if value >= self.start_beats
            and (self.end_beats is None or value < self.end_beats)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "relationship_id": self.relationship_id,
            "source_role": self.source_role,
            "target_role": self.target_role,
            "kind": self.kind,
            "start_beats": str(self.start_beats),
            "end_beats": None if self.end_beats is None else str(self.end_beats),
            "offset_beats": str(self.offset_beats),
            "response_gap_beats": str(self.response_gap_beats),
            "transition_intent": self.transition_intent,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RoleRelationship":
        return cls(**data)


@dataclass(frozen=True, slots=True)
class AttentionSpan:
    role: str
    start_beats: Beat
    end_beats: Beat
    depth: str
    handoff_id: str | None = None
    register_low: float | None = None
    register_high: float | None = None
    spectral_band: str | None = None
    reserved_silence: bool = False
    attention_role: str = "unassigned"
    onset_density: float | None = None
    transient_strength: float | None = None
    sustain: float | None = None
    spatial_position: float | None = None
    prominence: float | None = None
    intentional_overlap_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", _text(self.role, "attention role"))
        start = _time(self.start_beats, "attention start")
        end = _time(self.end_beats, "attention end")
        if end <= start:
            raise ValueError("attention end must be after start")
        if self.depth not in ATTENTION_DEPTHS:
            raise ValueError(f"unsupported attention depth: {self.depth}")
        if self.depth == "absence":
            object.__setattr__(self, "reserved_silence", True)
        object.__setattr__(self, "start_beats", start)
        object.__setattr__(self, "end_beats", end)
        if self.handoff_id is not None:
            object.__setattr__(self, "handoff_id", _text(self.handoff_id, "handoff_id"))
        for name in ("register_low", "register_high"):
            value = getattr(self, name)
            if value is not None:
                value = float(value)
                if not (-float("inf") < value < float("inf")):
                    raise ValueError("register bounds must be finite")
                object.__setattr__(self, name, value)
        if (
            self.register_low is not None
            and self.register_high is not None
            and self.register_high < self.register_low
        ):
            raise ValueError("register_high must be >= register_low")
        if self.spectral_band is not None:
            object.__setattr__(
                self, "spectral_band", _text(self.spectral_band, "spectral_band")
            )
        if self.attention_role not in ATTENTION_ROLES:
            raise ValueError(
                f"unsupported semantic attention role: {self.attention_role}"
            )
        if self.intentional_overlap_id is not None:
            object.__setattr__(
                self,
                "intentional_overlap_id",
                _text(self.intentional_overlap_id, "intentional_overlap_id"),
            )
        for name in (
            "onset_density",
            "transient_strength",
            "sustain",
            "spatial_position",
            "prominence",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            value = float(value)
            if not (-float("inf") < value < float("inf")):
                raise ValueError(f"{name} must be finite")
            if name == "onset_density":
                if value < 0.0:
                    raise ValueError("onset_density cannot be negative")
            elif name == "spatial_position":
                if not -1.0 <= value <= 1.0:
                    raise ValueError("spatial_position must be between -1 and 1")
            elif not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between zero and one")
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "start_beats": str(self.start_beats),
            "end_beats": str(self.end_beats),
            "depth": self.depth,
            "handoff_id": self.handoff_id,
            "register_low": self.register_low,
            "register_high": self.register_high,
            "spectral_band": self.spectral_band,
            "reserved_silence": self.reserved_silence,
            "attention_role": self.attention_role,
            "onset_density": self.onset_density,
            "transient_strength": self.transient_strength,
            "sustain": self.sustain,
            "spatial_position": self.spatial_position,
            "prominence": self.prominence,
            "intentional_overlap_id": self.intentional_overlap_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AttentionSpan":
        return cls(**data)


@dataclass(frozen=True, slots=True)
class MutationPolicy:
    phrase_id: str
    stable_anchors: tuple[str, ...] = ()
    preserve_pattern: tuple[str, ...] = ()
    preserve_motif: tuple[str, ...] = ()
    preserve_sound: tuple[str, ...] = ()
    allow_pattern: tuple[str, ...] = ()
    allow_motif: tuple[str, ...] = ()
    allow_sound: tuple[str, ...] = ()
    principal_developments: int = 1
    deliberate_rupture: bool = False
    rupture_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "phrase_id", _text(self.phrase_id, "mutation phrase_id")
        )
        for name in (
            "stable_anchors",
            "preserve_pattern",
            "preserve_motif",
            "preserve_sound",
            "allow_pattern",
            "allow_motif",
            "allow_sound",
        ):
            object.__setattr__(
                self, name, tuple(_text(value, name) for value in getattr(self, name))
            )
        if (
            isinstance(self.principal_developments, bool)
            or not isinstance(self.principal_developments, int)
            or self.principal_developments < 0
        ):
            raise ValueError("principal_developments must be a non-negative integer")
        if self.principal_developments > 1 and not self.deliberate_rupture:
            raise ValueError(
                "multiple principal developments require deliberate_rupture"
            )
        if self.deliberate_rupture and not (self.rupture_reason or "").strip():
            raise ValueError("deliberate_rupture requires rupture_reason")
        if not self.deliberate_rupture and self.rupture_reason is not None:
            raise ValueError("rupture_reason requires deliberate_rupture")

    def to_dict(self) -> dict[str, Any]:
        return {
            "phrase_id": self.phrase_id,
            "stable_anchors": list(self.stable_anchors),
            "preserve_pattern": list(self.preserve_pattern),
            "preserve_motif": list(self.preserve_motif),
            "preserve_sound": list(self.preserve_sound),
            "allow_pattern": list(self.allow_pattern),
            "allow_motif": list(self.allow_motif),
            "allow_sound": list(self.allow_sound),
            "principal_developments": self.principal_developments,
            "deliberate_rupture": self.deliberate_rupture,
            "rupture_reason": self.rupture_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MutationPolicy":
        tuple_fields = {
            "stable_anchors",
            "preserve_pattern",
            "preserve_motif",
            "preserve_sound",
            "allow_pattern",
            "allow_motif",
            "allow_sound",
        }
        values = {
            key: tuple(value) if key in tuple_fields else value
            for key, value in data.items()
        }
        return cls(**values)


@dataclass(frozen=True, slots=True)
class TransitionSpan:
    transition_id: str
    source_phrase_id: str
    target_phrase_id: str
    start_beats: Beat
    end_beats: Beat
    gesture: str
    intensity: float = 1.0
    affected_roles: tuple[str, ...] = ()
    transition_intent: str | None = None

    def __post_init__(self) -> None:
        for name in ("transition_id", "source_phrase_id", "target_phrase_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        start = _time(self.start_beats, "transition start")
        end = _time(self.end_beats, "transition end")
        if end <= start:
            raise ValueError("transition end must be after start")
        if self.gesture not in TRANSITION_GESTURES:
            raise ValueError(f"unsupported transition gesture: {self.gesture}")
        intensity = float(self.intensity)
        if not 0.0 <= intensity <= 1.0:
            raise ValueError("transition intensity must be between zero and one")
        object.__setattr__(self, "start_beats", start)
        object.__setattr__(self, "end_beats", end)
        object.__setattr__(self, "intensity", intensity)
        object.__setattr__(
            self,
            "affected_roles",
            tuple(_text(role, "affected role") for role in self.affected_roles),
        )
        if self.transition_intent is not None:
            object.__setattr__(
                self, "transition_intent", str(self.transition_intent).strip() or None
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "transition_id": self.transition_id,
            "source_phrase_id": self.source_phrase_id,
            "target_phrase_id": self.target_phrase_id,
            "start_beats": str(self.start_beats),
            "end_beats": str(self.end_beats),
            "gesture": self.gesture,
            "intensity": self.intensity,
            "affected_roles": list(self.affected_roles),
            "transition_intent": self.transition_intent,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TransitionSpan":
        return cls(**{**data, "affected_roles": tuple(data.get("affected_roles", ()))})


@dataclass(frozen=True, slots=True)
class OrchestrationPlan:
    phrases: tuple[PhraseSpan, ...] = ()
    cycles: tuple[CycleSpec, ...] = ()
    relationships: tuple[RoleRelationship, ...] = ()
    attention: tuple[AttentionSpan, ...] = ()
    mutation_policies: tuple[MutationPolicy, ...] = ()
    transitions: tuple[TransitionSpan, ...] = ()
    seed: int = 0
    title: str = ""

    def __post_init__(self) -> None:
        id_fields = (
            ("phrases", lambda item: item.phrase_id),
            ("cycles", lambda item: item.cycle_id),
            ("relationships", lambda item: item.relationship_id),
            ("mutation_policies", lambda item: item.phrase_id),
            ("transitions", lambda item: item.transition_id),
        )
        for field_name, get_id in id_fields:
            values = tuple(getattr(self, field_name))
            ids = [get_id(item) for item in values]
            if len(ids) != len(set(ids)):
                raise ValueError(f"{field_name} IDs must be unique")
            object.__setattr__(self, field_name, values)
        object.__setattr__(self, "attention", tuple(self.attention))
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("orchestration seed must be an integer")
        phrase_ids = {item.phrase_id for item in self.phrases}
        for policy in self.mutation_policies:
            if policy.phrase_id not in phrase_ids:
                raise ValueError(
                    f"mutation policy references unknown phrase: {policy.phrase_id}"
                )
        for transition in self.transitions:
            if (
                transition.source_phrase_id not in phrase_ids
                or transition.target_phrase_id not in phrase_ids
            ):
                raise ValueError("transition references an unknown phrase")
        ordered = sorted(
            self.phrases,
            key=lambda item: (item.start_beats, item.end_beats, item.phrase_id),
        )
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                if right.start_beats >= left.end_beats:
                    break
                permitted = (
                    left.allow_overlap
                    or right.allow_overlap
                    or (
                        left.overlap_group is not None
                        and left.overlap_group == right.overlap_group
                    )
                )
                if not permitted:
                    raise ValueError(
                        f"phrases overlap without permission: {left.phrase_id}, {right.phrase_id}"
                    )

    @property
    def duration_beats(self) -> Beat:
        ends = [item.end_beats for item in self.phrases]
        ends.extend(item.end_beats for item in self.attention)
        ends.extend(item.end_beats for item in self.transitions)
        ends.extend(
            item.end_beats for item in self.relationships if item.end_beats is not None
        )
        ends.extend(
            item.end_beats for item in self.cycles if item.end_beats is not None
        )
        return max(ends, default=Fraction(0))

    def attention_at(self, role: str, beat: Beat | int | str) -> AttentionSpan | None:
        position = as_fraction(beat)
        active = [
            item
            for item in self.attention
            if item.role == role and item.start_beats <= position < item.end_beats
        ]
        return (
            max(active, key=lambda item: (item.start_beats, item.end_beats))
            if active
            else None
        )

    def foreground_at(self, beat: Beat | int | str) -> tuple[str, ...]:
        position = as_fraction(beat)
        return tuple(
            sorted(
                {
                    item.role
                    for item in self.attention
                    if item.depth == "foreground"
                    and item.start_beats <= position < item.end_beats
                }
            )
        )

    def cycle_alignments(
        self,
        left_cycle_id: str,
        right_cycle_id: str,
        *,
        start_beats: Beat | int | str = 0,
        end_beats: Beat | int | str,
    ) -> tuple[Beat, ...]:
        """Return exact shared onsets of two independent cycles in a bounded window."""
        by_id = {item.cycle_id: item for item in self.cycles}
        if left_cycle_id not in by_id or right_cycle_id not in by_id:
            raise KeyError("unknown cycle ID")
        left = set(
            by_id[left_cycle_id].onset_beats(from_beat=start_beats, until=end_beats)
        )
        right = set(
            by_id[right_cycle_id].onset_beats(from_beat=start_beats, until=end_beats)
        )
        return tuple(sorted(left & right))

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": PLAN_FORMAT,
            "schema_version": PLAN_SCHEMA_VERSION,
            "seed": self.seed,
            "title": self.title,
            "phrases": [item.to_dict() for item in self.phrases],
            "cycles": [item.to_dict() for item in self.cycles],
            "relationships": [item.to_dict() for item in self.relationships],
            "attention": [item.to_dict() for item in self.attention],
            "mutation_policies": [item.to_dict() for item in self.mutation_policies],
            "transitions": [item.to_dict() for item in self.transitions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OrchestrationPlan":
        if data.get("format") != PLAN_FORMAT:
            raise ValueError("unsupported orchestration plan format")
        version = int(data.get("schema_version", 0))
        if version not in {1, 2, PLAN_SCHEMA_VERSION}:
            raise ValueError(
                f"unsupported orchestration plan schema version: {version}"
            )
        return cls(
            phrases=tuple(
                PhraseSpan.from_dict(item) for item in data.get("phrases", ())
            ),
            cycles=tuple(CycleSpec.from_dict(item) for item in data.get("cycles", ())),
            relationships=tuple(
                RoleRelationship.from_dict(item)
                for item in data.get("relationships", ())
            ),
            attention=tuple(
                AttentionSpan.from_dict(item) for item in data.get("attention", ())
            ),
            mutation_policies=tuple(
                MutationPolicy.from_dict(item)
                for item in data.get("mutation_policies", ())
            ),
            transitions=tuple(
                TransitionSpan.from_dict(item) for item in data.get("transitions", ())
            ),
            seed=int(data.get("seed", 0)),
            title=str(data.get("title", "")),
        )


def build_orchestration_plan(
    *,
    phrases: Iterable[PhraseSpan] = (),
    cycles: Iterable[CycleSpec] = (),
    relationships: Iterable[RoleRelationship] = (),
    attention: Iterable[AttentionSpan] = (),
    mutation_policies: Iterable[MutationPolicy] = (),
    transitions: Iterable[TransitionSpan] = (),
    seed: int = 0,
    title: str = "",
) -> OrchestrationPlan:
    """Build deterministic, validated arrangement intent from explicit inputs."""
    return OrchestrationPlan(
        phrases=tuple(phrases),
        cycles=tuple(cycles),
        relationships=tuple(relationships),
        attention=tuple(attention),
        mutation_policies=tuple(mutation_policies),
        transitions=tuple(transitions),
        seed=seed,
        title=title,
    )


def inspect_attention_handoffs(plan: OrchestrationPlan) -> tuple[dict[str, Any], ...]:
    """Report incomplete or non-atomic foreground hand-offs at exact beat boundaries."""
    grouped: dict[str, list[AttentionSpan]] = {}
    for span in plan.attention:
        if span.handoff_id:
            grouped.setdefault(span.handoff_id, []).append(span)
    warnings: list[dict[str, Any]] = []
    for handoff_id, spans in sorted(grouped.items()):
        reason = None
        boundary = None
        if len(spans) != 2:
            reason = f"expected exactly two sides, found {len(spans)}"
        elif spans[0].role == spans[1].role:
            reason = "source and target roles must differ"
        else:
            shared = {
                (
                    spans[0].end_beats
                    if spans[0].end_beats == spans[1].start_beats
                    else None
                ),
                (
                    spans[1].end_beats
                    if spans[1].end_beats == spans[0].start_beats
                    else None
                ),
            } - {None}
            if len(shared) != 1:
                reason = "handoff sides must meet at one exact beat boundary without a gap or overlap"
            else:
                boundary = str(next(iter(shared)))
        if reason:
            warnings.append(
                {
                    "kind": "non_atomic_handoff",
                    "handoff_id": handoff_id,
                    "roles": sorted(span.role for span in spans),
                    "reason": reason,
                    "heuristic_only": False,
                }
            )
        else:
            warnings.append(
                {
                    "kind": "atomic_handoff",
                    "handoff_id": handoff_id,
                    "roles": [span.role for span in spans],
                    "boundary_beats": boundary,
                    "valid": True,
                    "heuristic_only": False,
                }
            )
    return tuple(warnings)


def inspect_attention_conflicts(plan: OrchestrationPlan) -> tuple[dict[str, Any], ...]:
    """Return evidence-led competition prompts, never a numerical quality ranking.

    Only overlapping spans with at least one explicit descriptor conflict are
    reported. Matching intentional_overlap_id values identify a designed merge.
    """
    warnings: list[dict[str, Any]] = []
    spans = sorted(
        plan.attention, key=lambda item: (item.start_beats, item.role, item.end_beats)
    )
    for index, left in enumerate(spans):
        for right in spans[index + 1 :]:
            if right.start_beats >= left.end_beats:
                break
            if left.role == right.role:
                continue
            if (
                left.intentional_overlap_id is not None
                and left.intentional_overlap_id == right.intentional_overlap_id
            ):
                continue
            register_overlap = (
                left.register_low is not None
                and left.register_high is not None
                and right.register_low is not None
                and right.register_high is not None
                and max(left.register_low, right.register_low)
                <= min(left.register_high, right.register_high)
            )
            spectral_overlap = (
                left.spectral_band is not None
                and left.spectral_band == right.spectral_band
            )
            transient_competition = (
                left.transient_strength is not None
                and right.transient_strength is not None
                and left.transient_strength >= 0.70
                and right.transient_strength >= 0.70
            )
            density_competition = (
                left.onset_density is not None
                and right.onset_density is not None
                and left.onset_density >= 0.75
                and right.onset_density >= 0.75
            )
            stereo_proximity = (
                left.spatial_position is not None
                and right.spatial_position is not None
                and abs(left.spatial_position - right.spatial_position) <= 0.25
            )
            sustain_overlap = (
                left.sustain is not None
                and right.sustain is not None
                and left.sustain >= 0.70
                and right.sustain >= 0.70
                and (register_overlap or spectral_overlap)
            )
            evidence = []
            if register_overlap:
                evidence.append("overlapping register ranges")
            if spectral_overlap:
                evidence.append(f"shared spectral zone: {left.spectral_band}")
            if transient_competition:
                evidence.append("both roles have strong transient descriptors")
            if density_competition:
                evidence.append(
                    "both roles have high onset density (>= 0.75 events/beat)"
                )
            if stereo_proximity:
                evidence.append(
                    "stereo positions are close (within 0.25 of normalized width)"
                )
            if sustain_overlap:
                evidence.append(
                    "both roles have sustained energy in an overlapping zone"
                )
            if evidence:
                warnings.append(
                    {
                        "kind": "attention_competition",
                        "roles": [left.role, right.role],
                        "semantic_roles": [left.attention_role, right.attention_role],
                        "start_beats": str(max(left.start_beats, right.start_beats)),
                        "end_beats": str(min(left.end_beats, right.end_beats)),
                        "evidence": evidence,
                        "register_overlap": register_overlap,
                        "spectral_overlap": spectral_overlap,
                        "transient_competition": transient_competition,
                        "density_competition": density_competition,
                        "stereo_proximity": stereo_proximity,
                        "sustain_overlap": sustain_overlap,
                        "heuristic_only": True,
                        "review_state": "unreviewed",
                    }
                )
    return tuple(warnings)


def inspect_event_onset_conflicts(
    events: Sequence[Any],
    *,
    tolerance_beats: Beat | int | str = Fraction(0),
    ignore_kinds: tuple[str, ...] = ("marker", "control"),
) -> tuple[dict[str, Any], ...]:
    """List near-simultaneous events from different roles as review prompts."""
    tolerance = _time(tolerance_beats, "onset tolerance")
    ordered = sorted(
        (event for event in events if getattr(event, "kind", None) not in ignore_kinds),
        key=lambda event: (as_fraction(event.onset_beats), str(event.event_id)),
    )
    groups: list[list[Any]] = []
    for event in ordered:
        onset = as_fraction(event.onset_beats)
        if not groups or onset - as_fraction(groups[-1][0].onset_beats) > tolerance:
            groups.append([event])
        else:
            groups[-1].append(event)
    warnings = []
    for group in groups:
        roles = sorted({str(event.voice_id) for event in group})
        if len(roles) < 2:
            continue
        warnings.append(
            {
                "kind": "onset_overlap",
                "onset_beats": str(as_fraction(group[0].onset_beats)),
                "roles": roles,
                "event_ids": sorted(str(event.event_id) for event in group),
                "heuristic_only": True,
            }
        )
    return tuple(warnings)
