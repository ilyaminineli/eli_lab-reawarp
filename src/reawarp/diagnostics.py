"""Signal-level diagnostics shared by tests, benchmarks, and the desktop UI.

The functions in this module inspect buffers without modifying them. Metrics are
descriptive rather than perceptual: they can expose clipping, non-finite values,
alignment errors, and level differences, but cannot judge musical quality.
"""
from __future__ import annotations

import math
from typing import Mapping

import numpy as np


def analyze_audio(
    audio: np.ndarray,
    sample_rate: int,
    *,
    expected_frames: int | None = None,
) -> dict[str, int | float | bool | None]:
    """Return stable signal diagnostics for a mono or channel-last audio buffer."""
    if int(sample_rate) <= 0:
        raise ValueError("sample_rate must be positive")
    samples = np.asarray(audio)
    if samples.ndim not in (1, 2):
        raise ValueError("audio must be a mono 1-D or channel-last 2-D array")
    if not np.issubdtype(samples.dtype, np.number) or np.iscomplexobj(samples):
        raise ValueError("audio samples must use a real numeric dtype")
    channels = 1 if samples.ndim == 1 else int(samples.shape[1])
    if channels < 1:
        raise ValueError("audio must contain at least one channel")
    frames = int(samples.shape[0])
    finite_mask = np.isfinite(samples)
    finite = np.asarray(samples[finite_mask], dtype=np.float64)
    non_finite = int(samples.size - finite.size)

    if finite.size:
        absolute = np.abs(finite)
        peak = float(np.max(absolute))
        rms = float(np.sqrt(np.mean(np.square(finite))))
        peak_dbfs = 20.0 * math.log10(peak) if peak > 0.0 else None
        rms_dbfs = 20.0 * math.log10(rms) if rms > 0.0 else None
        crest_factor_db = (
            20.0 * math.log10(peak / rms) if peak > 0.0 and rms > 0.0 else None
        )
        clipped = int(np.count_nonzero(absolute > 1.0))
    else:
        peak = rms = 0.0
        peak_dbfs = rms_dbfs = crest_factor_db = None
        clipped = 0

    return {
        "sample_rate": int(sample_rate),
        "frame_count": frames,
        "channel_count": channels,
        "duration_seconds": frames / float(sample_rate),
        "peak": peak,
        "rms": rms,
        "peak_dbfs": peak_dbfs,
        "rms_dbfs": rms_dbfs,
        "crest_factor_db": crest_factor_db,
        "finite_sample_count": int(finite.size),
        "non_finite_sample_count": non_finite,
        "clipped_sample_count": clipped,
        "is_finite": non_finite == 0,
        "expected_frame_count": expected_frames,
        "frame_count_matches": (
            None if expected_frames is None else frames == int(expected_frames)
        ),
    }


def analyze_stems(
    stems: Mapping[str, np.ndarray],
    sample_rate: int,
    *,
    expected_frames: int | None = None,
) -> dict[str, object]:
    """Analyse all stems and report whether their frame counts are aligned."""
    diagnostics = {
        str(name): analyze_audio(audio, sample_rate, expected_frames=expected_frames)
        for name, audio in stems.items()
    }
    frame_counts = {int(item["frame_count"]) for item in diagnostics.values()}
    aligned = len(frame_counts) <= 1
    if expected_frames is not None:
        aligned = aligned and all(
            item["frame_count_matches"] is True for item in diagnostics.values()
        )
    return {
        "sample_rate": int(sample_rate),
        "stem_count": len(diagnostics),
        "aligned": aligned,
        "frame_counts": sorted(frame_counts),
        "stems": diagnostics,
    }
