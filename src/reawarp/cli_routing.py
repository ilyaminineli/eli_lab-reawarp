"""Offline rendering of a generated Reawarp project through an FX routing file."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from reawarp.export.wav import write_wav
from reawarp.fx_automation import load_fx_automation, normalise_fx_automation, save_fx_automation
from reawarp.fx_routing import (
    default_fx_routing, load_fx_routing,
    render_fx_routing, render_master_with_returns, save_fx_routing,
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="reawarp-routing", description="Render role-aware stem FX routing offline.")
    parser.add_argument("project", type=Path, help="generated project directory containing project.json and stems/")
    parser.add_argument("--routing", type=Path, help="routing JSON; if omitted, a conservative starter file is created")
    parser.add_argument("--automation", type=Path, help="optional beat-based FX automation JSON")
    parser.add_argument("--output", type=Path, default=Path("output/routed"), help="destination directory")
    parser.add_argument("--validate", action="store_true", help="validate routing JSON and exit")
    args = parser.parse_args()
    project_dir = args.project.expanduser()
    manifest_path = project_dir / "project.json"
    if not manifest_path.is_file():
        raise SystemExit(f"project.json not found: {manifest_path}")
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    names = list(manifest.get("stems", []))
    sample_rate = int(manifest["sample_rate"])
    routing_path = args.routing
    if routing_path is None:
        if args.validate:
            raise SystemExit("--routing is required with --validate")
        routing_path = args.output / "routing.json"
        save_fx_routing(routing_path, default_fx_routing(names), names, sample_rate)
    try:
        routing = load_fx_routing(routing_path, names, sample_rate)
        automation = (
            load_fx_automation(args.automation, names)
            if args.automation is not None else normalise_fx_automation(None, names)
        )
    except Exception as exc:
        raise SystemExit(f"Invalid routing or automation: {exc}") from exc
    bpm = float(manifest.get("config", {}).get("bpm", 120.0))
    if args.validate:
        print(
            f"Valid FX routing · {len(names)} stems · {len(routing['buses'])} buses · "
            f"{len(automation['lanes'])} automation lane(s) · {bpm:g} BPM"
        )
        return
    try:
        import soundfile as sf
    except ImportError as exc:
        raise SystemExit('SoundFile required: python -m pip install -e ".[pyo]"') from exc
    stems = {}
    for name in names:
        path = project_dir / "stems" / f"{name}.wav"
        if not path.is_file():
            raise SystemExit(f"Missing stem WAV: {path}")
        audio, rate = sf.read(path, dtype="float32", always_2d=True)
        if int(rate) != sample_rate:
            raise SystemExit(f"Sample rate mismatch for {path.name}")
        stems[name] = np.ascontiguousarray(audio, dtype=np.float32)
    try:
        processed, meta = render_fx_routing(
            stems, sample_rate, routing, bpm=bpm, automation=automation
        )
    except Exception as exc:
        raise SystemExit(f"FX routing render failed: {exc}") from exc
    returns = meta.pop("bus_returns_audio")
    output = args.output.expanduser()
    output.mkdir(parents=True, exist_ok=True)
    for name, audio in processed.items():
        write_wav(output / "stems" / f"{name}.wav", audio, sample_rate, 24)
    for name, audio in returns.items():
        write_wav(output / "returns" / f"{name}.wav", audio, sample_rate, 24)
    save_fx_automation(output / "fx_automation.json", automation, names)
    master = render_master_with_returns(processed, returns, master_wet=meta["master_wet"])
    write_wav(output / "master.wav", master, sample_rate, 24)
    save_fx_routing(output / "fx_routing.json", routing, names, sample_rate)
    (output / "render.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"Routed render complete · {len(processed)} stems · {len(returns)} active return(s) · "
        f"{len(automation['lanes'])} automation lane(s) · {output.resolve()}"
    )


if __name__ == "__main__":
    main()
