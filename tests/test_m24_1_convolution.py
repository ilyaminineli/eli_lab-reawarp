from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from reawarp.dsp.convolution import (
    ImpulseResponse,
    convolve_partitioned,
    design_resonant_ir,
    spectral_imprint,
)


_FIXTURE = Path(__file__).parent / "fixtures" / "m24" / "convolution_reference.json"


def test_reference_fixture_matches_direct_linear_convolution():
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    source = np.asarray(fixture["input"], dtype=np.float32)
    response = np.asarray(fixture["impulse_response"], dtype=np.float32)
    result = convolve_partitioned(
        source, response, int(fixture["sample_rate"]),
        block_size=int(fixture["block_size"]),
    )
    np.testing.assert_allclose(
        result.audio, np.asarray(fixture["expected"], dtype=np.float32),
        rtol=1e-6, atol=1e-6,
    )
    assert result.diagnostics["latency_frames"] == 0
    assert result.diagnostics["tail_frames"] == len(response) - 1


@pytest.mark.parametrize("block_size", [64, 128, 256, 512])
def test_partitioned_engine_matches_numpy_linear_convolution(block_size):
    rng = np.random.default_rng(241)
    source = rng.normal(0.0, 0.1, 731).astype(np.float32)
    response = rng.normal(0.0, 0.05, 277).astype(np.float32)
    original_source, original_response = source.copy(), response.copy()
    result = convolve_partitioned(source, response, 48_000, block_size=block_size)
    expected = np.convolve(source, response).astype(np.float32)

    assert result.audio.shape == (len(source) + len(response) - 1,)
    np.testing.assert_allclose(result.audio, expected, rtol=2e-5, atol=2e-6)
    np.testing.assert_array_equal(source, original_source)
    np.testing.assert_array_equal(response, original_response)
    assert result.diagnostics["finite_output"] is True
    assert result.diagnostics["algorithm"] == "uniform_partitioned_overlap_add"


def test_convolution_supports_stereo_source_and_mono_ir_without_crossfeed():
    source = np.zeros((160, 2), dtype=np.float32)
    source[0, 0], source[0, 1] = 1.0, 0.5
    response = np.asarray([1.0, 0.5, 0.25], dtype=np.float32)
    result = convolve_partitioned(source, response, 48_000, block_size=64)

    assert result.audio.shape == (162, 2)
    np.testing.assert_allclose(result.audio[:, 0], np.pad(response, (0, 159)))
    np.testing.assert_allclose(result.audio[:, 1], np.pad(response * 0.5, (0, 159)))


def test_mono_source_with_stereo_ir_produces_stereo_dual_mono_output():
    source = np.zeros(100, dtype=np.float32)
    source[0] = 1.0
    ir = np.column_stack((
        np.asarray([1.0, 0.5, 0.25], dtype=np.float32),
        np.asarray([0.5, 0.25, 0.125], dtype=np.float32),
    ))
    result = convolve_partitioned(source, ir, 44_100, block_size=64)
    assert result.audio.shape == (102, 2)
    np.testing.assert_allclose(result.audio[:3], ir, rtol=1e-6, atol=1e-6)


def test_ir_design_is_deterministic_and_preserves_authored_gain():
    modes = [
        {"frequency_hz": 330.0, "gain": 0.8, "decay_seconds": 0.45},
        {"frequency_hz": 511.3, "gain": 0.35, "decay_seconds": 0.9},
        {"frequency_hz": 997.0, "gain": 0.12, "decay_seconds": 1.2},
    ]
    left = design_resonant_ir(
        22_050, 1.5, modes, seed=33, diffuse_noise=0.08,
        stereo_spread=0.002, impulse_id="glass-machine",
    )
    right = design_resonant_ir(
        22_050, 1.5, modes, seed=33, diffuse_noise=0.08,
        stereo_spread=0.002, impulse_id="glass-machine",
    )
    assert left.sha256 == right.sha256
    np.testing.assert_array_equal(left.samples, right.samples)
    assert left.samples.shape == (int(round(22_050 * 1.5)), 2)
    assert left.design["normalization"] == "none"
    assert not left.samples.flags.writeable
    assert left.source_identity_id == "designed:glass-machine"


