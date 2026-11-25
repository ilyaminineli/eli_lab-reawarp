from __future__ import annotations

import hashlib
import wave
from fractions import Fraction

import numpy as np
import pytest

from reawarp.score.automation import AutomationLane, AutomationPoint, AutomationTargetRegistry
from reawarp.synthesis.sound_object import (
    EnvelopeSpec,
    HybridVoiceRenderer,
    SoundObjectLayer,
    SoundObjectPatch,
    SoundObjectSource,
    TransformationRecord,
    build_envelope_curve,
    derive_sound_object_seed,
    register_sound_object_automation_targets,
    render_additive_partial_voice,
    render_modal_resonator_bank,
    resample_audio_non_destructive,
    sound_object_automation_targets,
)


SAMPLE_RATE = 8_000


def _patch(patch_id: str = "metallic-test") -> SoundObjectPatch:
    return SoundObjectPatch(
        patch_id=patch_id,
        name="Metallic composite impact",
        sample_rate=SAMPLE_RATE,
        seed=20261125,
        source_identity_id="source:impact-noise",
        processing_identity_id="process:modal-metal-body",
        sources=(
            SoundObjectSource(
                "transient-source", source_kind="procedural",
                sample_rate=SAMPLE_RATE, source_model="short-noise-impulse",
            ),
            SoundObjectSource(
                "body-source", source_kind="procedural",
                sample_rate=SAMPLE_RATE, source_model="inharmonic-modal-bank",
            ),
            SoundObjectSource(
                "tail-source", source_kind="procedural",
                sample_rate=SAMPLE_RATE, source_model="filtered-resonant-tail",
            ),
        ),
        layers=(
            SoundObjectLayer(
                "transient", "transient", "transient-source", 0, 512,
                gain=0.7, envelope=EnvelopeSpec(
                    attack_seconds=0.001, decay_seconds=0.045,
                    sustain_level=0.0, release_seconds=0.02,
                ), phase_group="impact", identity_tags=("attack",),
            ),
            SoundObjectLayer(
                "body", "body", "body-source", 128, 3_072,
                gain=0.5, envelope=EnvelopeSpec(
                    attack_seconds=0.003, decay_seconds=0.22,
                    sustain_level=0.24, release_seconds=0.10,
                ), phase_group="resonant-body", identity_tags=("metallic", "inharmonic"),
            ),
            SoundObjectLayer(
                "tail", "tail", "tail-source", 1_536, 4_096,
                gain=0.3, envelope=EnvelopeSpec(
                    attack_seconds=0.02, decay_seconds=0.3,
                    sustain_level=0.08, release_seconds=0.22,
                ), phase_group="space-tail", identity_tags=("residue",),
            ),
        ),
        pitch_model={"kind": "resonant", "frequency_hz": 440.0, "model": "modal"},
        spectrum={"partials": [
            {"ratio": 1.0, "gain": 1.0, "decay_seconds": 0.5},
            {"ratio": 1.414, "gain": 0.45, "decay_seconds": 0.24},
        ]},
        modulation={"waveform": "sine", "rate_hz": 2.2, "depth": 0.15},
        spatial={"pan": 0.0, "width": 1.0},
    )


def _sources(frames: int = 4_096):
    t = np.arange(frames, dtype=np.float64) / SAMPLE_RATE
    return {
        "transient-source": (
            np.random.default_rng(15).normal(0.0, 0.12, frames)
        ).astype(np.float32),
        "body-source": np.sin(2.0 * np.pi * 440.0 * t).astype(np.float32),
        "tail-source": (
            np.sin(2.0 * np.pi * 621.0 * t) * np.exp(-t * 2.0)
        ).astype(np.float32),
    }


def test_sound_object_schema_separates_identity_and_validates_source_refs():
    patch = _patch()
    payload = patch.to_dict()
    restored = SoundObjectPatch.from_dict(payload)

    assert restored.to_dict() == payload
    assert restored.source_identity_id == "source:impact-noise"
    assert restored.processing_identity_id == "process:modal-metal-body"
    assert restored.duration_frames == 4_096
    assert {layer.role for layer in restored.layers} >= {"transient", "body", "tail"}
    with pytest.raises(ValueError, match="unknown source"):
        SoundObjectPatch(
            patch_id="bad-reference", name="Invalid", sample_rate=SAMPLE_RATE, seed=1,
            source_identity_id="source", processing_identity_id="processing",
            sources=(SoundObjectSource(
                "known", source_kind="procedural", sample_rate=SAMPLE_RATE,
                source_model="sine",
            ),),
            layers=(SoundObjectLayer("bad", "body", "missing", 0, 128),),
        )


