"""Command-line interface for generating loops and synchronized stems."""

from __future__ import annotations

import argparse
from pathlib import Path

from reawarp import GenerationConfig, ReawarpEngine
from reawarp.synthesis.profiles import HAT_PROFILES, KICK_PROFILES, SNARE_PROFILES
from reawarp.transforms.pipeline import BREAK_TRANSFORMS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reawarp",
        description="Generate deterministic mathematical IDM loops and stems.",
    )
    parser.add_argument("--bpm", type=float, default=137.0, help="tempo in BPM (60–220)")
    parser.add_argument("--duration", type=float, default=12.0, help="duration in seconds (5–20)")
    parser.add_argument("--seed", default="20261123", help="integer or text seed")
    parser.add_argument("--complexity", type=float, default=0.68, help="complexity (0–1)")
    parser.add_argument("--sample-rate", type=int, default=48_000, help="render sample rate")
    parser.add_argument("--output", type=Path, default=Path("output/reawarp"), help="export directory")
    parser.add_argument("--bit-depth", type=int, choices=(16, 24), default=24)
    parser.add_argument("--midi-output", type=Path, help="optional MIDI export path for the generated score")
    parser.add_argument("--kick-sample", type=Path, help="optional custom kick WAV")
    parser.add_argument("--snare-sample", type=Path, help="optional custom snare WAV")
    parser.add_argument("--hat-sample", type=Path, help="optional custom hat WAV")
    parser.add_argument("--break-sample", type=Path, help="optional custom break WAV")
    parser.add_argument("--no-melody", action="store_true", help="disable geometric FM melody")
    parser.add_argument("--no-texture", action="store_true", help="disable noise texture")
    parser.add_argument(
        "--kick-profile", choices=("auto", *KICK_PROFILES), default="auto",
        help="fixed kick timbre or deterministic per-hit profile selection",
    )
    parser.add_argument(
        "--snare-profile", choices=("auto", *SNARE_PROFILES), default="auto",
        help="fixed snare timbre or deterministic per-hit profile selection",
    )
    parser.add_argument(
        "--hat-profile", choices=("auto", *HAT_PROFILES), default="auto",
        help="fixed hi-hat timbre or deterministic per-hit profile selection",
    )
    parser.add_argument(
        "--break-transforms", default="",
        help="comma-separated operations: " + ", ".join(BREAK_TRANSFORMS),
    )
    parser.add_argument("--break-slice-count", type=int, default=16)
    parser.add_argument("--break-stutter-repeats", type=int, default=4)
    parser.add_argument("--break-dropout-probability", type=float, default=0.18)
    parser.add_argument("--break-pitch-semitones", type=float, default=0.0)
    parser.add_argument("--break-time-stretch", type=float, default=1.0,
                        help="output/input duration ratio (0.25–4.0)")
    parser.add_argument("--break-gate-rate", type=float, default=8.0, help="gate rate in Hz")
    parser.add_argument("--break-gate-duty", type=float, default=0.62)
    parser.add_argument("--break-grain-size-ms", type=float, default=80.0)
    parser.add_argument("--break-grain-density", type=float, default=1.5)
    parser.add_argument("--break-freeze-position", type=float, default=0.25,
                        help="spectral freeze position from 0.0 to 1.0")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    sample_paths = {
        role: str(path)
        for role, path in {
            "kick": args.kick_sample,
            "snare": args.snare_sample,
            "hat": args.hat_sample,
            "break": args.break_sample,
        }.items()
        if path is not None
    }
    seed: int | str = int(args.seed) if str(args.seed).lstrip("-+").isdigit() else str(args.seed)
    transforms = tuple(
        item.strip() for item in args.break_transforms.split(",") if item.strip()
    )
    config = GenerationConfig(
        bpm=args.bpm,
        duration=args.duration,
        sample_rate=args.sample_rate,
        seed=seed,
        complexity=args.complexity,
        include_melody=not args.no_melody,
        include_texture=not args.no_texture,
        sample_paths=sample_paths,
        kick_profile=args.kick_profile,
        snare_profile=args.snare_profile,
        hat_profile=args.hat_profile,
        break_transforms=transforms,
        break_slice_count=args.break_slice_count,
        break_stutter_repeats=args.break_stutter_repeats,
        break_dropout_probability=args.break_dropout_probability,
        break_pitch_semitones=args.break_pitch_semitones,
        break_time_stretch=args.break_time_stretch,
        break_gate_rate_hz=args.break_gate_rate,
        break_gate_duty=args.break_gate_duty,
        break_grain_size_ms=args.break_grain_size_ms,
        break_grain_density=args.break_grain_density,
        break_spectral_freeze_position=args.break_freeze_position,
    )
    project = ReawarpEngine().generate(config)
    output = project.export(args.output, bit_depth=args.bit_depth)
    print(f"Reawarp rendered {project.duration:.3f}s at {project.sample_rate} Hz")
    print(f"Stems: {', '.join(project.stems)}")
    print(f"Events: {len(project.events)}")
    if transforms:
        print(f"Break transforms: {', '.join(transforms)}")
    print(f"Output: {output.resolve()}")
    if args.midi_output is not None:
        midi_path = project.to_score().export_midi(args.midi_output)
        print(f"MIDI: {midi_path.resolve()}")


if __name__ == "__main__":
    main()
