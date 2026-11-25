"""Benchmark M24.1 partitioned convolution, IR design and memory diagnostics."""
from __future__ import annotations

import argparse
import json
import platform
import time
import tracemalloc
from pathlib import Path

import numpy as np

from reawarp.dsp.convolution import convolve_partitioned, design_resonant_ir


def benchmark_case(sample_rate: int, duration: float, ir_duration: float, seed: int, block_size: int):
    frames = int(round(sample_rate * duration))
    rng = np.random.default_rng(seed)
    source = (rng.standard_normal(frames) * 0.035).astype(np.float32)
    response = design_resonant_ir(
        sample_rate,
        ir_duration,
        [
            {"frequency_hz": 211.0, "gain": 0.5, "decay_seconds": ir_duration * 0.42},
            {"frequency_hz": 337.7, "gain": 0.25, "decay_seconds": ir_duration * 0.72},
            {"frequency_hz": 593.1, "gain": 0.14, "decay_seconds": ir_duration * 0.9},
            {"frequency_hz": 1_017.3, "gain": 0.08, "decay_seconds": ir_duration},
            {"frequency_hz": 2_119.0, "gain": 0.04, "decay_seconds": ir_duration * 0.8},
        ],
        seed=seed,
        diffuse_noise=0.025,
        name="M24.1 benchmark resonator",
        impulse_id=f"m24-bench-{sample_rate}-{seed}",
    )
    tracemalloc.start()
    started = time.perf_counter()
    result = convolve_partitioned(
        source, response, sample_rate, block_size=block_size
    )
    wall_seconds = time.perf_counter() - started
    _current, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    diagnostics = dict(result.diagnostics)
    diagnostics.update({
        "requested_duration_seconds": duration,
        "requested_ir_duration_seconds": ir_duration,
        "wall_seconds": wall_seconds,
        "tracemalloc_peak_bytes": int(traced_peak),
        "ir_sha256": response.sha256,
        "seed": seed,
    })
    return diagnostics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--durations", nargs="+", type=float, default=(0.5, 5.0))
    parser.add_argument("--ir-durations", nargs="+", type=float, default=(0.25, 1.5))
    parser.add_argument("--sample-rates", nargs="+", type=int, default=(22_050, 48_000))
    parser.add_argument("--block-size", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=20261125)
    parser.add_argument("--output", type=Path, default=Path("benchmark-m24-1-convolution.json"))
    args = parser.parse_args()
    if (
        any(value <= 0 for value in args.durations)
        or any(value <= 0 for value in args.ir_durations)
        or any(value < 1_000 for value in args.sample_rates)
    ):
        parser.error("durations and sample rates must be positive")
    results = []
    for rate in args.sample_rates:
        for duration in args.durations:
            for ir_duration in args.ir_durations:
                results.append(
                    benchmark_case(rate, duration, ir_duration, args.seed, args.block_size)
                )
    payload = {
        "schema_version": 1,
        "module": "m24.1.convolution",
        "algorithm": "uniform_partitioned_overlap_add",
        "seed": args.seed,
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "results": results,
        "note": (
            "tracemalloc does not observe every native NumPy allocation; "
            "estimated_working_bytes is the module's buffer accounting."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    print(f"Wrote {len(results)} M24.1 benchmark cases to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