def test_adsr_envelope_and_hybrid_renderer_keep_exact_frame_spans():
    patch = _patch()
    source_audio = _sources()
    before = {key: value.copy() for key, value in source_audio.items()}
    renderer = HybridVoiceRenderer()
    result = renderer.render(patch, source_audio)

    assert result.audio.shape == (patch.duration_frames, 2)
    assert result.audio.dtype == np.float32
    assert set(result.layers) == {"transient", "body", "tail"}
    assert all(audio.shape == result.audio.shape for audio in result.layers.values())
    assert np.isfinite(result.audio).all()
    assert result.diagnostics["peak_after_headroom"] <= 0.98 + 1e-6
    assert result.diagnostics["rendered_layer_count"] == 3
    for key in before:
        np.testing.assert_array_equal(source_audio[key], before[key])

    envelope = build_envelope_curve(
        513, SAMPLE_RATE,
        EnvelopeSpec(attack_seconds=0.01, decay_seconds=0.03,
                     sustain_level=0.4, release_seconds=0.02),
    )
    assert envelope.shape == (513,)
    assert envelope[0] == pytest.approx(0.0)
    assert np.isfinite(envelope).all()


def test_hybrid_renderer_warns_about_correlated_phase_cancellation():
    source = np.sin(
        2.0 * np.pi * 330.0 * np.arange(1_024, dtype=np.float64) / SAMPLE_RATE
    ).astype(np.float32)
    inverted = -source
    flat = EnvelopeSpec(attack_seconds=0, decay_seconds=0, sustain_level=1, release_seconds=0)
    patch = SoundObjectPatch(
        patch_id="phase-check", name="Phase check", sample_rate=SAMPLE_RATE, seed=7,
        source_identity_id="source:test-tone", processing_identity_id="process:layer-pair",
        sources=(
            SoundObjectSource("a", source_kind="procedural", sample_rate=SAMPLE_RATE, source_model="sine"),
            SoundObjectSource("b", source_kind="procedural", sample_rate=SAMPLE_RATE, source_model="inverted-sine"),
        ),
        layers=(
            SoundObjectLayer("positive", "body", "a", 0, len(source), envelope=flat),
            SoundObjectLayer("negative", "tail", "b", 0, len(source), envelope=flat),
        ),
    )
    result = HybridVoiceRenderer().render(patch, {"a": source, "b": inverted})
    warnings = result.diagnostics["warnings"]
    assert any(item["kind"] == "correlated_phase_cancellation_risk" for item in warnings)
    assert all(item["heuristic_only"] for item in warnings if "heuristic_only" in item)


def test_hybrid_renderer_reports_headroom_compensation():
    signal = np.full(512, 0.9, dtype=np.float32)
    flat = EnvelopeSpec(attack_seconds=0, decay_seconds=0, sustain_level=1, release_seconds=0)
    patch = SoundObjectPatch(
        patch_id="headroom-check", name="Headroom check",
        sample_rate=SAMPLE_RATE, seed=1,
        source_identity_id="source:flat", processing_identity_id="process:gain",
        sources=(SoundObjectSource(
            "src", source_kind="procedural", sample_rate=SAMPLE_RATE,
            source_model="constant",
        ),),
        layers=(
            SoundObjectLayer("layer-a", "body", "src", 0, 512, gain=2.0, envelope=flat),
            SoundObjectLayer("layer-b", "tail", "src", 0, 512, gain=2.0, envelope=flat),
        ),
    )
    result = HybridVoiceRenderer(peak_ceiling=0.9).render(patch, {"src": signal})
    assert result.diagnostics["peak_before_headroom"] > 1.0
    assert result.diagnostics["headroom_gain"] < 1.0
    assert result.diagnostics["peak_after_headroom"] <= 0.9 + 1e-6
    assert any(item["kind"] == "headroom_compensation" for item in result.diagnostics["warnings"])


