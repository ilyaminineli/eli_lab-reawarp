from __future__ import annotations

from threading import Event

import numpy as np
import pytest

from reawarp.dsp.feedback_network import (
    FeedbackDelayNetwork,
    FeedbackNetworkCancelledError,
    feedback_delay_network,
)


def _settings(**overrides):
    values = {
        "sample_rate": 8_000,
        "delay_times_ms": (17.1, 23.3, 29.7, 37.1),
        "feedback_gain": 0.72,
        "input_gain": 0.6,
        "dry": 0.7,
        "wet": 0.4,
        "max_tail_seconds": 1.5,
        "tail_threshold_db": 70.0,
        "output_ceiling": 0.85,
    }
    values.update(overrides)
    return values


def test_fixed_feedback_matrix_is_orthogonal_and_gain_is_contractive():
    network = FeedbackDelayNetwork(**_settings(feedback_gain=0.98))
    matrix = network.feedback_matrix
    np.testing.assert_allclose(matrix @ matrix.T, np.eye(4), atol=1e-12)
    assert network.feedback_matrix.flags.writeable is False
    assert network.stability_margin == pytest.approx(0.02)
    assert network.feedback_gain * np.linalg.norm(matrix, ord=2) < 1.0


def test_impulse_render_is_deterministic_stereo_safe_and_headroom_guarded():
    source = np.zeros((2_000, 2), dtype=np.float32)
    source[0] = (1.2, -0.8)
    original = source.copy()
    first = feedback_delay_network(source, **_settings(output_ceiling=0.5))
    second = feedback_delay_network(source, **_settings(output_ceiling=0.5))

    assert first.audio.shape[0] > len(source)
    assert first.audio.shape[1] == 2
    np.testing.assert_array_equal(first.audio, second.audio)
    np.testing.assert_array_equal(source, original)
    assert np.isfinite(first.audio).all()
    assert np.max(np.abs(first.audio)) <= 0.5 + 1e-6
    assert first.diagnostics["feedback_operator_norm_bound"] < 1.0
    assert first.diagnostics["tail_frames"] <= int(1.5 * 8_000)
    assert first.diagnostics["output_guard_gain"] < 1.0


def test_tail_is_bounded_and_decay_estimate_is_reported():
    source = np.zeros(128, dtype=np.float32)
    source[0] = 0.7
    result = feedback_delay_network(
        source,
        **_settings(max_tail_seconds=0.05, feedback_gain=0.95),
    )
    assert len(result.audio) == len(source) + int(0.05 * 8_000)
    assert result.diagnostics["tail_truncated"] is True
    assert result.diagnostics["requested_tail_frames"] > result.diagnostics["tail_frames"]
    assert result.diagnostics["tail_seconds"] <= 0.05


def test_zero_feedback_produces_only_the_first_bounded_echo_pass():
    source = np.zeros(64, dtype=np.float32)
    source[0] = 0.5
    result = feedback_delay_network(
        source,
        **_settings(feedback_gain=0.0, max_tail_seconds=0.5, wet=1.0, dry=0.0),
    )
    assert result.diagnostics["decay_passes_estimate"] == 0
    assert result.diagnostics["tail_frames"] == max(result.diagnostics["delay_frames"])
    assert np.max(np.abs(result.audio[len(source):])) > 0.0


def test_reset_repeats_state_exactly_and_panic_stops_until_restart():
    source = np.zeros(1_024, dtype=np.float32)
    source[0] = 0.9
    network = FeedbackDelayNetwork(**_settings())
    first = network.process(source)
    tail_first = network.flush()

    network.reset()
    second = network.process(source)
    tail_second = network.flush()
    np.testing.assert_array_equal(first, second)
    np.testing.assert_array_equal(tail_first, tail_second)

    network.panic()
    with pytest.raises(RuntimeError, match="panic-stopped"):
        network.process(source)
    network.start()
    restarted = network.process(source)
    np.testing.assert_array_equal(second, restarted)


def test_streaming_block_boundaries_do_not_change_the_render():
    rng = np.random.default_rng(246)
    source = rng.normal(0.0, 0.08, 4_321).astype(np.float32)
    source_a = FeedbackDelayNetwork(**_settings())
    whole_head = source_a.process(source)
    whole_tail = source_a.flush()
    whole = np.concatenate((whole_head, whole_tail))

    source_b = FeedbackDelayNetwork(**_settings())
    parts = [
        source_b.process(source[:111]),
        source_b.process(source[111:1_888]),
        source_b.process(source[1_888:3_000]),
        source_b.process(source[3_000:]),
    ]
    parts.append(source_b.flush())
    chunked = np.concatenate(parts)
    np.testing.assert_allclose(chunked, whole, rtol=0.0, atol=1e-7)


def test_mono_vector_and_mono_matrix_shapes_are_preserved():
    vector = np.zeros(500, dtype=np.float32)
    vector[0] = 0.4
    as_vector = feedback_delay_network(vector, **_settings())
    matrix = vector[:, None]
    as_matrix = feedback_delay_network(matrix, **_settings())
    assert as_vector.audio.ndim == 1
    assert as_matrix.audio.shape[1] == 1
    np.testing.assert_array_equal(as_vector.audio, as_matrix.audio[:, 0])


def test_bypass_is_an_exact_non_mutating_copy_with_no_tail():
    source = np.linspace(-1.2, 1.2, 257, dtype=np.float32)
    original = source.copy()
    result = feedback_delay_network(source, **_settings(bypass=True))
    np.testing.assert_array_equal(result.audio, source)
    np.testing.assert_array_equal(source, original)
    assert result.diagnostics["bypass"] is True
    assert result.diagnostics["tail_frames"] == 0


def test_cancelled_network_clears_state_and_requires_explicit_restart():
    source = np.ones(4_000, dtype=np.float32) * 0.1
    cancel = Event()
    cancel.set()
    network = FeedbackDelayNetwork(**_settings())
    with pytest.raises(FeedbackNetworkCancelledError, match="cancelled"):
        network.process(source, cancel_event=cancel)
    with pytest.raises(RuntimeError, match="panic-stopped"):
        network.process(source)
    network.start()
    assert len(network.process(source)) == len(source)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"feedback_gain": 1.0}, "feedback_gain"),
        ({"feedback_gain": 0.99}, "feedback_gain"),
        ({"delay_times_ms": (20, 20, 30, 40)}, "distinct"),
        ({"delay_times_ms": (2, 20, 30, 40)}, "delay_times_ms"),
        ({"max_tail_seconds": 31.0}, "max_tail_seconds"),
        ({"tail_threshold_db": 20.0}, "tail_threshold_db"),
    ],
)
def test_invalid_topology_and_unstable_feedback_are_rejected(kwargs, message):
    with pytest.raises(ValueError, match=message):
        FeedbackDelayNetwork(**_settings(**kwargs))


def test_non_finite_audio_is_rejected():
    source = np.zeros(128, dtype=np.float32)
    source[4] = np.nan
    with pytest.raises(ValueError, match="finite"):
        feedback_delay_network(source, **_settings())
