"""Independent, deterministic bass-role grammars on shared phrase boundaries."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Sequence

from reawarp.score.events import MusicalEvent
from reawarp.score.pitch import PitchField, Sonority, TuningSystem
from reawarp.score.sonority import generate_sonority
from reawarp.score.time import as_fraction
from reawarp.score.voice_leading import SonorityBoundary, SonoritySequencePlan

_BASS_MODES = {
    "pedal",
    "kick_locked",
    "syncopated_ostinato",
    "independent_cycle",
    "melodic",
    "punctuation",
}
_KICK_RELATIONSHIPS = {"independent", "align", "avoid", "interlock"}
_CADENCE_AVOIDANCE = {"none", "root", "repeat"}


def _number(
    value: object,
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and number < minimum:
        raise ValueError(f"{name} must be at least {minimum:g}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{name} must be at most {maximum:g}")
    return number


def _stable_value(seed: int | str, *parts: object) -> float:
    payload = "|".join(
        (type(seed).__name__, str(seed), *(str(part) for part in parts))
    ).encode("utf-8")
    raw = hashlib.blake2b(payload, digest_size=8).digest()
    return int.from_bytes(raw, "big") / float(2**64)


def _derived_seed(seed: int | str, *parts: object) -> int:
    payload = "|".join(
        (
            "reawarp:m19.4",
            type(seed).__name__,
            str(seed),
            *(str(part) for part in parts),
        )
    ).encode("utf-8")
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")


@dataclass(frozen=True, slots=True)
class BassRoleConfig:
    """Serializable controls for rhythm, register, movement and kick interaction.

    Pitch values and all beat values use Score tuning coordinates and quarter-note
    beats respectively. Density is a deterministic event-retention probability,
    not a velocity or loudness control.
    """

    mode: str = "melodic"
    voice_id: str = "bass"
    density: float = 0.65
    register_min: float = 28.0
    register_max: float = 60.0
    movement_range: float = 12.0
    kick_relationship: str | None = None
    kick_tolerance_beats: str = "1/8"
    interlock_offset_beats: str = "1/4"
    cycle_beats: str = "5/2"
    cycle_pulses: int = 3
    cycle_phase_beats: str = "0"
    steps_per_bar: int = 8
    syncopation: float = 0.7
    note_duration_beats: str = "1/2"
    cadence_avoidance: str = "none"
    cadence_window_beats: str = "1"
    cadence_avoidance_amount: float = 0.75
    velocity: float = 0.82
    seed: int | str = 0

    def __post_init__(self) -> None:
        if self.mode not in _BASS_MODES:
            raise ValueError(f"unsupported bass role mode: {self.mode}")
        if not isinstance(self.voice_id, str) or not self.voice_id.strip():
            raise ValueError("bass voice_id cannot be empty")
        object.__setattr__(
            self, "density", _number(self.density, "density", minimum=0.0, maximum=1.0)
        )
        low = _number(self.register_min, "register_min")
        high = _number(self.register_max, "register_max")
        if low >= high:
            raise ValueError("register_min must be lower than register_max")
        object.__setattr__(self, "register_min", low)
        object.__setattr__(self, "register_max", high)
        object.__setattr__(
            self,
            "movement_range",
            _number(self.movement_range, "movement_range", minimum=0.0),
        )
        relationship = self.kick_relationship
        if relationship is None:
            relationship = "align" if self.mode == "kick_locked" else "independent"
        if relationship not in _KICK_RELATIONSHIPS:
            raise ValueError(
                "kick_relationship must be independent, align, avoid, or interlock"
            )
        if self.mode == "kick_locked" and relationship != "align":
            raise ValueError("kick_locked mode requires kick_relationship='align'")
        if self.mode == "pedal" and relationship != "independent":
            raise ValueError(
                "pedal mode sustains across the phrase and requires independent kick relationship"
            )
        object.__setattr__(self, "kick_relationship", relationship)
        for name in (
            "kick_tolerance_beats",
            "interlock_offset_beats",
            "cycle_beats",
            "cycle_phase_beats",
            "note_duration_beats",
            "cadence_window_beats",
        ):
            value = as_fraction(getattr(self, name))
            if (
                name in {"kick_tolerance_beats", "cycle_beats", "note_duration_beats"}
                and value <= 0
            ):
                raise ValueError(f"{name} must be positive")
            if name in {"interlock_offset_beats", "cadence_window_beats"} and value < 0:
                raise ValueError(f"{name} cannot be negative")
            object.__setattr__(self, name, str(value))
        if (
            isinstance(self.cycle_pulses, bool)
            or not isinstance(self.cycle_pulses, int)
            or not 1 <= self.cycle_pulses <= 32
        ):
            raise ValueError("cycle_pulses must be an integer between 1 and 32")
        if (
            isinstance(self.steps_per_bar, bool)
            or not isinstance(self.steps_per_bar, int)
            or not 1 <= self.steps_per_bar <= 64
        ):
            raise ValueError("steps_per_bar must be an integer between 1 and 64")
        object.__setattr__(
            self,
            "syncopation",
            _number(self.syncopation, "syncopation", minimum=0.0, maximum=1.0),
        )
        if self.cadence_avoidance not in _CADENCE_AVOIDANCE:
            raise ValueError("cadence_avoidance must be none, root, or repeat")
        object.__setattr__(
            self,
            "cadence_avoidance_amount",
            _number(
                self.cadence_avoidance_amount,
                "cadence_avoidance_amount",
                minimum=0.0,
                maximum=1.0,
            ),
        )
        object.__setattr__(
            self,
            "velocity",
            _number(self.velocity, "velocity", minimum=0.0, maximum=1.0),
        )
        if isinstance(self.seed, bool) or not isinstance(self.seed, (int, str)):
            raise ValueError("seed must be an integer or string")

    def to_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "voice_id": self.voice_id,
            "density": self.density,
            "register_min": self.register_min,
            "register_max": self.register_max,
            "movement_range": self.movement_range,
            "kick_relationship": self.kick_relationship,
            "kick_tolerance_beats": self.kick_tolerance_beats,
            "interlock_offset_beats": self.interlock_offset_beats,
            "cycle_beats": self.cycle_beats,
            "cycle_pulses": self.cycle_pulses,
            "cycle_phase_beats": self.cycle_phase_beats,
            "steps_per_bar": self.steps_per_bar,
            "syncopation": self.syncopation,
            "note_duration_beats": self.note_duration_beats,
            "cadence_avoidance": self.cadence_avoidance,
            "cadence_window_beats": self.cadence_window_beats,
            "cadence_avoidance_amount": self.cadence_avoidance_amount,
            "velocity": self.velocity,
            "seed": self.seed,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "BassRoleConfig":
        if not isinstance(data, Mapping):
            raise ValueError("bass role config must be an object")
        allowed = set(cls.__dataclass_fields__)
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(
                "unknown bass config field(s): " + ", ".join(sorted(unknown))
            )
        return cls(**dict(data))


@dataclass(frozen=True, slots=True)
class _BassCandidate:
    onset: object
    duration: object
    boundary_index: int
    pitch_offset: float
    tag: str
    source_kick_id: str | None = None
    phrase_end: object | None = None


@dataclass(frozen=True, slots=True)
class BassRolePlan:
    """Bass events plus the shared form boundaries and reproducible config."""

    boundaries: tuple[SonorityBoundary, ...]
    config: BassRoleConfig
    events: tuple[MusicalEvent, ...]
    kick_event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        boundaries = tuple(self.boundaries)
        if not boundaries:
            raise ValueError("bass role plan requires at least one boundary")
        if any(not isinstance(item, SonorityBoundary) for item in boundaries):
            raise ValueError("bass plan boundaries must be SonorityBoundary records")
        if not isinstance(self.config, BassRoleConfig):
            raise ValueError("bass plan config must be BassRoleConfig")
        events = tuple(self.events)
        if any(not isinstance(item, MusicalEvent) for item in events):
            raise ValueError("bass plan events must be MusicalEvent records")
        if any(
            item.voice_id != self.config.voice_id or item.kind != "note"
            for item in events
        ):
            raise ValueError(
                "bass plan events must be note events on its configured voice"
            )
        ids = [item.event_id for item in events]
        if len(ids) != len(set(ids)):
            raise ValueError("bass event IDs must be unique")
        if any(not math.isfinite(item.pitch or 0.0) for item in events):
            raise ValueError("bass pitches must be finite")
        ordered = tuple(
            sorted(events, key=lambda item: (item.onset_beats, item.event_id))
        )
        kick_ids = tuple(self.kick_event_ids)
        if any(not isinstance(item, str) or not item.strip() for item in kick_ids):
            raise ValueError("kick_event_ids must contain non-empty strings")
        if len(kick_ids) != len(set(kick_ids)):
            raise ValueError("kick_event_ids must be unique")
        object.__setattr__(self, "boundaries", boundaries)
        object.__setattr__(self, "events", ordered)
        object.__setattr__(self, "kick_event_ids", tuple(sorted(kick_ids)))

    def to_dict(self, *, include_events: bool = True) -> dict[str, object]:
        data: dict[str, object] = {
            "format": "eli_lab_reawarp_bass_role_plan",
            "schema_version": 1,
            "config": self.config.to_dict(),
            "boundaries": [item.to_dict() for item in self.boundaries],
            "kick_event_ids": list(self.kick_event_ids),
            "event_ids": [item.event_id for item in self.events],
        }
        if include_events:
            data["events"] = [item.to_dict() for item in self.events]
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "BassRolePlan":
        if data.get("format") != "eli_lab_reawarp_bass_role_plan":
            raise ValueError("data is not a Reawarp bass role plan")
        if int(data.get("schema_version", 1)) != 1:
            raise ValueError("unsupported bass role plan schema version")
        return cls(
            boundaries=tuple(
                SonorityBoundary.from_dict(item) for item in data.get("boundaries", ())
            ),
            config=BassRoleConfig.from_dict(data.get("config", {})),
            events=tuple(
                MusicalEvent.from_dict(item) for item in data.get("events", ())
            ),
            kick_event_ids=tuple(str(item) for item in data.get("kick_event_ids", ())),
        )

    def attach_to_score(self, score):
        """Return a new Score containing the bass notes and their planning metadata."""
        previous_ids = set()
        if score.bass_plan is not None:
            previous_ids = set(score.bass_plan.get("event_ids", ()))
        retained = tuple(
            event for event in score.events if event.event_id not in previous_ids
        )
        new_ids = {event.event_id for event in retained}
        if any(event.event_id in new_ids for event in self.events):
            raise ValueError("bass event IDs collide with existing Score events")
        score_event_map = {event.event_id: event for event in score.events}
        for kick_id in self.kick_event_ids:
            kick = score_event_map.get(kick_id)
            if kick is None or kick.kind != "hit":
                raise ValueError(
                    "bass plan kick provenance must reference kick hit events in the Score"
                )
            if not (
                kick.voice_id.casefold() == "kick"
                or str(kick.parameters.get("source_kind", "")).casefold() == "kick"
                or "kick" in {tag.casefold() for tag in kick.tags}
            ):
                raise ValueError(
                    "bass plan kick provenance references a non-kick Score event"
                )
        plan_record = self.to_dict(include_events=False)
        return replace(score, events=retained + self.events, bass_plan=plan_record)

    @classmethod
    def from_score(cls, score) -> "BassRolePlan":
        if score.bass_plan is None:
            raise ValueError("score does not contain a bass role plan")
        record = dict(score.bass_plan)
        event_ids = tuple(str(item) for item in record.get("event_ids", ()))
        by_id = {event.event_id: event for event in score.events}
        if any(item not in by_id for item in event_ids):
            raise ValueError("Score is missing bass events referenced by bass_plan")
        record["events"] = [by_id[item].to_dict() for item in event_ids]
        return cls.from_dict(record)


def _kick_events(events: Iterable[MusicalEvent]) -> tuple[MusicalEvent, ...]:
    result = []
    for event in events:
        if not isinstance(event, MusicalEvent) or event.kind != "hit":
            continue
        role = event.voice_id.casefold()
        source_kind = str(event.parameters.get("source_kind", "")).casefold()
        tagged = {tag.casefold() for tag in event.tags}
        if role == "kick" or source_kind == "kick" or "kick" in tagged:
            result.append(event)
    return tuple(sorted(result, key=lambda item: (item.onset_beats, item.event_id)))


def _anchor_for(
    boundary: SonorityBoundary,
    sonority: Sonority,
    config: BassRoleConfig,
) -> float:
    if boundary.bass_pitch is not None:
        pitch = boundary.bass_pitch
    elif sonority.bass_pitch is not None:
        pitch = sonority.bass_pitch
    else:
        pitch = min(sonority.pitches)
    pitch = min(config.register_max, max(config.register_min, pitch))
    return float(pitch)


def _event_id(seed: int | str, mode: str, index: int, onset, boundary_id: str) -> str:
    suffix = hashlib.blake2b(
        f"{type(seed).__name__}:{seed}:{mode}:{index}:{onset}:{boundary_id}".encode(
            "utf-8"
        ),
        digest_size=5,
    ).hexdigest()
    return f"bass-{mode}-{index:05d}-{suffix}"


def _inside(value, start, end) -> bool:
    return start <= value < end


def _boundary_ends(boundaries: tuple[SonorityBoundary, ...]):
    starts = [as_fraction(item.onset_beats) for item in boundaries]
    ends = []
    for index, item in enumerate(boundaries):
        end = as_fraction(item.onset_beats) + as_fraction(item.duration_beats)
        if index + 1 < len(boundaries):
            end = min(end, starts[index + 1])
        if end <= starts[index]:
            raise ValueError(
                "bass boundaries must have positive, non-overlapping spans"
            )
        ends.append(end)
    return tuple(starts), tuple(ends)


def _phrase_end_map(
    boundaries: tuple[SonorityBoundary, ...],
    ends: tuple[object, ...],
) -> tuple[object, ...]:
    result = list(ends)
    for index in range(len(boundaries) - 2, -1, -1):
        current = boundaries[index]
        following = boundaries[index + 1]
        if (
            current.section_id == following.section_id
            and current.phrase_id == following.phrase_id
        ):
            result[index] = result[index + 1]
    return tuple(result)


def _phrase_start_map(
    boundaries: tuple[SonorityBoundary, ...],
    starts: tuple[object, ...],
) -> tuple[object, ...]:
    result = list(starts)
    for index in range(1, len(boundaries)):
        current = boundaries[index - 1]
        following = boundaries[index]
        if (
            current.section_id == following.section_id
            and current.phrase_id == following.phrase_id
        ):
            result[index] = result[index - 1]
    return tuple(result)


def _make_sonorities(
    boundaries: tuple[SonorityBoundary, ...],
    tuning: TuningSystem,
    pitch_field: PitchField | None,
    config: BassRoleConfig,
    supplied: Sequence[Sonority] | None,
) -> tuple[Sonority, ...]:
    if supplied is not None:
        sonorities = tuple(supplied)
        if len(sonorities) != len(boundaries):
            raise ValueError("supplied sonorities must match the boundary count")
        if tuple(item.sonority_id for item in sonorities) != tuple(
            item.sonority_id for item in boundaries
        ):
            raise ValueError("supplied sonority IDs must match boundary order")
    else:
        generated = []
        for boundary in boundaries:
            if boundary.pitches:
                generated.append(
                    Sonority(
                        sonority_id=boundary.sonority_id,
                        onset_beats=boundary.onset_beats,
                        duration_beats=boundary.duration_beats,
                        pitches=boundary.pitches,
                        bass_pitch=boundary.bass_pitch,
                        tension=boundary.tension,
                        transform="boundary",
                        transform_parameters={
                            "section_id": boundary.section_id,
                            "phrase_id": boundary.phrase_id,
                        },
                    )
                )
            else:
                seed = _derived_seed(config.seed, boundary.sonority_id)
                generated_sonority = generate_sonority(
                    pitch_field,
                    tuning,
                    sonority_id=boundary.sonority_id,
                    onset_beats=boundary.onset_beats,
                    duration_beats=boundary.duration_beats,
                    voice_count=boundary.voice_count,
                    minimum_pitch=boundary.minimum_pitch,
                    maximum_pitch=boundary.maximum_pitch,
                    pitch_step=boundary.pitch_step,
                    minimum_spacing=boundary.minimum_spacing,
                    maximum_spacing=boundary.maximum_spacing,
                    bass_pitch=boundary.bass_pitch,
                    seed=seed,
                    temperature=boundary.temperature,
                )
                generated.append(generated_sonority)
        sonorities = tuple(generated)

    if pitch_field is not None and pitch_field.hard_constraint:
        for sonority in sonorities:
            checked_pitches = sonority.pitches + (
                () if sonority.bass_pitch is None else (sonority.bass_pitch,)
            )
            rejected = tuple(
                pitch
                for pitch in checked_pitches
                if not pitch_field.evaluate(pitch, tuning).allowed
            )
            if rejected:
                raise ValueError(
                    f"sonority {sonority.sonority_id} violates hard pitch-field "
                    f"constraints: {rejected}"
                )
    return sonorities


def _candidates_for_boundary(
    index: int,
    boundary: SonorityBoundary,
    start,
    end,
    phrase_end,
    rhythm_start,
    anchor: float,
    config: BassRoleConfig,
) -> list[_BassCandidate]:
    duration = as_fraction(config.note_duration_beats)
    result: list[_BassCandidate] = []

    def add(onset, offset, tag, source_kick_id=None, requested_duration=None):
        if _inside(onset, start, end):
            result.append(
                _BassCandidate(
                    onset=onset,
                    duration=min(
                        duration if requested_duration is None else requested_duration,
                        end - onset,
                    ),
                    boundary_index=index,
                    pitch_offset=float(offset),
                    tag=tag,
                    source_kick_id=source_kick_id,
                    phrase_end=phrase_end,
                )
            )

    mode = config.mode
    if mode == "pedal":
        return result
    if mode in {"syncopated_ostinato", "melodic"}:
        step = as_fraction("4") / config.steps_per_bar
        first_pulse = max(0, math.ceil(float((start - rhythm_start) / step) - 1e-12))
        last_pulse = math.ceil(float((end - rhythm_start) / step) - 1e-12)
        offsets = (0.0, 3.0, 7.0, 5.0, 2.0, 9.0, 5.0, -2.0)
        for pulse in range(first_pulse, last_pulse):
            onset = rhythm_start + pulse * step
            offset = 0.0
            tag = "ostinato" if mode == "syncopated_ostinato" else "melodic"
            if mode == "syncopated_ostinato" and pulse % 2 == 1:
                onset += step * as_fraction(str(config.syncopation)) / 2
                offset = offsets[pulse % len(offsets)] * 0.25
            elif mode == "melodic":
                offset = offsets[pulse % len(offsets)]
            add(onset, offset, tag)
    elif mode == "punctuation" and phrase_end == end:
        phrase_span = end - start
        positions = (
            start + max(as_fraction(0), phrase_span - as_fraction("1")),
            start + max(as_fraction(0), phrase_span - as_fraction("1/2")),
        )
        offsets = (7.0, 10.0)
        for onset, offset in zip(positions, offsets):
            add(
                onset,
                offset,
                "punctuation",
                requested_duration=min(duration, end - onset),
            )
    return result


def _apply_kick_relationship(
    candidates: Sequence[_BassCandidate],
    kicks: tuple[MusicalEvent, ...],
    start,
    end,
    config: BassRoleConfig,
    boundary_index: int,
) -> list[_BassCandidate]:
    relationship = config.kick_relationship
    if relationship == "independent":
        return list(candidates)
    tolerance = as_fraction(config.kick_tolerance_beats)
    local_kicks = tuple(
        event for event in kicks if _inside(event.onset_beats, start, end)
    )
    if config.mode == "kick_locked" or relationship == "align":
        aligned = []
        for index, kick in enumerate(local_kicks):
            template = candidates[index % len(candidates)] if candidates else None
            if template is None:
                offset = 0.0
                phrase_end = end
            else:
                offset = template.pitch_offset
                phrase_end = template.phrase_end
            aligned.append(
                _BassCandidate(
                    onset=kick.onset_beats,
                    duration=min(
                        as_fraction(config.note_duration_beats),
                        end - kick.onset_beats,
                    ),
                    boundary_index=boundary_index,
                    pitch_offset=offset,
                    tag=(
                        "kick_locked"
                        if config.mode == "kick_locked"
                        else "kick_aligned"
                    ),
                    source_kick_id=kick.event_id,
                    phrase_end=phrase_end,
                )
            )
        return aligned
    result = []
    offset = as_fraction(config.interlock_offset_beats)
    for candidate in candidates:
        nearest = min(
            local_kicks,
            key=lambda event: (
                abs(event.onset_beats - candidate.onset),
                event.onset_beats,
                event.event_id,
            ),
            default=None,
        )
        if nearest is None or abs(nearest.onset_beats - candidate.onset) > tolerance:
            result.append(candidate)
        elif relationship == "avoid":
            continue
        else:
            shifted = nearest.onset_beats + offset
            if _inside(shifted, start, end):
                result.append(
                    _BassCandidate(
                        onset=shifted,
                        duration=min(candidate.duration, end - shifted),
                        boundary_index=candidate.boundary_index,
                        pitch_offset=candidate.pitch_offset,
                        tag="kick_interlock",
                        source_kick_id=nearest.event_id,
                        phrase_end=candidate.phrase_end,
                    )
                )
    return result


def _cadence_pitch(
    anchor: float,
    pitch: float,
    previous_phrase_end: float | None,
    config: BassRoleConfig,
    *,
    is_phrase_end: bool,
    index: int,
) -> float:
    if not is_phrase_end or config.cadence_avoidance == "none":
        return pitch
    if config.cadence_avoidance == "repeat" and previous_phrase_end is not None:
        if math.isclose(pitch, previous_phrase_end, abs_tol=1e-7):
            pitch += max(1.0, config.movement_range * config.cadence_avoidance_amount)
    elif config.cadence_avoidance == "root" and math.isclose(
        pitch, anchor, abs_tol=1e-7
    ):
        direction = -1.0 if index % 2 else 1.0
        pitch += direction * max(
            1.0, config.movement_range * config.cadence_avoidance_amount
        )
    lower = max(config.register_min, anchor - config.movement_range)
    upper = min(config.register_max, anchor + config.movement_range)
    return min(upper, max(lower, pitch))


def plan_bass_role(
    boundaries: Sequence[SonorityBoundary] | SonoritySequencePlan,
    tuning: TuningSystem,
    *,
    config: BassRoleConfig = BassRoleConfig(),
    kick_events: Iterable[MusicalEvent] = (),
    pitch_field: PitchField | None = None,
    sonorities: Sequence[Sonority] | None = None,
) -> BassRolePlan:
    """Plan an independent bass line over the shared section/phrase boundaries.

    Kick alignment is driven only by supplied score hit events. Other bass modes
    own their pulse grid or cycle, and all modes keep their own pitch motion.
    """
    sequence_plan = boundaries if isinstance(boundaries, SonoritySequencePlan) else None
    boundary_items = (
        sequence_plan.boundaries if sequence_plan is not None else tuple(boundaries)
    )
    if not boundary_items:
        raise ValueError("at least one bass phrase boundary is required")
    if any(not isinstance(item, SonorityBoundary) for item in boundary_items):
        raise ValueError("boundaries must be SonorityBoundary records")
    starts, ends = _boundary_ends(tuple(boundary_items))
    if any(right <= left for left, right in zip(starts, starts[1:])):
        raise ValueError("bass phrase boundaries must be in increasing beat order")
    if sequence_plan is not None:
        if sonorities is not None:
            raise ValueError(
                "pass either a SonoritySequencePlan or sonorities, not both"
            )
        sonorities = sequence_plan.sonorities
    kick_event_items = tuple(kick_events)
    if config.mode == "kick_locked" and not kick_event_items:
        raise ValueError("kick_locked mode requires kick_events from the score")

    sonority_items = _make_sonorities(
        tuple(boundary_items),
        tuning,
        pitch_field,
        config,
        sonorities,
    )
    anchors = tuple(
        _anchor_for(boundary, sonority, config)
        for boundary, sonority in zip(boundary_items, sonority_items)
    )
    kicks = _kick_events(kick_event_items)
    if config.kick_relationship != "independent" and not kicks:
        raise ValueError(
            f"kick_relationship='{config.kick_relationship}' requires kick hit events"
        )

    phrase_ends = _phrase_end_map(tuple(boundary_items), ends)
    phrase_starts = _phrase_start_map(tuple(boundary_items), starts)
    candidates: list[_BassCandidate] = []
    if config.mode == "pedal":
        if (
            config.density > 0
            and _stable_value(config.seed, "pedal", starts[0], ends[-1])
            < config.density
        ):
            start, end = starts[0], ends[-1]
            if end > start:
                candidates.append(
                    _BassCandidate(
                        onset=start,
                        duration=end - start,
                        boundary_index=0,
                        pitch_offset=0.0,
                        tag="pedal",
                        phrase_end=phrase_ends[-1],
                    )
                )
    elif config.mode == "kick_locked":
        for index, (boundary, start, end) in enumerate(
            zip(boundary_items, starts, ends)
        ):
            for kick in kicks:
                if _inside(kick.onset_beats, start, end):
                    candidates.append(
                        _BassCandidate(
                            onset=kick.onset_beats,
                            duration=min(
                                as_fraction(config.note_duration_beats),
                                end - kick.onset_beats,
                            ),
                            boundary_index=index,
                            pitch_offset=0.0,
                            tag="kick_locked",
                            source_kick_id=kick.event_id,
                            phrase_end=phrase_ends[index],
                        )
                    )
    elif config.mode == "independent_cycle":
        cycle = as_fraction(config.cycle_beats)
        phase = as_fraction(config.cycle_phase_beats)
        pulse = cycle / config.cycle_pulses
        global_start, global_end = starts[0], ends[-1]
        first_index = math.floor(float((global_start - phase) / pulse))
        last_index = math.ceil(float((global_end - phase) / pulse))
        for cycle_index in range(first_index, last_index + 1):
            onset = phase + cycle_index * pulse
            if not _inside(onset, global_start, global_end):
                continue
            boundary_index = next(
                (
                    i
                    for i, (start, end) in enumerate(zip(starts, ends))
                    if _inside(onset, start, end)
                ),
                None,
            )
            if boundary_index is None:
                continue
            candidates.append(
                _BassCandidate(
                    onset=onset,
                    duration=min(
                        as_fraction(config.note_duration_beats),
                        ends[boundary_index] - onset,
                    ),
                    boundary_index=boundary_index,
                    pitch_offset=(0.0, 5.0, -2.0)[cycle_index % 3],
                    tag="independent_cycle",
                    phrase_end=phrase_ends[boundary_index],
                )
            )
    else:
        for index, (boundary, start, end) in enumerate(
            zip(boundary_items, starts, ends)
        ):
            candidates.extend(
                _candidates_for_boundary(
                    index,
                    boundary,
                    start,
                    end,
                    phrase_ends[index],
                    phrase_starts[index],
                    anchors[index],
                    config,
                )
            )

    if config.mode not in {"kick_locked", "pedal"}:
        adjusted: list[_BassCandidate] = []
        for index, (start, end) in enumerate(zip(starts, ends)):
            local = [item for item in candidates if item.boundary_index == index]
            adjusted.extend(
                _apply_kick_relationship(
                    local,
                    kicks,
                    start,
                    end,
                    config,
                    index,
                )
            )
        candidates = adjusted

    retained = []
    for index, candidate in enumerate(
        sorted(
            candidates,
            key=lambda item: (
                item.onset,
                item.boundary_index,
                item.tag,
                item.source_kick_id or "",
            ),
        )
    ):
        if (
            config.density < 1.0
            and _stable_value(
                config.seed,
                candidate.onset,
                candidate.boundary_index,
                candidate.tag,
                index,
            )
            >= config.density
        ):
            continue
        retained.append(candidate)

    events = []
    grouped_candidates: list[list[_BassCandidate]] = []
    for candidate in retained:
        boundary = boundary_items[candidate.boundary_index]
        phrase_key = (boundary.section_id, boundary.phrase_id)
        if not grouped_candidates:
            grouped_candidates.append([candidate])
            continue
        prior = grouped_candidates[-1][-1]
        prior_boundary = boundary_items[prior.boundary_index]
        prior_key = (prior_boundary.section_id, prior_boundary.phrase_id)
        if phrase_key == prior_key:
            grouped_candidates[-1].append(candidate)
        else:
            grouped_candidates.append([candidate])

    previous_phrase_end: float | None = None
    event_index = 0
    for phrase_candidates in grouped_candidates:
        phrase_events = []
        for candidate in phrase_candidates:
            boundary = boundary_items[candidate.boundary_index]
            anchor = anchors[candidate.boundary_index]
            raw_pitch = anchor + candidate.pitch_offset
            phrase_end = phrase_ends[candidate.boundary_index]
            is_phrase_end = candidate.onset >= phrase_end - as_fraction(
                config.cadence_window_beats
            )
            pitch = _cadence_pitch(
                anchor,
                raw_pitch,
                previous_phrase_end,
                config,
                is_phrase_end=is_phrase_end,
                index=event_index,
            )
            pitch = min(
                anchor + config.movement_range,
                max(anchor - config.movement_range, pitch),
            )
            pitch = min(config.register_max, max(config.register_min, pitch))
            if (
                pitch_field is not None
                and pitch_field.hard_constraint
                and not pitch_field.evaluate(pitch, tuning).allowed
            ):
                raise ValueError(
                    f"bass pitch {pitch:g} violates hard pitch-field constraints"
                )
            if candidate.duration <= 0:
                continue
            event_id = _event_id(
                config.seed,
                config.mode,
                event_index,
                candidate.onset,
                boundary.sonority_id,
            )
            params = {
                "planner": "m19.4_bass_role",
                "bass_mode": config.mode,
                "section_id": boundary.section_id,
                "phrase_id": boundary.phrase_id,
                "boundary_id": boundary.sonority_id,
                "pattern": candidate.tag,
                "pitch_anchor": anchor,
                "pitch_offset": candidate.pitch_offset,
                "kick_relationship": config.kick_relationship,
                "cadence_avoidance": config.cadence_avoidance,
                "movement_range": config.movement_range,
            }
            if candidate.source_kick_id is not None:
                params["kick_event_id"] = candidate.source_kick_id
            event = MusicalEvent(
                event_id=event_id,
                voice_id=config.voice_id,
                onset_beats=candidate.onset,
                duration_beats=candidate.duration,
                kind="note",
                pitch=pitch,
                frequency_hz=tuning.frequency_for_pitch(pitch),
                velocity=config.velocity,
                articulation="bass",
                parameters=params,
                tags=("bass", config.mode, candidate.tag),
                source_id=boundary.sonority_id,
                seed=_derived_seed(config.seed, event_id),
                tuning_id=tuning.identifier,
            )
            events.append(event)
            phrase_events.append(event)
            event_index += 1
        if phrase_events:
            previous_phrase_end = phrase_events[-1].pitch

    kick_ids = tuple(
        str(event.parameters["kick_event_id"])
        for event in events
        if "kick_event_id" in event.parameters
    )
    return BassRolePlan(
        boundaries=tuple(boundary_items),
        config=config,
        events=tuple(events),
        kick_event_ids=kick_ids,
    )
