from __future__ import annotations

from reawarp.cli import build_parser


def test_parser_exposes_ui_composition_axes_and_source_automation() -> None:
    parser = build_parser()
    args = parser.parse_args([
        "--bpm", "137",
        "--duration", "30",
        "--arrangement-density", "0.76",
        "--rhythmic-syncopation", "0.86",
        "--arrangement-instability", "0.82",
        "--melodic-activity", "0.72",
        "--melody-register-semitones", "7",
        "--tonal-brightness", "0.67",
        "--spatial-intent", "0.88",
        "--drum-sample-automation", "automatic",
        "--percussion-source-mode", "hybrid",
        "--percussion-hybrid-architecture", "feature_guided",
    ])

    assert args.bpm == 137.0
    assert args.duration == 30.0
    assert args.arrangement_density == 0.76
    assert args.rhythmic_syncopation == 0.86
    assert args.arrangement_instability == 0.82
    assert args.melodic_activity == 0.72
    assert args.melody_register_semitones == 7
    assert args.tonal_brightness == 0.67
    assert args.spatial_intent == 0.88
    assert args.drum_sample_automation == "automatic"
    assert args.percussion_hybrid_architecture == "feature_guided"
