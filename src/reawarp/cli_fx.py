"""Command-line rendering and validation for the optional Pyo FX rack."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from reawarp.export.wav import write_wav
from reawarp.fx import (
    FX_PRESET_DESCRIPTIONS,
    FX_PRESETS,
    FX_STAGE_DESCRIPTIONS,
    load_fx_chain,
    render_pyo_fx,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reawarp-fx",
        description="Render an ordered, non-destructive offline audio effect chain.",
    )
    parser.add_argument("input", nargs="?", type=Path, help="source audio file")
    parser.add_argument("output", nargs="?", type=Path, help="destination WAV file")
    parser.add_argument(
        "--preset", choices=tuple(FX_PRESETS), default=None,
        help="starter chain (default: restrained_space unless --chain-json is used)",
    )
    parser.add_argument(
        "--chain-json", type=Path,
        help="render a portable custom chain saved by the FX Lab",
    )
    parser.add_argument(
        "--validate-chain-json", type=Path,
        help="validate a chain file and exit without requiring Pyo or an audio file",
    )
    parser.add_argument("--wet", type=float, default=None, help="global wet mix (0–1)")
    parser.add_argument(
        "--tail", type=float, default=None,
        help="seconds appended for delay/reverb tails (0–12)",
    )
    parser.add_argument("--list-presets", action="store_true", help="list starter chains and exit")
    parser.add_argument("--list-stages", action="store_true", help="list available stage types and exit")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.list_presets:
        for name, description in FX_PRESET_DESCRIPTIONS.items():
            print(f"{name}: {description}")
        return
    if args.list_stages:
        for name, description in FX_STAGE_DESCRIPTIONS.items():
            print(f"{name}: {description}")
        return
    if args.validate_chain_json is not None:
        try:
            chain = load_fx_chain(args.validate_chain_json)
        except Exception as exc:
            raise SystemExit(f"Invalid FX chain: {exc}") from exc
        print(
            f"Valid FX chain: {chain['name']} · "
            f"{len(chain['stages'])} stage(s) · schema {chain['schema_version']}"
        )
        return

    if args.input is None or args.output is None:
        raise SystemExit(
            "input and output paths are required unless a list or validation option is used"
        )
    if args.chain_json is not None and args.preset is not None:
        raise SystemExit("Choose either --chain-json or --preset, not both.")

    try:
        import soundfile as sf
    except ImportError as exc:
        raise SystemExit(
            'SoundFile is required. Install it with: python -m pip install -e ".[pyo]"'
        ) from exc

    source_path = args.input.expanduser().resolve()
    if not source_path.is_file():
        raise SystemExit(f"Input file does not exist: {source_path}")
    audio, sample_rate = sf.read(str(source_path), dtype="float32", always_2d=True)
    if audio.shape[1] not in (1, 2):
        raise SystemExit("Only mono and stereo files are supported.")

    stages = None
    preset = args.preset or "restrained_space"
    wet = 0.75 if args.wet is None else float(args.wet)
    tail = 1.5 if args.tail is None else float(args.tail)
    chain_name = preset
    if args.chain_json is not None:
        try:
            chain = load_fx_chain(args.chain_json, sample_rate=int(sample_rate))
        except Exception as exc:
            raise SystemExit(f"Invalid FX chain: {exc}") from exc
        stages = chain["stages"]
        preset = None
        chain_name = chain["name"]
        if args.wet is None:
            wet = chain["wet"]
        if args.tail is None:
            tail = chain["tail_seconds"]

    try:
        processed = render_pyo_fx(
            np.asarray(audio, dtype=np.float32),
            int(sample_rate),
            preset=preset,
            stages=stages,
            wet=wet,
            tail_seconds=tail,
        )
    except Exception as exc:
        raise SystemExit(f"FX render failed: {exc}") from exc

    destination = write_wav(args.output, processed, int(sample_rate), bit_depth=24)
    print(
        f"FX render complete: {len(processed) / float(sample_rate):.3f}s "
        f"at {sample_rate} Hz · {chain_name} · "
        f"{len(stages) if stages is not None else len(FX_PRESETS[preset])} stage(s) · "
        f"wet {wet:.2f}"
    )
    print(f"Output: {destination.resolve()}")


if __name__ == "__main__":
    main()
