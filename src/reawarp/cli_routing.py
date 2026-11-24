"""Offline routing renders and role-combination audition exports."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from reawarp.export.wav import write_wav
from reawarp.fx_automation import (
    load_fx_automation, normalise_fx_automation, save_fx_automation,
)
from reawarp.fx_routing import (
    build_role_audition_matrix,
    default_fx_routing,
    load_fx_routing,
    normalise_fx_routing,
    render_fx_routing,
    render_master_with_returns,
    save_fx_routing,
)


def _sum_buffers(buffers: Mapping[str, np.ndarray]) -> np.ndarray:
    frames = max((len(audio) for audio in buffers.values()), default=0)
    result = np.zeros((frames, 2), dtype=np.float32)
    for audio in buffers.values():
        value = np.asarray(audio, dtype=np.float32)
        result[:len(value)] += value
    return result


def _rms(audio: np.ndarray) -> float:
    value = np.asarray(audio, dtype=np.float64)
    return float(np.sqrt(np.mean(value * value))) if value.size else 0.0


def _db_ratio(numerator: float, denominator: float) -> float | None:
    if numerator <= 0.0 or denominator <= 0.0:
        return None
    return 20.0 * math.log10(numerator / denominator)


def _write_render(
    output: Path,
    stems: Mapping[str, np.ndarray],
    processed: Mapping[str, np.ndarray],
    returns: Mapping[str, np.ndarray],
    metadata: dict[str, Any],
    routing: Mapping[str, Any],
    automation: Mapping[str, Any],
    sample_rate: int,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    for name, audio in processed.items():
        write_wav(output / "stems" / f"{name}.wav", audio, sample_rate, 24)
    for name, audio in returns.items():
        write_wav(output / "returns" / f"{name}.wav", audio, sample_rate, 24)
    master = render_master_with_returns(
        processed, returns, master_wet=float(metadata["master_wet"])
    )
    write_wav(output / "master.wav", master, sample_rate, 24)
    save_fx_routing(output / "fx_routing.json", routing, tuple(stems), sample_rate)
    save_fx_automation(output / "fx_automation.json", automation, tuple(stems))

    direct_mix = _sum_buffers(processed)
    return_mix = _sum_buffers(returns)
    analysis_frames = max(len(direct_mix), len(return_mix))
    direct_aligned = np.pad(direct_mix, ((0, analysis_frames - len(direct_mix)), (0, 0)))
    return_aligned = np.pad(return_mix, ((0, analysis_frames - len(return_mix)), (0, 0)))
    direct_rms = _rms(direct_aligned)
    return_rms = _rms(return_aligned)
    peak = float(np.max(np.abs(master))) if master.size else 0.0
    analysis = {
        "direct_rms": direct_rms,
        "return_rms": return_rms,
        "return_to_direct_rms_db": _db_ratio(return_rms, direct_rms),
        "direct_peak": float(np.max(np.abs(direct_mix))) if direct_mix.size else 0.0,
        "return_peak": float(np.max(np.abs(return_mix))) if return_mix.size else 0.0,
        "master_peak": peak,
        "master_frames": int(len(master)),
        "source_frames": max((len(audio) for audio in stems.values()), default=0),
        "return_names": list(returns),
    }
    metadata["mix_analysis"] = analysis
    (output / "render.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return analysis


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="reawarp-routing",
        description="Render role-aware per-stem FX routing and beat automation offline.",
    )
    parser.add_argument(
        "project", type=Path,
        help="generated project directory containing project.json and stems/",
    )
    parser.add_argument(
        "--routing", type=Path,
        help="routing JSON; if omitted, a conservative starter file is created",
    )
    parser.add_argument("--automation", type=Path, help="optional beat-based FX automation JSON")
    parser.add_argument("--output", type=Path, default=Path("output/routed"), help="destination directory")
    parser.add_argument("--validate", action="store_true", help="validate routing/automation and exit")
    parser.add_argument(
        "--audition-matrix", action="store_true",
        help="render percussion, melody, ambience, and combined role comparisons",
    )
    args = parser.parse_args()

    project_dir = args.project.expanduser()
    manifest_path = project_dir / "project.json"
    if not manifest_path.is_file():
        raise SystemExit(f"project.json not found: {manifest_path}")
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    names = list(manifest.get("stems", []))
    sample_rate = int(manifest["sample_rate"])
    bpm = float(manifest.get("config", {}).get("bpm", 120.0))

    if args.audition_matrix and args.routing is not None:
        raise SystemExit("--audition-matrix creates its own routing profiles; omit --routing")

    try:
        automation = (
            load_fx_automation(args.automation, names)
            if args.automation is not None else normalise_fx_automation(None, names)
        )
        if args.audition_matrix:
            routings = build_role_audition_matrix(names)
            for routing in routings.values():
                normalise_fx_routing(routing, names, sample_rate)
        else:
            routing_path = args.routing
            if routing_path is None:
                if args.validate:
                    raise SystemExit("--routing is required with --validate")
                routing_path = args.output / "routing.json"
                save_fx_routing(routing_path, default_fx_routing(names), names, sample_rate)
            routings = {"custom": load_fx_routing(routing_path, names, sample_rate)}
    except SystemExit:
        raise
    except Exception as exc:
        raise SystemExit(f"Invalid routing or automation: {exc}") from exc

    if args.validate:
        print(
            f"Valid FX data · {len(names)} stems · {len(automation['lanes'])} automation lane(s) · "
            f"{bpm:g} BPM · {len(routings)} routing profile(s)"
        )
        return

    try:
        import soundfile as sf
    except ImportError as exc:
        raise SystemExit('SoundFile required: python -m pip install -e ".[pyo]"') from exc

    stems: dict[str, np.ndarray] = {}
    for name in names:
        path = project_dir / "stems" / f"{name}.wav"
        if not path.is_file():
            raise SystemExit(f"Missing stem WAV: {path}")
        audio, rate = sf.read(path, dtype="float32", always_2d=True)
        if int(rate) != sample_rate:
            raise SystemExit(f"Sample rate mismatch for {path.name}")
        stems[name] = np.ascontiguousarray(audio, dtype=np.float32)

    report: dict[str, Any] = {
        "schema_version": 1,
        "project": str(project_dir.resolve()),
        "bpm": bpm,
        "profiles": {},
    }
    for profile_name, routing in routings.items():
        try:
            processed, metadata = render_fx_routing(
                stems, sample_rate, routing, bpm=bpm, automation=automation
            )
        except Exception as exc:
            raise SystemExit(f"FX routing render failed for {profile_name}: {exc}") from exc
        returns = metadata.pop("bus_returns_audio")
        destination = (
            args.output / profile_name if args.audition_matrix else args.output
        )
        analysis = _write_render(
            destination, stems, processed, returns, metadata,
            routing, automation, sample_rate,
        )
        report["profiles"][profile_name] = analysis
        print(
            f"{profile_name}: return/direct "
            f"{analysis['return_to_direct_rms_db'] if analysis['return_to_direct_rms_db'] is not None else 'n/a'} dB · "
            f"{len(returns)} active return(s) · {destination.resolve()}"
        )

    if args.audition_matrix:
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "audition_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print("Audition matrix exported. RMS ratios are signal measurements; use listening to judge masking and musical fit.")


if __name__ == "__main__":
    main()
