"""Bounded four-line feedback delay network for offline resonant sound design.

M24.6 intentionally exposes one fixed orthogonal topology. It is not a
user-wired feedback graph, a live effect callback, or an M22 default insert.
"""
from __future__ import annotations

import math
import time
from threading import Event
from typing import Any, Sequence

import numpy as np

from reawarp.dsp._stft import audio_channels, finite_range, restore_shape, signal_diagnostics

_TOPOLOGY = (
    np.asarray(
        (
            (1.0, 1.0, 1.0, 1.0),
            (1.0, -1.0, 1.0, -1.0),
            (1.0, 1.0, -1.0, -1.0),
            (1.0, -1.0, -1.0, 1.0),
        ),
        dtype=np.float64,
    )
    * 0.5
)
_TOPOLOGY.setflags(write=False)

_MONO_INJECTION = np.full((4, 1), 0.5, dtype=np.float64)
_STEREO_INJECTION = np.asarray(
    (
        (0.5, 0.5),
        (0.5, -0.5),
        (-0.5, 0.5),
        (-0.5, -0.5),
    ),
    dtype=np.float64,
)
_MONO_INJECTION.setflags(write=False)
_STEREO_INJECTION.setflags(write=False)


class FeedbackNetworkCancelledError(RuntimeError):
    """Raised when offline feedback rendering is cancelled at a block boundary."""


class FeedbackNetworkResult:
    __slots__ = ("audio", "diagnostics")

    def __init__(self, audio: np.ndarray, diagnostics: dict[str, Any]):
        self.audio = audio
        self.diagnostics = diagnostics


