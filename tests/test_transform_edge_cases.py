import numpy as np
import pytest

from reawarp.transforms.analysis import auto_slice, detect_transients
from reawarp.transforms.pipeline import BREAK_TRANSFORMS, apply_break_transforms


@pytest.mark.parametrize(
    "audio",
    [
        np.zeros(0, dtype=np.float32),
        np.zeros(1, dtype=np.float32),
        np.zeros(32, dtype=np.float32),
        np.zeros((0, 2), dtype=np.float32),
        np.zeros((1, 2), dtype=np.float32),
        np.zeros((32, 2), dtype=np.float32),
    ],
)
def test_silent_and_short_audio_is_safe_for_slice_and_transform_pipeline(audio):
    original = audio.copy()
    assert detect_transients(audio, 22_050) == []
    slices = auto_slice(audio, 22_050)
    if len(audio) == 0:
        assert slices == []
    else:
        assert [(item.start, item.end) for item in slices] == [(0, len(audio))]

    rendered = apply_break_transforms(
        audio,
        22_050,
        BREAK_TRANSFORMS,
        np.random.default_rng(17),
        stretch_factor=1.0,
    )

    assert rendered.shape == audio.shape
    assert np.isfinite(rendered).all()
    np.testing.assert_array_equal(audio, original)


def test_full_transform_chain_is_seeded_stereo_safe_and_non_destructive():
    rng = np.random.default_rng(2026)
    source = rng.normal(0.0, 0.12, (4096, 2)).astype(np.float32)
    source[::256, 0] += 0.65
    source[128::256, 1] -= 0.55
    original = source.copy()
    options = {
        "bpm": 137.0,
        "slice_count": 12,
        "stutter_repeats": 3,
        "dropout_probability": 0.2,
        "pitch_semitones": 3.0,
        "stretch_factor": 1.125,
        "gate_rate_hz": 7.0,
        "gate_duty": 0.68,
        "grain_size_ms": 12.0,
        "grain_density": 1.4,
        "freeze_position": 0.42,
    }

    first = apply_break_transforms(
        source, 22_050, BREAK_TRANSFORMS, np.random.default_rng(91), **options
    )
    second = apply_break_transforms(
        source, 22_050, BREAK_TRANSFORMS, np.random.default_rng(91), **options
    )

    assert first.shape == (int(round(len(source) * options["stretch_factor"])), 2)
    assert np.isfinite(first).all()
    np.testing.assert_array_equal(first, second)
    np.testing.assert_array_equal(source, original)


def test_transform_pipeline_rejects_invalid_audio_shape_and_unknown_operation():
    with pytest.raises(ValueError):
        auto_slice(np.zeros((64, 3), dtype=np.float32), 22_050)
    with pytest.raises(ValueError, match="unknown break transforms"):
        apply_break_transforms(
            np.zeros(64, dtype=np.float32),
            22_050,
            ("not_a_transform",),
            np.random.default_rng(1),
        )
