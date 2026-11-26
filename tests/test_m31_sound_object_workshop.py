from __future__ import annotations

from dataclasses import replace
import hashlib
import wave

import numpy as np
import pytest

from reawarp.library.store import SampleLibrary
from reawarp.synthesis.sound_object import (
    EnvelopeSpec, SoundObjectLayer, SoundObjectPatch, SoundObjectSource,
)
from reawarp.synthesis.workshop import (
    ResampleRecord, RoleAssignment, SoundObjectVersion,
    create_sound_object_from_asset, print_sound_object_to_asset,
    render_sound_object_audition,
)


def _patch():
    source = SoundObjectSource(
        "osc", source_kind="procedural", sample_rate=8_000, source_model="modal-sine",
    )
    layers = (
        SoundObjectLayer("transient", "transient", "osc", 0, 256, gain=0.5,
                         envelope=EnvelopeSpec(attack_seconds=0.001, release_seconds=0.02)),
        SoundObjectLayer("body", "body", "osc", 128, 1_024, gain=0.35),
        SoundObjectLayer("tail", "tail", "osc", 700, 1_600, gain=0.2,
                         envelope=EnvelopeSpec(attack_seconds=0.01, release_seconds=0.12)),
    )
    return SoundObjectPatch(
        patch_id="m31-object", name="M31 metallic object", sample_rate=8_000, seed=21,
        source_identity_id="source:m31-metal", processing_identity_id="process:m31-metal",
        sources=(source,), layers=layers, pitch_model={"frequency_hz": 440.0},
    )


def test_sound_object_versions_are_immutable_and_content_addressed():
    library = SampleLibrary(":memory:")
    try:
        patch = _patch()
        digest = library.save_sound_object(patch)
        versions = library.list_sound_object_versions(patch.patch_id)
        assert len(versions) == 1 and versions[0]["content_sha256"] == digest
        assert versions[0]["revision"] == 1
        assert versions[0]["patch"].to_dict() == patch.to_dict()
        library.save_sound_object(patch)
        assert len(library.list_sound_object_versions(patch.patch_id)) == 1
        changed = replace(patch, name="M31 metallic body")
        library.save_sound_object(changed)
        history = library.list_sound_object_versions(patch.patch_id)
        assert [item["revision"] for item in history] == [1, 2]
        assert history[0]["patch"].to_dict() == patch.to_dict()
        assert history[1]["patch"].to_dict() == changed.to_dict()
    finally:
        library.close()


def test_layer_solo_and_full_object_are_frame_aligned():
    library = SampleLibrary(":memory:")
    try:
        patch = _patch()
        library.save_sound_object(patch)
        full = render_sound_object_audition(patch, library)
        transient = render_sound_object_audition(patch, library, layer_id="transient")
        tail = render_sound_object_audition(patch, library, layer_id="tail")
        assert full.audio.shape == transient.audio.shape == tail.audio.shape == (patch.duration_frames, 2)
        assert set(full.layers) == {"transient", "body", "tail"}
        assert set(transient.layers) == {"transient"} and set(tail.layers) == {"tail"}
        assert np.max(np.abs(transient.audio)) > 0 and np.max(np.abs(tail.audio)) > 0
    finally:
        library.close()


def test_print_creates_new_asset_with_source_and_role_lineage(tmp_path):
    library = SampleLibrary(":memory:")
    try:
        source_path = tmp_path / "source.wav"
        sample_rate = 8_000
        tone = np.sin(2.0 * np.pi * 440.0 * np.arange(4_000) / sample_rate) * 0.2
        pcm = np.clip(tone * 32767, -32768, 32767).astype("<i2")
        with wave.open(str(source_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm.tobytes())
        before = hashlib.sha256(source_path.read_bytes()).hexdigest()
        asset = library.index_file(source_path, asset_type="sample", role="body")
        patch = create_sound_object_from_asset(asset, name="Imported bell")
        library.save_sound_object(patch)
        destination = tmp_path / "printed-bell.wav"
        result = print_sound_object_to_asset(
            patch, library, destination, target_sample_rate=16_000, seed=34, target_role="kick"
        )
        assert result.asset.asset_type == "sound_object_print" and result.asset.role == "kick"
        assert result.record.source_hashes == (asset.sha256,)
        assert result.record.source_asset_ids == (asset.asset_id,)
        assert result.record.output_sample_rate_hz == 16_000
        assert result.record.object_version_id == result.version.version_id
        assert result.record.role_assignment["target_role"] == "kick"
        assert hashlib.sha256(source_path.read_bytes()).hexdigest() == before
        assert hashlib.sha256(destination.read_bytes()).hexdigest() == result.record.output_file_sha256
        assert len(library.sound_object_variants(patch.patch_id)) == 1
        stored = library.get_asset(result.asset.asset_id).metadata["resample_record"]
        assert ResampleRecord.from_dict(stored) == result.record
    finally:
        library.close()


def test_print_refuses_to_overwrite_original_source(tmp_path):
    library = SampleLibrary(":memory:")
    try:
        source_path = tmp_path / "source.wav"
        with wave.open(str(source_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8_000)
            handle.writeframes(np.zeros(1_024, dtype="<i2").tobytes())
        asset = library.index_file(source_path, asset_type="sample")
        patch = create_sound_object_from_asset(asset)
        library.save_sound_object(patch)
        before = source_path.read_bytes()
        with pytest.raises(ValueError, match="cannot overwrite"):
            print_sound_object_to_asset(patch, library, source_path)
        assert source_path.read_bytes() == before
    finally:
        library.close()


def test_role_assignments_have_distinct_processing_identities():
    version = SoundObjectVersion.from_patch(_patch(), 1)
    kick = RoleAssignment.for_version(version, "kick")
    bass = RoleAssignment.for_version(version, "bass")
    assert kick.object_version_id == version.version_id
    assert kick.processing_identity_id != bass.processing_identity_id
    assert kick.assignment_id != bass.assignment_id
