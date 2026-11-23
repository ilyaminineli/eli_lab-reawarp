import numpy as np
import pytest

from reawarp import GenerationConfig, ReawarpEngine
from reawarp.export.wav import write_wav
from reawarp.synthesis.profiles import HAT_PROFILES, KICK_PROFILES, SNARE_PROFILES
from reawarp.transforms import (
    BREAK_TRANSFORMS,
    apply_break_transforms,
    auto_slice,
    detect_transients,
    dropout,
    gate_audio,
    granular_resynthesis,
    pitch_shift,
    rearrange_slices,
    reverse_audio,
    slice_audio,
    spectral_freeze,
    stutter,
    time_stretch,
)


def test_transient_detection_and_auto_slicing_find_onsets():
    sample_rate = 8_000
    audio = np.zeros(sample_rate, dtype=np.float32)
    burst = np.sin(np.linspace(0, 35 * np.pi, 220, dtype=np.float32)) * np.hanning(220)
    for start in (800, 3_200, 5_600):
        audio[start : start + len(burst)] += burst
    onsets = detect_transients(audio, sample_rate, threshold=0.12, min_interval_ms=80)
    assert len(onsets) >= 2
    slices = auto_slice(audio, sample_rate, max_slices=3)
    assert slices[0].start == 0
    assert slices[-1].end == len(audio)
    assert len(slices) <= 3


def test_slice_audio_and_rearrangement_preserve_all_frames():
    audio = np.arange(9, dtype=np.float32)
    chunks = slice_audio(audio, [3, 6])
    assert [chunk.tolist() for chunk in chunks] == [[0, 1, 2], [3, 4, 5], [6, 7, 8]]
    arranged = rearrange_slices(audio, [3, 6], order=[2, 1, 0])
    assert arranged.tolist() == [6, 7, 8, 3, 4, 5, 0, 1, 2]


def test_reverse_and_stutter_keep_original_length():
    audio = np.arange(16, dtype=np.float32)
    assert np.array_equal(reverse_audio(audio), audio[::-1])
    result = stutter(audio, repeats=4, start=0, end=8)
    assert len(result) == len(audio)
    assert result[:8].tolist() == [0, 1, 0, 1, 0, 1, 0, 1]


def test_dropout_is_seeded_and_probability_one_mutes_everything():
    audio = np.ones(2_000, dtype=np.float32)
    first = dropout(audio, probability=1.0, sample_rate=10_000, rng=np.random.default_rng(2))
    second = dropout(audio, probability=1.0, sample_rate=10_000, rng=np.random.default_rng(2))
    assert np.array_equal(first, second)
    assert not np.any(first)


def test_gate_applies_requested_duty_cycle():
    audio = np.ones(1_000, dtype=np.float32)
    gated = gate_audio(audio, 1_000, rate_hz=10, duty=0.5, fade_ms=0)
    assert np.count_nonzero(gated) == 500


def test_time_stretch_and_pitch_shift_return_valid_buffers():
    sample_rate = 8_000
    time = np.arange(4_000, dtype=np.float32) / sample_rate
    audio = np.sin(2 * np.pi * 440 * time).astype(np.float32)
    stretched = time_stretch(audio, 1.5)
    shifted = pitch_shift(audio, 7.0)
    assert len(stretched) == 6_000
    assert len(shifted) == len(audio)
    assert np.all(np.isfinite(stretched))
    assert np.all(np.isfinite(shifted))
    assert np.max(np.abs(shifted)) > 0.05


def test_granular_processing_is_reproducible_and_length_preserving():
    audio = np.sin(np.linspace(0, 20 * np.pi, 5_000)).astype(np.float32)
    first = granular_resynthesis(
        audio, 10_000, grain_size_ms=60, density=1.7, rng=np.random.default_rng(99)
    )
    second = granular_resynthesis(
        audio, 10_000, grain_size_ms=60, density=1.7, rng=np.random.default_rng(99)
    )
    assert len(first) == len(audio)
    assert np.array_equal(first, second)


