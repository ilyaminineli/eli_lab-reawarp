"""Command-line rendering for the optional Pyo offline FX rack."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from reawarp.export.wav import write_wav
from reawarp.fx import FX_PRESET_DESCRIPTIONS, FX_PRESETS, render_pyo_fx


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reawarp-fx",
        description="Apply a non-destructive Pyo FX preset to an audio file.",
    )
    parser.add_argument("input", nargs="?", type=Path, help="source audio file")
    parser.add_argument("output", nargs="?", type=Path, help="destination WAV file")
    parser.add_argument(
        "--preset", choices=tuple(FX_PRESETS), default="restrained_space",
        help="ordered effect-chain preset",
    )
    parser.add_argument("--wet", type=float, default=0.75, help="global wet mix (0–1)")
    parser.add_argument(
        "--tail", type=float, default=1.5,
        help="seconds appended for delay/reverb tails (0–12)",
    )
    parser.add_argument("--list-presets", action="store_true", help="list presets and exit")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.list_presets:
        for name, description in FX_PRESET_DESCRIPTIONS.items():
            print(f"{name}: {description}")
        return
    if args.input is None or args.output is None:
        raise SystemExit("input and output paths are required unless --list-presets is used")

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
    processed = render_pyo_fx(
        np.asarray(audio, dtype=np.float32),
        int(sample_rate),
        preset=args.preset,
        wet=args.wet,
        tail_seconds=args.tail,
    )
    destination = write_wav(args.output, processed, int(sample_rate), bit_depth=24)
    print(
        f"FX render complete: {len(processed) / float(sample_rate):.3f}s "
        f"at {sample_rate} Hz · {args.preset} · wet {args.wet:.2f}"
    )
    print(f"Output: {destination.resolve()}")


if __name__ == "__main__":
    main()
