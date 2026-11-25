from __future__ import annotations

import numpy as np
import pytest

from reawarp.dsp.nonlinear import oversampled_waveshaper


def _alias_bin_energy(signal: np.ndarray, sample_rate: int, frequency: float) -> float:
    window = np.hanning(len(signal))
    spectrum = np.abs(np.fft.rfft(signal * window))
    bins = np.fft.rfftfreq(len(signal), 1 / sample_rate)
    index = int(np.argmin(np.abs(bins - frequency)))
    return float(spectrum[index])


def test_oversampled_waveshaper_reduces_folded_harmonic_energy():
    rate = 48_000
    n = 48_000
    t = np.arange(n) / rate
    source = (0.7 * np.sin(2 * np.pi * 7000 * t)).astype(np.float32)
    native = oversampled_waveshaper(source, rate, shape="tanh", drive=5.0, oversample=1)
    four_x = oversampled_waveshaper(source, rate, shape="tanh", drive=5.0, oversample=4)
    # 5th harmonic (35 kHz) aliases to 13 kHz at 48 kHz; 7th (49 kHz) to 1 kHz.
    folded_native = _alias_bin_energy(native.audio[1000:-1000], rate, 13_000)
    folded_oversampled = _alias_bin_energy(four_x.audio[1000:-1000], rate, 13_000)
    assert folded_oversampled < folded_native * 0.25
    assert four_x.diagnostics["anti_alias_filter"] == "kaiser_windowed_sinc"


@pytest.mark.parametrize("shape", ["tanh", "atan", "hard_clip", "sine_fold", "softsign"])
def test_shapes_return_aligned_finite_stereo_audio(shape):
    source = np.column_stack((np.linspace(-1, 1, 513), np.linspace(1, -1, 513))).astype(np.float32)
    result = oversampled_waveshaper(source, 44_100, shape=shape, oversample=2, drive=3.0)
    assert result.audio.shape == source.shape
    assert np.isfinite(result.audio).all()
    assert result.diagnostics["latency_frames"] == 0
    assert result.diagnostics["delay_compensated"] is True


def test_bypass_is_exact_and_never_changes_source():
    source = np.linspace(-0.7, 0.7, 101, dtype=np.float32)
    original = source.copy()
    result = oversampled_waveshaper(source, 48_000, bypass=True, oversample=8)
    np.testing.assert_array_equal(result.audio, source)
    np.testing.assert_array_equal(source, original)
    assert result.diagnostics["bypass"] is True


def test_invalid_oversampling_and_non_finite_audio_are_rejected():
    with pytest.raises(ValueError, match="oversample"):
        oversampled_waveshaper(np.ones(64, dtype=np.float32), 48_000, oversample=3)
    with pytest.raises(ValueError, match="finite"):
        oversampled_waveshaper(np.asarray([0.0, np.nan], dtype=np.float32), 48_000)
