#!/usr/bin/env python3
"""Reproducible M24.3 cross-synthesis CPU/memory benchmark."""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
import tracemalloc
from pathlib import Path

import numpy as np

from reawarp.dsp.cross_synthesis import (
    frequency_shift, ring_modulate, spectral_envelope_transfer, vocoder,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--sample-rate", type=int, default=48_000)
    parser.add_argument("--output", type=Path, default=Path("m24-3-benchmark.json"))
    args = parser.parse_args()
    if args.duration <= 0 or args.sample_rate < 1000:
        parser.error("duration and sample rate must be positive")
    count = int(round(args.duration * args.sample_rate))
    t = np.arange(count, dtype=np.float32) / args.sample_rate
    carrier = (0.15 * np.sin(2 * np.pi * 110 * t) + 0.06 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    modulator = (0.15 * np.sin(2 * np.pi * (220 + 40 * np.sin(2 * np.pi * 0.25 * t)) * t)).astype(np.float32)
    cases = []
    operations = (
        ("ring_modulation", lambda: ring_modulate(carrier, modulator, args.sample_rate)),
        ("frequency_shift", lambda: frequency_shift(carrier, args.sample_rate, 35.0)),
        ("spectral_envelope_transfer", lambda: spectral_envelope_transfer(carrier, modulator, args.sample_rate)),
        ("vocoder", lambda: vocoder(carrier, modulator, args.sample_rate)),
    )
    for name, operation in operations:
        tracemalloc.start()
        started = time.perf_counter()
        result = operation()
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        cases.append({
            "operation": name, "wall_seconds": elapsed,
            "real_time_factor": elapsed / args.duration,
            "tracemalloc_peak_bytes": peak,
            "estimated_working_bytes": result.diagnostics.get("estimated_working_bytes"),
            "output_bytes": result.audio.nbytes, "diagnostics": result.diagnostics,
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "module": "m24.3.cross_synthesis", "python": sys.version,
        "numpy": np.__version__, "platform": platform.platform(),
        "duration_seconds": args.duration, "sample_rate": args.sample_rate,
        "cases": cases,
    }, indent=2), encoding="utf-8")
    for case in cases:
        print(f"M24.3 {case['operation']} · {case['wall_seconds']:.3f}s · RTF {case['real_time_factor']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
