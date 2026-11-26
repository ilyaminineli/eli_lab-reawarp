"""M31 sound-object workshop services over the existing M21 renderer."""
from __future__ import annotations

import hashlib
import json
import re
import wave
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from reawarp.library.store import LibraryAsset, SampleLibrary
from reawarp.synthesis.sound_object import (
    EnvelopeSpec, HybridRenderResult, HybridVoiceRenderer, SoundObjectLayer,
    SoundObjectPatch, SoundObjectSource, TransformationRecord,
    derive_sound_object_seed, resample_audio_non_destructive,
)

RENDERER_VERSION = "hybrid-m21-v1"


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _audio_hash(audio: np.ndarray) -> str:
    array = np.ascontiguousarray(np.asarray(audio, dtype="<f4"))
    digest = hashlib.sha256()
    digest.update(str(array.shape).encode("ascii"))
    digest.update(array.tobytes())
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class SoundObjectVersion:
    object_id: str
    version_id: str
    revision: int
    content_sha256: str
    source_identity_id: str
    processing_identity_id: str
    source_hashes: tuple[str, ...]

    @classmethod
    def from_patch(cls, patch: SoundObjectPatch, revision: int) -> "SoundObjectVersion":
        digest = hashlib.sha256(_json(patch.to_dict()).encode("utf-8")).hexdigest()
        return cls(
            patch.patch_id, f"{patch.patch_id}@{revision:04d}-{digest[:12]}",
            revision, digest, patch.source_identity_id,
            patch.processing_identity_id, patch.source_hashes,
        )


