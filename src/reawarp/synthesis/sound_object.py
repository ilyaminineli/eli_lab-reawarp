"""Sound-object schemas and deterministic hybrid instrument rendering.

Core implementation is NumPy-only. Source identity and processing identity are
stored separately; rendering never mutates supplied source arrays or assets.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


SOUND_OBJECT_FORMAT = "eli_lab_reawarp_sound_object"
SOUND_OBJECT_SCHEMA_VERSION = 1
LAYER_ROLES = frozenset({"transient", "body", "tail", "texture", "voice"})
ENVELOPE_CURVES = frozenset({"linear", "exponential"})
MODULATION_WAVES = frozenset({"sine", "triangle", "saw", "square"})


def _identifier(value: str, field_name: str) -> str:
    result = str(value).strip()
    if not result:
        raise ValueError(f"{field_name} cannot be empty")
    return result


def _json_object(value: Mapping[str, Any], field_name: str) -> dict[str, Any]:
    try:
        result = json.loads(json.dumps(dict(value), ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be finite JSON-compatible data") from exc
    return result


def _number(
    value: Any, field_name: str, low: float | None = None,
    high: float | None = None,
) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    if low is not None and result < low:
        raise ValueError(f"{field_name} must be >= {low}")
    if high is not None and result > high:
        raise ValueError(f"{field_name} must be <= {high}")
    return result


@dataclass(frozen=True, slots=True)
class EnvelopeSpec:
    """ADSR envelope with times in seconds and a unitless sustain level."""

    attack_seconds: float = 0.001
    decay_seconds: float = 0.08
    sustain_level: float = 0.82
    release_seconds: float = 0.12
    attack_curve: str = "linear"
    decay_curve: str = "exponential"
    release_curve: str = "linear"

    def __post_init__(self) -> None:
        for name in ("attack_seconds", "decay_seconds", "release_seconds"):
            object.__setattr__(self, name, _number(getattr(self, name), name, 0.0, 30.0))
        object.__setattr__(
            self, "sustain_level", _number(self.sustain_level, "sustain_level", 0.0, 1.0)
        )
        for name in ("attack_curve", "decay_curve", "release_curve"):
            if getattr(self, name) not in ENVELOPE_CURVES:
                raise ValueError(f"unsupported {name}: {getattr(self, name)}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "EnvelopeSpec":
        return cls(**dict(data or {}))


@dataclass(frozen=True, slots=True)
class SoundObjectSource:
    """Immutable source reference; SHA-256 binds the patch to source bytes."""

    source_id: str
    source_kind: str = "asset"
    asset_id: str | None = None
    asset_sha256: str | None = None
    uri: str | None = None
    sample_rate: int = 48_000
    channels: int = 1
    source_model: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _identifier(self.source_id, "source_id"))
        if self.source_kind not in {"asset", "procedural"}:
            raise ValueError("source_kind must be asset or procedural")
        if isinstance(self.sample_rate, bool) or int(self.sample_rate) <= 0:
            raise ValueError("source sample_rate must be a positive integer")
        if int(self.channels) not in {1, 2}:
            raise ValueError("source channels must be one or two")
        object.__setattr__(self, "sample_rate", int(self.sample_rate))
        object.__setattr__(self, "channels", int(self.channels))
        if self.source_kind == "asset":
            if not self.asset_sha256 or not re.fullmatch(r"[0-9a-fA-F]{64}", self.asset_sha256):
                raise ValueError("asset sources require a valid SHA-256 digest")
            if not (self.asset_id or self.uri):
                raise ValueError("asset sources require asset_id or uri")
            object.__setattr__(self, "asset_sha256", self.asset_sha256.casefold())
        elif not (self.source_model or "").strip():
            raise ValueError("procedural sources require source_model")
        if self.asset_id is not None:
            object.__setattr__(self, "asset_id", _identifier(self.asset_id, "asset_id"))
        if self.uri is not None:
            object.__setattr__(self, "uri", _identifier(self.uri, "uri"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SoundObjectSource":
        return cls(**dict(data))


@dataclass(frozen=True, slots=True)
class SoundObjectLayer:
    """A reusable transient/body/tail/texture voice layer on an exact frame span."""

    layer_id: str
    role: str
    source_id: str
    start_frame: int
    end_frame: int
    source_start_frame: int = 0
    gain: float = 1.0
    pan: float = 0.0
    envelope: EnvelopeSpec = field(default_factory=EnvelopeSpec)
    phase_group: str | None = None
    identity_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "layer_id", _identifier(self.layer_id, "layer_id"))
        object.__setattr__(self, "source_id", _identifier(self.source_id, "source_id"))
        if self.role not in LAYER_ROLES:
            raise ValueError(f"unsupported sound-object layer role: {self.role}")
        for name in ("start_frame", "end_frame", "source_start_frame"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.end_frame <= self.start_frame:
            raise ValueError("layer end_frame must be after start_frame")
        object.__setattr__(self, "gain", _number(self.gain, "layer gain", 0.0, 4.0))
        object.__setattr__(self, "pan", _number(self.pan, "layer pan", -1.0, 1.0))
        if not isinstance(self.envelope, EnvelopeSpec):
            object.__setattr__(self, "envelope", EnvelopeSpec.from_dict(self.envelope))
        if self.phase_group is not None:
            object.__setattr__(self, "phase_group", _identifier(self.phase_group, "phase_group"))
        object.__setattr__(
            self, "identity_tags", tuple(_identifier(tag, "identity tag") for tag in self.identity_tags)
        )

    @property
    def frame_count(self) -> int:
        return self.end_frame - self.start_frame

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer_id": self.layer_id, "role": self.role, "source_id": self.source_id,
            "start_frame": self.start_frame, "end_frame": self.end_frame,
            "source_start_frame": self.source_start_frame, "gain": self.gain,
            "pan": self.pan, "envelope": self.envelope.to_dict(),
            "phase_group": self.phase_group, "identity_tags": list(self.identity_tags),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SoundObjectLayer":
        values = dict(data)
        values["envelope"] = EnvelopeSpec.from_dict(values.get("envelope"))
        values["identity_tags"] = tuple(values.get("identity_tags", ()))
        return cls(**values)


@dataclass(frozen=True, slots=True)
class TransformationRecord:
    """Non-destructive operation with deterministic provenance and optional content hashes."""

    operation: str
    seed: int
    parameters: dict[str, Any] = field(default_factory=dict)
    source_sha256: str | None = None
    output_sha256: str | None = None
    preserved_dimensions: tuple[str, ...] = ()
    changed_dimensions: tuple[str, ...] = ()
    non_destructive: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _identifier(self.operation, "transformation operation"))
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("transformation seed must be an integer")
        object.__setattr__(self, "parameters", _json_object(self.parameters, "transformation parameters"))
        for name in ("source_sha256", "output_sha256"):
            value = getattr(self, name)
            if value is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", str(value)):
                raise ValueError(f"{name} must be a SHA-256 digest")
            if value is not None:
                object.__setattr__(self, name, str(value).casefold())
        if not self.non_destructive:
            raise ValueError("sound-object transformations must be non-destructive")
        for name in ("preserved_dimensions", "changed_dimensions"):
            object.__setattr__(
                self, name, tuple(_identifier(item, name) for item in getattr(self, name))
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation, "seed": self.seed,
            "parameters": self.parameters, "source_sha256": self.source_sha256,
            "output_sha256": self.output_sha256,
            "preserved_dimensions": list(self.preserved_dimensions),
            "changed_dimensions": list(self.changed_dimensions),
            "non_destructive": self.non_destructive,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TransformationRecord":
        values = dict(data)
        values["preserved_dimensions"] = tuple(values.get("preserved_dimensions", ()))
        values["changed_dimensions"] = tuple(values.get("changed_dimensions", ()))
        return cls(**values)


@dataclass(frozen=True, slots=True)
class SoundObjectPatch:
    """Versioned patch separating source identity from processing identity."""

    patch_id: str
    name: str
    sample_rate: int
    seed: int
    source_identity_id: str
    processing_identity_id: str
    sources: tuple[SoundObjectSource, ...]
    layers: tuple[SoundObjectLayer, ...]
    pitch_model: dict[str, Any] = field(default_factory=dict)
    spectrum: dict[str, Any] = field(default_factory=dict)
    modulation: dict[str, Any] = field(default_factory=dict)
    spatial: dict[str, Any] = field(default_factory=dict)
    transformations: tuple[TransformationRecord, ...] = ()
    schema_version: int = SOUND_OBJECT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "patch_id", _identifier(self.patch_id, "patch_id"))
        object.__setattr__(self, "name", _identifier(self.name, "sound-object name"))
        object.__setattr__(self, "source_identity_id", _identifier(self.source_identity_id, "source_identity_id"))
        object.__setattr__(self, "processing_identity_id", _identifier(self.processing_identity_id, "processing_identity_id"))
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", self.patch_id):
            raise ValueError("patch_id must contain only letters, digits, underscore or hyphen")
        if isinstance(self.sample_rate, bool) or not isinstance(self.sample_rate, int) or self.sample_rate <= 0:
            raise ValueError("sound-object sample_rate must be a positive integer")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("sound-object seed must be an integer")
        if self.schema_version != SOUND_OBJECT_SCHEMA_VERSION:
            raise ValueError(f"unsupported sound-object schema version: {self.schema_version}")

        sources = tuple(
            item if isinstance(item, SoundObjectSource) else SoundObjectSource.from_dict(item)
            for item in self.sources
        )
        layers = tuple(
            item if isinstance(item, SoundObjectLayer) else SoundObjectLayer.from_dict(item)
            for item in self.layers
        )
        transforms = tuple(
            item if isinstance(item, TransformationRecord) else TransformationRecord.from_dict(item)
            for item in self.transformations
        )
        if not sources or not layers:
            raise ValueError("sound-object patches require at least one source and one layer")
        source_ids = [item.source_id for item in sources]
        layer_ids = [item.layer_id for item in layers]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("sound-object source IDs must be unique")
        if len(layer_ids) != len(set(layer_ids)):
            raise ValueError("sound-object layer IDs must be unique")
        missing = {item.source_id for item in layers} - set(source_ids)
        if missing:
            raise ValueError("sound-object layer references unknown source(s): " + ", ".join(sorted(missing)))
        if any(source.sample_rate != self.sample_rate for source in sources):
            raise ValueError("source sample_rate must match patch sample_rate; resample explicitly first")
        object.__setattr__(self, "sources", sources)
        object.__setattr__(self, "layers", layers)
        object.__setattr__(self, "transformations", transforms)
        pitch = _json_object(self.pitch_model, "pitch_model")
        spectrum = _json_object(self.spectrum, "spectrum")
        modulation = _json_object(self.modulation, "modulation")
        spatial = _json_object(self.spatial, "spatial")
        pitch_kind = pitch.get("kind", "unpitched")
        if pitch_kind not in {"unpitched", "pitched", "resonant", "noise"}:
            raise ValueError("pitch_model.kind must be unpitched, pitched, resonant or noise")
        if pitch.get("frequency_hz") is not None:
            _number(pitch["frequency_hz"], "pitch_model.frequency_hz", 0.001)
        partials = spectrum.get("partials", [])
        if not isinstance(partials, list):
            raise ValueError("spectrum.partials must be a list")
        for partial in partials:
            if not isinstance(partial, dict):
                raise ValueError("each spectral partial must be an object")
            _number(partial.get("ratio", 0), "partial ratio", 0.0001)
            _number(partial.get("gain", 0), "partial gain", 0.0, 4.0)
            if partial.get("decay_seconds") is not None:
                _number(partial["decay_seconds"], "partial decay_seconds", 0.0, 60.0)
        if modulation:
            _number(modulation.get("rate_hz", 0.0), "modulation.rate_hz", 0.0, 40.0)
            _number(modulation.get("depth", 0.0), "modulation.depth", 0.0, 1.0)
            if modulation.get("waveform", "sine") not in MODULATION_WAVES:
                raise ValueError("unsupported sound-object modulation waveform")
        if spatial:
            _number(spatial.get("pan", 0.0), "spatial.pan", -1.0, 1.0)
            _number(spatial.get("width", 1.0), "spatial.width", 0.0, 2.0)
        object.__setattr__(self, "pitch_model", pitch)
        object.__setattr__(self, "spectrum", spectrum)
        object.__setattr__(self, "modulation", modulation)
        object.__setattr__(self, "spatial", spatial)

    @property
    def duration_frames(self) -> int:
        return max(layer.end_frame for layer in self.layers)

    @property
    def source_hashes(self) -> tuple[str, ...]:
        return tuple(sorted(
            source.asset_sha256 for source in self.sources if source.asset_sha256 is not None
        ))

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": SOUND_OBJECT_FORMAT,
            "schema_version": self.schema_version,
            "patch_id": self.patch_id,
            "name": self.name,
            "sample_rate": self.sample_rate,
            "seed": self.seed,
            "source_identity_id": self.source_identity_id,
            "processing_identity_id": self.processing_identity_id,
            "sources": [item.to_dict() for item in self.sources],
            "layers": [item.to_dict() for item in self.layers],
            "pitch_model": self.pitch_model,
            "spectrum": self.spectrum,
            "modulation": self.modulation,
            "spatial": self.spatial,
            "transformations": [item.to_dict() for item in self.transformations],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SoundObjectPatch":
        if data.get("format") not in {None, SOUND_OBJECT_FORMAT}:
            raise ValueError("file is not a Reawarp sound-object patch")
        return cls(
            patch_id=str(data["patch_id"]), name=str(data["name"]),
            sample_rate=int(data["sample_rate"]), seed=int(data.get("seed", 0)),
            source_identity_id=str(data["source_identity_id"]),
            processing_identity_id=str(data["processing_identity_id"]),
            sources=tuple(SoundObjectSource.from_dict(item) for item in data.get("sources", ())),
            layers=tuple(SoundObjectLayer.from_dict(item) for item in data.get("layers", ())),
            pitch_model=dict(data.get("pitch_model", {})),
            spectrum=dict(data.get("spectrum", {})),
            modulation=dict(data.get("modulation", {})),
            spatial=dict(data.get("spatial", {})),
            transformations=tuple(
                TransformationRecord.from_dict(item) for item in data.get("transformations", ())
            ),
            schema_version=int(data.get("schema_version", 1)),
        )


@dataclass(frozen=True, slots=True)
class HybridRenderResult:
    audio: np.ndarray
    layers: dict[str, np.ndarray]
    diagnostics: dict[str, Any]


def derive_sound_object_seed(root_seed: int | str, patch_id: str, layer_id: str = "") -> int:
    """Domain-separated deterministic seed for a sound-object or one of its layers."""
    payload = f"reawarp:sound-object:v1:{root_seed}:{patch_id}:{layer_id}".encode("utf-8")
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "little")


def _audio_hash(audio: np.ndarray) -> str:
    array = np.ascontiguousarray(np.asarray(audio, dtype="<f4"))
    digest = hashlib.sha256()
    digest.update(str(array.shape).encode("ascii"))
    digest.update(array.tobytes())
    return digest.hexdigest()


def _to_stereo(audio: np.ndarray, pan: float, width: float) -> np.ndarray:
    source = np.asarray(audio, dtype=np.float32)
    if source.ndim == 1:
        mono = source
        angle = (float(pan) + 1.0) * math.pi / 4.0
        return np.column_stack((mono * math.cos(angle), mono * math.sin(angle))).astype(np.float32)
    if source.ndim != 2 or source.shape[1] != 2:
        raise ValueError("source audio must be mono or stereo (frames, 2)")
    result = source.copy()
    mid = (result[:, 0] + result[:, 1]) * 0.5
    side = (result[:, 0] - result[:, 1]) * 0.5 * float(width)
    result[:, 0] = mid + side
    result[:, 1] = mid - side
    pan = float(pan)
    if pan > 0.0:
        result[:, 0] *= math.sqrt(1.0 - pan)
    elif pan < 0.0:
        result[:, 1] *= math.sqrt(1.0 + pan)
    return result.astype(np.float32, copy=False)


def _curve(length: int, curve: str, *, rising: bool) -> np.ndarray:
    if length <= 0:
        return np.empty(0, dtype=np.float64)
    x = np.linspace(0.0, 1.0, length, endpoint=False, dtype=np.float64)
    if curve == "exponential":
        shaped = (1.0 - np.exp(-5.0 * x)) / (1.0 - math.exp(-5.0))
    else:
        shaped = x
    return shaped if rising else 1.0 - shaped


def build_envelope_curve(frames: int, sample_rate: int, spec: EnvelopeSpec) -> np.ndarray:
    """Render an exact-length ADSR curve; all segment lengths are frame-addressed."""
    if frames < 0 or sample_rate <= 0:
        raise ValueError("frames must be non-negative and sample_rate positive")
    if frames == 0:
        return np.empty(0, dtype=np.float32)
    attack = min(frames, int(round(spec.attack_seconds * sample_rate)))
    decay = min(frames - attack, int(round(spec.decay_seconds * sample_rate)))
    release = min(frames, int(round(spec.release_seconds * sample_rate)))
    result = np.full(frames, spec.sustain_level, dtype=np.float64)
    cursor = 0
    if attack:
        result[:attack] = _curve(attack, spec.attack_curve, rising=True)
        cursor = attack
    if decay:
        decay_curve = _curve(decay, spec.decay_curve, rising=False)
        result[cursor:cursor + decay] = (
            spec.sustain_level + (1.0 - spec.sustain_level) * decay_curve
        )
        cursor += decay
    if release:
        release_start = frames - release
        start_level = float(result[release_start])
        fade = _curve(release, spec.release_curve, rising=False)
        result[release_start:] = start_level * fade
    return np.clip(result, 0.0, 1.0).astype(np.float32)


def _phase_warnings(layer_audio: Mapping[str, np.ndarray]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    names = sorted(layer_audio)
    for i, left_name in enumerate(names):
        for right_name in names[i + 1:]:
            left = layer_audio[left_name]
            right = layer_audio[right_name]
            count = min(len(left), len(right))
            if count < 32:
                continue
            a = np.mean(left[:count], axis=1, dtype=np.float64)
            b = np.mean(right[:count], axis=1, dtype=np.float64)
            a -= np.mean(a)
            b -= np.mean(b)
            denom = float(np.linalg.norm(a) * np.linalg.norm(b))
            if denom <= 1e-12:
                continue
            correlation = float(np.dot(a, b) / denom)
            if correlation <= -0.70:
                warnings.append({
                    "kind": "correlated_phase_cancellation_risk",
                    "layers": [left_name, right_name],
                    "correlation": correlation,
                    "heuristic_only": True,
                })
    return warnings


class HybridVoiceRenderer:
    """Frame-exact transient/body/tail renderer with transparent diagnostics."""

    def __init__(self, *, peak_ceiling: float = 0.98) -> None:
        self.peak_ceiling = _number(peak_ceiling, "peak_ceiling", 0.1, 1.0)

    def render(
        self,
        patch: SoundObjectPatch,
        source_audio: Mapping[str, np.ndarray],
        *,
        frame_count: int | None = None,
        control_values: Mapping[str, float] | None = None,
    ) -> HybridRenderResult:
        if not isinstance(patch, SoundObjectPatch):
            patch = SoundObjectPatch.from_dict(patch)
        frames = patch.duration_frames if frame_count is None else int(frame_count)
        if frames < patch.duration_frames:
            raise ValueError("frame_count cannot truncate any declared layer span")
        if frames < 0:
            raise ValueError("frame_count must be non-negative")
        controls = dict(control_values or {})
        patch_gain = _number(
            controls.get(f"sound_object.{patch.patch_id}.gain", 1.0),
            "sound-object gain", 0.0, 4.0,
        )
        prefix = f"sound_object.{patch.patch_id}"
        global_pan = _number(
            controls.get(f"{prefix}.spatial.pan", patch.spatial.get("pan", 0.0)),
            "spatial.pan", -1.0, 1.0,
        )
        width = _number(
            controls.get(f"{prefix}.spatial.width", patch.spatial.get("width", 1.0)),
            "spatial.width", 0.0, 2.0,
        )
        pitch_semitones = _number(
            controls.get(f"{prefix}.pitch", 0.0), "sound-object pitch", -48.0, 48.0
        )
        attack_override = controls.get(f"{prefix}.attack")
        decay_override = controls.get(f"{prefix}.decay")
        release_override = controls.get(f"{prefix}.release")
        spatial_stems: dict[str, np.ndarray] = {}
        source_map = {item.source_id: item for item in patch.sources}

        modulation_depth = _number(
            controls.get(f"{prefix}.modulation.depth", patch.modulation.get("depth", 0.0)),
            "modulation.depth", 0.0, 1.0,
        )
        modulation_rate = _number(
            controls.get(f"{prefix}.modulation.rate", patch.modulation.get("rate_hz", 0.0)),
            "modulation.rate_hz", 0.0, 40.0,
        )
        if modulation_depth > 0.0 and modulation_rate > 0.0:
            phase_seed = derive_sound_object_seed(patch.seed, patch.patch_id, "coherent-modulation")
            phase = 2.0 * math.pi * (phase_seed / float(1 << 64))
            t = np.arange(frames, dtype=np.float64) / patch.sample_rate
            wave = str(patch.modulation.get("waveform", "sine"))
            cycles = np.mod(modulation_rate * t + phase / (2 * math.pi), 1.0)
            if wave == "triangle":
                lfo = 1.0 - 4.0 * np.abs(cycles - 0.5)
            elif wave == "saw":
                lfo = 2.0 * cycles - 1.0
            elif wave == "square":
                lfo = np.where(cycles < 0.5, 1.0, -1.0)
            else:
                lfo = np.sin(2.0 * math.pi * cycles)
            modulation = (1.0 - modulation_depth) + modulation_depth * (0.5 + 0.5 * lfo)
        else:
            modulation = np.ones(frames, dtype=np.float64)

        for layer in patch.layers:
            source_spec = source_map[layer.source_id]
            if layer.source_id not in source_audio:
                raise KeyError(f"missing source audio for {layer.source_id!r}")
            if source_spec.sample_rate != patch.sample_rate:
                raise ValueError("source and patch sample rates differ; explicit resampling is required")
            source = np.asarray(source_audio[layer.source_id], dtype=np.float32)
            if source.ndim == 2 and source.shape[1] == 1:
                source = source[:, 0]
            if source.ndim not in {1, 2} or (source.ndim == 2 and source.shape[1] != 2):
                raise ValueError("source audio must have shape (frames,) or (frames, 2)")
            actual_channels = 1 if source.ndim == 1 else 2
            if actual_channels != source_spec.channels:
                raise ValueError(
                    f"source {layer.source_id!r} declares {source_spec.channels} channels "
                    f"but supplied audio has {actual_channels}"
                )
            if not np.isfinite(source).all():
                raise ValueError("source audio must contain only finite samples")
            length = layer.frame_count
            source_begin = layer.source_start_frame
            pitch_ratio = 2.0 ** (pitch_semitones / 12.0)
            required_source_frames = max(
                1, int(math.ceil(max(0, length - 1) * pitch_ratio)) + 1
            )
            source_end = min(len(source), source_begin + required_source_frames)
            segment = source[source_begin:source_end]
            if len(segment) < required_source_frames:
                shape = (
                    (required_source_frames - len(segment),)
                    if source.ndim == 1
                    else (required_source_frames - len(segment), 2)
                )
                segment = np.concatenate(
                    (segment, np.zeros(shape, dtype=np.float32)), axis=0
                )
            if abs(pitch_semitones) > 1e-9:
                source_positions = np.arange(length, dtype=np.float64) * pitch_ratio
                source_axis = np.arange(len(segment), dtype=np.float64)
                if segment.ndim == 1:
                    segment = np.interp(
                        source_positions, source_axis, segment,
                        left=0.0, right=0.0,
                    ).astype(np.float32)
                else:
                    segment = np.column_stack([
                        np.interp(
                            source_positions, source_axis, segment[:, channel],
                            left=0.0, right=0.0,
                        )
                        for channel in range(2)
                    ]).astype(np.float32)
            envelope_spec = layer.envelope
            if any(value is not None for value in (
                attack_override, decay_override, release_override
            )):
                envelope_spec = EnvelopeSpec(
                    attack_seconds=(
                        envelope_spec.attack_seconds if attack_override is None
                        else _number(attack_override, "attack override", 0.0, 30.0)
                    ),
                    decay_seconds=(
                        envelope_spec.decay_seconds if decay_override is None
                        else _number(decay_override, "decay override", 0.0, 30.0)
                    ),
                    sustain_level=envelope_spec.sustain_level,
                    release_seconds=(
                        envelope_spec.release_seconds if release_override is None
                        else _number(release_override, "release override", 0.0, 30.0)
                    ),
                    attack_curve=envelope_spec.attack_curve,
                    decay_curve=envelope_spec.decay_curve,
                    release_curve=envelope_spec.release_curve,
                )
            envelope = build_envelope_curve(length, patch.sample_rate, envelope_spec)
            layer_gain = _number(
                controls.get(f"{prefix}.layer.{layer.layer_id}.gain", layer.gain),
                "layer gain", 0.0, 4.0,
            )
            segment = segment * envelope.reshape((-1,) if segment.ndim == 1 else (-1, 1))
            segment = segment * float(layer_gain) * modulation[
                layer.start_frame:layer.end_frame
            ].reshape((-1,) if segment.ndim == 1 else (-1, 1))
            pan = _number(global_pan + layer.pan, "combined pan", -2.0, 2.0)
            segment = _to_stereo(segment, max(-1.0, min(1.0, pan)), width)
            rendered = np.zeros((frames, 2), dtype=np.float32)
            rendered[layer.start_frame:layer.end_frame] = segment
            spatial_stems[layer.layer_id] = rendered

        mix = np.zeros((frames, 2), dtype=np.float64)
        for stem in spatial_stems.values():
            mix += stem.astype(np.float64)
        mix *= patch_gain
        pre_peak = float(np.max(np.abs(mix))) if mix.size else 0.0
        clip_count = int(np.count_nonzero(np.abs(mix) > 1.0))
        headroom_gain = min(1.0, self.peak_ceiling / pre_peak) if pre_peak > 0 else 1.0
        mix *= headroom_gain
        final = mix.astype(np.float32)
        mono = (final[:, 0] + final[:, 1]) * 0.5 if frames else np.empty(0)
        stereo_rms = float(np.sqrt(np.mean(np.square(final, dtype=np.float64)))) if frames else 0.0
        mono_rms = float(np.sqrt(np.mean(np.square(mono, dtype=np.float64)))) if frames else 0.0
        mono_loss_db = (
            20.0 * math.log10(max(mono_rms, 1e-12) / max(stereo_rms, 1e-12))
            if stereo_rms > 0 else 0.0
        )
        warnings = _phase_warnings(spatial_stems)
        if mono_loss_db < -6.0:
            warnings.append({
                "kind": "mono_fold_level_loss",
                "loss_db": mono_loss_db,
                "heuristic_only": True,
            })
        if clip_count:
            warnings.append({
                "kind": "headroom_compensation",
                "pre_scale_clipped_samples": clip_count,
                "applied_gain": headroom_gain,
            })
        return HybridRenderResult(
            audio=final,
            layers=spatial_stems,
            diagnostics={
                "sample_rate": patch.sample_rate,
                "frame_count": frames,
                "peak_before_headroom": pre_peak,
                "peak_after_headroom": float(np.max(np.abs(final))) if final.size else 0.0,
                "headroom_gain": headroom_gain,
                "pre_scale_clipped_samples": clip_count,
                "mono_fold_loss_db": mono_loss_db,
                "warnings": warnings,
                "rendered_layer_count": len(spatial_stems),
                "pitch_semitones": pitch_semitones,
                "modulation_rate_hz": modulation_rate,
                "modulation_depth": modulation_depth,
                "audio_bytes": int(final.nbytes + sum(item.nbytes for item in spatial_stems.values())),
            },
        )


def sound_object_automation_targets(patch: SoundObjectPatch):
    """Return typed Score automation destinations scoped to one sound-object patch."""
    from reawarp.score.automation import AutomationTarget

    prefix = f"sound_object.{patch.patch_id}"
    targets = [
        AutomationTarget(f"{prefix}.gain", "synthesis", "normalized", minimum=0.0, maximum=4.0),
        AutomationTarget(f"{prefix}.pitch", "synthesis", "semitones", minimum=-48.0, maximum=48.0, update_clock="event"),
        AutomationTarget(f"{prefix}.attack", "synthesis", "seconds", minimum=0.0, maximum=30.0, update_clock="event"),
        AutomationTarget(f"{prefix}.decay", "synthesis", "seconds", minimum=0.0, maximum=30.0, update_clock="event"),
        AutomationTarget(f"{prefix}.release", "synthesis", "seconds", minimum=0.0, maximum=30.0, update_clock="event"),
        AutomationTarget(f"{prefix}.modulation.rate", "synthesis", "Hz", minimum=0.0, maximum=40.0, update_clock="event"),
        AutomationTarget(f"{prefix}.modulation.depth", "synthesis", "normalized", minimum=0.0, maximum=1.0, update_clock="event"),
        AutomationTarget(f"{prefix}.spatial.pan", "spatial", "normalized", minimum=-1.0, maximum=1.0, update_clock="event"),
        AutomationTarget(f"{prefix}.spatial.width", "spatial", "ratio", minimum=0.0, maximum=2.0, update_clock="event"),
    ]
    targets.extend(
        AutomationTarget(
            f"{prefix}.layer.{layer.layer_id}.gain",
            "synthesis", "normalized", minimum=0.0, maximum=4.0,
            update_clock="event",
        )
        for layer in patch.layers
    )
    return tuple(targets)


def register_sound_object_automation_targets(registry: Any, patch: SoundObjectPatch):
    """Register patch-scoped controls in an existing AutomationTargetRegistry."""
    for target in sound_object_automation_targets(patch):
        registry.register(target)
    return registry


def render_modal_resonator_bank(
    frequencies_hz: Sequence[float],
    amplitudes: Sequence[float],
    *,
    frames: int,
    sample_rate: int,
    decay_seconds: float | Sequence[float] = 1.5,
    attack_seconds: float = 0.002,
    seed: int = 0,
) -> np.ndarray:
    """CPU modal bank for metallic, bell-like or inharmonic resonant bodies."""
    if frames < 0 or sample_rate <= 0:
        raise ValueError("frames must be non-negative and sample_rate positive")
    frequencies = np.asarray(frequencies_hz, dtype=np.float64)
    gains = np.asarray(amplitudes, dtype=np.float64)
    if frequencies.ndim != 1 or gains.shape != frequencies.shape or len(frequencies) == 0:
        raise ValueError("frequencies_hz and amplitudes must be matching non-empty vectors")
    if not np.isfinite(frequencies).all() or np.any(frequencies <= 0) or np.any(frequencies >= sample_rate / 2):
        raise ValueError("modal frequencies must be positive and below Nyquist")
    if not np.isfinite(gains).all() or np.any(gains < 0) or not np.any(gains > 0):
        raise ValueError("modal amplitudes must be finite, non-negative and not all zero")
    decays = np.asarray(decay_seconds if np.ndim(decay_seconds) else [decay_seconds] * len(frequencies), dtype=np.float64)
    if decays.shape != frequencies.shape or not np.isfinite(decays).all() or np.any(decays <= 0):
        raise ValueError("each modal decay must be finite and positive")
    attack = _number(attack_seconds, "attack_seconds", 0.0, 30.0)
    rng = np.random.default_rng(derive_sound_object_seed(seed, "modal-bank"))
    phases = rng.uniform(0.0, 2.0 * math.pi, len(frequencies))
    t = np.arange(frames, dtype=np.float64) / float(sample_rate)
    attack_curve = 1.0 - np.exp(-t / max(attack, 1e-5))
    audio = np.zeros(frames, dtype=np.float64)
    for frequency, gain, decay, phase in zip(frequencies, gains, decays, phases, strict=True):
        audio += gain * np.sin(2.0 * math.pi * frequency * t + phase) * np.exp(-t / decay)
    audio *= attack_curve
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak > 0.8:
        audio *= 0.8 / peak
    return audio.astype(np.float32)


def render_additive_partial_voice(
    fundamental_hz: float,
    partials: Sequence[Mapping[str, float]],
    *,
    frames: int,
    sample_rate: int,
    seed: int = 0,
    attack_seconds: float = 0.005,
) -> np.ndarray:
    """Additive voice with independently decaying partials and deterministic phases."""
    fundamental = _number(fundamental_hz, "fundamental_hz", 0.001, sample_rate / 2)
    if frames < 0 or sample_rate <= 0:
        raise ValueError("frames must be non-negative and sample_rate positive")
    if not partials:
        raise ValueError("at least one additive partial is required")
    validated = []
    for item in partials:
        ratio = _number(item.get("ratio", 1.0), "partial ratio", 0.0001)
        gain = _number(item.get("gain", 0.0), "partial gain", 0.0, 4.0)
        decay = _number(item.get("decay_seconds", 1.0), "partial decay", 0.001, 60.0)
        frequency = fundamental * ratio
        if frequency >= sample_rate / 2:
            raise ValueError("additive partial frequency must remain below Nyquist")
        validated.append((frequency, gain, decay))
    rng = np.random.default_rng(derive_sound_object_seed(seed, "additive-partials"))
    phases = rng.uniform(0.0, 2.0 * math.pi, len(validated))
    t = np.arange(frames, dtype=np.float64) / float(sample_rate)
    attack = _number(attack_seconds, "attack_seconds", 0.0, 30.0)
    envelope = 1.0 - np.exp(-t / max(attack, 1e-5))
    audio = np.zeros(frames, dtype=np.float64)
    for (frequency, gain, decay), phase in zip(validated, phases, strict=True):
        audio += gain * np.sin(2.0 * math.pi * frequency * t + phase) * np.exp(-t / decay)
    audio *= envelope
    peak = float(np.max(np.abs(audio))) if len(audio) else 0.0
    if peak > 0.8:
        audio *= 0.8 / peak
    return audio.astype(np.float32)


def resample_audio_non_destructive(
    audio: np.ndarray, source_sample_rate: int, target_sample_rate: int,
    *, seed: int = 0,
) -> tuple[np.ndarray, TransformationRecord]:
    """Linearly resample a new buffer and record both source/output hashes."""
    if source_sample_rate <= 0 or target_sample_rate <= 0:
        raise ValueError("sample rates must be positive")
    source = np.asarray(audio, dtype=np.float32)
    if source.ndim not in {1, 2} or (source.ndim == 2 and source.shape[1] not in {1, 2}):
        raise ValueError("audio must be mono or stereo")
    if not np.isfinite(source).all():
        raise ValueError("audio must contain only finite samples")
    out_frames = int(round(len(source) * target_sample_rate / source_sample_rate))
    if len(source) == 0 or out_frames == 0:
        output = np.zeros((out_frames,) if source.ndim == 1 else (out_frames, source.shape[1]), dtype=np.float32)
    else:
        old_positions = np.arange(len(source), dtype=np.float64)
        new_positions = np.arange(out_frames, dtype=np.float64) * source_sample_rate / target_sample_rate
        new_positions = np.clip(new_positions, 0.0, max(0, len(source) - 1))
        if source.ndim == 1:
            output = np.interp(new_positions, old_positions, source).astype(np.float32)
        else:
            output = np.column_stack([
                np.interp(new_positions, old_positions, source[:, channel])
                for channel in range(source.shape[1])
            ]).astype(np.float32)
    record = TransformationRecord(
        operation="resample",
        seed=int(seed),
        parameters={"source_sample_rate": int(source_sample_rate), "target_sample_rate": int(target_sample_rate), "frames_before": len(source), "frames_after": out_frames, "interpolation": "linear"},
        source_sha256=_audio_hash(source),
        output_sha256=_audio_hash(output),
        preserved_dimensions=("source_identity", "relative_timing", "channel_count"),
        changed_dimensions=("sample_rate", "frame_count"),
    )
    return output, record



def build_score_sound_object_renderer(
    patch: SoundObjectPatch,
    source_audio: Mapping[str, np.ndarray],
):
    """Adapt one sound-object patch to the ScoreRenderer voice callback contract.

    The score event duration must contain the complete patch layer span. Any
    longer event duration becomes explicit post-object silence/tail room. The
    callback returns exactly ScheduledScoreEvent.duration_frames and consumes
    the patch-scoped typed automation targets registered by
    `register_sound_object_automation_targets`.
    """
    from reawarp.synthesis.sound_object import HybridVoiceRenderer as _Renderer

    if not isinstance(patch, SoundObjectPatch):
        patch = SoundObjectPatch.from_dict(patch)
    frozen_sources: dict[str, np.ndarray] = {}
    source_specs = {item.source_id: item for item in patch.sources}
    for source_id, audio in source_audio.items():
        if source_id not in source_specs:
            raise ValueError(f"audio supplied for undeclared source {source_id!r}")
        array = np.asarray(audio, dtype=np.float32)
        if array.ndim not in {1, 2} or (
            array.ndim == 2 and array.shape[1] not in {1, 2}
        ):
            raise ValueError(f"source {source_id!r} must be mono or stereo")
        if not np.isfinite(array).all():
            raise ValueError(f"source {source_id!r} contains non-finite samples")
        frozen_sources[source_id] = np.ascontiguousarray(array).copy()
    missing = set(source_specs) - set(frozen_sources)
    if missing:
        raise KeyError("missing sound-object source(s): " + ", ".join(sorted(missing)))
    target_ids = {
        target.target_id for target in sound_object_automation_targets(patch)
    }
    renderer = _Renderer()

    def render(scheduled, sample_rate: int, controls) -> np.ndarray:
        if int(sample_rate) != patch.sample_rate:
            raise ValueError(
                "Score sample rate must match sound-object patch; resample sources explicitly"
            )
        if scheduled.duration_frames < patch.duration_frames:
            raise ValueError(
                "Score event duration is shorter than the sound-object layers; "
                "extend the event so the tail can complete"
            )
        values: dict[str, float] = {}
        for target_id in target_ids.intersection(controls.target_ids):
            value, active = controls.value_and_active_for_context(
                target_id,
                scheduled.start_frame,
                event_id=scheduled.event.event_id,
                default_value=0.0,
            )
            if active:
                values[target_id] = float(value)
        result = renderer.render(
            patch,
            frozen_sources,
            frame_count=scheduled.duration_frames,
            control_values=values,
        )
        return result.audio

    return render


def sound_object_editor_model(patch: SoundObjectPatch) -> dict[str, Any]:
    """Return a stable, UI-neutral editing model with units, ranges and choices."""
    if not isinstance(patch, SoundObjectPatch):
        patch = SoundObjectPatch.from_dict(patch)
    return {
        "format": SOUND_OBJECT_FORMAT,
        "schema_version": patch.schema_version,
        "identity": {
            "patch_id": patch.patch_id,
            "name": patch.name,
            "source_identity_id": patch.source_identity_id,
            "processing_identity_id": patch.processing_identity_id,
            "seed": patch.seed,
        },
        "clock": {"sample_rate_hz": patch.sample_rate, "frame_unit": "frames"},
        "sources": [
            {
                **item.to_dict(),
                "hash_verified_on_library_save": item.source_kind == "asset",
            }
            for item in patch.sources
        ],
        "layers": [
            {
                **item.to_dict(),
                "frame_count": item.frame_count,
                "editable_fields": {
                    "role": sorted(LAYER_ROLES),
                    "start_frame": {"minimum": 0, "unit": "frames"},
                    "end_frame": {"minimum": item.start_frame + 1, "unit": "frames"},
                    "source_start_frame": {"minimum": 0, "unit": "frames"},
                    "gain": {"minimum": 0.0, "maximum": 4.0, "unit": "linear"},
                    "pan": {"minimum": -1.0, "maximum": 1.0, "unit": "normalized"},
                    "envelope": {
                        "attack_seconds": {"minimum": 0.0, "maximum": 30.0, "unit": "seconds"},
                        "decay_seconds": {"minimum": 0.0, "maximum": 30.0, "unit": "seconds"},
                        "sustain_level": {"minimum": 0.0, "maximum": 1.0, "unit": "normalized"},
                        "release_seconds": {"minimum": 0.0, "maximum": 30.0, "unit": "seconds"},
                    },
                },
            }
            for item in patch.layers
        ],
        "pitch_model": patch.pitch_model,
        "spectrum": patch.spectrum,
        "modulation": patch.modulation,
        "spatial": patch.spatial,
        "transformations": [item.to_dict() for item in patch.transformations],
        "controls": [
            {
                "target_id": item.target_id,
                "domain": item.domain,
                "unit": item.unit,
                "value_type": item.value_type,
                "minimum": item.minimum,
                "maximum": item.maximum,
                "update_clock": item.update_clock,
            }
            for item in sound_object_automation_targets(patch)
        ],
    }
