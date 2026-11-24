import numpy as np
import pytest

from reawarp.diagnostics import analyze_audio, analyze_stems


def test_analyze_audio_reports_levels_and_shape():
    audio = np.array([[0.5, -0.5], [1.1, 0.0]], dtype=np.float32)

    result = analyze_audio(audio, 48_000, expected_frames=2)

    assert result["frame_count"] == 2
    assert result["channel_count"] == 2
    assert result["duration_seconds"] == pytest.approx(2 / 48_000)
    assert result["peak"] == pytest.approx(1.1)
    assert result["clipped_sample_count"] == 1
    assert result["non_finite_sample_count"] == 0
    assert result["frame_count_matches"] is True


def test_analyze_audio_counts_non_finite_samples_without_mutating_input():
    audio = np.array([0.25, np.nan, np.inf, -0.25], dtype=np.float32)
    original = audio.copy()

    result = analyze_audio(audio, 22_050)

    assert result["non_finite_sample_count"] == 2
    assert result["finite_sample_count"] == 2
    assert result["is_finite"] is False
    np.testing.assert_array_equal(audio, original)


def test_analyze_audio_handles_silence_and_invalid_shapes():
    result = analyze_audio(np.zeros((8, 2), dtype=np.float32), 48_000)
    assert result["peak"] == 0.0
    assert result["rms"] == 0.0
    assert result["peak_dbfs"] is None
    with pytest.raises(ValueError):
        analyze_audio(np.zeros((2, 2, 2)), 48_000)
    with pytest.raises(ValueError):
        analyze_audio(np.zeros(4), 0)


def test_analyze_stems_reports_alignment():
    stems = {
        "kick": np.zeros((16, 2), dtype=np.float32),
        "melody": np.zeros((16, 2), dtype=np.float32),
    }
    result = analyze_stems(stems, 48_000, expected_frames=16)
    assert result["aligned"] is True
    assert result["stem_count"] == 2
    stems["melody"] = np.zeros((15, 2), dtype=np.float32)
    result = analyze_stems(stems, 48_000, expected_frames=16)
    assert result["aligned"] is False
