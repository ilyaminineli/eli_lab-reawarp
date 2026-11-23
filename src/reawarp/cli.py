"""Command-line interface for generating loops and synchronized stems."""

from __future__ import annotations

import argparse
from pathlib import Path

from reawarp import GenerationConfig, ReawarpEngine


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
    parser.add_argument("--kick-sample", type=Path, help="optional custom kick WAV")
    parser.add_argument("--snare-sample", type=Path, help="optional custom snare WAV")
    parser.add_argument("--hat-sample", type=Path, help="optional custom hat WAV")
    parser.add_argument("--break-sample", type=Path, help="optional custom break-hit WAV")
    parser.add_argument("--no-melody", action="store_true", help="disable geometric FM melody")
    parser.add_argument("--no-texture", action="store_true", help="disable noise texture")
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
    config = GenerationConfig(
        bpm=args.bpm,
        duration=args.duration,
        sample_rate=args.sample_rate,
        seed=seed,
        complexity=args.complexity,
        include_melody=not args.no_melody,
        include_texture=not args.no_texture,
        sample_paths=sample_paths,
    )
    project = ReawarpEngine().generate(config)
    output = project.export(args.output, bit_depth=args.bit_depth)
    print(f"Reawarp rendered {project.duration:.3f}s at {project.sample_rate} Hz")
    print(f"Stems: {', '.join(project.stems)}")
    print(f"Events: {len(project.events)}")
    print(f"Output: {output.resolve()}")


if __name__ == "__main__":
    main()
