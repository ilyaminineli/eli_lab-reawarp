#!/usr/bin/env python3
"""Reproducible M24.4 oversampled nonlinear CPU/memory benchmark."""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np

from reawarp.dsp.nonlinear import oversampled_waveshaper


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--sample-rate", type=int, default=48_000)
    parser.add_argument("--output", type=Path, default=Path("m24-4-benchmark.json"))
    args = parser.parse_args()
    if args.duration <= 0 or args.sample_rate < 1000:
        parser.error("duration and sample rate must be positive")
    count = int(round(args.duration * args.sample_rate))
    t = np.arange(count, dtype=np.float32) / args.sample_rate
    source = (0.45 * np.sin(2 * np.pi * 997 * t) + 0.22 * np.sin(2 * np.pi * 5100 * t)).astype(np.float32)
    cases = []
    for factor in (1, 2, 4, 8):
        tracemalloc.start()
        started = time.perf_counter()
        result = oversampled_waveshaper(source, args.sample_rate, shape="tanh", drive=4.0, oversample=factor)
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        cases.append({
            "oversample": factor, "wall_seconds": elapsed,
            "real_time_factor": elapsed / args.duration,
            "tracemalloc_peak_bytes": peak,
            "estimated_working_bytes": result.diagnostics["estimated_working_bytes"],
            "output_bytes": result.audio.nbytes, "diagnostics": result.diagnostics,
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "module": "m24.4.oversampled_nonlinear", "python": sys.version,
        "numpy": np.__version__, "platform": platform.platform(),
        "duration_seconds": args.duration, "sample_rate": args.sample_rate,
        "cases": cases,
    }, indent=2), encoding="utf-8")
    for case in cases:
        print(f"M24.4 {case['oversample']}x · {case['wall_seconds']:.3f}s · RTF {case['real_time_factor']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
