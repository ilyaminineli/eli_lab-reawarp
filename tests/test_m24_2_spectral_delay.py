from __future__ import annotations

import numpy as np
import pytest

from reawarp.dsp._stft import istft, stft
from reawarp.dsp.spectral_delay import spectral_delay


def test_stft_roundtrip_is_aligned_and_exact_length_for_mono_and_stereo():
    rng = np.random.default_rng(2402)
    for source in (rng.normal(0, 0.1, 8191).astype(np.float32),
                   rng.normal(0, 0.1, (4097, 2)).astype(np.float32)):
        spectra, metadata = stft(source, 1024, 256)
        restored = istft(spectra, metadata)
        assert restored.shape == source.shape
        np.testing.assert_allclose(restored, source, rtol=2e-5, atol=2e-6)


def test_zero_feedback_is_same_length_and_retains_direct_signal():
    source = np.zeros(2400, dtype=np.float32)
    source[0], source[300], source[1200] = 0.8, -0.3, 0.2
    result = spectral_delay(
        source, 48_000, frequency_bands=[{"low_hz": 0, "high_hz": 24_000, "delay_ms": 50}],
        frame_size=512, hop_size=128, feedback=0.0,
    )
    assert result.audio.shape == source.shape
    np.testing.assert_allclose(result.audio, source, atol=2e-6)
    assert result.diagnostics["tail_frames"] == 0
    assert result.diagnostics["latency_frames"] == 0


def test_frequency_regions_have_independent_delays_and_bounded_tail():
    source = np.zeros(4096, dtype=np.float32)
    source[0] = 0.5
    bands = [
        {"low_hz": 0, "high_hz": 1500, "delay_ms": 80, "feedback": 0.4},
        {"low_hz": 1500, "high_hz": 24000, "delay_ms": 180, "feedback": 0.6},
    ]
    result = spectral_delay(source, 48_000, frequency_bands=bands,
                            frame_size=512, hop_size=128, max_tail_seconds=1.5)
    assert len(result.audio) > len(source)
    assert result.diagnostics["tail_frames"] <= 72_000
    assert result.diagnostics["maximum_feedback"] == pytest.approx(0.6)
    assert result.diagnostics["finite_output"] is True
    assert np.max(np.abs(result.audio)) < 3.0


def test_feedback_tail_limit_is_reported_and_source_is_not_mutated():
    source = np.zeros((2048, 2), dtype=np.float32)
    source[0] = [0.6, -0.4]
    original = source.copy()
    result = spectral_delay(
        source, 48_000,
        frequency_bands=[{"low_hz": 0, "high_hz": 24_000, "delay_ms": 500, "feedback": 0.85}],
        frame_size=512, hop_size=128, max_tail_seconds=0.1,
    )
    assert result.diagnostics["tail_truncated"] is True
    assert result.diagnostics["tail_seconds"] <= 0.1
    np.testing.assert_array_equal(source, original)


def test_bypass_and_zero_wet_are_exact_dry_copies():
    source = np.linspace(-0.5, 0.5, 257, dtype=np.float32)
    for kwargs in ({"bypass": True}, {"wet": 0.0}):
        result = spectral_delay(source, 48_000, **kwargs)
        np.testing.assert_array_equal(result.audio, source)
        assert result.diagnostics["tail_frames"] == 0


def test_invalid_bands_feedback_and_stft_settings_are_rejected():
    source = np.ones(512, dtype=np.float32)
    with pytest.raises(ValueError, match="overlap"):
        spectral_delay(source, 48_000, frequency_bands=[
            {"low_hz": 0, "high_hz": 3000, "delay_ms": 20},
            {"low_hz": 2000, "high_hz": 24000, "delay_ms": 30},
        ])
    with pytest.raises(ValueError, match="feedback"):
        spectral_delay(source, 48_000, feedback=0.95)
    with pytest.raises(ValueError, match="frame_size"):
        spectral_delay(source, 48_000, frame_size=1000)
