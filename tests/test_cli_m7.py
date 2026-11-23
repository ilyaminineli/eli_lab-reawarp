"""Tests for M7 command-line options."""
from reawarp.cli import build_parser


def test_cli_accepts_45_seconds_and_formal_controls():
    args = build_parser().parse_args([
        "--duration", "45", "--structure", "episodic",
        "--energy", "0.72", "--variation", "0.8",
    ])
    assert args.duration == 45
    assert args.structure == "episodic"
    assert args.energy == 0.72
    assert args.variation == 0.8
