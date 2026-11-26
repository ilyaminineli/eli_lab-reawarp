#!/usr/bin/env python3
"""Reproducible CPU/memory benchmark for the M24.6 fixed-topology FDN."""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np

from reawarp.dsp.feedback_network import feedback_delay_network


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--sample-rate", type=int, default=48_000)
    parser.add_argument("--output", type=Path, default=Path("m24-6-feedback-benchmark.json"))
    args = parser.parse_args()
    if not 0.05 <= args.duration <= 180.0:
        parser.error("duration must be between 0.05 and 180 seconds")
    if not 8_000 <= args.sample_rate <= 192_000:
        parser.error("sample rate must be between 8000 and 192000 Hz")
    frames = int(round(args.duration * args.sample_rate))
    rng = np.random.default_rng(246)
    source = np.zeros((frames, 2), dtype=np.float32)
    pulse_positions = np.arange(0, frames, max(1, int(args.sample_rate * 0.17)))
    source[pulse_positions, 0] = 0.22
    source[pulse_positions, 1] = -0.16
    source += (rng.standard_normal(source.shape).astype(np.float32) * 0.001)

    tracemalloc.start()
    started = time.perf_counter()
    result = feedback_delay_network(
        source,
        args.sample_rate,
        delay_times_ms=(29.7, 37.1, 41.1, 43.7),
        feedback_gain=0.72,
        input_gain=0.55,
        dry=0.65,
        wet=0.45,
        max_tail_seconds=4.0,
        output_ceiling=0.98,
    )
    elapsed = time.perf_counter() - started
    _current, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    report = {
        "module": "m24.6.feedback_network",
        "python": sys.version,
        "numpy": np.__version__,
        "platform": platform.platform(),
        "source_duration_seconds": args.duration,
        "sample_rate": args.sample_rate,
        "wall_seconds": elapsed,
        "real_time_factor": elapsed / args.duration,
        "tracemalloc_peak_bytes": peak_bytes,
        "diagnostics": result.diagnostics,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        f"M24.6 {args.duration:g}s · {elapsed:.3f}s · "
        f"RTF {elapsed / args.duration:.3f} · {peak_bytes} traced bytes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
