"""Command-line interface for generating loops and synchronized stems."""

from __future__ import annotations

import argparse
from pathlib import Path

from reawarp import GenerationConfig, ReawarpEngine
from reawarp.generators.percussion import BREAK_STYLE_NAMES
from reawarp.synthesis.profiles import (
    HAT_PROFILES, KICK_PROFILES, MELODY_PROFILES, SNARE_PROFILES, SYNTH_PALETTES
)
from reawarp.composition.patterns import PATTERN_FAMILIES, PATTERN_RELATIONSHIPS
from reawarp.composition.director import STRUCTURES
from reawarp.mathematics.theory import SCALE_STEPS
from reawarp.samples.catalog import default_sample_for_role
from reawarp.transforms.pipeline import BREAK_TRANSFORMS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reawarp",
        description="Generate deterministic, structure-aware IDM compositions and stems.",
    )
    parser.add_argument("--bpm", type=float, default=137.0, help="tempo in BPM (60–220)")
    parser.add_argument("--duration", type=float, default=24.0, help="duration in seconds (5–180)")
    parser.add_argument(
        "--structure", choices=tuple(STRUCTURES), default="evolving",
        help="formal composition trajectory",
    )
    parser.add_argument("--flow", choices=("preset", "mix", "mutate"), default="preset", help="keep the preset, cross-mix its sections, or mutate its middle flow")
    parser.add_argument("--pattern-family", choices=tuple(PATTERN_FAMILIES), default="broken_funk", help="structure-aware rhythmic family")
    parser.add_argument("--pattern-relationship", choices=PATTERN_RELATIONSHIPS, default="interlock", help="relationship between pattern voices")
    parser.add_argument(
        "--pattern-follow-structure", action=argparse.BooleanOptionalAction, default=True,
        help="automatically evolve linked kick/snare/hat parts at formal section boundaries",
    )
    parser.add_argument("--drum-change-intensity", type=float, default=0.68)
    parser.add_argument("--drum-part-cycle-bars", type=int, choices=(1, 2, 4), default=2)
    parser.add_argument(
        "--drum-sample-automation", choices=("fixed", "section", "cycle", "automatic"),
        default="automatic", help="when percussion sample banks switch through the arrangement",
    )
    parser.add_argument("--arrangement-density", type=float, default=0.55)
    parser.add_argument("--rhythmic-syncopation", type=float, default=0.52)
    parser.add_argument("--arrangement-instability", type=float, default=0.40)
    parser.add_argument("--melodic-activity", type=float, default=0.62)
    parser.add_argument("--melody-register-semitones", type=int, choices=range(-24, 25), default=0)
    parser.add_argument("--tonal-brightness", type=float, default=0.55)
    parser.add_argument("--spatial-intent", type=float, default=0.52)
    parser.add_argument("--synth-palette", choices=SYNTH_PALETTES, default="subtractive", help="lead synthesis architecture palette")
    parser.add_argument("--percussion-synthesis", choices=("minimal", "extended", "samples"), default="minimal", help="synthetic drum architecture used when synthesis is active")
    parser.add_argument(
        "--percussion-source-mode", choices=("automatic", "synth", "sample", "hybrid"),
        default="automatic", help="section-aware sample/synthesis source mode",
    )
    parser.add_argument(
        "--percussion-hybrid-architecture", choices=("transient_body", "layered", "feature_guided"),
        default="transient_body", help="sample transient + synth body, or two full parallel layers",
    )
    parser.add_argument("--percussion-sample-mix", type=float, default=0.46)
    parser.add_argument("--hybrid-transient-ms", type=float, default=28.0)
    parser.add_argument("--melody-scale", choices=tuple(SCALE_STEPS), default="chromatic")
    parser.add_argument("--melody-root", type=int, choices=range(12), default=0, help="melody pitch-field root class (0=C)")
    parser.add_argument("--energy", type=float, default=0.62, help="composition energy target, not output gain (0–1)")
    parser.add_argument("--variation", type=float, default=0.45, help="bounded formal variation (0–1)")
    parser.add_argument("--seed", default="20261123", help="integer or text seed")
    parser.add_argument("--complexity", type=float, default=0.68, help="complexity (0–1)")
    parser.add_argument("--sample-rate", type=int, default=48_000, help="render sample rate")
    parser.add_argument("--output", type=Path, default=Path("output/reawarp"), help="export directory")
    parser.add_argument("--bit-depth", type=int, choices=(16, 24), default=24)
    parser.add_argument("--midi-output", type=Path, help="optional MIDI export path for the generated score")
    parser.add_argument("--kick-sample", type=Path, help="optional custom kick WAV (overrides bundled default)")
    parser.add_argument("--snare-sample", type=Path, help="optional custom snare WAV (overrides bundled default)")
    parser.add_argument("--hat-sample", type=Path, help="optional custom hat WAV (overrides bundled default)")
    parser.add_argument(
        "--bundled-samples", action=argparse.BooleanOptionalAction, default=True,
        help="use the repository's bundled kick/snare/hat sources when no custom path is supplied",
    )
    parser.add_argument("--break-sample", type=Path, help="optional custom break WAV")
    parser.add_argument("--no-melody", action="store_true", help="disable geometric FM melody")
    parser.add_argument("--no-texture", action="store_true", help="disable noise texture")
    parser.add_argument("--no-ambience", action="store_true", help="disable harmonic ambience")
    parser.add_argument("--ambience-level", type=float, default=0.16,
                        help="ambient stem level (0–1)")
    parser.add_argument(
        "--melody-profile", choices=("auto", *MELODY_PROFILES), default="auto",
        help="profiled additive/FM melody voice",
    )
    parser.add_argument(
        "--break-style", choices=("auto", *BREAK_STYLE_NAMES), default="broken_funk",
        help="16-step break rhythm grammar",
    )
    parser.add_argument("--break-density", type=float, default=0.50,
                        help="break events per bar, from sparse to full (0–1)")
    parser.add_argument("--break-variation", type=float, default=0.25,
                        help="probability of bounded phrase mutation (0–1)")
    parser.add_argument("--break-cycle-bars", type=int, choices=(1, 2, 4), default=2,
                        help="break phrase length before a variation")
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
    sample_paths: dict[str, str] = {}
    sample_metadata: dict[str, dict[str, object]] = {}
    requested_samples = {
        "kick": args.kick_sample,
        "snare": args.snare_sample,
        "hat": args.hat_sample,
        "break": args.break_sample,
    }
    for role, explicit_path in requested_samples.items():
        selected = explicit_path
        bundled = None
        if selected is None and args.bundled_samples and role in {"kick", "snare", "hat"}:
            bundled = default_sample_for_role(role)
            selected = bundled.path if bundled is not None else None
        if selected is not None:
            sample_paths[role] = str(selected)
            sample_metadata[role] = {
                "provider": "bundled_sample_library" if bundled else "cli_sample",
                "relative_path": bundled.relative_path if bundled else Path(selected).name,
                "source_name": Path(selected).name,
            }
    seed: int | str = int(args.seed) if str(args.seed).lstrip("-+").isdigit() else str(args.seed)
    transforms = tuple(
        item.strip() for item in args.break_transforms.split(",") if item.strip()
    )
    config = GenerationConfig(
        bpm=args.bpm,
        duration=args.duration,
        structure=args.structure,
        composition_flow=args.flow,
        pattern_family=args.pattern_family,
        pattern_relationship=args.pattern_relationship,
        pattern_follow_structure=args.pattern_follow_structure,
        drum_change_intensity=args.drum_change_intensity,
        drum_part_cycle_bars=args.drum_part_cycle_bars,
        drum_sample_automation=args.drum_sample_automation,
        arrangement_density=args.arrangement_density,
        rhythmic_syncopation=args.rhythmic_syncopation,
        arrangement_instability=args.arrangement_instability,
        melodic_activity=args.melodic_activity,
        melody_register_semitones=args.melody_register_semitones,
        tonal_brightness=args.tonal_brightness,
        spatial_intent=args.spatial_intent,
        synth_palette=args.synth_palette,
        percussion_synthesis=args.percussion_synthesis,
        percussion_source_mode=args.percussion_source_mode,
        percussion_hybrid_architecture=args.percussion_hybrid_architecture,
        percussion_sample_mix=args.percussion_sample_mix,
        hybrid_transient_ms=args.hybrid_transient_ms,
        melody_scale=args.melody_scale,
        melody_root=args.melody_root,
        composition_energy=args.energy,
        composition_variation=args.variation,
        sample_rate=args.sample_rate,
        seed=seed,
        complexity=args.complexity,
        include_melody=not args.no_melody,
        include_texture=not args.no_texture,
        include_ambience=not args.no_ambience,
        ambience_level=args.ambience_level,
        sample_paths=sample_paths,
        sample_metadata=sample_metadata,
        kick_profile=args.kick_profile,
        snare_profile=args.snare_profile,
        hat_profile=args.hat_profile,
        melody_profile=args.melody_profile,
        break_style=args.break_style,
        break_density=args.break_density,
        break_variation=args.break_variation,
        break_cycle_bars=args.break_cycle_bars,
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
