"""Small command-line adapters for Reawarp score JSON and MIDI files."""

from __future__ import annotations

import argparse
from pathlib import Path

from reawarp.score import Score


def export_main() -> None:
    parser = argparse.ArgumentParser(
        prog="reawarp-midi-export",
        description="Export a Reawarp score JSON file as a standard MIDI 1.0 file.",
    )
    parser.add_argument("score", type=Path, help="input score.json")
    parser.add_argument(
        "-o", "--output", type=Path, required=True, help="output .mid file"
    )
    parser.add_argument("--ppq", type=int, help="override MIDI ticks per quarter note")
    parser.add_argument(
        "--tempo-ramp-resolution",
        default="1/4",
        help="tempo-ramp sampling interval in quarter-note beats (default: 1/4)",
    )
    args = parser.parse_args()
    score = Score.load(args.score)
    output = score.export_midi(
        args.output,
        ticks_per_beat=args.ppq,
        tempo_ramp_resolution=args.tempo_ramp_resolution,
    )
    print(f"Exported {len(score.events)} score events to {output.resolve()}")


def import_main() -> None:
    parser = argparse.ArgumentParser(
        prog="reawarp-midi-import",
        description="Import a standard MIDI 1.0 file as a Reawarp score JSON file.",
    )
    parser.add_argument("midi", type=Path, help="input .mid file")
    parser.add_argument(
        "-o", "--output", type=Path, required=True, help="output score.json"
    )
    args = parser.parse_args()
    score = Score.from_midi(args.midi)
    output = score.save(args.output)
    print(f"Imported {len(score.events)} note events to {output.resolve()}")
