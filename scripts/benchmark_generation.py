#!/usr/bin/env python3
"""Reproducible Reawarp generation benchmark for M14.

Run from the repository root after installing the package:
    python scripts/benchmark_generation.py --durations 5 30 180

The benchmark records wall-clock time, Python/NumPy allocation peak, render
metadata timings, stem statistics, and an optional process-RSS sample when
psutil is installed. Results are measurements, not performance guarantees.
"""
from __future__ import annotations

import argparse
import gc
import json
import platform
import sys
import time
import tracemalloc
from pathlib import Path

from reawarp import GenerationConfig, ReawarpEngine
from reawarp.diagnostics import analyze_stems
from reawarp.synthesis.profiles import SYNTH_PALETTES


def _rss_mb() -> float | None:
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return None
    return psutil.Process().memory_info().rss / (1024.0 * 1024.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Reawarp offline generation.")
    parser.add_argument("--durations", nargs="+", type=float, default=[5.0, 30.0, 180.0])
    parser.add_argument(
        "--palettes", nargs="+", choices=sorted(SYNTH_PALETTES), default=["subtractive"]
    )
    parser.add_argument("--sample-rate", type=int, default=48_000)
    parser.add_argument("--seed", default="m14-benchmark")
    parser.add_argument("--complexity", type=float, default=0.45)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    results: list[dict[str, object]] = []
    for palette in args.palettes:
        for duration in args.durations:
            config = GenerationConfig(
                duration=duration,
                sample_rate=args.sample_rate,
                seed=f"{args.seed}:{duration:g}:{palette}",
                complexity=args.complexity,
                synth_palette=palette,
            )
            gc.collect()
            rss_before = _rss_mb()
            tracemalloc.start()
            started = time.perf_counter()
            project = ReawarpEngine().generate(config)
            wall_seconds = time.perf_counter() - started
            _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            stem_report = analyze_stems(
                project.stems,
                project.sample_rate,
                expected_frames=config.frame_count,
            )
            results.append({
                "duration_seconds": duration,
                "sample_rate": args.sample_rate,
                "palette": palette,
                "complexity": args.complexity,
                "seed": config.seed,
                "wall_seconds": wall_seconds,
                "real_time_factor": wall_seconds / duration,
                "python_peak_allocated_mb": peak_bytes / (1024.0 * 1024.0),
                "rss_before_mb": rss_before,
                "rss_after_mb": _rss_mb(),
                "frame_count": project.frame_count,
                "stem_count": len(project.stems),
                "event_count": len(project.events),
                "engine_timings": project.metadata.get("performance", {}),
                "signal": stem_report,
            })
            print(
                f"{duration:6.1f}s · {palette:12s} · "
                f"render {wall_seconds:8.3f}s · "
                f"RTF {wall_seconds / duration:6.3f} · "
                f"{len(project.stems)} stems · {len(project.events)} events"
            )
            del project
            gc.collect()

    report = {
        "benchmark_schema": 1,
        "python": sys.version,
        "platform": platform.platform(),
        "results": results,
    }
    encoded = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