def test_modal_and_additive_voice_families_are_deterministic_and_finite():
    modal_a = render_modal_resonator_bank(
        (220, 331, 497, 712), (1.0, 0.5, 0.3, 0.15),
        frames=4_096, sample_rate=SAMPLE_RATE,
        decay_seconds=(0.3, 0.24, 0.19, 0.12), seed=45,
    )
    modal_b = render_modal_resonator_bank(
        (220, 331, 497, 712), (1.0, 0.5, 0.3, 0.15),
        frames=4_096, sample_rate=SAMPLE_RATE,
        decay_seconds=(0.3, 0.24, 0.19, 0.12), seed=45,
    )
    additive_a = render_additive_partial_voice(
        110, (
            {"ratio": 1, "gain": 0.8, "decay_seconds": 0.5},
            {"ratio": 2.01, "gain": 0.45, "decay_seconds": 0.3},
            {"ratio": 3.97, "gain": 0.2, "decay_seconds": 0.2},
        ), frames=4_096, sample_rate=SAMPLE_RATE, seed=91,
    )
    additive_b = render_additive_partial_voice(
        110, (
            {"ratio": 1, "gain": 0.8, "decay_seconds": 0.5},
            {"ratio": 2.01, "gain": 0.45, "decay_seconds": 0.3},
            {"ratio": 3.97, "gain": 0.2, "decay_seconds": 0.2},
        ), frames=4_096, sample_rate=SAMPLE_RATE, seed=91,
    )
    np.testing.assert_array_equal(modal_a, modal_b)
    np.testing.assert_array_equal(additive_a, additive_b)
    assert np.isfinite(modal_a).all() and np.max(np.abs(modal_a)) <= 0.8 + 1e-6
    assert np.isfinite(additive_a).all() and np.max(np.abs(additive_a)) <= 0.8 + 1e-6
    assert derive_sound_object_seed(1, "metal") == derive_sound_object_seed(1, "metal")
    assert derive_sound_object_seed(1, "metal") != derive_sound_object_seed(1, "wood")


def test_resampling_returns_a_new_buffer_and_transformation_lineage():
    source = np.sin(2.0 * np.pi * 440.0 * np.arange(2_000) / SAMPLE_RATE).astype(np.float32)
    original = source.copy()
    output, record = resample_audio_non_destructive(source, SAMPLE_RATE, SAMPLE_RATE * 2, seed=93)

    assert len(output) == len(source) * 2
    np.testing.assert_array_equal(source, original)
    assert record.operation == "resample"
    digest = hashlib.sha256()
    digest.update(str(source.shape).encode("ascii"))
    digest.update(source.astype("<f4", copy=False).tobytes())
    assert record.source_sha256 == digest.hexdigest()
    assert record.output_sha256 and record.source_sha256
    assert record.preserved_dimensions == (
        "source_identity", "relative_timing", "channel_count"
    )
    assert record.changed_dimensions == ("sample_rate", "frame_count")


def test_sound_object_automation_targets_are_typed_and_patch_scoped():
    patch = _patch("automation-targets")
    registry = AutomationTargetRegistry()
    register_sound_object_automation_targets(registry, patch)
    target = registry.resolve("sound_object.automation-targets.layer.body.gain")
    assert target is not None
    assert target.domain == "synthesis" and target.unit == "normalized"
    lane = AutomationLane(
        "sound_object.automation-targets.layer.body.gain",
        (AutomationPoint(Fraction(0), 0.5), AutomationPoint(Fraction(2), 0.8)),
        unit="normalized", minimum=0.0, maximum=1.0,
    )
    registry.validate_lane(lane)


