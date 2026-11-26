"""M30 transition grammar compiled to canonical Score marker events.

A transition is a bounded three-phase instruction over existing M28/M20 phrase
identity. The model records intent and an atomic scene-change boundary; it does
not create a second playback timeline or silently mutate rendered audio.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Any, Iterable, Mapping

from reawarp.score.events import MusicalEvent
from reawarp.score.model import Score
from reawarp.score.time import as_fraction

TRANSITION_SCHEMA_VERSION = 1
TRANSITION_FORMAT = "eli_lab_reawarp_transition_plan"
TRANSITION_TYPES = frozenset(
    {
        "additive",
        "subtractive",
        "filtered_registral",
        "rhythmic_displacement",
        "metric_reinterpretation",
        "fragmentation",
        "overlap",
        "silence",
        "false_return",
        "motif_bridge",
    }
)
TRANSITION_PHASES = ("preparation", "change", "arrival")
TRANSITION_DIMENSIONS = frozenset(
    {
        "roles",
        "density",
        "register",
        "rhythm",
        "meter",
        "timbre",
        "articulation",
        "harmony",
        "space",
        "texture",
        "motif",
        "silence",
        "energy",
        "dynamics",
        "duration",
        "identity",
    }
)
_TRANSITION_METADATA_KEY = "m30_transition_plans"
_TRANSITION_FINGERPRINT_KEY = "m30_transition_plan_fingerprint"
_MARKER_PARAMETER_KEY = "m30_transition_marker"
_MARKER_VOICE_ID = "transition_director"


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


def _json_object(value: Mapping[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a JSON object")
    try:
        return json.loads(
            json.dumps(dict(value), sort_keys=True, ensure_ascii=False, allow_nan=False)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain finite JSON-compatible values") from exc


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
class TransitionPhase:
    """One exact region in the preparation → change → arrival sequence."""

    phase: str
    start_beats: Fraction
    end_beats: Fraction
    intent: str = ""

    def __post_init__(self) -> None:
        phase = str(self.phase).strip()
        if phase not in TRANSITION_PHASES:
            raise ValueError(
                "transition phase must be one of " + ", ".join(TRANSITION_PHASES)
            )
        start = _beat(self.start_beats, f"{phase} start")
        end = _beat(self.end_beats, f"{phase} end")
        if end <= start:
            raise ValueError(f"{phase} phase must have positive duration")
        object.__setattr__(self, "phase", phase)
        object.__setattr__(self, "start_beats", start)
        object.__setattr__(self, "end_beats", end)
        object.__setattr__(self, "intent", str(self.intent).strip())

    @property
    def duration_beats(self) -> Fraction:
        return self.end_beats - self.start_beats

    @property
    def atomic_scene_commit(self) -> bool:
        """The change phase is a single boundary, never a sequence of role commits."""
        return self.phase == "change"

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "start_beats": str(self.start_beats),
            "end_beats": str(self.end_beats),
            "intent": self.intent,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TransitionPhase":
        return cls(
            phase=str(data.get("phase", "")),
            start_beats=data.get("start_beats", "0"),
            end_beats=data.get("end_beats", "0"),
            intent=str(data.get("intent", "")),
        )


@dataclass(frozen=True, slots=True)
class TransitionPlan:
    """Versioned transition contract referencing two existing Score phrases.

    The three phase intervals are contiguous and use rational quarter-note beats.
    A plan states which dimensions change or remain invariant, the participating
    roles, optional motif bridge, source/target state snapshots and named seed
    lineage. The change phase has one atomic commit boundary.
    """

    transition_id: str
    source_phrase_id: str
    target_phrase_id: str
    transition_type: str
    phases: tuple[TransitionPhase, ...]
    changed_dimensions: tuple[str, ...]
    preserved_dimensions: tuple[str, ...]
    participating_roles: tuple[str, ...]
    source_state: Mapping[str, Any]
    target_state: Mapping[str, Any]
    seed_name: str
    seed: int
    motif_bridge_id: str | None = None
    rationale: str = ""
    schema_version: int = TRANSITION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != TRANSITION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported transition plan schema version: {self.schema_version}"
            )
        for name in (
            "transition_id",
            "source_phrase_id",
            "target_phrase_id",
            "seed_name",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.source_phrase_id == self.target_phrase_id:
            raise ValueError("transition source and target phrases must be different")
        transition_type = str(self.transition_type).strip()
        if transition_type not in TRANSITION_TYPES:
            raise ValueError(
                f"unsupported transition type: {transition_type}; "
                f"expected one of {', '.join(sorted(TRANSITION_TYPES))}"
            )
        object.__setattr__(self, "transition_type", transition_type)

        phases = tuple(
            (
                item
                if isinstance(item, TransitionPhase)
                else TransitionPhase.from_dict(item)
            )
            for item in self.phases
        )
        if (
            len(phases) != 3
            or tuple(item.phase for item in phases) != TRANSITION_PHASES
        ):
            raise ValueError(
                "transition plan requires preparation, change and arrival phases in order"
            )
        if phases[0].end_beats != phases[1].start_beats:
            raise ValueError(
                "preparation and change phases must meet at one exact beat"
            )
        if phases[1].end_beats != phases[2].start_beats:
            raise ValueError("change and arrival phases must meet at one exact beat")
        object.__setattr__(self, "phases", phases)

        changed = tuple(
            _text(item, "changed dimension") for item in self.changed_dimensions
        )
        preserved = tuple(
            _text(item, "preserved dimension") for item in self.preserved_dimensions
        )
        if not changed:
            raise ValueError("transition must declare at least one changed dimension")
        if len(changed) != len(set(changed)) or len(preserved) != len(set(preserved)):
            raise ValueError("changed and preserved dimensions must be unique")
        unknown = (set(changed) | set(preserved)) - TRANSITION_DIMENSIONS
        if unknown:
            raise ValueError(
                "unsupported transition dimensions: " + ", ".join(sorted(unknown))
            )
        overlap = set(changed) & set(preserved)
        if overlap:
            raise ValueError(
                "a transition dimension cannot be both changed and preserved"
            )
        object.__setattr__(self, "changed_dimensions", changed)
        object.__setattr__(self, "preserved_dimensions", preserved)

        roles = tuple(
            _text(item, "participating role") for item in self.participating_roles
        )
        if len(roles) != len(set(roles)):
            raise ValueError("participating roles must be unique")
        object.__setattr__(self, "participating_roles", roles)

        source_state = _json_object(self.source_state, "source_state")
        target_state = _json_object(self.target_state, "target_state")
        object.__setattr__(self, "source_state", source_state)
        object.__setattr__(self, "target_state", target_state)

        if (
            isinstance(self.seed, bool)
            or not isinstance(self.seed, int)
            or self.seed < 0
        ):
            raise ValueError("transition seed must be a non-negative integer")
        if transition_type == "motif_bridge":
            motif_id = _text(self.motif_bridge_id or "", "motif_bridge_id")
            object.__setattr__(self, "motif_bridge_id", motif_id)
        elif self.motif_bridge_id is not None:
            object.__setattr__(
                self, "motif_bridge_id", _text(self.motif_bridge_id, "motif_bridge_id")
            )
        object.__setattr__(self, "rationale", str(self.rationale).strip())

    @property
    def start_beats(self) -> Fraction:
        return self.phases[0].start_beats

    @property
    def change_beat(self) -> Fraction:
        return self.phases[1].start_beats

    @property
    def end_beats(self) -> Fraction:
        return self.phases[-1].end_beats

    @property
    def duration_beats(self) -> Fraction:
        return self.end_beats - self.start_beats

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": TRANSITION_FORMAT,
            "schema_version": self.schema_version,
            "transition_id": self.transition_id,
            "source_phrase_id": self.source_phrase_id,
            "target_phrase_id": self.target_phrase_id,
            "transition_type": self.transition_type,
            "phases": [item.to_dict() for item in self.phases],
            "changed_dimensions": list(self.changed_dimensions),
            "preserved_dimensions": list(self.preserved_dimensions),
            "participating_roles": list(self.participating_roles),
            "source_state": _json_object(self.source_state, "source_state"),
            "target_state": _json_object(self.target_state, "target_state"),
            "seed_name": self.seed_name,
            "seed": self.seed,
            "motif_bridge_id": self.motif_bridge_id,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TransitionPlan":
        if data.get("format") != TRANSITION_FORMAT:
            raise ValueError("not a Reawarp transition plan")
        return cls(
            schema_version=int(data.get("schema_version", 0)),
            transition_id=str(data.get("transition_id", "")),
            source_phrase_id=str(data.get("source_phrase_id", "")),
            target_phrase_id=str(data.get("target_phrase_id", "")),
            transition_type=str(data.get("transition_type", "")),
            phases=tuple(
                TransitionPhase.from_dict(item) for item in data.get("phases", ())
            ),
            changed_dimensions=tuple(data.get("changed_dimensions", ())),
            preserved_dimensions=tuple(data.get("preserved_dimensions", ())),
            participating_roles=tuple(data.get("participating_roles", ())),
            source_state=data.get("source_state", {}),
            target_state=data.get("target_state", {}),
            seed_name=str(data.get("seed_name", "")),
            seed=data.get("seed", 0),
            motif_bridge_id=data.get("motif_bridge_id"),
            rationale=str(data.get("rationale", "")),
        )


def _score_phrase_lookup(score: Score) -> dict[str, Any]:
    phrase_record = score.metadata.get("m28_phrase_plan")
    if isinstance(phrase_record, dict):
        from reawarp.composition.phrases import PhrasePlan

        plan = PhrasePlan.from_score(score)
        return {item.phrase_id: item for item in plan.phrases}

    if score.orchestration_plan is not None:
        from reawarp.score.orchestration_intent import OrchestrationPlan

        plan = OrchestrationPlan.from_dict(score.orchestration_plan)
        return {item.phrase_id: item for item in plan.phrases}

    raise ValueError(
        "transition compilation requires an attached M28 PhrasePlan or M20 OrchestrationPlan"
    )


def _validate_phrase_references(score: Score, plan: TransitionPlan) -> None:
    phrases = _score_phrase_lookup(score)
    source = phrases.get(plan.source_phrase_id)
    target = phrases.get(plan.target_phrase_id)
    if source is None:
        raise ValueError(
            f"transition references unknown source phrase: {plan.source_phrase_id}"
        )
    if target is None:
        raise ValueError(
            f"transition references unknown target phrase: {plan.target_phrase_id}"
        )
    if source.start_beats >= target.start_beats:
        raise ValueError("transition target phrase must follow its source phrase")
    if not source.start_beats <= plan.start_beats < source.end_beats:
        raise ValueError("transition preparation must begin inside its source phrase")
    if not target.start_beats < plan.end_beats <= target.end_beats:
        raise ValueError("transition arrival must extend into its target phrase")


def _marker_event_id(transition_id: str, phase: str) -> str:
    digest = hashlib.sha256(
        f"reawarp:m30:{transition_id}:{phase}".encode("utf-8")
    ).hexdigest()[:24]
    return f"m30-transition-{digest}"


def transition_marker_events(plan: TransitionPlan) -> tuple[MusicalEvent, ...]:
    """Project one transition into non-audio Score markers.

    Three phase-start markers carry the complete contract. A completion marker
    records the half-open end boundary so downstream directors can respect it.
    The change marker contains the complete target state in one event and is
    flagged as the only atomic scene-commit point.
    """
    events: list[MusicalEvent] = []
    for phase in plan.phases:
        marker = {
            "schema_version": TRANSITION_SCHEMA_VERSION,
            "transition_id": plan.transition_id,
            "transition_type": plan.transition_type,
            "phase": phase.phase,
            "phase_start_beats": str(phase.start_beats),
            "phase_end_beats": str(phase.end_beats),
            "intent": phase.intent,
            "source_phrase_id": plan.source_phrase_id,
            "target_phrase_id": plan.target_phrase_id,
            "atomic_scene_commit": phase.atomic_scene_commit,
            "scene_state": (
                _json_object(plan.target_state, "target_state")
                if phase.atomic_scene_commit
                else None
            ),
            "source_state": _json_object(plan.source_state, "source_state"),
            "target_state": _json_object(plan.target_state, "target_state"),
            "changed_dimensions": list(plan.changed_dimensions),
            "preserved_dimensions": list(plan.preserved_dimensions),
            "participating_roles": list(plan.participating_roles),
            "motif_bridge_id": plan.motif_bridge_id,
            "seed_name": plan.seed_name,
            "seed": plan.seed,
        }
        events.append(
            MusicalEvent(
                event_id=_marker_event_id(plan.transition_id, phase.phase),
                voice_id=_MARKER_VOICE_ID,
                onset_beats=phase.start_beats,
                duration_beats=Fraction(0),
                kind="marker",
                velocity=0.0,
                articulation="marker",
                parameters={_MARKER_PARAMETER_KEY: marker},
                tags=("m30_transition", f"m30_phase:{phase.phase}"),
            )
        )

    end = plan.end_beats
    completion = {
        "schema_version": TRANSITION_SCHEMA_VERSION,
        "transition_id": plan.transition_id,
        "transition_type": plan.transition_type,
        "phase": "complete",
        "phase_start_beats": str(end),
        "phase_end_beats": str(end),
        "source_phrase_id": plan.source_phrase_id,
        "target_phrase_id": plan.target_phrase_id,
        "atomic_scene_commit": False,
        "changed_dimensions": list(plan.changed_dimensions),
        "preserved_dimensions": list(plan.preserved_dimensions),
        "participating_roles": list(plan.participating_roles),
        "motif_bridge_id": plan.motif_bridge_id,
        "seed_name": plan.seed_name,
        "seed": plan.seed,
    }
    events.append(
        MusicalEvent(
            event_id=_marker_event_id(plan.transition_id, "complete"),
            voice_id=_MARKER_VOICE_ID,
            onset_beats=end,
            duration_beats=Fraction(0),
            kind="marker",
            velocity=0.0,
            articulation="marker",
            parameters={_MARKER_PARAMETER_KEY: completion},
            tags=("m30_transition", "m30_phase:complete"),
        )
    )
    return tuple(events)


def compile_transition_plans(
    score: Score,
    plans: Iterable[TransitionPlan],
    *,
    replace_existing: bool = True,
) -> Score:
    """Attach M30 transition contracts and phase markers to a canonical Score.

    Plans reference an existing M28 or M20 phrase model. Compilation is
    idempotent by transition ID: replacing a plan replaces only its owned marker
    events. Unrelated Score events and existing orchestration/automation remain
    unchanged.
    """
    if not isinstance(score, Score):
        raise TypeError("score must be a reawarp Score")
    incoming = tuple(
        item if isinstance(item, TransitionPlan) else TransitionPlan.from_dict(item)
        for item in plans
    )
    if not incoming:
        return score
    incoming_ids = [item.transition_id for item in incoming]
    if len(incoming_ids) != len(set(incoming_ids)):
        raise ValueError(
            "transition plan IDs must be unique within one compilation batch"
        )

    existing_records = score.metadata.get(_TRANSITION_METADATA_KEY, [])
    if not isinstance(existing_records, list):
        raise ValueError("Score m30_transition_plans metadata must be an array")
    existing = tuple(TransitionPlan.from_dict(item) for item in existing_records)
    existing_by_id = {item.transition_id: item for item in existing}
    collision = set(incoming_ids) & set(existing_by_id)
    if collision and not replace_existing:
        raise ValueError(
            "transition plan already exists: " + ", ".join(sorted(collision))
        )

    for plan in incoming:
        _validate_phrase_references(score, plan)

    merged_by_id = dict(existing_by_id)
    merged_by_id.update({item.transition_id: item for item in incoming})
    merged = tuple(
        sorted(
            merged_by_id.values(),
            key=lambda item: (item.start_beats, item.change_beat, item.transition_id),
        )
    )

    old_marker_ids = {
        event.event_id for plan in existing for event in transition_marker_events(plan)
    }
    source_events = [
        event for event in score.events if event.event_id not in old_marker_ids
    ]
    source_ids = {event.event_id for event in source_events}
    generated: list[MusicalEvent] = []
    for plan in merged:
        for event in transition_marker_events(plan):
            if event.event_id in source_ids:
                raise ValueError(
                    f"transition marker ID collides with existing Score event: {event.event_id}"
                )
            generated.append(event)
    metadata = copy.deepcopy(score.metadata)
    metadata[_TRANSITION_METADATA_KEY] = [item.to_dict() for item in merged]
    metadata[_TRANSITION_FINGERPRINT_KEY] = _fingerprint(
        metadata[_TRANSITION_METADATA_KEY]
    )
    return replace(score, events=tuple((*source_events, *generated)), metadata=metadata)


def transition_plans_from_score(score: Score) -> tuple[TransitionPlan, ...]:
    """Read and verify M30 plan provenance from a Score."""
    records = score.metadata.get(_TRANSITION_METADATA_KEY, [])
    if not isinstance(records, list):
        raise ValueError("Score m30_transition_plans metadata must be an array")
    plans = tuple(TransitionPlan.from_dict(item) for item in records)
    ids = [item.transition_id for item in plans]
    if len(ids) != len(set(ids)):
        raise ValueError("Score contains duplicate M30 transition plan IDs")
    expected = score.metadata.get(_TRANSITION_FINGERPRINT_KEY)
    if expected and expected != _fingerprint([item.to_dict() for item in plans]):
        raise ValueError("M30 transition plan fingerprint does not match its contents")
    by_id = {event.event_id: event for event in score.events}
    for plan in plans:
        for expected_marker in transition_marker_events(plan):
            actual_marker = by_id.get(expected_marker.event_id)
            if actual_marker != expected_marker:
                raise ValueError(
                    "M30 transition marker is missing or does not match its plan: "
                    f"{plan.transition_id}/{expected_marker.tags[-1]}"
                )
    return plans


@dataclass(frozen=True, slots=True)
class TransitionActuation:
    """Resolved M30 transition state at one exact Score beat.

    This is an immutable planning snapshot for a downstream consumer. It does
    not run inside the audio callback and does not itself render or mutate audio.
    """

    transition_id: str
    at_beats: Fraction
    phase: str
    atomic_scene_commit: bool
    scene_state: Mapping[str, Any]
    participating_roles: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "at_beats", _beat(self.at_beats, "actuation beat"))
        if self.phase not in {*TRANSITION_PHASES, "complete"}:
            raise ValueError("unsupported transition actuation phase")
        object.__setattr__(
            self, "scene_state", _json_object(self.scene_state, "actuation scene_state")
        )
        roles = tuple(
            _text(item, "actuation role") for item in self.participating_roles
        )
        if len(roles) != len(set(roles)):
            raise ValueError("actuation roles must be unique")
        object.__setattr__(self, "participating_roles", roles)


def transition_actuation_at(
    score: Score,
    at_beats: Any,
) -> tuple[TransitionActuation, ...]:
    """Resolve transition phases at an exact Score beat.

    Before the change boundary the source scene remains authoritative. At the
    exact change beat the full target scene is committed atomically; throughout
    change/arrival and at completion the target snapshot is exposed. Multiple
    disjoint transition plans may be returned together for one boundary.
    """
    if not isinstance(score, Score):
        raise TypeError("score must be a reawarp Score")
    beat = _beat(at_beats, "actuation beat")
    resolved: list[TransitionActuation] = []
    for plan in transition_plans_from_score(score):
        if beat < plan.start_beats or beat > plan.end_beats:
            continue
        if beat == plan.end_beats:
            phase = "complete"
        else:
            phase = next(
                (
                    item.phase
                    for item in plan.phases
                    if item.start_beats <= beat < item.end_beats
                ),
                None,
            )
            if phase is None:
                continue
        committed = beat >= plan.change_beat
        resolved.append(
            TransitionActuation(
                transition_id=plan.transition_id,
                at_beats=beat,
                phase=phase,
                atomic_scene_commit=beat == plan.change_beat,
                scene_state=plan.target_state if committed else plan.source_state,
                participating_roles=plan.participating_roles,
            )
        )
    return tuple(resolved)


__all__ = [
    "TRANSITION_DIMENSIONS",
    "TRANSITION_FORMAT",
    "TRANSITION_PHASES",
    "TRANSITION_SCHEMA_VERSION",
    "TRANSITION_TYPES",
    "TransitionPhase",
    "TransitionPlan",
    "compile_transition_plans",
    "transition_marker_events",
    "transition_plans_from_score",
    "TransitionActuation",
    "transition_actuation_at",
]