class FeedbackDelayNetwork:
    """Stateful four-delay orthogonal feedback network.

    The fixed 4x4 Hadamard feedback matrix is orthogonal, so its induced 2-norm
    is exactly one. Multiplying it by feedback_gain in [0, 0.98] makes the
    feedback operator contractive with a stability margin of at least 0.02.

    process() returns an unguarded streaming block. flush() emits the bounded
    tail. reset() clears all delay memory; panic() clears it and stops processing
    until start() or reset() is called. The one-shot feedback_delay_network()
    wrapper additionally applies a deterministic peak guard to the complete
    rendered result.
    """

    topology_id = "hadamard_4line_orthogonal_v1"

    def __init__(
        self,
        sample_rate: int,
        *,
        delay_times_ms: Sequence[float] = (29.7, 37.1, 41.1, 43.7),
        feedback_gain: float = 0.68,
        input_gain: float = 0.5,
        dry: float = 1.0,
        wet: float = 0.35,
        max_tail_seconds: float = 6.0,
        tail_threshold_db: float = 80.0,
        output_ceiling: float = 0.98,
    ) -> None:
        if isinstance(sample_rate, bool) or not isinstance(sample_rate, (int, np.integer)):
            raise ValueError("sample_rate must be an integer")
        if not 8_000 <= int(sample_rate) <= 192_000:
            raise ValueError("sample_rate must be between 8000 and 192000 Hz")
        if isinstance(delay_times_ms, (str, bytes)) or len(delay_times_ms) != 4:
            raise ValueError("delay_times_ms must contain exactly four delay times")
        self.sample_rate = int(sample_rate)
        normalized = tuple(
            finite_range(value, f"delay_times_ms[{index}]", 5.0, 2_000.0)
            for index, value in enumerate(delay_times_ms)
        )
        self.delay_times_ms = normalized
        self.delay_frames = tuple(
            max(1, int(round(value * self.sample_rate / 1_000.0)))
            for value in normalized
        )
        if len(set(self.delay_frames)) != 4:
            raise ValueError("delay_times_ms must resolve to four distinct sample delays")
        self.feedback_gain = finite_range(feedback_gain, "feedback_gain", 0.0, 0.98)
        self.input_gain = finite_range(input_gain, "input_gain", 0.0, 1.0)
        self.dry = finite_range(dry, "dry", 0.0, 1.0)
        self.wet = finite_range(wet, "wet", 0.0, 1.0)
        self.max_tail_seconds = finite_range(max_tail_seconds, "max_tail_seconds", 0.0, 30.0)
        self.tail_threshold_db = finite_range(tail_threshold_db, "tail_threshold_db", 40.0, 120.0)
        self.output_ceiling = finite_range(output_ceiling, "output_ceiling", 0.1, 1.0)

        self._block_size = min(min(self.delay_frames), 8_192)
        self._ring_size = max(self.delay_frames) + self._block_size + 1
        self._ring = np.zeros((4, self._ring_size), dtype=np.float32)
        self._frame_index = 0
        self._channels: int | None = None
        self._was_vector: bool | None = None
        self._injection: np.ndarray | None = None
        self._decode: np.ndarray | None = None
        self._stopped = False
        self._flushed = False

    @property
    def feedback_matrix(self) -> np.ndarray:
        """Return a read-only copy of the fixed orthogonal feedback matrix."""
        result = _TOPOLOGY.copy()
        result.setflags(write=False)
        return result

    @property
    def stability_margin(self) -> float:
        return 1.0 - self.feedback_gain

    def tail_plan(self, max_tail_seconds: float | None = None) -> dict[str, Any]:
        """Return a conservative -threshold dB decay estimate and hard tail cap."""
        cap_seconds = (
            self.max_tail_seconds
            if max_tail_seconds is None
            else finite_range(max_tail_seconds, "max_tail_seconds", 0.0, 30.0)
        )
        maximum_delay = max(self.delay_frames)
        if self.feedback_gain <= 0.0:
            repeats = 0
        else:
            decay_per_pass_db = -20.0 * math.log10(self.feedback_gain)
            repeats = int(math.ceil(self.tail_threshold_db / decay_per_pass_db))
        requested_frames = maximum_delay * (repeats + 1)
        cap_frames = int(math.floor(cap_seconds * self.sample_rate))
        tail_frames = min(requested_frames, cap_frames)
        return {
            "requested_tail_frames": int(requested_frames),
            "tail_frames": int(tail_frames),
            "tail_seconds": tail_frames / float(self.sample_rate),
            "tail_truncated": tail_frames < requested_frames,
            "decay_passes_estimate": repeats,
            "tail_threshold_db": self.tail_threshold_db,
            "max_tail_seconds": cap_seconds,
        }

    def _configure_channels(self, source: np.ndarray, was_vector: bool) -> None:
        channels = int(source.shape[1])
        if channels not in {1, 2}:
            raise ValueError("feedback network supports mono or stereo only")
        if self._channels is None:
            self._channels = channels
            self._was_vector = was_vector
            self._injection = _MONO_INJECTION if channels == 1 else _STEREO_INJECTION
            self._decode = self._injection.T
        elif self._channels != channels:
            raise ValueError("feedback network channel count cannot change before reset")

    def process(
        self,
        audio: np.ndarray,
        *,
        cancel_event: Event | None = None,
    ) -> np.ndarray:
        """Process one streaming block and retain the network state."""
        if self._stopped:
            raise RuntimeError("feedback network is panic-stopped; call start() or reset()")
        if self._flushed:
            raise RuntimeError("feedback network has been flushed; call start() or reset()")
        source, was_vector = audio_channels(audio, "feedback input")
        self._configure_channels(source, was_vector)
        if len(source) == 0:
            return restore_shape(source.copy(), was_vector)

        output = np.empty_like(source, dtype=np.float32)
        for offset in range(0, len(source), self._block_size):
            if cancel_event is not None and cancel_event.is_set():
                self.panic()
                raise FeedbackNetworkCancelledError("feedback network render cancelled")
            count = min(self._block_size, len(source) - offset)
            positions = np.arange(
                self._frame_index, self._frame_index + count, dtype=np.int64
            )
            delayed = np.zeros((4, count), dtype=np.float64)
            for line, delay in enumerate(self.delay_frames):
                valid = positions >= delay
                if np.any(valid):
                    slots = (positions[valid] - delay) % self._ring_size
                    delayed[line, valid] = self._ring[line, slots]

            chunk = source[offset:offset + count].astype(np.float64, copy=False)
            assert self._injection is not None and self._decode is not None
            injected = (chunk @ self._injection.T).T * self.input_gain
            feedback = _TOPOLOGY @ delayed
            written = injected + self.feedback_gain * feedback
            write_slots = positions % self._ring_size
            self._ring[:, write_slots] = written.astype(np.float32)

            echo = (self._decode @ delayed).T
            mixed = self.dry * chunk + self.wet * echo
            output[offset:offset + count] = mixed.astype(np.float32)
            self._frame_index += count

        return restore_shape(output, was_vector)

    def flush(
        self,
        max_tail_seconds: float | None = None,
        *,
        cancel_event: Event | None = None,
    ) -> np.ndarray:
        """Render and return the remaining bounded feedback tail."""
        if self._stopped:
            raise RuntimeError("feedback network is panic-stopped; call start() or reset()")
        if self._flushed:
            raise RuntimeError("feedback network has already been flushed")
        plan = self.tail_plan(max_tail_seconds)
        channels = self._channels or 1
        was_vector = self._was_vector if self._was_vector is not None else True
        tail_frames = int(plan["tail_frames"])
        if tail_frames == 0:
            empty = np.zeros((0, channels), dtype=np.float32)
            self._flushed = True
            return restore_shape(empty, was_vector)
        silence = np.zeros((tail_frames, channels), dtype=np.float32)
        result = self.process(silence, cancel_event=cancel_event)
        self._flushed = True
        return restore_shape(np.asarray(result), was_vector)

    def reset(self) -> None:
        """Clear all delay memory and restore the ready state."""
        self._ring.fill(0.0)
        self._frame_index = 0
        self._channels = None
        self._was_vector = None
        self._injection = None
        self._decode = None
        self._stopped = False
        self._flushed = False

    def panic(self) -> None:
        """Immediately clear all feedback memory and stop processing."""
        self.reset()
        self._stopped = True

    def start(self) -> None:
        """Start a fresh render after a panic stop."""
        self.reset()


