#!/usr/bin/env python3
"""Reproducible M24.2 spectral-delay CPU/memory benchmark."""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np

from reawarp.dsp.spectral_delay import spectral_delay


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--sample-rate", type=int, default=48_000)
    parser.add_argument("--frame-size", type=int, default=1024)
    parser.add_argument("--hop-size", type=int, default=256)
    parser.add_argument("--output", type=Path, default=Path("m24-2-benchmark.json"))
    args = parser.parse_args()
    if args.duration <= 0 or args.sample_rate < 1000:
        parser.error("duration and sample rate must be positive")
    count = int(round(args.duration * args.sample_rate))
    time_axis = np.arange(count, dtype=np.float32) / args.sample_rate
    rng = np.random.default_rng(242)
    source = (0.08 * np.sin(2 * np.pi * 220 * time_axis) + 0.015 * rng.standard_normal(count)).astype(np.float32)
    tracemalloc.start()
    started = time.perf_counter()
    result = spectral_delay(
        source, args.sample_rate, frame_size=args.frame_size, hop_size=args.hop_size,
        frequency_bands=[
            {"low_hz": 0, "high_hz": 500, "delay_ms": 90, "feedback": 0.35},
            {"low_hz": 500, "high_hz": args.sample_rate / 2, "delay_ms": 170, "feedback": 0.55},
        ],
    )
    elapsed = time.perf_counter() - started
    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "module": "m24.2.spectral_delay", "python": sys.version,
        "numpy": np.__version__, "platform": platform.platform(),
        "source_duration_seconds": args.duration, "sample_rate": args.sample_rate,
        "frame_size": args.frame_size, "hop_size": args.hop_size,
        "wall_seconds": elapsed, "real_time_factor": elapsed / args.duration,
        "tracemalloc_peak_bytes": peak_memory,
        "estimated_working_bytes": result.diagnostics["estimated_working_bytes"],
        "output_bytes": result.audio.nbytes, "diagnostics": result.diagnostics,
    }, indent=2), encoding="utf-8")
    print(f"M24.2 {args.duration:g}s · {elapsed:.3f}s · RTF {elapsed/args.duration:.3f} · {peak_memory} traced bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