@dataclass(frozen=True, slots=True)
class RoleAssignment:
    assignment_id: str
    object_version_id: str
    target_role: str
    processing_identity_id: str
    parameters: Mapping[str, Any] | None = None

    @classmethod
    def for_version(cls, version: SoundObjectVersion, target_role: str) -> "RoleAssignment":
        role = str(target_role).strip().casefold()
        if not role:
            raise ValueError("target role cannot be empty")
        processing = f"{version.processing_identity_id}:role:{role}"
        identity = hashlib.sha256(
            f"{version.version_id}|{role}|{processing}".encode("utf-8")
        ).hexdigest()[:24]
        return cls(f"role-{identity}", version.version_id, role, processing, {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "assignment_id": self.assignment_id,
            "object_version_id": self.object_version_id,
            "target_role": self.target_role,
            "processing_identity_id": self.processing_identity_id,
            "parameters": dict(self.parameters or {}),
        }


@dataclass(frozen=True, slots=True)
class ResampleRecord:
    record_id: str
    object_id: str
    object_version_id: str
    source_asset_ids: tuple[str, ...]
    source_hashes: tuple[str, ...]
    render_settings: Mapping[str, Any]
    seed: int
    source_sample_rate_hz: int
    output_sample_rate_hz: int
    rendered_audio_sha256: str
    output_file_sha256: str
    parent_lineage: tuple[str, ...]
    role_assignment: Mapping[str, Any]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported resample-record schema")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("resample seed must be non-negative")
        for name in ("source_sample_rate_hz", "output_sample_rate_hz"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be positive")
        for name in ("rendered_audio_sha256", "output_file_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", str(getattr(self, name)).casefold()):
                raise ValueError(f"{name} must be a SHA-256 digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "object_id": self.object_id,
            "object_version_id": self.object_version_id,
            "source_asset_ids": list(self.source_asset_ids),
            "source_hashes": list(self.source_hashes),
            "render_settings": dict(self.render_settings),
            "seed": self.seed,
            "source_sample_rate_hz": self.source_sample_rate_hz,
            "output_sample_rate_hz": self.output_sample_rate_hz,
            "rendered_audio_sha256": self.rendered_audio_sha256,
            "output_file_sha256": self.output_file_sha256,
            "parent_lineage": list(self.parent_lineage),
            "role_assignment": dict(self.role_assignment),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ResampleRecord":
        return cls(
            schema_version=int(data.get("schema_version", 0)),
            record_id=str(data["record_id"]),
            object_id=str(data["object_id"]),
            object_version_id=str(data["object_version_id"]),
            source_asset_ids=tuple(data.get("source_asset_ids", ())),
            source_hashes=tuple(data.get("source_hashes", ())),
            render_settings=dict(data.get("render_settings", {})),
            seed=int(data["seed"]),
            source_sample_rate_hz=int(data["source_sample_rate_hz"]),
            output_sample_rate_hz=int(data["output_sample_rate_hz"]),
            rendered_audio_sha256=str(data["rendered_audio_sha256"]),
            output_file_sha256=str(data["output_file_sha256"]),
            parent_lineage=tuple(data.get("parent_lineage", ())),
            role_assignment=dict(data.get("role_assignment", {})),
        )


def create_sound_object_from_asset(
    asset: LibraryAsset, *, name: str | None = None, patch_id: str | None = None
) -> SoundObjectPatch:
    safe_name = str(name or Path(asset.file_name).stem).strip()
    if not safe_name:
        raise ValueError("sound-object name cannot be empty")
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", safe_name).strip("-")[:36] or "object"
    stable_id = patch_id or f"so-{slug}-{asset.sha256[:10]}"
    rate = int(asset.source_sample_rate)
    frames = max(1, int(round(asset.duration_seconds * rate)))
    source = SoundObjectSource(
        "source", source_kind="asset", asset_id=asset.asset_id,
        asset_sha256=asset.sha256, sample_rate=rate, channels=1,
    )
    layer = SoundObjectLayer(
        "body", "body", "source", 0, frames, gain=1.0,
        envelope=EnvelopeSpec(), identity_tags=("imported-source",),
    )
    return SoundObjectPatch(
        patch_id=stable_id, name=safe_name, sample_rate=rate, seed=0,
        source_identity_id=f"source:{asset.sha256[:20]}",
        processing_identity_id="processing:unshaped-source",
        sources=(source,), layers=(layer,),
    )


def _read_source(path: Path, rate: int, channels: int):
    if not path.is_file():
        raise FileNotFoundError(f"sound-object source is missing: {path}")
    try:
        import soundfile as sf
        audio, source_rate = sf.read(str(path), dtype="float32", always_2d=True)
    except ImportError:
        from reawarp.samples.io import read_sample
        if channels != 1:
            raise RuntimeError("stereo audition requires the optional soundfile backend")
        return read_sample(path, rate), None
    if audio.size == 0:
        raise ValueError(f"sound-object source is empty: {path}")
    if channels == 1:
        audio = audio.mean(axis=1, dtype=np.float32)
    elif audio.shape[1] >= 2:
        audio = audio[:, :2]
    else:
        raise ValueError(f"source {path} is mono but the patch declares two channels")
    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
    record = None
    if int(source_rate) != int(rate):
        audio, record = resample_audio_non_destructive(audio, int(source_rate), int(rate), seed=0)
    return audio, record


def load_sound_object_sources(
    patch: SoundObjectPatch, library: SampleLibrary, *, cancel_event: Any | None = None
) -> tuple[dict[str, np.ndarray], tuple[TransformationRecord, ...], tuple[str, ...]]:
    audio_map: dict[str, np.ndarray] = {}
    transforms: list[TransformationRecord] = []
    asset_ids: list[str] = []
    for source in patch.sources:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("sound-object source loading cancelled")
        needed = max(
            layer.source_start_frame + layer.frame_count
            for layer in patch.layers if layer.source_id == source.source_id
        )
        if source.source_kind == "asset":
            if source.asset_id:
                asset = library.get_asset(source.asset_id)
                if asset is None:
                    raise KeyError(f"sound-object source asset not indexed: {source.asset_id}")
                if asset.sha256.casefold() != str(source.asset_sha256).casefold():
                    raise ValueError(f"source hash changed for asset {source.asset_id}")
                path = Path(asset.path)
                asset_ids.append(asset.asset_id)
            else:
                path = Path(str(source.uri)).expanduser()
            if _file_hash(path).casefold() != str(source.asset_sha256).casefold():
                raise ValueError(f"source hash changed or source is missing: {path}")
            audio, record = _read_source(path, patch.sample_rate, source.channels)
            if record is not None:
                transforms.append(record)
        else:
            seed = derive_sound_object_seed(patch.seed, patch.patch_id, source.source_id)
            rng = np.random.default_rng(seed)
            time = np.arange(needed, dtype=np.float64) / patch.sample_rate
            model = str(source.source_model or "").casefold()
            frequency = float(patch.pitch_model.get("frequency_hz", 220.0))
            noise = rng.normal(0.0, 1.0, needed)
            if "impulse" in model or "noise" in model:
                audio = noise * np.exp(-time * (18.0 if "impulse" in model else 5.0))
            elif any(word in model for word in ("modal", "reson", "sine")):
                ratios = [
                    float(item.get("ratio", 1.0))
                    for item in patch.spectrum.get("partials", [])
                ] or [1.0, 1.414, 2.17]
                audio = np.sum([
                    np.sin(2 * np.pi * frequency * ratio * time) / (1 + index)
                    for index, ratio in enumerate(ratios)
                ], axis=0)
                if "tail" in model:
                    audio *= np.exp(-time * 3.5)
            else:
                audio = noise * np.exp(-time * 1.5)
            audio = np.asarray(audio, dtype=np.float32)
            if source.channels == 2:
                audio = np.column_stack((audio, audio))
        if len(audio) < needed:
            audio = np.pad(audio, ((0, needed - len(audio)),) if audio.ndim == 1
                           else ((0, needed - len(audio)), (0, 0)))
        audio_map[source.source_id] = np.ascontiguousarray(audio[:needed], dtype=np.float32)
    return audio_map, tuple(transforms), tuple(asset_ids)


def render_sound_object_audition(
    patch: SoundObjectPatch, library: SampleLibrary, *,
    layer_id: str | None = None, cancel_event: Any | None = None,
) -> HybridRenderResult:
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("sound-object audition cancelled")
    sources, _, _ = load_sound_object_sources(patch, library, cancel_event=cancel_event)
    render_patch = patch
    if layer_id:
        layer = next((item for item in patch.layers if item.layer_id == layer_id), None)
        if layer is None:
            raise KeyError(f"unknown layer: {layer_id}")
        render_patch = replace(patch, layers=(layer,))
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("sound-object audition cancelled")
    return HybridVoiceRenderer().render(render_patch, sources, frame_count=patch.duration_frames)


def _write_wave(path: Path, audio: np.ndarray, sample_rate: int) -> None:
    samples = np.asarray(audio, dtype=np.float32)
    if samples.ndim == 1:
        samples = np.column_stack((samples, samples))
    if samples.ndim != 2 or samples.shape[1] != 2 or not np.isfinite(samples).all():
        raise ValueError("print audio must be finite mono/stereo audio")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import soundfile as sf
        sf.write(str(path), np.clip(samples, -1.0, 1.0), int(sample_rate), subtype="PCM_24")
    except ImportError:
        pcm = np.rint(np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(2)
            handle.setsampwidth(2)
            handle.setframerate(int(sample_rate))
            handle.writeframes(pcm.tobytes())


@dataclass(frozen=True, slots=True)
class SoundObjectPrintResult:
    asset: LibraryAsset
    version: SoundObjectVersion
    record: ResampleRecord
    variant_id: str
    diagnostics: Mapping[str, Any]


def print_sound_object_to_asset(
    patch: SoundObjectPatch,
    library: SampleLibrary,
    output_path: str | Path,
    *,
    target_sample_rate: int | None = None,
    seed: int | None = None,
    target_role: str = "texture",
    cancel_event: Any | None = None,
) -> SoundObjectPrintResult:
    chosen_seed = patch.seed if seed is None else seed
    if isinstance(chosen_seed, bool) or not isinstance(chosen_seed, int) or chosen_seed < 0:
        raise ValueError("print seed must be non-negative")
    target_rate = patch.sample_rate if target_sample_rate is None else int(target_sample_rate)
    if target_rate <= 0:
        raise ValueError("target sample rate must be positive")
    destination = Path(output_path).expanduser().resolve()
    if destination.suffix.casefold() != ".wav":
        raise ValueError("print destination must be WAV")
    protected = {
        str(Path(asset.path).expanduser().resolve())
        for source in patch.sources if source.asset_id
        for asset in [library.get_asset(source.asset_id)] if asset is not None
    }
    protected.update(
        str(Path(source.uri).expanduser().resolve())
        for source in patch.sources if source.uri
    )
    if str(destination) in protected:
        raise ValueError("print destination cannot overwrite an original sound-object source")
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("sound-object print cancelled")

    render_patch = replace(patch, seed=chosen_seed)
    source_audio, source_transforms, source_asset_ids = load_sound_object_sources(
        render_patch, library, cancel_event=cancel_event
    )
    rendered = HybridVoiceRenderer().render(render_patch, source_audio)
    audio = rendered.audio
    resample_transform = None
    if target_rate != patch.sample_rate:
        audio, resample_transform = resample_audio_non_destructive(
            audio, patch.sample_rate, target_rate, seed=chosen_seed
        )
    if cancel_event is not None and cancel_event.is_set():
        raise RuntimeError("sound-object print cancelled")

    patch_digest = library.save_sound_object(patch)
    versions = library.list_sound_object_versions(patch.patch_id)
    latest = versions[-1]
    version = SoundObjectVersion(
        patch.patch_id, latest["version_id"], int(latest["revision"]),
        latest["content_sha256"], patch.source_identity_id,
        patch.processing_identity_id, patch.source_hashes,
    )
    role = RoleAssignment.for_version(version, target_role)
    temporary = destination.with_name(destination.stem + ".reawarp-tmp.wav")
    try:
        _write_wave(temporary, audio, target_rate)
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("sound-object print cancelled")
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()

    output_hash = _file_hash(destination)
    transform_chain = [item.to_dict() for item in (*patch.transformations, *source_transforms)]
    if resample_transform is not None:
        transform_chain.append(resample_transform.to_dict())
    record_id = hashlib.sha256(
        f"{version.version_id}|{chosen_seed}|{target_rate}|{output_hash}".encode("utf-8")
    ).hexdigest()[:24]
    record = ResampleRecord(
        record_id=f"resample-{record_id}",
        object_id=patch.patch_id,
        object_version_id=version.version_id,
        source_asset_ids=source_asset_ids,
        source_hashes=patch.source_hashes,
        render_settings={
            "renderer": "HybridVoiceRenderer",
            "renderer_version": RENDERER_VERSION,
            "patch_sha256": patch_digest,
            "source_frame_count": patch.duration_frames,
            "output_frame_count": len(audio),
            "source_sample_rate_hz": patch.sample_rate,
            "output_sample_rate_hz": target_rate,
            "resampler": None if resample_transform is None else "linear",
            "source_transformations": transform_chain,
            "render_diagnostics": dict(rendered.diagnostics),
        },
        seed=chosen_seed,
        source_sample_rate_hz=patch.sample_rate,
        output_sample_rate_hz=target_rate,
        rendered_audio_sha256=_audio_hash(audio),
        output_file_sha256=output_hash,
        parent_lineage=(patch.source_identity_id, *source_asset_ids),
        role_assignment=role.to_dict(),
    )
    transform = TransformationRecord(
        operation="m31_sound_object_print",
        seed=chosen_seed,
        parameters={"resample_record": record.to_dict()},
        source_sha256=version.content_sha256,
        output_sha256=output_hash,
        preserved_dimensions=("source_identity", "source_hashes", "object_id"),
        changed_dimensions=("printed_asset", "output_sample_rate", "role_processing_identity"),
    )
    asset = library.index_file(
        destination, asset_type="sound_object_print", role=role.target_role,
        tags=("m31-print", "sound-object", patch.name),
        metadata={
            "sound_object_version_id": version.version_id,
            "role_assignment": role.to_dict(),
            "resample_record": record.to_dict(),
        },
    )
    variant_id = library.record_sound_object_variant(
        patch.patch_id, asset.asset_id, seed=chosen_seed,
        source_hashes=patch.source_hashes,
        transformations=(*patch.transformations, transform),
    )
    return SoundObjectPrintResult(asset, version, record, variant_id, rendered.diagnostics)


def create_sound_object_from_file(path: str | Path, *, name: str | None = None) -> SoundObjectPatch:
    with SampleLibrary() as library:
        asset = library.index_file(path, asset_type="sound_object_source", tags=("m31-source",))
        patch = create_sound_object_from_asset(asset, name=name)
        library.save_sound_object(patch)
        return patch


__all__ = [
    "RENDERER_VERSION", "ResampleRecord", "RoleAssignment", "SoundObjectPrintResult",
    "SoundObjectVersion", "create_sound_object_from_asset", "create_sound_object_from_file",
    "load_sound_object_sources", "print_sound_object_to_asset", "render_sound_object_audition",
]
