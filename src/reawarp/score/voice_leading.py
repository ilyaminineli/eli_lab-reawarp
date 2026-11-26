"""Sequence-level sonority planning and configurable melodic voice leading."""

from __future__ import annotations

import hashlib
import heapq
import itertools
import math
from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

from reawarp.score.harmony import VoiceLeadingWeights
from reawarp.score.pitch import PitchField, Sonority, TuningSystem
from reawarp.score.sonority import generate_sonority
from reawarp.score.time import as_fraction


def _finite(value: object, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or (minimum is not None and number < minimum):
        suffix = "" if minimum is None else f" and at least {minimum:g}"
        raise ValueError(f"{name} must be finite{suffix}")
    return number


@dataclass(frozen=True, slots=True)
class VoiceRoleTarget:
    """A named melodic role's preferred pitch and/or permitted register at one boundary."""

    voice_id: str
    role: str
    preferred_pitch: float | None = None
    register_min: float | None = None
    register_max: float | None = None
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not self.voice_id.strip() or not self.role.strip():
            raise ValueError("voice role requires non-empty voice_id and role")
        for name in ("preferred_pitch", "register_min", "register_max"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _finite(value, name))
        if (
            self.register_min is not None
            and self.register_max is not None
            and self.register_min > self.register_max
        ):
            raise ValueError("role register_min cannot exceed register_max")
        object.__setattr__(
            self, "weight", _finite(self.weight, "role weight", minimum=0.0)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "voice_id": self.voice_id,
            "role": self.role,
            "preferred_pitch": self.preferred_pitch,
            "register_min": self.register_min,
            "register_max": self.register_max,
            "weight": self.weight,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "VoiceRoleTarget":
        return cls(
            voice_id=str(data.get("voice_id", "")),
            role=str(data.get("role", "")),
            preferred_pitch=(
                None
                if data.get("preferred_pitch") is None
                else float(data["preferred_pitch"])
            ),
            register_min=(
                None
                if data.get("register_min") is None
                else float(data["register_min"])
            ),
            register_max=(
                None
                if data.get("register_max") is None
                else float(data["register_max"])
            ),
            weight=float(data.get("weight", 1.0)),
        )


@dataclass(frozen=True, slots=True)
class VoiceLeadingConstraints:
    """Hard limits. With defaults, crossing and unresolved motion remain available."""

    maximum_leap: float | None = None
    minimum_motion: float | None = None
    maximum_motion: float | None = None
    allow_voice_crossing: bool = True
    maximum_voice_crossings: int | None = None
    minimum_common_tones: int = 0
    common_tone_tolerance: float = 1e-7
    hard_role_registers: bool = False

    def __post_init__(self) -> None:
        for name in ("maximum_leap", "minimum_motion", "maximum_motion"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _finite(value, name, minimum=0.0))
        if (
            self.minimum_motion is not None
            and self.maximum_motion is not None
            and self.minimum_motion > self.maximum_motion
        ):
            raise ValueError("minimum_motion cannot exceed maximum_motion")
        if not isinstance(self.allow_voice_crossing, bool):
            raise ValueError("allow_voice_crossing must be a boolean")
        if not isinstance(self.hard_role_registers, bool):
            raise ValueError("hard_role_registers must be a boolean")
        for name in ("maximum_voice_crossings", "minimum_common_tones"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer or None")
        object.__setattr__(
            self,
            "common_tone_tolerance",
            _finite(self.common_tone_tolerance, "common_tone_tolerance", minimum=0.0),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "maximum_leap": self.maximum_leap,
            "minimum_motion": self.minimum_motion,
            "maximum_motion": self.maximum_motion,
            "allow_voice_crossing": self.allow_voice_crossing,
            "maximum_voice_crossings": self.maximum_voice_crossings,
            "minimum_common_tones": self.minimum_common_tones,
            "common_tone_tolerance": self.common_tone_tolerance,
            "hard_role_registers": self.hard_role_registers,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "VoiceLeadingConstraints":
        return cls(
            maximum_leap=(
                None
                if data.get("maximum_leap") is None
                else float(data["maximum_leap"])
            ),
            minimum_motion=(
                None
                if data.get("minimum_motion") is None
                else float(data["minimum_motion"])
            ),
            maximum_motion=(
                None
                if data.get("maximum_motion") is None
                else float(data["maximum_motion"])
            ),
            allow_voice_crossing=bool(data.get("allow_voice_crossing", True)),
            maximum_voice_crossings=(
                None
                if data.get("maximum_voice_crossings") is None
                else int(data["maximum_voice_crossings"])
            ),
            minimum_common_tones=int(data.get("minimum_common_tones", 0)),
            common_tone_tolerance=float(data.get("common_tone_tolerance", 1e-7)),
            hard_role_registers=bool(data.get("hard_role_registers", False)),
        )


@dataclass(frozen=True, slots=True)
class VoiceLeadingPreferences:
    """Named motion behaviours and explicit common-tone/crossing intent."""

    motion_styles: tuple[str, ...] = ()
    retain_common_tones: bool = True
    crossing: str = "avoid"

    def __post_init__(self) -> None:
        allowed = {"contrary", "oblique", "parallel"}
        styles = tuple(self.motion_styles)
        if len(styles) != len(set(styles)) or any(
            item not in allowed for item in styles
        ):
            raise ValueError(
                "motion_styles may contain unique values from contrary, oblique, parallel"
            )
        canonical = tuple(
            item for item in ("contrary", "oblique", "parallel") if item in styles
        )
        object.__setattr__(self, "motion_styles", canonical)
        if not isinstance(self.retain_common_tones, bool):
            raise ValueError("retain_common_tones must be a boolean")
        if self.crossing not in {"avoid", "neutral", "prefer"}:
            raise ValueError("crossing preference must be avoid, neutral, or prefer")

    def to_dict(self) -> dict[str, object]:
        return {
            "motion_styles": list(self.motion_styles),
            "retain_common_tones": self.retain_common_tones,
            "crossing": self.crossing,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "VoiceLeadingPreferences":
        return cls(
            motion_styles=tuple(str(item) for item in data.get("motion_styles", ())),
            retain_common_tones=bool(data.get("retain_common_tones", True)),
            crossing=str(data.get("crossing", "avoid")),
        )


@dataclass(frozen=True, slots=True)
class VoiceLeadingPlanConfig:
    """Serializable controls for the full sonority sequence search."""

    weights: VoiceLeadingWeights = VoiceLeadingWeights()
    constraints: VoiceLeadingConstraints = VoiceLeadingConstraints()
    preferences: VoiceLeadingPreferences = VoiceLeadingPreferences()
    voice_ids: tuple[str, ...] = ()
    beam_width: int = 16
    seed: int | str = 0

    def __post_init__(self) -> None:
        if not isinstance(self.weights, VoiceLeadingWeights):
            raise ValueError("weights must be VoiceLeadingWeights")
        if not isinstance(self.constraints, VoiceLeadingConstraints):
            raise ValueError("constraints must be VoiceLeadingConstraints")
        if not isinstance(self.preferences, VoiceLeadingPreferences):
            raise ValueError("preferences must be VoiceLeadingPreferences")
        if (
            isinstance(self.beam_width, bool)
            or not isinstance(self.beam_width, int)
            or not 1 <= self.beam_width <= 64
        ):
            raise ValueError("beam_width must be an integer between 1 and 64")
        if isinstance(self.seed, bool) or not isinstance(self.seed, (int, str)):
            raise ValueError("seed must be an integer or string")
        voices = tuple(self.voice_ids)
        if any(not isinstance(item, str) or not item.strip() for item in voices):
            raise ValueError("voice_ids must contain non-empty strings")
        if len(voices) != len(set(voices)):
            raise ValueError("voice_ids must be unique")
        object.__setattr__(self, "voice_ids", voices)
        if (
            self.preferences.crossing == "prefer"
            and not self.constraints.allow_voice_crossing
        ):
            raise ValueError(
                "crossing preference 'prefer' conflicts with allow_voice_crossing=False"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "weights": self.weights.to_dict(),
            "constraints": self.constraints.to_dict(),
            "preferences": self.preferences.to_dict(),
            "voice_ids": list(self.voice_ids),
            "beam_width": self.beam_width,
            "seed": self.seed,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "VoiceLeadingPlanConfig":
        return cls(
            weights=VoiceLeadingWeights.from_dict(dict(data.get("weights", {}))),
            constraints=VoiceLeadingConstraints.from_dict(
                dict(data.get("constraints", {}))
            ),
            preferences=VoiceLeadingPreferences.from_dict(
                dict(data.get("preferences", {}))
            ),
            voice_ids=tuple(str(item) for item in data.get("voice_ids", ())),
            beam_width=int(data.get("beam_width", 16)),
            seed=data.get("seed", 0),
        )


@dataclass(frozen=True, slots=True)
class SonorityBoundary:
    """One section/phrase sonority boundary and its local generation/role targets."""

    sonority_id: str
    onset_beats: str
    duration_beats: str
    section_id: str = "section-1"
    phrase_id: str = "phrase-1"
    pitches: tuple[float, ...] = ()
    bass_pitch: float | None = None
    tension: float = 0.0
    voice_count: int = 4
    minimum_pitch: float = 48.0
    maximum_pitch: float = 84.0
    pitch_step: float = 1.0
    minimum_spacing: float = 0.0
    maximum_spacing: float | None = None
    temperature: float = 0.0
    voice_roles: tuple[VoiceRoleTarget, ...] = ()

    def __post_init__(self) -> None:
        from reawarp.score.time import as_fraction

        if not isinstance(self.sonority_id, str) or not self.sonority_id.strip():
            raise ValueError("sonority boundary requires a non-empty sonority_id")
        if not self.section_id.strip() or not self.phrase_id.strip():
            raise ValueError("section_id and phrase_id cannot be empty")
        onset = as_fraction(self.onset_beats)
        duration = as_fraction(self.duration_beats)
        if onset < 0 or duration <= 0:
            raise ValueError(
                "boundary onset must be non-negative and duration positive"
            )
        if (
            isinstance(self.voice_count, bool)
            or not isinstance(self.voice_count, int)
            or not 1 <= self.voice_count <= 8
        ):
            raise ValueError("voice_count must be an integer between 1 and 8")
        pitches = tuple(_finite(item, "boundary pitch") for item in self.pitches)
        if pitches and len(pitches) != self.voice_count:
            raise ValueError("explicit boundary pitches must match voice_count")
        if self.bass_pitch is not None:
            object.__setattr__(
                self, "bass_pitch", _finite(self.bass_pitch, "bass_pitch")
            )
        object.__setattr__(self, "tension", _finite(self.tension, "tension"))
        low = _finite(self.minimum_pitch, "minimum_pitch")
        high = _finite(self.maximum_pitch, "maximum_pitch")
        step = _finite(self.pitch_step, "pitch_step", minimum=0.0)
        min_gap = _finite(self.minimum_spacing, "minimum_spacing", minimum=0.0)
        max_gap = (
            None
            if self.maximum_spacing is None
            else _finite(self.maximum_spacing, "maximum_spacing", minimum=0.0)
        )
        temperature = _finite(self.temperature, "temperature", minimum=0.0)
        if low > high or step <= 0 or (max_gap is not None and max_gap < min_gap):
            raise ValueError("invalid boundary pitch range, step, or spacing")
        roles = tuple(self.voice_roles)
        if any(not isinstance(item, VoiceRoleTarget) for item in roles):
            raise ValueError("voice_roles must contain VoiceRoleTarget records")
        role_ids = [item.voice_id for item in roles]
        if len(role_ids) != len(set(role_ids)):
            raise ValueError("voice role targets must be unique per voice")
        object.__setattr__(self, "onset_beats", str(onset))
        object.__setattr__(self, "duration_beats", str(duration))
        object.__setattr__(self, "pitches", tuple(sorted(pitches)))
        object.__setattr__(self, "minimum_pitch", low)
        object.__setattr__(self, "maximum_pitch", high)
        object.__setattr__(self, "pitch_step", step)
        object.__setattr__(self, "minimum_spacing", min_gap)
        object.__setattr__(self, "maximum_spacing", max_gap)
        object.__setattr__(self, "temperature", temperature)
        object.__setattr__(self, "voice_roles", roles)

    def to_dict(self) -> dict[str, object]:
        return {
            "sonority_id": self.sonority_id,
            "onset_beats": self.onset_beats,
            "duration_beats": self.duration_beats,
            "section_id": self.section_id,
            "phrase_id": self.phrase_id,
            "pitches": list(self.pitches),
            "bass_pitch": self.bass_pitch,
            "tension": self.tension,
            "voice_count": self.voice_count,
            "minimum_pitch": self.minimum_pitch,
            "maximum_pitch": self.maximum_pitch,
            "pitch_step": self.pitch_step,
            "minimum_spacing": self.minimum_spacing,
            "maximum_spacing": self.maximum_spacing,
            "temperature": self.temperature,
            "voice_roles": [item.to_dict() for item in self.voice_roles],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "SonorityBoundary":
        return cls(
            sonority_id=str(data.get("sonority_id", "")),
            onset_beats=str(data.get("onset_beats", "0")),
            duration_beats=str(data.get("duration_beats", "1")),
            section_id=str(data.get("section_id", "section-1")),
            phrase_id=str(data.get("phrase_id", "phrase-1")),
            pitches=tuple(float(item) for item in data.get("pitches", ())),
            bass_pitch=(
                None if data.get("bass_pitch") is None else float(data["bass_pitch"])
            ),
            tension=float(data.get("tension", 0.0)),
            voice_count=int(data.get("voice_count", 4)),
            minimum_pitch=float(data.get("minimum_pitch", 48.0)),
            maximum_pitch=float(data.get("maximum_pitch", 84.0)),
            pitch_step=float(data.get("pitch_step", 1.0)),
            minimum_spacing=float(data.get("minimum_spacing", 0.0)),
            maximum_spacing=(
                None
                if data.get("maximum_spacing") is None
                else float(data["maximum_spacing"])
            ),
            temperature=float(data.get("temperature", 0.0)),
            voice_roles=tuple(
                VoiceRoleTarget.from_dict(item) for item in data.get("voice_roles", ())
            ),
        )


@dataclass(frozen=True, slots=True)
class VoiceLeadingTransition:
    """Auditable mapping between two adjacent sonorities."""

    source_sonority_id: str
    target_sonority_id: str
    source_section_id: str
    target_section_id: str
    source_phrase_id: str
    target_phrase_id: str
    assignments: tuple[tuple[str, float, float], ...]
    total_cost: float
    cost_components: tuple[tuple[str, float], ...]
    crossed_pairs: tuple[tuple[str, str], ...]
    motion_types: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "source_sonority_id": self.source_sonority_id,
            "target_sonority_id": self.target_sonority_id,
            "source_section_id": self.source_section_id,
            "target_section_id": self.target_section_id,
            "source_phrase_id": self.source_phrase_id,
            "target_phrase_id": self.target_phrase_id,
            "assignments": [list(item) for item in self.assignments],
            "total_cost": self.total_cost,
            "cost_components": [list(item) for item in self.cost_components],
            "crossed_pairs": [list(item) for item in self.crossed_pairs],
            "motion_types": list(self.motion_types),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "VoiceLeadingTransition":
        return cls(
            source_sonority_id=str(data["source_sonority_id"]),
            target_sonority_id=str(data["target_sonority_id"]),
            source_section_id=str(data["source_section_id"]),
            target_section_id=str(data["target_section_id"]),
            source_phrase_id=str(data["source_phrase_id"]),
            target_phrase_id=str(data["target_phrase_id"]),
            assignments=tuple(
                (str(item[0]), float(item[1]), float(item[2]))
                for item in data.get("assignments", ())
            ),
            total_cost=_finite(data.get("total_cost", 0.0), "transition total_cost"),
            cost_components=tuple(
                (str(item[0]), _finite(item[1], "transition cost component"))
                for item in data.get("cost_components", ())
            ),
            crossed_pairs=tuple(
                (str(item[0]), str(item[1])) for item in data.get("crossed_pairs", ())
            ),
            motion_types=tuple(str(item) for item in data.get("motion_types", ())),
        )


@dataclass(frozen=True, slots=True)
class _BeamState:
    total_cost: float
    voicings: tuple[tuple[float, ...], ...]
    transitions: tuple[VoiceLeadingTransition, ...]


@dataclass(frozen=True, slots=True)
class SonoritySequencePlan:
    """Complete sequence plan, including chosen melodic lines and cost provenance."""

    boundaries: tuple[SonorityBoundary, ...]
    sonorities: tuple[Sonority, ...]
    voice_ids: tuple[str, ...]
    voicings: tuple[tuple[float, ...], ...]
    initial_cost_components: tuple[tuple[str, float], ...]
    transitions: tuple[VoiceLeadingTransition, ...]
    total_cost: float
    config: VoiceLeadingPlanConfig

    def __post_init__(self) -> None:
        count = len(self.boundaries)
        if count == 0 or len(self.sonorities) != count or len(self.voicings) != count:
            raise ValueError(
                "a sequence plan requires one sonority and voicing per boundary"
            )
        if len(self.transitions) != count - 1:
            raise ValueError(
                "sequence plan transition count must be boundary count minus one"
            )
        if len(self.voice_ids) == 0 or len(self.voice_ids) > 8:
            raise ValueError("sequence plan requires one to eight voice IDs")
        if any(len(item) != len(self.voice_ids) for item in self.voicings):
            raise ValueError("every planned voicing must match the voice ID count")
        if any(
            not math.isfinite(float(value)) for row in self.voicings for value in row
        ):
            raise ValueError("planned voicings must contain finite pitches")
        if not math.isfinite(float(self.total_cost)):
            raise ValueError("sequence plan total_cost must be finite")
        expected_ids = tuple(item.sonority_id for item in self.sonorities)
        if expected_ids != tuple(item.sonority_id for item in self.boundaries):
            raise ValueError("sequence sonority IDs must match the boundary order")

    def to_dict(self, *, include_sonorities: bool = True) -> dict[str, object]:
        result: dict[str, object] = {
            "format": "eli_lab_reawarp_sonority_sequence_plan",
            "schema_version": 1,
            "config": self.config.to_dict(),
            "boundaries": [item.to_dict() for item in self.boundaries],
            "voice_ids": list(self.voice_ids),
            "voicings": [list(item) for item in self.voicings],
            "initial_cost_components": [
                list(item) for item in self.initial_cost_components
            ],
            "transitions": [item.to_dict() for item in self.transitions],
            "total_cost": self.total_cost,
        }
        if include_sonorities:
            result["sonorities"] = [item.to_score_record() for item in self.sonorities]
        return result

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "SonoritySequencePlan":
        if data.get("format") != "eli_lab_reawarp_sonority_sequence_plan":
            raise ValueError("data is not a Reawarp sonority sequence plan")
        if int(data.get("schema_version", 1)) != 1:
            raise ValueError("unsupported sonority sequence plan schema version")
        return cls(
            boundaries=tuple(
                SonorityBoundary.from_dict(item) for item in data.get("boundaries", ())
            ),
            sonorities=tuple(
                Sonority.from_score_record(item) for item in data.get("sonorities", ())
            ),
            voice_ids=tuple(str(item) for item in data.get("voice_ids", ())),
            voicings=tuple(
                tuple(float(value) for value in item)
                for item in data.get("voicings", ())
            ),
            initial_cost_components=tuple(
                (str(item[0]), _finite(item[1], "initial cost component"))
                for item in data.get("initial_cost_components", ())
            ),
            transitions=tuple(
                VoiceLeadingTransition.from_dict(item)
                for item in data.get("transitions", ())
            ),
            total_cost=_finite(data.get("total_cost", 0.0), "plan total_cost"),
            config=VoiceLeadingPlanConfig.from_dict(data.get("config", {})),
        )

    def attach_to_score(self, score):
        """Return a new Score with planned sonorities and a compact plan record."""
        return replace(
            score,
            sonorities=tuple(item.to_score_record() for item in self.sonorities),
            sonority_plan=self.to_dict(include_sonorities=False),
        )

    @classmethod
    def from_score(cls, score) -> "SonoritySequencePlan":
        """Restore a plan attached by attach_to_score()."""
        if score.sonority_plan is None:
            raise ValueError("score does not contain a sonority sequence plan")
        data = dict(score.sonority_plan)
        data["sonorities"] = list(score.sonorities)
        return cls.from_dict(data)


def _derived_seed(seed: int | str, sonority_id: str) -> int:
    payload = f"reawarp:m19.3:{type(seed).__name__}:{seed}:{sonority_id}".encode(
        "utf-8"
    )
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")


def _build_sonority(
    boundary: SonorityBoundary,
    tuning: TuningSystem,
    pitch_field: PitchField | None,
    seed: int | str,
) -> Sonority:
    provenance = {
        "boundary_id": boundary.sonority_id,
        "section_id": boundary.section_id,
        "phrase_id": boundary.phrase_id,
    }
    if boundary.pitches:
        if pitch_field is not None and pitch_field.hard_constraint:
            checked_pitches = boundary.pitches + (
                () if boundary.bass_pitch is None else (boundary.bass_pitch,)
            )
            rejected = tuple(
                pitch
                for pitch in checked_pitches
                if not pitch_field.evaluate(pitch, tuning).allowed
            )
            if rejected:
                raise ValueError(
                    f"explicit sonority {boundary.sonority_id} violates hard "
                    f"pitch-field constraints: {rejected}"
                )
        return Sonority(
            sonority_id=boundary.sonority_id,
            onset_beats=boundary.onset_beats,
            duration_beats=boundary.duration_beats,
            pitches=boundary.pitches,
            bass_pitch=boundary.bass_pitch,
            tension=boundary.tension,
            transform="boundary",
            transform_parameters={**provenance, "pitch_source": "explicit"},
        )
    generated_seed = _derived_seed(seed, boundary.sonority_id)
    generated = generate_sonority(
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
        seed=generated_seed,
        temperature=boundary.temperature,
    )
    return Sonority(
        sonority_id=generated.sonority_id,
        onset_beats=generated.onset_beats,
        duration_beats=generated.duration_beats,
        pitches=generated.pitches,
        bass_pitch=generated.bass_pitch,
        tension=generated.tension,
        transform=generated.transform,
        source_sonority_id=generated.source_sonority_id,
        transform_parameters={
            **dict(generated.transform_parameters),
            **provenance,
            "generation_seed": generated_seed,
        },
    )


def _roles_by_voice(
    boundary: SonorityBoundary,
    voice_ids: tuple[str, ...],
) -> dict[str, VoiceRoleTarget]:
    known = set(voice_ids)
    unknown = sorted({item.voice_id for item in boundary.voice_roles} - known)
    if unknown:
        raise ValueError(
            f"boundary {boundary.sonority_id} has role targets for unknown voice(s): "
            + ", ".join(unknown)
        )
    return {item.voice_id: item for item in boundary.voice_roles}


def _role_costs(
    voicing: tuple[float, ...],
    voice_ids: tuple[str, ...],
    roles: Mapping[str, VoiceRoleTarget],
    config: VoiceLeadingPlanConfig,
) -> tuple[float, float] | None:
    register_distance = 0.0
    role_distance = 0.0
    for voice_id, pitch in zip(voice_ids, voicing):
        role = roles.get(voice_id)
        if role is None:
            continue
        below = (
            0.0 if role.register_min is None else max(0.0, role.register_min - pitch)
        )
        above = (
            0.0 if role.register_max is None else max(0.0, pitch - role.register_max)
        )
        outside = below + above
        if config.constraints.hard_role_registers and outside > 1e-9:
            return None
        register_distance += role.weight * outside
        preferred = role.preferred_pitch
        if preferred is None:
            if role.register_min is not None and role.register_max is not None:
                preferred = (role.register_min + role.register_max) / 2.0
            elif role.register_min is not None:
                preferred = role.register_min
            elif role.register_max is not None:
                preferred = role.register_max
        if preferred is not None:
            role_distance += role.weight * abs(pitch - preferred)
    return (
        config.weights.register_crossing * register_distance,
        config.weights.target_role * role_distance,
    )


def _crossed_voice_pairs(
    source: tuple[float, ...],
    target: tuple[float, ...],
    voice_ids: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    pairs = []
    for left in range(len(source)):
        for right in range(left + 1, len(source)):
            before = source[left] - source[right]
            after = target[left] - target[right]
            if (before > 1e-9 and after < -1e-9) or (before < -1e-9 and after > 1e-9):
                pairs.append((voice_ids[left], voice_ids[right]))
    return tuple(pairs)


def _score_transition(
    source: tuple[float, ...],
    target: tuple[float, ...],
    voice_ids: tuple[str, ...],
    source_boundary: SonorityBoundary,
    target_boundary: SonorityBoundary,
    config: VoiceLeadingPlanConfig,
) -> VoiceLeadingTransition | None:
    constraints = config.constraints
    weights = config.weights
    deltas = tuple(target[index] - source[index] for index in range(len(source)))
    distances = tuple(abs(value) for value in deltas)
    motion = sum(distances)
    common_tones = sum(
        distance <= constraints.common_tone_tolerance for distance in distances
    )
    if constraints.maximum_leap is not None and any(
        distance > constraints.maximum_leap + 1e-9 for distance in distances
    ):
        return None
    if (
        constraints.minimum_motion is not None
        and motion < constraints.minimum_motion - 1e-9
    ):
        return None
    if (
        constraints.maximum_motion is not None
        and motion > constraints.maximum_motion + 1e-9
    ):
        return None
    if common_tones < constraints.minimum_common_tones:
        return None

    crossed_pairs = _crossed_voice_pairs(source, target, voice_ids)
    if not constraints.allow_voice_crossing and crossed_pairs:
        return None
    if (
        constraints.maximum_voice_crossings is not None
        and len(crossed_pairs) > constraints.maximum_voice_crossings
    ):
        return None

    roles = _roles_by_voice(target_boundary, voice_ids)
    role_costs = _role_costs(target, voice_ids, roles, config)
    if role_costs is None:
        return None
    register_cost, role_cost = role_costs

    components = {
        "motion": weights.motion * motion,
        "large_leaps": weights.leap
        * sum(
            max(0.0, distance - weights.leap_threshold) ** 2 for distance in distances
        ),
        "register_crossing": register_cost,
        "target_role": role_cost,
        "common_tone": (
            -weights.common_tone_bonus * common_tones
            if config.preferences.retain_common_tones
            else 0.0
        ),
        "voice_crossing": (
            weights.crossing * len(crossed_pairs)
            if config.preferences.crossing == "avoid"
            else 0.0
        ),
        "deliberate_crossing": (
            -weights.deliberate_crossing_bonus * len(crossed_pairs)
            if config.preferences.crossing == "prefer"
            else 0.0
        ),
        "contrary_preference": 0.0,
        "oblique_preference": 0.0,
        "parallel_preference": 0.0,
    }

    directions = tuple(
        0 if distance <= constraints.common_tone_tolerance else (1 if delta > 0 else -1)
        for delta, distance in zip(deltas, distances)
    )
    moving_directions = tuple(value for value in directions if value != 0)
    if "contrary" in config.preferences.motion_styles:
        same_direction_pairs = sum(
            1
            for left in range(len(moving_directions))
            for right in range(left + 1, len(moving_directions))
            if moving_directions[left] == moving_directions[right]
        )
        components["contrary_preference"] = (
            weights.contrary_motion * same_direction_pairs
        )
    if "oblique" in config.preferences.motion_styles:
        has_stationary = len(moving_directions) < len(directions)
        has_motion = bool(moving_directions)
        if has_motion and not has_stationary:
            components["oblique_preference"] = weights.oblique_motion
    if "parallel" in config.preferences.motion_styles and len(deltas) > 1:
        pairwise_spread = sum(
            abs(deltas[left] - deltas[right])
            for left in range(len(deltas))
            for right in range(left + 1, len(deltas))
        )
        pair_count = len(deltas) * (len(deltas) - 1) / 2
        components["parallel_preference"] = (
            weights.parallel_motion * pairwise_spread / pair_count
        )

    ordered_names = (
        "motion",
        "large_leaps",
        "register_crossing",
        "target_role",
        "common_tone",
        "voice_crossing",
        "deliberate_crossing",
        "contrary_preference",
        "oblique_preference",
        "parallel_preference",
    )
    cost_components = tuple((name, float(components[name])) for name in ordered_names)
    total_cost = float(sum(value for _name, value in cost_components))
    if not math.isfinite(total_cost):
        raise ValueError("voice-leading weights produced a non-finite transition cost")

    positive = any(value > constraints.common_tone_tolerance for value in deltas)
    negative = any(value < -constraints.common_tone_tolerance for value in deltas)
    stationary = common_tones > 0
    motion_types = []
    if positive and negative:
        motion_types.append("contrary")
    if stationary and any(value != 0 for value in directions):
        motion_types.append("oblique")
    if (
        len(deltas) > 1
        and all(value != 0 for value in directions)
        and len(set(directions)) == 1
        and max(deltas) - min(deltas) <= max(0.5, constraints.common_tone_tolerance)
    ):
        motion_types.append("parallel")
    if common_tones:
        motion_types.append("common_tone")
    if crossed_pairs:
        motion_types.append("crossing")

    return VoiceLeadingTransition(
        source_sonority_id=source_boundary.sonority_id,
        target_sonority_id=target_boundary.sonority_id,
        source_section_id=source_boundary.section_id,
        target_section_id=target_boundary.section_id,
        source_phrase_id=source_boundary.phrase_id,
        target_phrase_id=target_boundary.phrase_id,
        assignments=tuple(
            (voice_ids[index], source[index], target[index])
            for index in range(len(voice_ids))
        ),
        total_cost=total_cost,
        cost_components=cost_components,
        crossed_pairs=crossed_pairs,
        motion_types=tuple(motion_types),
    )


def _unique_voicings(pitches: tuple[float, ...]) -> tuple[tuple[float, ...], ...]:
    # Deduplicate doubled pitches, then sort explicitly; no set iteration order leaks.
    return tuple(sorted(set(itertools.permutations(pitches))))


def plan_sonority_sequence(
    boundaries: Sequence[SonorityBoundary],
    tuning: TuningSystem,
    *,
    pitch_field: PitchField | None = None,
    config: VoiceLeadingPlanConfig = VoiceLeadingPlanConfig(),
) -> SonoritySequencePlan:
    """Generate/accept boundary sonorities and plan melodic lines across the sequence.

    The bounded beam search optimises the whole supplied order rather than making
    independent greedy pair assignments. It preserves unresolved motion and can
    reward friction, crossing, contrary movement or large travel when requested.
    """
    boundary_items = tuple(boundaries)
    if not boundary_items:
        raise ValueError("at least one sonority boundary is required")
    if any(not isinstance(item, SonorityBoundary) for item in boundary_items):
        raise ValueError("boundaries must contain SonorityBoundary objects")
    ids = [item.sonority_id for item in boundary_items]
    if len(ids) != len(set(ids)):
        raise ValueError("sonority boundary IDs must be unique")
    starts = [as_fraction(item.onset_beats) for item in boundary_items]
    if any(right <= left for left, right in zip(starts, starts[1:])):
        raise ValueError(
            "sonority boundaries must be in strictly increasing beat order"
        )
    voice_count = boundary_items[0].voice_count
    if any(item.voice_count != voice_count for item in boundary_items):
        raise ValueError("all sequence boundaries must use the same voice_count")
    if config.voice_ids and len(config.voice_ids) != voice_count:
        raise ValueError("configured voice_ids must match the sequence voice_count")
    voice_ids = config.voice_ids or tuple(
        f"voice-{index + 1}" for index in range(voice_count)
    )

    sonorities = tuple(
        _build_sonority(item, tuning, pitch_field, config.seed)
        for item in boundary_items
    )
    for boundary in boundary_items:
        _roles_by_voice(boundary, voice_ids)

    first = boundary_items[0]
    first_roles = _roles_by_voice(first, voice_ids)
    first_candidates = (
        _unique_voicings(sonorities[0].pitches)
        if first_roles
        else (sonorities[0].pitches,)
    )
    initial_candidates = []
    for candidate in first_candidates:
        role_costs = _role_costs(candidate, voice_ids, first_roles, config)
        if role_costs is None:
            continue
        register_cost, target_role_cost = role_costs
        components = (
            ("register_crossing", float(register_cost)),
            ("target_role", float(target_role_cost)),
        )
        total = float(register_cost + target_role_cost)
        initial_candidates.append((total, candidate, components))
    if not initial_candidates:
        raise ValueError(
            "first sonority cannot satisfy its hard role-register constraints"
        )
    initial_candidates.sort(key=lambda item: (item[0], item[1]))
    initial_cost, first_voicing, initial_components = initial_candidates[0]
    beam = [_BeamState(initial_cost, (first_voicing,), ())]

    for index in range(1, len(boundary_items)):
        source_boundary = boundary_items[index - 1]
        target_boundary = boundary_items[index]
        target_voicings = _unique_voicings(sonorities[index].pitches)
        expanded = []
        for state in beam:
            source_voicing = state.voicings[-1]

            def candidates_for_state():
                for target_voicing in target_voicings:
                    transition = _score_transition(
                        source_voicing,
                        target_voicing,
                        voice_ids,
                        source_boundary,
                        target_boundary,
                        config,
                    )
                    if transition is None:
                        continue
                    next_state = _BeamState(
                        total_cost=state.total_cost + transition.total_cost,
                        voicings=state.voicings + (target_voicing,),
                        transitions=state.transitions + (transition,),
                    )
                    rank = (next_state.total_cost, next_state.voicings)
                    yield rank, next_state

            expanded.extend(
                heapq.nsmallest(
                    config.beam_width, candidates_for_state(), key=lambda item: item[0]
                )
            )
        if not expanded:
            raise ValueError(
                f"no voice-leading path satisfies hard constraints between "
                f"{source_boundary.sonority_id} and {target_boundary.sonority_id}"
            )
        expanded.sort(key=lambda item: item[0])
        beam = [item[1] for item in expanded[: config.beam_width]]

    best = min(beam, key=lambda item: (item.total_cost, item.voicings))
    return SonoritySequencePlan(
        boundaries=boundary_items,
        sonorities=sonorities,
        voice_ids=voice_ids,
        voicings=best.voicings,
        initial_cost_components=initial_components,
        transitions=best.transitions,
        total_cost=best.total_cost,
        config=config,
    )
