from __future__ import annotations

import numpy as np
import pytest

from reawarp.dsp.cross_synthesis import (
    frequency_shift, ring_modulate, spectral_envelope_transfer, vocoder,
)


def test_ring_modulation_is_explicit_product_and_preserves_channels():
    t = np.arange(2048) / 48_000
    carrier = (0.4 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    modulator = (0.5 * np.sin(2 * np.pi * 90 * t)).astype(np.float32)
    result = ring_modulate(carrier, modulator, 48_000)
    np.testing.assert_allclose(result.audio, carrier * modulator, atol=1e-7)
    assert result.diagnostics["formula"].startswith("y[n]")


def test_frequency_shift_moves_partial_by_fixed_hz_not_ratio():
    rate = 48_000
    t = np.arange(rate) / rate
    source = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    result = frequency_shift(source, rate, 175.0, edge_padding_ms=100)
    spectrum = np.abs(np.fft.rfft(result.audio[5000:-5000]))
    frequencies = np.fft.rfftfreq(len(result.audio[5000:-5000]), 1 / rate)
    peak = frequencies[np.argmax(spectrum)]
    assert peak == pytest.approx(615.0, abs=1.5)
    assert result.audio.shape == source.shape
    assert result.diagnostics["frequency_shift_is_not_pitch_shift"] is True


def test_spectral_envelope_transfer_is_finite_same_length_and_changes_carrier():
    rate = 22_050
    t = np.arange(4097) / rate
    carrier = (0.2 * np.sin(2 * np.pi * 220 * t) + 0.1 * np.sin(2 * np.pi * 1760 * t)).astype(np.float32)
    modulator = (0.25 * np.sin(2 * np.pi * 700 * t) + 0.1 * np.sin(2 * np.pi * 1050 * t)).astype(np.float32)
    original = carrier.copy()
    result = spectral_envelope_transfer(carrier, modulator, rate, frame_size=512, hop_size=128)
    assert result.audio.shape == carrier.shape
    assert np.isfinite(result.audio).all()
    assert not np.allclose(result.audio, carrier)
    assert result.diagnostics["carrier_phase_retained"] is True
    np.testing.assert_array_equal(carrier, original)


def test_vocoder_has_distinct_band_articulation_and_stereo_support():
    rate = 16_000
    t = np.arange(4096) / rate
    carrier = np.column_stack((np.sin(2 * np.pi * 110 * t), np.sin(2 * np.pi * 220 * t))).astype(np.float32) * 0.25
    envelope = (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t))
    modulator = np.column_stack((envelope * np.sin(2 * np.pi * 300 * t), envelope * np.sin(2 * np.pi * 500 * t))).astype(np.float32)
    result = vocoder(carrier, modulator, rate, bands=16, frame_size=512, hop_size=128)
    assert result.audio.shape == carrier.shape
    assert result.diagnostics["bands"] == 16
    assert result.diagnostics["carrier_phase_retained"] is True
    assert np.isfinite(result.audio).all()
    assert np.max(np.abs(result.audio)) > 0


def test_exact_bypass_and_input_alignment_validation():
    source = np.ones(128, dtype=np.float32) * 0.2
    other = np.ones(128, dtype=np.float32) * 0.5
    result = ring_modulate(source, other, 48_000, bypass=True)
    np.testing.assert_array_equal(result.audio, source)
    with pytest.raises(ValueError, match="same frame count"):
        ring_modulate(source, np.ones(127, dtype=np.float32), 48_000)


def test_invalid_frequency_shift_is_rejected():
    with pytest.raises(ValueError, match="shift_hz"):
        frequency_shift(np.ones(32, dtype=np.float32), 48_000, 30_000)