def test_ir_archive_roundtrip_and_hash_tamper_detection(tmp_path):
    response = design_resonant_ir(
        8_000, 0.25,
        [{"frequency_hz": 410.0, "gain": 0.7, "decay_seconds": 0.2}],
        seed=12,
    )
    path = response.save(tmp_path / "metallic.npz")
    reopened = ImpulseResponse.load(path)
    assert reopened.sha256 == response.sha256
    assert reopened.to_manifest() == response.to_manifest()
    np.testing.assert_array_equal(reopened.samples, response.samples)

    tampered = tmp_path / "tampered.npz"
    with np.load(path, allow_pickle=False) as archive:
        manifest = str(archive["manifest"].item())
        samples = np.asarray(archive["samples"]).copy()
    samples[0, 0] += 0.125
    np.savez_compressed(tampered, manifest=np.asarray(manifest), samples=samples)
    with pytest.raises(ValueError, match="hash"):
        ImpulseResponse.load(tampered)


def test_wet_dry_tail_and_headroom_diagnostics_are_explicit():
    source = np.zeros(128, dtype=np.float32)
    source[0] = 0.4
    response = np.asarray([1.0, 0.5, 0.25, 0.125], dtype=np.float32)
    full = convolve_partitioned(source, response, 8_000, wet=1.0, block_size=64)
    half = convolve_partitioned(source, response, 8_000, wet=0.5, block_size=64)

    assert len(full.audio) == 131
    assert full.diagnostics["tail_frames"] == 3
    assert full.diagnostics["tail_seconds"] == pytest.approx(3 / 8_000)
    assert full.diagnostics["latency_frames"] == 0
    np.testing.assert_allclose(half.audio[:4], (source[:4] * 0.5) + (full.audio[:4] * 0.5))
    assert half.diagnostics["estimated_working_bytes"] > half.diagnostics["output_bytes"]
    assert full.diagnostics["headroom_db"] > 0.0


def test_bypass_is_exact_length_non_mutating_and_does_not_require_ir():
    source = np.linspace(-0.4, 0.4, 64, dtype=np.float32)
    original = source.copy()
    result = convolve_partitioned(source, None, 48_000, bypass=True)
    zero_wet = convolve_partitioned(source, None, 48_000, wet=0.0)

    assert result.audio.shape == source.shape
    np.testing.assert_array_equal(result.audio, source)
    np.testing.assert_array_equal(zero_wet.audio, source)
    np.testing.assert_array_equal(source, original)
    assert result.diagnostics["bypass"] is True
    assert result.diagnostics["tail_frames"] == 0


def test_spectral_imprint_uses_the_same_safe_fir_contract():
    response = design_resonant_ir(
        8_000, 0.1,
        [{"frequency_hz": 900.0, "gain": 0.5, "decay_seconds": 0.08}],
        seed=7,
    )
    source = np.zeros(512, dtype=np.float32)
    source[0] = 1.0
    result = spectral_imprint(source, response, 8_000, block_size=64)
    assert result.diagnostics["instrument"] == "spectral_imprint"
    assert result.diagnostics["spectral_imprint_semantics"] == "causal_fir_resonant_coloration"
    assert len(result.audio) == len(source) + response.frame_count - 1


def test_invalid_sample_rates_ir_mismatch_nonfinite_and_blocks_are_rejected():
    source = np.ones(128, dtype=np.float32)
    ir = design_resonant_ir(
        8_000, 0.05, [{"frequency_hz": 330.0, "gain": 1.0, "decay_seconds": 0.04}]
    )
    with pytest.raises(ValueError, match="sample rate"):
        convolve_partitioned(source, ir, 44_100)
    with pytest.raises(ValueError, match="block_size"):
        convolve_partitioned(source, np.ones(4, dtype=np.float32), 8_000, block_size=96)
    with pytest.raises(ValueError, match="finite"):
        convolve_partitioned(source, np.asarray([1.0, np.nan], dtype=np.float32), 8_000)
    with pytest.raises(ValueError, match="frequency_hz"):
        design_resonant_ir(
            8_000, 0.1, [{"frequency_hz": 9_000, "gain": 1.0, "decay_seconds": 0.1}]
        )
    with pytest.raises(ValueError, match="frequency_hz"):
        design_resonant_ir(
            8_000, 0.1,
            [{"frequency_hz": 3_900, "gain": 1.0, "decay_seconds": 0.1}],
            stereo_spread=0.05,
        )