def feedback_delay_network(
    audio: np.ndarray,
    sample_rate: int,
    *,
    delay_times_ms: Sequence[float] = (29.7, 37.1, 41.1, 43.7),
    feedback_gain: float = 0.68,
    input_gain: float = 0.5,
    dry: float = 1.0,
    wet: float = 0.35,
    max_tail_seconds: float = 6.0,
    tail_threshold_db: float = 80.0,
    output_ceiling: float = 0.98,
    bypass: bool = False,
    cancel_event: Event | None = None,
) -> FeedbackNetworkResult:
    """Render a fixed-topology four-line FDN and its bounded resonant tail.

    The feedback matrix is orthogonal (operator norm 1). feedback_gain is
    strictly below unity, so each feedback traversal contracts the state.
    The tail estimate uses the longest delay and the requested decay threshold;
    max_tail_seconds is an unconditional upper bound. A final static peak guard
    scales the complete render only when its peak exceeds output_ceiling.
    """
    source, was_vector = audio_channels(audio, "feedback input")
    processor = FeedbackDelayNetwork(
        sample_rate,
        delay_times_ms=delay_times_ms,
        feedback_gain=feedback_gain,
        input_gain=input_gain,
        dry=dry,
        wet=wet,
        max_tail_seconds=max_tail_seconds,
        tail_threshold_db=tail_threshold_db,
        output_ceiling=output_ceiling,
    )
    started = time.perf_counter()
    if bypass or (processor.wet == 0.0 and processor.dry == 1.0) or len(source) == 0:
        direct = restore_shape(source.copy(), was_vector)
        return FeedbackNetworkResult(direct, {
            "module": "m24.6.feedback_network",
            "topology": processor.topology_id,
            "bypass": True,
            "sample_rate": processor.sample_rate,
            "input_frames": len(source),
            "output_frames": len(source),
            "tail_frames": 0,
            "tail_seconds": 0.0,
            "tail_truncated": False,
            "feedback_gain": processor.feedback_gain,
            "feedback_matrix_operator_norm": 1.0,
            "stability_margin": processor.stability_margin,
            "processing_seconds": time.perf_counter() - started,
            **signal_diagnostics(direct),
        })

    head = processor.process(source, cancel_event=cancel_event)
    tail = processor.flush(cancel_event=cancel_event)
    combined = np.concatenate((np.asarray(head), np.asarray(tail)), axis=0)
    raw_peak = float(np.max(np.abs(combined))) if combined.size else 0.0
    guard_gain = min(1.0, processor.output_ceiling / raw_peak) if raw_peak > 0.0 else 1.0
    guarded = np.asarray(combined * np.float32(guard_gain), dtype=np.float32)
    output = restore_shape(guarded, was_vector)
    tail_plan = processor.tail_plan()
    diagnostics = {
        "module": "m24.6.feedback_network",
        "topology": processor.topology_id,
        "bypass": False,
        "sample_rate": processor.sample_rate,
        "delay_times_ms": list(processor.delay_times_ms),
        "delay_frames": list(processor.delay_frames),
        "input_frames": len(source),
        "output_frames": len(output),
        "tail_frames": int(tail_plan["tail_frames"]),
        "tail_seconds": float(tail_plan["tail_seconds"]),
        "requested_tail_frames": int(tail_plan["requested_tail_frames"]),
        "tail_truncated": bool(tail_plan["tail_truncated"]),
        "tail_threshold_db": processor.tail_threshold_db,
        "decay_passes_estimate": int(tail_plan["decay_passes_estimate"]),
        "feedback_gain": processor.feedback_gain,
        "feedback_matrix_operator_norm": 1.0,
        "feedback_operator_norm_bound": processor.feedback_gain,
        "stability_margin": processor.stability_margin,
        "input_gain": processor.input_gain,
        "dry": processor.dry,
        "wet": processor.wet,
        "output_ceiling": processor.output_ceiling,
        "peak_before_guard": raw_peak,
        "output_guard_gain": guard_gain,
        "estimated_working_bytes": int(
            processor._ring.nbytes + np.asarray(head).nbytes
            + np.asarray(tail).nbytes + combined.nbytes + guarded.nbytes
        ),
        "processing_seconds": time.perf_counter() - started,
        **signal_diagnostics(output),
    }
    return FeedbackNetworkResult(output, diagnostics)


__all__ = [
    "FeedbackDelayNetwork",
    "FeedbackNetworkCancelledError",
    "FeedbackNetworkResult",
    "feedback_delay_network",
]
