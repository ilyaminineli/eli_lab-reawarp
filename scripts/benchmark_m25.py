#!/usr/bin/env python3
"""M25 target-machine 30s/180s generation, export, reopen and optional Pyo sign-off."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import sys
import tempfile
import threading
import time
import tracemalloc
from pathlib import Path
from typing import Any

import numpy as np

from reawarp import GenerationConfig, ReawarpEngine, ReawarpProject
from reawarp.core.manifest import audit_project_assets
from reawarp.export.wav import write_wav
from reawarp.fx_routing import (
    render_fx_routing, render_master_with_returns, role_aware_fx_routing,
)


def _rss_bytes() -> int | None:
    if sys.platform == "win32":
        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        try:
            process = ctypes.windll.kernel32.GetCurrentProcess()
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(
                process, ctypes.byref(counters), counters.cb
            )
            return int(counters.WorkingSetSize) if ok else None
        except (AttributeError, OSError):
            return None
    statm = Path("/proc/self/statm")
    if statm.is_file():
        try:
            resident_pages = int(statm.read_text(encoding="ascii").split()[1])
            return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
        except (OSError, ValueError, IndexError):
            return None
    try:
        import resource
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value if sys.platform == "darwin" else value * 1024
    except (ImportError, AttributeError, OSError, ValueError):
        return None


class RSSSampler:
    def __init__(self, interval_seconds: float = 0.02):
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.peak_bytes: int | None = None

    def start(self) -> None:
        self.peak_bytes = _rss_bytes()
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()

    def _sample(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            current = _rss_bytes()
            if current is not None:
                self.peak_bytes = max(self.peak_bytes or 0, current)

    def stop(self) -> int | None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
        current = _rss_bytes()
        if current is not None:
            self.peak_bytes = max(self.peak_bytes or 0, current)
        return self.peak_bytes


def _directory_bytes(directory: Path) -> int:
    return sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())


def _case(duration: float, args: argparse.Namespace) -> dict[str, Any]:
    seed_material = f"{args.seed}:{duration:g}".encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(seed_material).digest()[:4], "big")
    config = GenerationConfig(
        duration=duration,
        sample_rate=args.sample_rate,
        seed=seed,
        complexity=args.complexity,
        synth_palette=args.palette,
    )
    automation = {"schema_version": 1, "lanes": {}}
    tracemalloc.start()
    sampler = RSSSampler()
    sampler.start()
    case_started = time.perf_counter()

    generation_started = time.perf_counter()
    project = ReawarpEngine().generate(config)
    generation_seconds = time.perf_counter() - generation_started
    routing = role_aware_fx_routing(tuple(project.stems))

    pyo_report: dict[str, Any] = {"requested": bool(args.pyo), "status": "not_requested"}
    routed_master = None
    if args.pyo:
        pyo_started = time.perf_counter()
        try:
            processed, routing_metadata = render_fx_routing(
                project.stems, project.sample_rate, routing, bpm=config.bpm
            )
            returns = routing_metadata.pop("bus_returns_audio")
            routed_master = render_master_with_returns(processed, returns)
            pyo_report = {
                "requested": True, "status": "rendered",
                "wall_seconds": time.perf_counter() - pyo_started,
                "routing_metadata": routing_metadata,
            }
        except Exception as exc:
            pyo_report = {
                "requested": True, "status": "failed",
                "wall_seconds": time.perf_counter() - pyo_started,
                "error": f"{type(exc).__name__}: {exc}",
            }

    with tempfile.TemporaryDirectory(prefix="reawarp-m25-") as temporary:
        export_directory = Path(temporary) / "project"
        export_started = time.perf_counter()
        project.export(
            export_directory,
            bit_depth=24,
            include_stems=True,
            include_master=True,
            fx_routing=routing,
            fx_automation=automation,
            asset_policy="copy",
        )
        if routed_master is not None:
            write_wav(export_directory / "master.wav", routed_master, project.sample_rate, 24)
        export_seconds = time.perf_counter() - export_started

        reopen_started = time.perf_counter()
        reopened = ReawarpProject.load(export_directory)
        reopen_seconds = time.perf_counter() - reopen_started
        if reopened.sample_rate != project.sample_rate or reopened.frame_count != project.frame_count:
            raise RuntimeError("reopened project timing differs from the generated project")
        if tuple(reopened.stems) != tuple(project.stems):
            raise RuntimeError("reopened project stem set differs from the generated project")
        asset_audit = audit_project_assets(export_directory)
        project_file_audit = dict(reopened.metadata.get("project_file_validation", {}))
        archive_manifest = json.loads(
            (export_directory / "manifest.json").read_text(encoding="utf-8")
        )
        artifact_bytes = _directory_bytes(export_directory)

    total_seconds = time.perf_counter() - case_started
    _current_bytes, allocation_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_rss = sampler.stop()

    stem_bytes = sum(int(audio.nbytes) for audio in project.stems.values())
    master_bytes = int(project.frame_count * 2 * np.dtype(np.float32).itemsize)
    performance = dict(project.metadata.get("performance", {}))
    stage_timings = {
        "planning_seconds": performance.get("planning_seconds"),
        "composition_plan_seconds": performance.get("composition_plan_seconds"),
        "event_generation_seconds": performance.get("event_generation_seconds"),
        "score_render_seconds": performance.get("score_render_seconds"),
        "field_render_seconds": performance.get("field_render_seconds"),
        "headroom_seconds": performance.get("headroom_seconds"),
        "fx_render_seconds": pyo_report.get("wall_seconds"),
        "export_seconds": export_seconds,
        "reopen_seconds": reopen_seconds,
    }
    return {
        "duration_seconds": duration,
        "sample_rate": project.sample_rate,
        "seed": config.seed,
        "palette": args.palette,
        "complexity": args.complexity,
        "wall_seconds": total_seconds,
        "generation_seconds": generation_seconds,
        "generation_real_time_factor": generation_seconds / duration,
        "real_time_factor": total_seconds / duration,
        "config": config.to_dict(),
        "render_environment": archive_manifest.get("render_environment", {}),
        "stage_timings": stage_timings,
        "engine_performance": performance,
        "frame_count": project.frame_count,
        "event_count": len(project.events),
        "stem_count": len(project.stems),
        "stem_buffer_bytes": stem_bytes,
        "estimated_master_buffer_bytes": master_bytes,
        "python_tracemalloc_peak_bytes": int(allocation_peak),
        "process_peak_rss_bytes": peak_rss,
        "artifact_bytes": artifact_bytes,
        "asset_audit": asset_audit,
        "project_file_audit": project_file_audit,
        "pyo_integration": pyo_report,
        "human_listening": {
            "status": "pending",
            "checks": [
                "Listen at deliberately low monitor volume before raising level.",
                "Audition the routed master and individual returns in context.",
                "Check master and key stems in mono for phase loss and masking.",
                "Record audible artifacts, stability, noise and export/reopen parity.",
            ],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--durations", nargs="+", type=float, default=[30.0, 180.0])
    parser.add_argument("--sample-rate", type=int, default=48_000)
    parser.add_argument("--seed", default="m25-target-signoff")
    parser.add_argument("--complexity", type=float, default=0.45)
    parser.add_argument("--palette", default="subtractive")
    parser.add_argument("--pyo", action="store_true", help="run the optional Pyo-backed role-routing render")
    parser.add_argument("--max-rss-gb", type=float, default=None)
    parser.add_argument("--max-wall-seconds", type=float, default=None)
    parser.add_argument("--output", type=Path, default=Path("m25-target-windows.json"))
    args = parser.parse_args()
    if any(duration <= 0 or duration > 180 for duration in args.durations):
        parser.error("durations must be greater than 0 and no greater than 180 seconds")
    if args.sample_rate != 48_000:
        parser.error("M25 target sign-off is defined at 48000 Hz")
    if args.max_rss_gb is not None and args.max_rss_gb <= 0:
        parser.error("--max-rss-gb must be positive")
    if args.max_wall_seconds is not None and args.max_wall_seconds <= 0:
        parser.error("--max-wall-seconds must be positive")

    results = [_case(duration, args) for duration in args.durations]
    limits = {
        "max_rss_gb": args.max_rss_gb,
        "max_wall_seconds": args.max_wall_seconds,
    }
    for result in results:
        peak = result["process_peak_rss_bytes"]
        rss_pass = (
            None if args.max_rss_gb is None or peak is None
            else peak <= args.max_rss_gb * (1024 ** 3)
        )
        wall_pass = (
            None if args.max_wall_seconds is None
            else result["wall_seconds"] <= args.max_wall_seconds
        )
        result["budget_check"] = {
            "rss_budget_pass": rss_pass,
            "wall_budget_pass": wall_pass,
        }

    report = {
        "benchmark_schema": 1,
        "benchmark": "M25 long-form project durability",
        "environment": {
            "os": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor() or platform.machine(),
            "python": sys.version,
            "numpy": np.__version__,
            "scipy": results[0]["render_environment"].get("scipy") if results else None,
            "physical_memory_bytes": (
                results[0]["render_environment"].get("physical_memory_bytes")
                if results else None
            ),
        },
        "target": {"sample_rate": 48_000, "durations_seconds": args.durations, "budgets": limits},
        "results": results,
        "acceptance": {
            "render_export_reopen": all(
                item["artifact_bytes"] > 0 and item["asset_audit"]["ok"]
                and item["project_file_audit"].get("ok", False)
                for item in results
            ),
            "resource_budgets_declared": (
                args.max_rss_gb is not None and args.max_wall_seconds is not None
            ),
            "resource_budget_pass": (
                "not_declared" if args.max_rss_gb is None or args.max_wall_seconds is None
                else all(
                    item["budget_check"]["rss_budget_pass"] is True
                    and item["budget_check"]["wall_budget_pass"] is True
                    for item in results
                )
            ),
            "pyo_integration": (
                all(item["pyo_integration"]["status"] == "rendered" for item in results)
                if args.pyo else "not_run"
            ),
            "human_listening": "pending_user_signoff",
            "target_machine_signoff": "pending_resource_budget_pyo_and_human_listening",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    for result in results:
        rss = result["process_peak_rss_bytes"]
        rss_text = f"{rss / (1024 ** 3):.2f} GiB" if rss is not None else "unavailable"
        print(
            f"M25 {result['duration_seconds']:6.1f}s · "
            f"{result['wall_seconds']:8.2f}s · RTF {result['real_time_factor']:.3f} · "
            f"RSS {rss_text} · export {result['export_seconds']:.2f}s · reopen {result['reopen_seconds']:.2f}s"
        )
    print(f"Report written to {args.output}")
    failures = any(
        item["budget_check"]["rss_budget_pass"] is False
        or item["budget_check"]["wall_budget_pass"] is False
        or (args.pyo and item["pyo_integration"]["status"] != "rendered")
        for item in results
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