def test_spectral_freeze_and_full_pipeline_are_finite_and_do_not_mutate_source():
    sample_rate = 8_000
    time = np.arange(4_000, dtype=np.float32) / sample_rate
    source = np.column_stack((
        np.sin(2 * np.pi * 220 * time),
        np.sin(2 * np.pi * 330 * time),
    )).astype(np.float32)
    original = source.copy()
    frozen = spectral_freeze(source, sample_rate, position=0.4)
    assert frozen.shape == source.shape
    assert np.all(np.isfinite(frozen))
    transforms = ("slice_rearrange", "stutter", "dropout", "reverse", "gate")
    first = apply_break_transforms(
        source, sample_rate, transforms, np.random.default_rng(7), slice_count=8
    )
    second = apply_break_transforms(
        source, sample_rate, transforms, np.random.default_rng(7), slice_count=8
    )
    assert first.shape == source.shape
    assert np.array_equal(first, second)
    assert np.array_equal(source, original)
    assert set(BREAK_TRANSFORMS) == {
        "slice_rearrange", "stutter", "dropout", "reverse", "gate",
        "pitch_shift", "time_stretch", "granular", "spectral_freeze",
    }


def test_profile_catalogues_have_requested_sizes_and_valid_rendering():
    assert len(KICK_PROFILES) == 13
    assert len(SNARE_PROFILES) == 6
    assert len(HAT_PROFILES) == 6
    config = GenerationConfig(
        duration=5.0,
        sample_rate=22_050,
        seed=121,
        kick_profile="deep_sub",
        snare_profile="industrial",
        hat_profile="metallic",
    )
    project = ReawarpEngine().generate(config)
    profiles = {
        event["lane"]: event.get("sound_profile")
        for event in project.events
        if event.get("lane") in {"kick", "snare", "hat"}
    }
    assert profiles
    assert profiles["kick"] == "deep_sub"
    assert profiles["snare"] == "industrial"
    assert profiles["hat"] == "metallic"


def test_auto_profiles_are_deterministic_and_invalid_options_are_rejected():
    engine = ReawarpEngine()
    config = GenerationConfig(duration=5.0, sample_rate=22_050, seed=144)
    first = engine.generate(config)
    second = engine.generate(config)
    assert first.events == second.events
    with pytest.raises(ValueError):
        GenerationConfig(kick_profile="not-a-profile")
    with pytest.raises(ValueError):
        GenerationConfig(break_transforms=("unknown",))


def test_break_sample_processing_is_non_destructive_and_written_to_manifest(tmp_path):
    sample_rate = 22_050
    time = np.arange(5_000, dtype=np.float32) / sample_rate
    source = (0.5 * np.sin(2 * np.pi * 180 * time)).astype(np.float32)
    path = write_wav(tmp_path / "break.wav", source, sample_rate, 16)
    original_bytes = path.read_bytes()
    config = GenerationConfig(
        duration=5.0,
        sample_rate=sample_rate,
        seed=55,
        sample_paths={"break": str(path)},
        break_transforms=("time_stretch", "reverse"),
        break_time_stretch=1.5,
    )
    project = ReawarpEngine().generate(config)
    manifest = project.metadata["sample_sources"]["break"]
    assert manifest["transforms"] == ["time_stretch", "reverse"]
    assert manifest["frames_after_processing"] > manifest["frames_after_resampling"]
    assert path.read_bytes() == original_bytes
    assert "sample_break" in project.stems



def test_reverse_preserves_stereo_channel_order():
    left = np.arange(12, dtype=np.float32)
    right = left + 100
    stereo = np.column_stack((left, right))
    result = reverse_audio(stereo)
    assert result.shape == stereo.shape
    assert np.array_equal(result[:, 0], left[::-1])
    assert np.array_equal(result[:, 1], right[::-1])


def test_auto_slice_silence_returns_one_full_length_region():
    silence = np.zeros(2_048, dtype=np.float32)
    slices = auto_slice(silence, 8_000)
    assert len(slices) == 1
    assert slices[0].start == 0
    assert slices[0].end == len(silence)


def test_rearrange_rejects_non_permutation_order():
    with pytest.raises(ValueError):
        rearrange_slices(np.arange(12, dtype=np.float32), [4, 8], order=[0, 0, 2])


def test_pitch_time_granular_and_freeze_pipeline_accepts_stereo():
    sample_rate = 8_000
    time = np.arange(4_000, dtype=np.float32) / sample_rate
    source = np.column_stack((
        np.sin(2 * np.pi * 220 * time),
        np.sin(2 * np.pi * 440 * time),
    )).astype(np.float32)
    result = apply_break_transforms(
        source,
        sample_rate,
        ("pitch_shift", "time_stretch", "granular", "spectral_freeze"),
        np.random.default_rng(123),
        pitch_semitones=-5.0,
        stretch_factor=1.1,
        grain_size_ms=50.0,
        grain_density=1.4,
    )
    assert result.shape == (4_400, 2)
    assert np.all(np.isfinite(result))