def test_sample_library_stores_patches_and_rendered_variant_lineage(tmp_path):
    from reawarp.library.store import SampleLibrary

    patch = _patch("library-metal-patch")
    library = SampleLibrary(":memory:")
    try:
        digest = library.save_sound_object(patch, tags=("bell", "metallic", "resonant"))
        assert len(digest) == 64
        restored = library.get_sound_object(patch.patch_id)
        assert restored.to_dict() == patch.to_dict()
        assert [item.patch_id for item in library.search_sound_objects(
            query="metallic", tags=("bell",), source_identity_id="source:impact-noise"
        )] == [patch.patch_id]

        wav_path = tmp_path / "metallic-variant.wav"
        audio = np.sin(
            2.0 * np.pi * 220.0 * np.arange(4_096, dtype=np.float64) / 48_000
        )
        pcm = np.clip(audio * 32767, -32768, 32767).astype("<i2")
        with wave.open(str(wav_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(48_000)
            handle.writeframes(pcm.tobytes())

        asset = library.index_file(
            wav_path, asset_type="sound_object_variant", role="metal-body",
            tags=("sound-object", "metallic"),
            metadata={"patch_id": patch.patch_id, "seed": 17},
        )
        transform = TransformationRecord(
            operation="modal-render", seed=17,
            parameters={"family": "modal_resonator_bank"},
            preserved_dimensions=("source_identity",),
            changed_dimensions=("processing_identity", "spectrum"),
        )
        variant_id = library.record_sound_object_variant(
            patch.patch_id, asset.asset_id, seed=17, transformations=(transform,)
        )
        variants = library.sound_object_variants(patch.patch_id)
        assert len(variants) == 1 and variants[0]["variant_id"] == variant_id
        assert variants[0]["asset_sha256"] == asset.sha256
        assert variants[0]["transformations"][0]["operation"] == "modal-render"
        assert variants[0]["features"]
    finally:
        library.close()


def test_sound_object_schema_rejects_invalid_units_and_ranges():
    with pytest.raises(ValueError, match="SHA-256"):
        SoundObjectSource(
            "asset-source", source_kind="asset", asset_id="asset-1",
            asset_sha256="not-a-hash", sample_rate=SAMPLE_RATE,
        )
    with pytest.raises(ValueError, match="width"):
        SoundObjectPatch(
            patch_id="bad-spatial", name="Bad spatial", sample_rate=SAMPLE_RATE, seed=1,
            source_identity_id="source", processing_identity_id="processing",
            sources=(SoundObjectSource(
                "source", source_kind="procedural", sample_rate=SAMPLE_RATE,
                source_model="noise",
            ),),
            layers=(SoundObjectLayer("layer", "body", "source", 0, 128),),
            spatial={"width": 3.0},
        )


def test_typed_score_control_ids_change_rendered_object_parameters():
    patch = _patch("automation-consumer")
    source_audio = _sources()
    renderer = HybridVoiceRenderer()
    baseline = renderer.render(patch, source_audio)
    prefix = f"sound_object.{patch.patch_id}"
    automated = renderer.render(
        patch,
        source_audio,
        control_values={
            f"{prefix}.gain": 0.35,
            f"{prefix}.pitch": 7.0,
            f"{prefix}.attack": 0.008,
            f"{prefix}.decay": 0.15,
            f"{prefix}.release": 0.04,
            f"{prefix}.modulation.rate": 3.0,
            f"{prefix}.modulation.depth": 0.4,
            f"{prefix}.spatial.pan": 0.25,
            f"{prefix}.spatial.width": 1.4,
            f"{prefix}.layer.body.gain": 0.2,
        },
    )
    assert not np.array_equal(baseline.audio, automated.audio)
    assert automated.diagnostics["pitch_semitones"] == 7.0
    assert automated.diagnostics["modulation_rate_hz"] == 3.0
    assert automated.diagnostics["modulation_depth"] == 0.4
    assert automated.audio.shape == baseline.audio.shape
    assert np.isfinite(automated.audio).all()


def test_library_verifies_asset_backed_source_hash(tmp_path):
    from dataclasses import replace
    from reawarp.library.store import SampleLibrary

    wav_path = tmp_path / "source-asset.wav"
    sample_rate = 48_000
    sample = np.sin(
        2.0 * np.pi * 440.0 * np.arange(2_048, dtype=np.float64) / sample_rate
    )
    pcm = np.clip(sample * 32767, -32768, 32767).astype("<i2")
    with wave.open(str(wav_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())

    library = SampleLibrary(":memory:")
    try:
        asset = library.index_file(wav_path, asset_type="source", role="body")
        source = SoundObjectSource(
            "indexed-bronze-source", source_kind="asset",
            asset_id=asset.asset_id, asset_sha256=asset.sha256,
            sample_rate=sample_rate, channels=1,
        )
        patch = SoundObjectPatch(
            patch_id="asset-backed-patch", name="Asset-backed bronze",
            sample_rate=sample_rate, seed=12,
            source_identity_id="source:bronze", processing_identity_id="process:modal",
            sources=(source,),
            layers=(SoundObjectLayer("body", "body", source.source_id, 0, 1_024),),
        )
        assert len(library.save_sound_object(patch)) == 64
        invalid_source = replace(source, asset_sha256="0" * 64)
        invalid_patch = replace(patch, sources=(invalid_source,))
        with pytest.raises(ValueError, match="does not match"):
            library.save_sound_object(invalid_patch)
    finally:
        library.close()


def test_renderer_enforces_declared_source_channel_count():
    source = np.zeros(128, dtype=np.float32)
    patch = SoundObjectPatch(
        patch_id="stereo-contract", name="Stereo contract",
        sample_rate=SAMPLE_RATE, seed=3,
        source_identity_id="source:stereo", processing_identity_id="process:width",
        sources=(SoundObjectSource(
            "stereo-source", source_kind="procedural", sample_rate=SAMPLE_RATE,
            channels=2, source_model="stereo-field",
        ),),
        layers=(SoundObjectLayer("body", "body", "stereo-source", 0, 128),),
    )
    with pytest.raises(ValueError, match="declares 2 channels"):
        HybridVoiceRenderer().render(patch, {"stereo-source": source})



def test_sound_object_score_adapter_renders_exact_event_span_and_controls():
    from fractions import Fraction
    from reawarp.score import (
        AutomationLane, AutomationPoint, MusicalEvent, Score, ScoreRenderer,
        TempoMap,
    )
    from reawarp.score.automation import (
        AutomationTargetRegistry, DEFAULT_AUTOMATION_TARGETS,
    )
    from reawarp.synthesis.sound_object import (
        build_score_sound_object_renderer, register_sound_object_automation_targets,
    )

    patch = _patch("score-voice")
    register = AutomationTargetRegistry(DEFAULT_AUTOMATION_TARGETS.targets)
    register_sound_object_automation_targets(register, patch)
    target_id = "sound_object.score-voice.layer.body.gain"
    event = MusicalEvent(
        event_id="impact-01", voice_id="metal-impact",
        onset_beats=Fraction(0), duration_beats=Fraction(128, 125),
        kind="note", pitch=60, velocity=0.8,
    )
    score = Score(
        title="Sound object Score voice",
        tempo_map=TempoMap.constant(120.0),
        events=(event,),
        automation=(AutomationLane(
            target_id,
            (AutomationPoint(Fraction(0), 0.2),),
            unit="normalized", minimum=0.0, maximum=4.0,
        ),),
        metadata={"sample_rate": SAMPLE_RATE, "frame_count": 4_096},
    )
    renderer = build_score_sound_object_renderer(patch, _sources())
    result = ScoreRenderer().render(
        score, SAMPLE_RATE, frame_count=4_096,
        voice_renderers={"metal-impact": renderer},
        automation_registry=register,
    )
    assert result.stems["metal-impact"].shape == (4_096, 2)
    assert np.isfinite(result.stems["metal-impact"]).all()
    assert np.max(np.abs(result.stems["metal-impact"])) > 0


def test_sound_object_editor_model_exposes_units_ranges_and_role_choices():
    from reawarp.synthesis.sound_object import sound_object_editor_model

    model = sound_object_editor_model(_patch("editor-model"))
    assert model["clock"] == {"sample_rate_hz": SAMPLE_RATE, "frame_unit": "frames"}
    layer = next(item for item in model["layers"] if item["layer_id"] == "body")
    assert layer["editable_fields"]["gain"]["unit"] == "linear"
    assert layer["editable_fields"]["pan"]["minimum"] == -1.0
    assert "transient" in layer["editable_fields"]["role"]
    assert any(
        item["target_id"] == "sound_object.editor-model.layer.body.gain"
        for item in model["controls"]
    )


def test_sound_object_benchmark_harness_reports_time_and_memory():
    from scripts.benchmark_sound_objects import benchmark

    records = benchmark(12_000, 0.05, 1122)
    assert {item["family"] for item in records} == {
        "modal_resonator_bank", "additive_partial_voice",
        "hybrid_transient_body_tail",
    }
    assert all(item["frames"] == 600 for item in records)
    assert all(item["elapsed_seconds"] >= 0 for item in records)
    assert all(item["tracemalloc_peak_bytes"] > 0 for item in records)
    assert all(item["real_time_factor"] is not None for item in records)
