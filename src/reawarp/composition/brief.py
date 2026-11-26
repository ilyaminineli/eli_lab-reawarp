"""Versioned artistic intent and bounded mutation contracts (M27).

A CompositionBrief describes why the material belongs together. It is kept
separate from GenerationConfig, Score and renderer implementation. Brief source
references are identity constraints: resolving a brief never substitutes a
missing or changed asset.

The first bounded-exploration adapter operates on GenerationConfig fields.
Contracts at event, pattern, phrase and section scales share the same versioned
model and independent seed naming so later Score-native mutation services can
reuse them without changing this schema.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from reawarp.config import GenerationConfig
from reawarp.composition.director import STRUCTURES
from reawarp.composition.patterns import PATTERN_FAMILIES, PATTERN_RELATIONSHIPS
from reawarp.core.random_streams import derive_seed
from reawarp.mathematics.theory import SCALE_STEPS
from reawarp.synthesis.profiles import (
    HAT_PROFILES, KICK_PROFILES, MELODY_PROFILES, SNARE_PROFILES, SYNTH_PALETTES,
)
from reawarp.transforms.pipeline import BREAK_TRANSFORMS

BRIEF_FORMAT = "eli_lab_reawarp_composition_brief"
BRIEF_SCHEMA_VERSION = 1
BRIEF_ROLES = frozenset({
    "kick", "snare", "hat", "break", "melody", "texture", "ambience", "percussion",
})
MUTATION_SCALES = frozenset({"event", "pattern", "phrase", "section"})
ANCHOR_KINDS = frozenset({
    "none", "pulse", "motif", "sound_object", "role", "spatial_feature",
})
ENDING_MODES = frozenset({
    "unspecified", "residue", "dissolve", "hard_cut", "silence",
    "transformed_return", "open", "closed",
})
DECISION_BOUNDARIES = {
    "event": frozenset({"event_onset", "event_end", "bar_boundary", "manual"}),
    "pattern": frozenset({"pattern_cycle", "bar_boundary", "manual"}),
    "phrase": frozenset({"phrase_start", "phrase_end", "section_boundary", "manual"}),
    "section": frozenset({"section_start", "section_end", "manual"}),
}

# These maps constrain the first executable M27 adapter. They are intentionally
# explicit: a future field does not silently become randomisable.
FIELD_SCOPE: dict[str, str] = {
    "structure": "section",
    "composition_flow": "section",
    "composition_energy": "section",
    "composition_variation": "section",
    "arrangement_density": "section",
    "arrangement_instability": "section",
    "drum_sample_automation": "section",
    "include_melody": "section",
    "include_texture": "section",
    "include_ambience": "section",
    "ambience_level": "section",
    "bpm": "section",
    "duration": "section",
    "pattern_family": "pattern",
    "pattern_relationship": "pattern",
    "pattern_follow_structure": "pattern",
    "drum_change_intensity": "pattern",
    "drum_part_cycle_bars": "pattern",
    "rhythmic_syncopation": "pattern",
    "synth_palette": "pattern",
    "kick_profile": "pattern",
    "snare_profile": "pattern",
    "hat_profile": "pattern",
    "percussion_synthesis": "pattern",
    "percussion_source_mode": "pattern",
    "percussion_hybrid_architecture": "pattern",
    "percussion_sample_mix": "pattern",
    "hybrid_transient_ms": "pattern",
    "melodic_activity": "phrase",
    "melody_register_semitones": "phrase",
    "tonal_brightness": "phrase",
    "spatial_intent": "phrase",
    "melody_scale": "phrase",
    "melody_root": "phrase",
    "melody_profile": "phrase",
    "break_style": "phrase",
    "break_density": "phrase",
    "break_variation": "phrase",
    "break_cycle_bars": "phrase",
    "complexity": "event",
    "break_transforms": "event",
    "break_slice_count": "event",
    "break_stutter_repeats": "event",
    "break_dropout_probability": "event",
    "break_pitch_semitones": "event",
    "break_time_stretch": "event",
    "break_gate_rate_hz": "event",
    "break_gate_duty": "event",
    "break_grain_size_ms": "event",
    "break_grain_density": "event",
    "break_spectral_freeze_position": "event",
}

FIELD_TARGET: dict[str, str] = {
    "kick_profile": "kick",
    "snare_profile": "snare",
    "hat_profile": "hat",
    "melody_profile": "melody",
    "melody_scale": "melody",
    "melody_root": "melody",
    "melody_register_semitones": "melody",
    "melodic_activity": "melody",
    "include_melody": "melody",
    "tonal_brightness": "melody",
    "spatial_intent": "composition",
    "break_style": "break",
    "break_density": "break",
    "break_variation": "break",
    "break_cycle_bars": "break",
    "break_transforms": "break",
    "break_slice_count": "break",
    "break_stutter_repeats": "break",
    "break_dropout_probability": "break",
    "break_pitch_semitones": "break",
    "break_time_stretch": "break",
    "break_gate_rate_hz": "break",
    "break_gate_duty": "break",
    "break_grain_size_ms": "break",
    "break_grain_density": "break",
    "break_spectral_freeze_position": "break",
    "include_texture": "texture",
    "include_ambience": "ambience",
    "ambience_level": "ambience",
    "percussion_synthesis": "percussion",
    "synth_palette": "percussion",
    "percussion_source_mode": "percussion",
    "percussion_hybrid_architecture": "percussion",
    "percussion_sample_mix": "percussion",
    "hybrid_transient_ms": "percussion",
    "drum_change_intensity": "percussion",
    "drum_part_cycle_bars": "percussion",
    "drum_sample_automation": "percussion",
    "pattern_family": "composition",
    "pattern_relationship": "composition",
    "pattern_follow_structure": "composition",
    "composition_flow": "composition",
    "structure": "composition",
    "composition_energy": "composition",
    "composition_variation": "composition",
    "arrangement_density": "composition",
    "arrangement_instability": "composition",
    "rhythmic_syncopation": "composition",
    "complexity": "composition",
    "bpm": "composition",
    "duration": "composition",
}

NUMERIC_DOMAINS: dict[str, tuple[float, float, type]] = {
    "bpm": (60.0, 220.0, float),
    "duration": (5.0, 180.0, float),
    "composition_energy": (0.0, 1.0, float),
    "composition_variation": (0.0, 1.0, float),
    "arrangement_density": (0.0, 1.0, float),
    "arrangement_instability": (0.0, 1.0, float),
    "rhythmic_syncopation": (0.0, 1.0, float),
    "melodic_activity": (0.0, 1.0, float),
    "melody_register_semitones": (-24.0, 24.0, int),
    "tonal_brightness": (0.0, 1.0, float),
    "spatial_intent": (0.0, 1.0, float),
    "drum_change_intensity": (0.0, 1.0, float),
    "complexity": (0.0, 1.0, float),
    "ambience_level": (0.0, 1.0, float),
    "percussion_sample_mix": (0.0, 1.0, float),
    "hybrid_transient_ms": (5.0, 200.0, float),
    "break_density": (0.0, 1.0, float),
    "break_variation": (0.0, 1.0, float),
    "break_slice_count": (2.0, 128.0, int),
    "break_stutter_repeats": (2.0, 32.0, int),
    "break_dropout_probability": (0.0, 1.0, float),
    "break_pitch_semitones": (-24.0, 24.0, float),
    "break_time_stretch": (0.25, 4.0, float),
    "break_gate_rate_hz": (0.1, 100.0, float),
    "break_gate_duty": (0.05, 1.0, float),
    "break_grain_size_ms": (5.0, 1000.0, float),
    "break_grain_density": (0.25, 4.0, float),
    "break_spectral_freeze_position": (0.0, 1.0, float),
}

ENUM_DOMAINS: dict[str, tuple[Any, ...]] = {
    "structure": tuple(STRUCTURES),
    "composition_flow": ("preset", "mix", "mutate"),
    "pattern_family": tuple(PATTERN_FAMILIES),
    "pattern_relationship": tuple(PATTERN_RELATIONSHIPS),
    "drum_part_cycle_bars": (1, 2, 4),
    "drum_sample_automation": ("fixed", "section", "cycle", "automatic"),
    "kick_profile": ("auto", *KICK_PROFILES),
    "snare_profile": ("auto", *SNARE_PROFILES),
    "hat_profile": ("auto", *HAT_PROFILES),
    "melody_profile": ("auto", *MELODY_PROFILES),
    "synth_palette": tuple(SYNTH_PALETTES),
    "percussion_synthesis": ("minimal", "extended", "samples"),
    "synth_palette": tuple(SYNTH_PALETTES),
    "percussion_source_mode": ("automatic", "synth", "sample", "hybrid"),
    "percussion_hybrid_architecture": ("transient_body", "layered", "feature_guided"),
    "melody_scale": tuple(SCALE_STEPS),
    "melody_root": tuple(range(12)),
    "break_style": ("auto", "broken_funk", "half_time", "straight", "sparse"),
    "break_cycle_bars": (1, 2, 4),
}

# These inputs identify external material or the deterministic render clock.
# They are always invariant, even if a malformed contract tries to mutate them.
HARD_INVARIANTS = frozenset({
    "seed", "sample_rate", "sample_paths", "sample_metadata", "sample_banks",
})


def _text(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    text = str(value).strip()
    if not text and not allow_empty:
        raise ValueError(f"{field_name} must be non-empty")
    return text


def _json_copy(value: Any, field_name: str) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be finite JSON-compatible data") from exc


def _path_key(value: str) -> str:
    return os.path.normcase(str(Path(value).expanduser().resolve(strict=False)))


def _stable_path_id(value: str) -> str:
    return "path:" + hashlib.sha256(_path_key(value).encode("utf-8")).hexdigest()[:20]


def _reference_id(asset_id: str | None, sha256: str | None, path: str | None) -> str:
    if asset_id and sha256:
        return f"{asset_id}@{sha256[:16].lower()}"
    if asset_id:
        return f"{asset_id}@{_stable_path_id(path or asset_id)[5:17]}"
    if sha256:
        return f"sha256:{sha256.lower()}"
    if path:
        return _stable_path_id(path)
    raise ValueError("a source reference needs an asset ID, SHA-256 hash, or path")


@dataclass(frozen=True, slots=True)
class SourceAssetReference:
    reference_id: str
    role: str
    asset_id: str | None = None
    sha256: str | None = None
    path: str | None = None
    selected: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "reference_id", _text(self.reference_id, "source reference_id"))
        role = _text(self.role, "source role")
        if role not in BRIEF_ROLES:
            raise ValueError(f"unsupported source role: {role}")
        object.__setattr__(self, "role", role)
        if self.asset_id is not None:
            object.__setattr__(self, "asset_id", _text(self.asset_id, "source asset_id"))
        if self.sha256 is not None:
            digest = _text(self.sha256, "source SHA-256").lower()
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise ValueError("source SHA-256 must be 64 hexadecimal characters")
            object.__setattr__(self, "sha256", digest)
        if self.path is not None:
            path = _text(self.path, "source path")
            object.__setattr__(self, "path", str(Path(path).expanduser()))
        if self.asset_id is None and self.sha256 is None and self.path is None:
            raise ValueError("source reference requires asset_id, sha256, or path")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceAssetReference":
        return cls(**dict(data))


@dataclass(frozen=True, slots=True)
class SourceFamily:
    family_id: str
    role: str
    label: str
    assets: tuple[SourceAssetReference, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "family_id", _text(self.family_id, "source family_id"))
        role = _text(self.role, "source family role")
        if role not in BRIEF_ROLES:
            raise ValueError(f"unsupported source family role: {role}")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "label", _text(self.label, "source family label"))
        assets = tuple(
            item if isinstance(item, SourceAssetReference)
            else SourceAssetReference.from_dict(item)
            for item in self.assets
        )
        ids = [item.reference_id for item in assets]
        if len(ids) != len(set(ids)):
            raise ValueError(f"source family {self.family_id!r} contains duplicate references")
        if any(item.role != role for item in assets):
            raise ValueError(f"source family {self.family_id!r} contains a different role")
        object.__setattr__(self, "assets", assets)

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "role": self.role,
            "label": self.label,
            "assets": [item.to_dict() for item in self.assets],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceFamily":
        record = dict(data)
        record["assets"] = tuple(SourceAssetReference.from_dict(item) for item in record.get("assets", ()))
        return cls(**record)


@dataclass(frozen=True, slots=True)
class MaterialIdentity:
    material_id: str
    label: str
    function: str = "free"
    role: str = ""
    description: str = ""
    source_asset_ids: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "material_id", _text(self.material_id, "material_id"))
        object.__setattr__(self, "label", _text(self.label, "material label"))
        if self.function not in {"anchor", "response", "destabiliser", "free"}:
            raise ValueError(f"unsupported material function: {self.function}")
        role = str(self.role).strip()
        if role and role not in BRIEF_ROLES:
            raise ValueError(f"unsupported material role: {role}")
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "description", str(self.description).strip())
        sources = tuple(_text(item, "material source reference") for item in self.source_asset_ids)
        if len(sources) != len(set(sources)):
            raise ValueError(f"material {self.material_id!r} contains duplicate source references")
        object.__setattr__(self, "source_asset_ids", sources)
        object.__setattr__(self, "tags", tuple(_text(item, "material tag") for item in self.tags))

    def to_dict(self) -> dict[str, Any]:
        return {
            "material_id": self.material_id, "label": self.label,
            "function": self.function, "role": self.role,
            "description": self.description,
            "source_asset_ids": list(self.source_asset_ids),
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MaterialIdentity":
        record = dict(data)
        record["source_asset_ids"] = tuple(record.get("source_asset_ids", ()))
        record["tags"] = tuple(record.get("tags", ()))
        return cls(**record)


@dataclass(frozen=True, slots=True)
class AnchorSpec:
    kind: str = "none"
    material_id: str | None = None
    role: str | None = None
    description: str = ""
    stability: float = 0.5

    def __post_init__(self) -> None:
        if self.kind not in ANCHOR_KINDS:
            raise ValueError(f"unsupported anchor kind: {self.kind}")
        if self.material_id is not None:
            object.__setattr__(self, "material_id", _text(self.material_id, "anchor material_id"))
        if self.role is not None:
            role = _text(self.role, "anchor role")
            if role not in BRIEF_ROLES:
                raise ValueError(f"unsupported anchor role: {role}")
            object.__setattr__(self, "role", role)
        object.__setattr__(self, "description", str(self.description).strip())
        stability = float(self.stability)
        if not math.isfinite(stability) or not 0.0 <= stability <= 1.0:
            raise ValueError("anchor stability must be between zero and one")
        object.__setattr__(self, "stability", stability)
        if self.kind == "none" and (self.material_id is not None or self.role is not None):
            raise ValueError("a none anchor cannot target a material or role")
        if self.kind != "none" and not (
            self.material_id or self.role or self.description
        ):
            raise ValueError("a declared anchor needs a material, role, or description")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AnchorSpec":
        return cls(**dict(data))


@dataclass(frozen=True, slots=True)
class PitchWorld:
    scale: str = "chromatic"
    root: int = 0
    tuning_id: str = "12tet"
    reference_pitch: float = 69.0
    reference_frequency_hz: float = 440.0
    divisions_per_period: int = 12
    period_ratio: float = 2.0

    def __post_init__(self) -> None:
        if self.scale not in SCALE_STEPS:
            raise ValueError(f"unsupported pitch-world scale: {self.scale}")
        if isinstance(self.root, bool) or not 0 <= int(self.root) <= 11:
            raise ValueError("pitch-world root must be a pitch class from 0 to 11")
        object.__setattr__(self, "root", int(self.root))
        object.__setattr__(self, "tuning_id", _text(self.tuning_id, "tuning_id"))
        reference_pitch = float(self.reference_pitch)
        reference_hz = float(self.reference_frequency_hz)
        if not math.isfinite(reference_pitch):
            raise ValueError("pitch-world reference pitch must be finite")
        if not math.isfinite(reference_hz) or reference_hz <= 0:
            raise ValueError("pitch-world reference frequency must be positive")
        if isinstance(self.divisions_per_period, bool) or int(self.divisions_per_period) < 1:
            raise ValueError("pitch-world divisions_per_period must be positive")
        object.__setattr__(self, "reference_pitch", reference_pitch)
        object.__setattr__(self, "reference_frequency_hz", reference_hz)
        period_ratio = float(self.period_ratio)
        if not math.isfinite(period_ratio) or period_ratio <= 1.0:
            raise ValueError("pitch-world period ratio must be finite and greater than one")
        object.__setattr__(self, "divisions_per_period", int(self.divisions_per_period))
        object.__setattr__(self, "period_ratio", period_ratio)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PitchWorld":
        return cls(**dict(data))


@dataclass(frozen=True, slots=True)
class ContrastTarget:
    label: str
    material_ids: tuple[str, ...] = ()
    dimensions: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", _text(self.label, "contrast label"))
        object.__setattr__(self, "material_ids", tuple(_text(x, "contrast material_id") for x in self.material_ids))
        object.__setattr__(self, "dimensions", tuple(_text(x, "contrast dimension") for x in self.dimensions))
        object.__setattr__(self, "description", str(self.description).strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label, "material_ids": list(self.material_ids),
            "dimensions": list(self.dimensions), "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ContrastTarget":
        record = dict(data)
        record["material_ids"] = tuple(record.get("material_ids", ()))
        record["dimensions"] = tuple(record.get("dimensions", ()))
        return cls(**record)


@dataclass(frozen=True, slots=True)
class EndingIntent:
    mode: str = "unspecified"
    description: str = ""
    preserve_material_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.mode not in ENDING_MODES:
            raise ValueError(f"unsupported ending intent: {self.mode}")
        object.__setattr__(self, "description", str(self.description).strip())
        object.__setattr__(
            self, "preserve_material_ids",
            tuple(_text(item, "ending material_id") for item in self.preserve_material_ids),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode, "description": self.description,
            "preserve_material_ids": list(self.preserve_material_ids),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EndingIntent":
        record = dict(data)
        record["preserve_material_ids"] = tuple(record.get("preserve_material_ids", ()))
        return cls(**record)


@dataclass(frozen=True, slots=True)
class TempoFormPolicy:
    bpm_mode: str = "preserve"
    duration_mode: str = "preserve"
    form_mode: str = "preserve"
    bpm_bounds: tuple[float, float] = (60.0, 220.0)
    duration_bounds: tuple[float, float] = (5.0, 180.0)

    def __post_init__(self) -> None:
        for name in ("bpm_mode", "duration_mode", "form_mode"):
            if getattr(self, name) not in {"preserve", "explore"}:
                raise ValueError(f"{name} must be 'preserve' or 'explore'")
        for name, lower, upper in (
            ("bpm_bounds", 60.0, 220.0),
            ("duration_bounds", 5.0, 180.0),
        ):
            values = tuple(float(value) for value in getattr(self, name))
            if len(values) != 2 or not all(math.isfinite(value) for value in values):
                raise ValueError(f"{name} must contain two finite values")
            if values[0] > values[1] or values[0] < lower or values[1] > upper:
                raise ValueError(f"{name} must be within [{lower}, {upper}] and ordered")
            object.__setattr__(self, name, values)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bpm_mode": self.bpm_mode,
            "duration_mode": self.duration_mode,
            "form_mode": self.form_mode,
            "bpm_bounds": list(self.bpm_bounds),
            "duration_bounds": list(self.duration_bounds),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TempoFormPolicy":
        record = dict(data)
        record["bpm_bounds"] = tuple(record.get("bpm_bounds", (60.0, 220.0)))
        record["duration_bounds"] = tuple(record.get("duration_bounds", (5.0, 180.0)))
        return cls(**record)


@dataclass(frozen=True, slots=True)
class MutationContract:
    contract_id: str
    target_id: str
    scale: str
    mutable_fields: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    bounds: Mapping[str, Sequence[float]] | None = None
    allowed_values: Mapping[str, Sequence[Any]] | None = None
    cadence: str = "once_per_generation"
    decision_boundaries: tuple[str, ...] = ()
    stop_conditions: tuple[str, ...] = ("manual_freeze",)
    max_mutations: int | None = None
    freeze_condition: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "contract_id", _text(self.contract_id, "contract_id"))
        object.__setattr__(self, "target_id", _text(self.target_id, "contract target_id"))
        if self.scale not in MUTATION_SCALES:
            raise ValueError(f"mutation scale must be one of {sorted(MUTATION_SCALES)}")
        mutable = tuple(_text(item, "mutable field") for item in self.mutable_fields)
        invariants = tuple(_text(item, "invariant field") for item in self.invariants)
        if len(mutable) != len(set(mutable)) or len(invariants) != len(set(invariants)):
            raise ValueError(f"contract {self.contract_id!r} contains duplicate fields")
        conflict = set(mutable) & set(invariants)
        if conflict:
            raise ValueError(
                f"contract {self.contract_id!r} marks fields both mutable and invariant: "
                + ", ".join(sorted(conflict))
            )
        object.__setattr__(self, "mutable_fields", mutable)
        known_config_fields = set(GenerationConfig.__dataclass_fields__)
        unknown_invariants = set(invariants) - known_config_fields
        if unknown_invariants:
            raise ValueError(
                f"contract {self.contract_id!r} has unknown invariant fields: "
                + ", ".join(sorted(unknown_invariants))
            )
        object.__setattr__(self, "invariants", invariants)
        object.__setattr__(self, "cadence", _text(self.cadence, "mutation cadence"))
        object.__setattr__(self, "decision_boundaries", tuple(
            _text(item, "decision boundary") for item in self.decision_boundaries
        ))
        if mutable and not self.decision_boundaries:
            raise ValueError(
                f"contract {self.contract_id!r} needs a decision boundary for {self.scale} scale"
            )
        if any(item not in DECISION_BOUNDARIES[self.scale] for item in self.decision_boundaries):
            raise ValueError(
                f"contract {self.contract_id!r} has a decision boundary invalid for {self.scale} scale"
            )
        stops = tuple(_text(item, "stop condition") for item in self.stop_conditions)
        if not stops:
            raise ValueError("a mutation contract needs at least one stop condition")
        object.__setattr__(self, "stop_conditions", stops)
        if self.max_mutations is not None:
            if isinstance(self.max_mutations, bool) or int(self.max_mutations) < 1:
                raise ValueError("max_mutations must be a positive integer or None")
            object.__setattr__(self, "max_mutations", int(self.max_mutations))
        object.__setattr__(self, "freeze_condition", str(self.freeze_condition).strip())

        bounds: dict[str, tuple[float, float]] = {}
        for key, pair in dict(self.bounds or {}).items():
            if key not in mutable:
                raise ValueError(f"bounds supplied for non-mutable field {key!r}")
            values = tuple(float(value) for value in pair)
            if len(values) != 2 or not all(math.isfinite(value) for value in values):
                raise ValueError(f"bounds for {key!r} must contain two finite values")
            if values[0] > values[1]:
                raise ValueError(f"bounds for {key!r} must be ordered")
            bounds[str(key)] = values
        object.__setattr__(self, "bounds", bounds)

        allowed: dict[str, tuple[Any, ...]] = {}
        for key, values in dict(self.allowed_values or {}).items():
            if key not in mutable:
                raise ValueError(f"allowed_values supplied for non-mutable field {key!r}")
            if key in bounds:
                raise ValueError(f"{key!r} cannot have both numeric bounds and allowed_values")
            options = tuple(_json_copy(list(values), f"allowed values for {key}"))
            if not options:
                raise ValueError(f"allowed_values for {key!r} cannot be empty")
            allowed[str(key)] = options
        object.__setattr__(self, "allowed_values", allowed)

        for field_name in mutable:
            if field_name in HARD_INVARIANTS:
                raise ValueError(f"{field_name!r} is a hard source/clock invariant and cannot be mutated")
            if field_name not in FIELD_SCOPE:
                raise ValueError(f"{field_name!r} is not an M27-supported GenerationConfig mutation field")
            if FIELD_SCOPE[field_name] != self.scale:
                raise ValueError(
                    f"{field_name!r} belongs to {FIELD_SCOPE[field_name]} scale, not {self.scale}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "target_id": self.target_id,
            "scale": self.scale,
            "mutable_fields": list(self.mutable_fields),
            "invariants": list(self.invariants),
            "bounds": {key: list(value) for key, value in self.bounds.items()},
            "allowed_values": {key: list(value) for key, value in self.allowed_values.items()},
            "cadence": self.cadence,
            "decision_boundaries": list(self.decision_boundaries),
            "stop_conditions": list(self.stop_conditions),
            "max_mutations": self.max_mutations,
            "freeze_condition": self.freeze_condition,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "MutationContract":
        record = dict(data)
        record["mutable_fields"] = tuple(record.get("mutable_fields", ()))
        record["invariants"] = tuple(record.get("invariants", ()))
        record["decision_boundaries"] = tuple(record.get("decision_boundaries", ()))
        record["stop_conditions"] = tuple(record.get("stop_conditions", ("manual_freeze",)))
        return cls(**record)


@dataclass(frozen=True, slots=True)
class CompositionBrief:
    brief_id: str
    artistic_question: str = ""
    listening_mode: str = ""
    materials: tuple[MaterialIdentity, ...] = ()
    anchor: AnchorSpec = AnchorSpec()
    pitch_world: PitchWorld = PitchWorld()
    pitch_world_explicit: bool = False
    source_families: tuple[SourceFamily, ...] = ()
    target_contrasts: tuple[ContrastTarget, ...] = ()
    ending_intent: EndingIntent = EndingIntent()
    mutation_contracts: tuple[MutationContract, ...] = ()
    tempo_form_policy: TempoFormPolicy = TempoFormPolicy()
    schema_version: int = BRIEF_SCHEMA_VERSION
    authorship: str = "user"
    structured: bool = True
    notes: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != BRIEF_SCHEMA_VERSION:
            raise ValueError(f"unsupported CompositionBrief schema version: {self.schema_version}")
        object.__setattr__(self, "brief_id", _text(self.brief_id, "brief_id"))
        if self.authorship not in {"user", "imported", "legacy"}:
            raise ValueError("authorship must be user, imported, or legacy")
        object.__setattr__(self, "artistic_question", str(self.artistic_question).strip())
        object.__setattr__(self, "listening_mode", str(self.listening_mode).strip())
        object.__setattr__(self, "notes", str(self.notes).strip())
        materials = tuple(
            item if isinstance(item, MaterialIdentity) else MaterialIdentity.from_dict(item)
            for item in self.materials
        )
        material_ids = [item.material_id for item in materials]
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("material IDs must be unique")
        object.__setattr__(self, "materials", materials)
        anchor = self.anchor if isinstance(self.anchor, AnchorSpec) else AnchorSpec.from_dict(self.anchor)
        if anchor.material_id is not None and anchor.material_id not in set(material_ids):
            raise ValueError(f"anchor references unknown material {anchor.material_id!r}")
        object.__setattr__(self, "anchor", anchor)

        pitch = self.pitch_world if isinstance(self.pitch_world, PitchWorld) else PitchWorld.from_dict(self.pitch_world)
        if not isinstance(self.pitch_world_explicit, bool):
            raise ValueError("pitch_world_explicit must be a boolean")
        object.__setattr__(self, "pitch_world", pitch)
        families = tuple(
            item if isinstance(item, SourceFamily) else SourceFamily.from_dict(item)
            for item in self.source_families
        )
        family_ids = [item.family_id for item in families]
        if len(family_ids) != len(set(family_ids)):
            raise ValueError("source family IDs must be unique")
        reference_ids = {
            source.reference_id for family in families for source in family.assets
        }
        for material in materials:
            missing = set(material.source_asset_ids) - reference_ids
            if missing:
                raise ValueError(
                    f"material {material.material_id!r} references unknown source IDs: "
                    + ", ".join(sorted(missing))
                )
        object.__setattr__(self, "source_families", families)

        contrasts = tuple(
            item if isinstance(item, ContrastTarget) else ContrastTarget.from_dict(item)
            for item in self.target_contrasts
        )
        for contrast in contrasts:
            unknown = set(contrast.material_ids) - set(material_ids)
            if unknown:
                raise ValueError(
                    f"contrast {contrast.label!r} references unknown materials: "
                    + ", ".join(sorted(unknown))
                )
        object.__setattr__(self, "target_contrasts", contrasts)
        ending = (
            self.ending_intent if isinstance(self.ending_intent, EndingIntent)
            else EndingIntent.from_dict(self.ending_intent)
        )
        unknown_ending = set(ending.preserve_material_ids) - set(material_ids)
        if unknown_ending:
            raise ValueError("ending intent references unknown material IDs")
        object.__setattr__(self, "ending_intent", ending)

        contracts = tuple(
            item if isinstance(item, MutationContract) else MutationContract.from_dict(item)
            for item in self.mutation_contracts
        )
        contract_ids = [item.contract_id for item in contracts]
        if len(contract_ids) != len(set(contract_ids)):
            raise ValueError("mutation contract IDs must be unique")
        known_targets = set(BRIEF_ROLES) | {"composition"} | set(material_ids) | set(family_ids)
        unknown_targets = {item.target_id for item in contracts} - known_targets
        if unknown_targets:
            raise ValueError(
                "mutation contracts target unknown IDs: " + ", ".join(sorted(unknown_targets))
            )
        object.__setattr__(self, "mutation_contracts", contracts)

        policy = (
            self.tempo_form_policy if isinstance(self.tempo_form_policy, TempoFormPolicy)
            else TempoFormPolicy.from_dict(self.tempo_form_policy)
        )
        object.__setattr__(self, "tempo_form_policy", policy)
        if not self.structured and self.authorship != "legacy":
            raise ValueError("only a legacy brief may be unstructured")

    @classmethod
    def legacy(cls) -> "CompositionBrief":
        """Return a read-only representation for projects created before M27.

        Callers must not write this compatibility view into project metadata.
        """
        return cls(
            brief_id="legacy-unstructured",
            authorship="legacy",
            structured=False,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": BRIEF_FORMAT,
            "schema_version": self.schema_version,
            "brief_id": self.brief_id,
            "authorship": self.authorship,
            "structured": self.structured,
            "artistic_question": self.artistic_question,
            "listening_mode": self.listening_mode,
            "materials": [item.to_dict() for item in self.materials],
            "anchor": self.anchor.to_dict(),
            "pitch_world": self.pitch_world.to_dict(),
            "pitch_world_explicit": self.pitch_world_explicit,
            "source_families": [item.to_dict() for item in self.source_families],
            "target_contrasts": [item.to_dict() for item in self.target_contrasts],
            "ending_intent": self.ending_intent.to_dict(),
            "mutation_contracts": [item.to_dict() for item in self.mutation_contracts],
            "tempo_form_policy": self.tempo_form_policy.to_dict(),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CompositionBrief":
        if not isinstance(data, Mapping):
            raise ValueError("CompositionBrief must be a JSON object")
        record = dict(data)
        if record.pop("format", None) != BRIEF_FORMAT:
            raise ValueError("not an eli_lab_reawarp_composition_brief document")
        if record.get("schema_version") != BRIEF_SCHEMA_VERSION:
            raise ValueError(f"unsupported CompositionBrief schema version: {record.get('schema_version')!r}")
        allowed = {
            "schema_version", "brief_id", "authorship", "structured",
            "artistic_question", "listening_mode", "materials", "anchor",
            "pitch_world", "pitch_world_explicit", "source_families", "target_contrasts",
            "ending_intent", "mutation_contracts", "tempo_form_policy", "notes",
        }
        unknown = set(record) - allowed
        if unknown:
            raise ValueError("unknown CompositionBrief fields: " + ", ".join(sorted(unknown)))
        return cls(
            **{
                **record,
                "materials": tuple(MaterialIdentity.from_dict(x) for x in record.get("materials", ())),
                "anchor": AnchorSpec.from_dict(record.get("anchor", {})),
                "pitch_world": PitchWorld.from_dict(record.get("pitch_world", {})),
                "source_families": tuple(SourceFamily.from_dict(x) for x in record.get("source_families", ())),
                "target_contrasts": tuple(ContrastTarget.from_dict(x) for x in record.get("target_contrasts", ())),
                "ending_intent": EndingIntent.from_dict(record.get("ending_intent", {})),
                "mutation_contracts": tuple(MutationContract.from_dict(x) for x in record.get("mutation_contracts", ())),
                "tempo_form_policy": TempoFormPolicy.from_dict(record.get("tempo_form_policy", {})),
            }
        )

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, ensure_ascii=False,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def has_user_content(self) -> bool:
        return bool(
            self.artistic_question or self.listening_mode or self.materials
            or self.anchor.kind != "none" or self.target_contrasts
            or self.pitch_world_explicit
            or self.ending_intent.mode != "unspecified"
            or self.mutation_contracts or self.notes
        )


@dataclass(frozen=True, slots=True)
class ResolvedSourceFamily:
    family_id: str
    role: str
    assets: tuple[SourceAssetReference, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "role": self.role,
            "assets": [asset.to_dict() for asset in self.assets],
        }


@dataclass(frozen=True, slots=True)
class ResolvedCompositionIntent:
    brief_id: str
    brief_fingerprint: str
    generation_seed: int | str
    source_families: tuple[ResolvedSourceFamily, ...]
    preserved_fields: tuple[str, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "brief_id": self.brief_id,
            "brief_fingerprint": self.brief_fingerprint,
            "generation_seed": self.generation_seed,
            "source_families": [item.to_dict() for item in self.source_families],
            "preserved_fields": list(self.preserved_fields),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True, slots=True)
class BoundedExplorationResult:
    config: GenerationConfig
    field_changes: Mapping[str, Mapping[str, Any]]
    seed_lineage: Mapping[str, int]
    preserved_fields: tuple[str, ...]
    applied_contract_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "field_changes": _json_copy(dict(self.field_changes), "exploration field_changes"),
            "seed_lineage": dict(self.seed_lineage),
            "preserved_fields": list(self.preserved_fields),
            "applied_contract_ids": list(self.applied_contract_ids),
        }


def source_families_from_config(config: GenerationConfig) -> tuple[SourceFamily, ...]:
    """Snapshot the available source vocabulary without copying or relabelling files."""
    families: list[SourceFamily] = []
    roles = sorted(set(config.sample_paths) | set(config.sample_banks))
    for role in roles:
        selected_path = config.sample_paths.get(role)
        entries: list[SourceAssetReference] = []
        seen: set[str] = set()
        bank = config.sample_banks.get(role, ())
        for raw in bank:
            if not isinstance(raw, Mapping):
                continue
            path = str(raw.get("path", "")).strip()
            if not path:
                continue
            asset_id = str(raw.get("asset_id", "")).strip() or None
            sha = str(raw.get("sha256", "")).strip() or None
            ref_id = _reference_id(asset_id, sha, path)
            if ref_id in seen:
                continue
            seen.add(ref_id)
            entries.append(SourceAssetReference(
                reference_id=ref_id, role=role, asset_id=asset_id,
                sha256=sha, path=path,
                selected=bool(selected_path and _path_key(path) == _path_key(selected_path)),
            ))
        if selected_path:
            path = str(selected_path)
            metadata = config.sample_metadata.get(role, {})
            asset_id = str(metadata.get("asset_id", "")).strip() or None
            sha = str(metadata.get("sha256", "")).strip() or None
            ref_id = _reference_id(asset_id, sha, path)
            if ref_id not in seen:
                entries.insert(0, SourceAssetReference(
                    reference_id=ref_id, role=role, asset_id=asset_id,
                    sha256=sha, path=path, selected=True,
                ))
            else:
                entries = [
                    replace(item, selected=True) if item.reference_id == ref_id else item
                    for item in entries
                ]
        if entries:
            families.append(SourceFamily(
                family_id=f"source-family:{role}",
                role=role,
                label=f"{role.title()} source family",
                assets=tuple(entries),
            ))
    return tuple(families)


def _source_matches(reference: SourceAssetReference, candidate: SourceAssetReference) -> bool:
    if reference.role != candidate.role:
        return False
    if reference.asset_id is not None and reference.asset_id != candidate.asset_id:
        return False
    if reference.sha256 is not None:
        return reference.sha256 == candidate.sha256
    # An asset ID without a content hash is not sufficient evidence that two
    # different files are the same source. Require path identity as a fallback.
    if reference.path is None or candidate.path is None:
        return False
    return _path_key(reference.path) == _path_key(candidate.path)


def resolve_composition_brief(
    brief: CompositionBrief,
    config: GenerationConfig,
) -> ResolvedCompositionIntent:
    """Resolve every brief source reference against the currently available config.

    Matching is by stable asset ID and/or content hash when present; path identity
    is used only for unindexed/custom sources. A mismatch is an error, not a cue
    to substitute another member of the same percussion role.
    """
    if not isinstance(brief, CompositionBrief):
        raise TypeError("brief must be a CompositionBrief")
    if not isinstance(config, GenerationConfig):
        raise TypeError("config must be a GenerationConfig")
    available = {family.family_id: family for family in source_families_from_config(config)}
    resolved: list[ResolvedSourceFamily] = []
    missing: list[str] = []
    for family in brief.source_families:
        current = available.get(family.family_id)
        if current is not None and current.role != family.role:
            raise ValueError(
                f"CompositionBrief source family {family.family_id!r} changed role "
                f"from {family.role!r} to {current.role!r}"
            )
        if current is None:
            if family.assets:
                missing.extend(
                    f"{family.family_id}/{asset.reference_id}" for asset in family.assets
                )
            continue
        matched: list[SourceAssetReference] = []
        for reference in family.assets:
            candidate = next(
                (item for item in current.assets if _source_matches(reference, item)),
                None,
            )
            if candidate is None:
                missing.append(f"{family.family_id}/{reference.reference_id}")
            else:
                matched.append(candidate)
        resolved.append(ResolvedSourceFamily(
            family_id=family.family_id, role=family.role, assets=tuple(matched)
        ))
    if missing:
        raise ValueError(
            "CompositionBrief source references are missing or changed; no substitutions were made: "
            + ", ".join(missing)
        )

    source_ids = {
        asset.reference_id for family in brief.source_families for asset in family.assets
    }
    for material in brief.materials:
        unknown = set(material.source_asset_ids) - source_ids
        if unknown:
            raise ValueError(
                f"material {material.material_id!r} refers to unavailable source identities: "
                + ", ".join(sorted(unknown))
            )

    warnings: list[str] = []
    if brief.pitch_world.scale != config.melody_scale or brief.pitch_world.root != config.melody_root:
        warnings.append(
            "Pitch-world scale/root differ from GenerationConfig; GenerationConfig remains the render input."
        )
    return ResolvedCompositionIntent(
        brief_id=brief.brief_id,
        brief_fingerprint=brief.fingerprint,
        generation_seed=config.seed,
        source_families=tuple(resolved),
        preserved_fields=tuple(sorted(HARD_INVARIANTS | {"bpm", "duration"})),
        warnings=tuple(warnings),
    )


def _field_options(field_name: str) -> tuple[Any, ...] | None:
    if field_name in ENUM_DOMAINS:
        return ENUM_DOMAINS[field_name]
    if field_name in {"pattern_follow_structure", "include_melody", "include_texture", "include_ambience"}:
        return (False, True)
    return None


def _validate_target_field(brief: CompositionBrief, contract: MutationContract, field_name: str) -> None:
    expected_target = FIELD_TARGET.get(field_name, "composition")
    target = contract.target_id
    material_roles = {
        material.material_id: material.role
        for material in brief.materials if material.role
    }
    resolved_target = material_roles.get(target, target)
    family_roles = {
        family.family_id: family.role for family in brief.source_families
    }
    resolved_target = material_roles.get(target, family_roles.get(target, target))
    if resolved_target != "composition":
        matches = expected_target == resolved_target
        if expected_target == "percussion" and resolved_target in {"kick", "snare", "hat", "break"}:
            matches = True
        if not matches:
            raise ValueError(
                f"contract {contract.contract_id!r} targets {resolved_target!r}, "
                f"but {field_name!r} belongs to {expected_target!r}"
            )


def quick_mutation_contracts(fields_requested: Sequence[str]) -> tuple[MutationContract, ...]:
    """Create explicit role/scale contracts for quick Generator bounded exploration."""
    requested = tuple(dict.fromkeys(str(item).strip() for item in fields_requested if str(item).strip()))
    unknown = sorted(set(requested) - set(FIELD_SCOPE))
    if unknown:
        raise ValueError(
            "unknown or unsupported mutable GenerationConfig fields: " + ", ".join(unknown)
        )
    grouped: dict[tuple[str, str], list[str]] = {}
    for name in requested:
        target = FIELD_TARGET.get(name, "composition")
        grouped.setdefault((FIELD_SCOPE[name], target), []).append(name)
    contracts = []
    for (scale, target), mutable in sorted(grouped.items()):
        contracts.append(MutationContract(
            contract_id=f"quick:{target}:{scale}",
            target_id=target,
            scale=scale,
            mutable_fields=tuple(mutable),
            cadence="once_per_generation",
            decision_boundaries=({
                "event": "event_onset",
                "pattern": "pattern_cycle",
                "phrase": "phrase_start",
                "section": "section_start",
            }[scale],),
            stop_conditions=("one_generation_request", "manual_freeze"),
        ))
    return tuple(contracts)


def _sample_options(field_name: str, contract: MutationContract) -> tuple[Any, ...] | None:
    if field_name in contract.allowed_values:
        return tuple(contract.allowed_values[field_name])
    return _field_options(field_name)


def _draw_mutated_value(
    config: GenerationConfig,
    field_name: str,
    contract: MutationContract,
    rng: np.random.Generator,
    policy: TempoFormPolicy,
) -> Any:
    if field_name in HARD_INVARIANTS:
        raise ValueError(f"{field_name!r} is an immutable source/clock invariant")
    if field_name in {"bpm", "duration"}:
        mode = policy.bpm_mode if field_name == "bpm" else policy.duration_mode
        if mode != "explore":
            raise ValueError(f"{field_name!r} is preserved by the CompositionBrief tempo/form policy")
        default_bounds = policy.bpm_bounds if field_name == "bpm" else policy.duration_bounds
    elif field_name in {"structure", "composition_flow"} and policy.form_mode != "explore":
        raise ValueError(f"{field_name!r} is preserved by the CompositionBrief form policy")
    elif field_name in NUMERIC_DOMAINS:
        lower, upper, kind = NUMERIC_DOMAINS[field_name]
        default_bounds = (lower, upper)
    else:
        default_bounds = None

    if field_name == "break_transforms":
        options = tuple(contract.allowed_values.get(field_name, BREAK_TRANSFORMS))
        if not options:
            raise ValueError("break_transforms has no allowed transform operations")
        invalid = set(options) - set(BREAK_TRANSFORMS)
        if invalid:
            raise ValueError(
                "break_transforms choices must be implemented transform names: "
                + ", ".join(sorted(str(item) for item in invalid))
            )
        size = int(rng.integers(1, len(options) + 1))
        indices = rng.choice(len(options), size=size, replace=False)
        return tuple(str(options[int(index)]) for index in sorted(indices))

    options = _sample_options(field_name, contract)
    if options is not None:
        if not options:
            raise ValueError(f"field {field_name!r} has no mutation choices")
        if field_name in ENUM_DOMAINS and any(item not in ENUM_DOMAINS[field_name] for item in options):
            raise ValueError(f"contract {contract.contract_id!r} has invalid choices for {field_name!r}")
        if field_name in {"pattern_follow_structure", "include_melody", "include_texture", "include_ambience"}:
            if any(not isinstance(item, bool) for item in options):
                raise ValueError(f"allowed values for {field_name!r} must be booleans")
        if field_name in NUMERIC_DOMAINS:
            lower, upper, _kind = NUMERIC_DOMAINS[field_name]
            if any(
                isinstance(item, bool) or not isinstance(item, (int, float))
                or not math.isfinite(float(item))
                or not lower <= float(item) <= upper
                for item in options
            ):
                raise ValueError(f"allowed values for {field_name!r} exceed its GenerationConfig domain")
        if field_name == "break_transforms" and any(item not in BREAK_TRANSFORMS for item in options):
            raise ValueError("break_transforms choices must be implemented transform names")
        return options[int(rng.integers(0, len(options)))]

    if default_bounds is not None:
        lower, upper = contract.bounds.get(field_name, default_bounds)
        domain_lower, domain_upper = default_bounds
        if lower < domain_lower or upper > domain_upper:
            raise ValueError(
                f"contract bounds for {field_name!r} must remain inside "
                f"[{domain_lower}, {domain_upper}]"
            )
        kind = float if field_name in {"bpm", "duration"} else NUMERIC_DOMAINS[field_name][2]
        if kind is int:
            low_int, high_int = int(math.ceil(lower)), int(math.floor(upper))
            if low_int > high_int:
                raise ValueError(f"bounds for integer field {field_name!r} contain no integer")
            return int(rng.integers(low_int, high_int + 1))
        if lower == upper:
            return float(lower)
        return float(rng.uniform(lower, upper))
    raise ValueError(f"field {field_name!r} has no M27 mutation adapter")


def bounded_explore_generation_config(
    config: GenerationConfig,
    brief: CompositionBrief,
) -> BoundedExplorationResult:
    """Mutate only contract-approved settings with one stable stream per field.

    The root seed is not advanced or replaced. BPM/duration/form stay unchanged
    unless their respective explicit TempoFormPolicy modes say otherwise.
    Sample paths, asset metadata, sample banks and sample rate are hard invariants.
    """
    if not isinstance(config, GenerationConfig):
        raise TypeError("config must be a GenerationConfig")
    if not isinstance(brief, CompositionBrief):
        raise TypeError("brief must be a CompositionBrief")
    changes: dict[str, dict[str, Any]] = {}
    seeds: dict[str, int] = {}
    applied: list[str] = []
    updates: dict[str, Any] = {}
    used_fields: set[str] = set()
    material_roles = {item.material_id: item.role for item in brief.materials if item.role}

    declared_invariants = set(HARD_INVARIANTS)
    for contract in brief.mutation_contracts:
        declared_invariants.update(contract.invariants)
    all_requested_fields = {
        field_name
        for contract in brief.mutation_contracts
        for field_name in contract.mutable_fields
    }
    conflicts = all_requested_fields & declared_invariants
    if conflicts:
        raise ValueError(
            "mutation contracts attempt to change fields declared invariant: "
            + ", ".join(sorted(conflicts))
        )

    for contract in brief.mutation_contracts:
        if not contract.mutable_fields:
            continue
        if contract.cadence != "once_per_generation":
            raise ValueError(
                f"contract {contract.contract_id!r} uses unsupported GenerationConfig cadence "
                f"{contract.cadence!r}; only 'once_per_generation' is currently executable"
            )
        unsupported_stops = set(contract.stop_conditions) - {
            "manual_freeze", "one_generation_request"
        }
        if unsupported_stops:
            raise ValueError(
                f"contract {contract.contract_id!r} has unsupported stop conditions: "
                + ", ".join(sorted(unsupported_stops))
            )
        mutable_fields = contract.mutable_fields
        if contract.max_mutations is not None:
            mutable_fields = mutable_fields[:contract.max_mutations]
        for field_name in mutable_fields:
            _validate_target_field(brief, contract, field_name)
            if field_name in used_fields:
                raise ValueError(f"mutable field {field_name!r} appears in more than one contract")
            used_fields.add(field_name)
            if FIELD_SCOPE[field_name] != contract.scale:
                raise ValueError(f"{field_name!r} is not valid at {contract.scale} scale")
            seed_name = (
                f"composition-brief:v{BRIEF_SCHEMA_VERSION}:"
                f"{brief.brief_id}:{contract.contract_id}:{contract.scale}:{field_name}"
            )
            field_seed = derive_seed(config.seed, seed_name)
            seeds[seed_name] = field_seed
            rng = np.random.default_rng(field_seed)
            before = getattr(config, field_name)
            after = _draw_mutated_value(
                config, field_name, contract, rng, brief.tempo_form_policy
            )
            updates[field_name] = after
            changes[field_name] = {"before": before, "after": after, "contract_id": contract.contract_id}
        applied.append(contract.contract_id)

    if not updates:
        raise ValueError("bounded exploration is enabled but no mutation contract fields are active")
    # replace() re-runs GenerationConfig validation after all field choices.
    updated_config = replace(config, **updates)
    always_preserved = set(HARD_INVARIANTS)
    if brief.tempo_form_policy.bpm_mode == "preserve":
        always_preserved.add("bpm")
    if brief.tempo_form_policy.duration_mode == "preserve":
        always_preserved.add("duration")
    if brief.tempo_form_policy.form_mode == "preserve":
        always_preserved.update({"structure", "composition_flow"})
    preserved = tuple(sorted(always_preserved - set(updates)))
    # BPM/duration/form may be intentionally explored only under their explicit policy.
    return BoundedExplorationResult(
        config=updated_config,
        field_changes=changes,
        seed_lineage=seeds,
        preserved_fields=preserved,
        applied_contract_ids=tuple(applied),
    )


def resolve_and_explore(
    brief: CompositionBrief,
    config: GenerationConfig,
    *,
    bounded_exploration: bool = False,
) -> tuple[GenerationConfig, ResolvedCompositionIntent, BoundedExplorationResult | None]:
    """Validate source identity, apply optional bounded exploration, and re-resolve."""
    # The pitch world is part of artistic intent and becomes the initial
    # generation vocabulary. Explicit mutation contracts may deliberately alter
    # it later; that difference remains visible in the exploration record.
    # Keep the GenerationConfig pitch settings unless the brief explicitly
    # declares a pitch world. A default-valued PitchWorld must not silently
    # reset a generator configuration that already selected another scale.
    if brief.pitch_world_explicit or brief.pitch_world != PitchWorld():
        config = replace(
            config,
            melody_scale=brief.pitch_world.scale,
            melody_root=brief.pitch_world.root,
        )
    resolved = resolve_composition_brief(brief, config)
    result = bounded_explore_generation_config(config, brief) if bounded_exploration else None
    selected = result.config if result is not None else config
    resolved_after = resolve_composition_brief(brief, selected)
    return selected, resolved_after, result
