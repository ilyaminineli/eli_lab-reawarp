"""Pitch collections and optional symbolic-theory adapters.

The compact pitch-class tables keep the core renderer deterministic and
dependency-free. When the optional music21 extra is installed, callers can
request richer symbolic scale objects for analysis and notation workflows.
"""

from __future__ import annotations

from typing import Any

SCALE_STEPS: dict[str, tuple[int, ...]] = {
    "chromatic": tuple(range(12)),
    "major": (0, 2, 4, 5, 7, 9, 11),
    "natural_minor": (0, 2, 3, 5, 7, 8, 10),
    "harmonic_minor": (0, 2, 3, 5, 7, 8, 11),
    "melodic_minor": (0, 2, 3, 5, 7, 9, 11),
    "dorian": (0, 2, 3, 5, 7, 9, 10),
    "phrygian": (0, 1, 3, 5, 7, 8, 10),
    "lydian": (0, 2, 4, 6, 7, 9, 11),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10),
    "locrian": (0, 1, 3, 5, 6, 8, 10),
    "major_pentatonic": (0, 2, 4, 7, 9),
    "minor_pentatonic": (0, 3, 5, 7, 10),
    "blues": (0, 3, 5, 6, 7, 10),
    "whole_tone": (0, 2, 4, 6, 8, 10),
    "diminished": (0, 2, 3, 5, 6, 8, 9, 11),
    "hirajoshi": (0, 2, 3, 7, 8),
    "in_sen": (0, 1, 5, 7, 10),
    "iwato": (0, 1, 5, 6, 10),
}

ROOT_NAMES = ("C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B")


def get_scale_pitch_classes(root: int, scale: str) -> tuple[int, ...]:
    """Return sorted MIDI pitch classes for a named scale and chromatic root."""
    if scale not in SCALE_STEPS:
        raise ValueError(f"unknown scale: {scale}")
    root = int(root)
    if not 0 <= root <= 11:
        raise ValueError("scale root must be a MIDI pitch class from 0 to 11")
    return tuple(sorted({(root + step) % 12 for step in SCALE_STEPS[scale]}))


def scale_midi_notes(
    root_midi: int,
    scale: str,
    *,
    octaves: tuple[int, ...] = (-1, 0, 1, 2),
) -> tuple[int, ...]:
    """Build an ordered MIDI-note collection around a root MIDI note."""
    root_midi = int(root_midi)
    root_pc = root_midi % 12
    pcs = get_scale_pitch_classes(root_pc, scale)
    result = {
        root_midi + (octave * 12) + ((pc - root_pc) % 12)
        for octave in octaves
        for pc in pcs
    }
    return tuple(sorted(result))


def music21_scale(root: int, scale: str) -> Any:
    """Return a music21 Scale object when the optional theory extra is installed."""
    if scale not in SCALE_STEPS:
        raise ValueError(f"unknown scale: {scale}")
    try:
        from music21 import pitch, scale as m21_scale
    except ImportError as exc:
        raise RuntimeError(
            "music21 is optional; install Reawarp with the 'theory' extra"
        ) from exc

    tonic = pitch.Pitch(midi=60 + int(root) % 12)
    constructors = {
        "major": m21_scale.MajorScale,
        "natural_minor": m21_scale.MinorScale,
        "harmonic_minor": m21_scale.HarmonicMinorScale,
        "melodic_minor": m21_scale.MelodicMinorScale,
        "dorian": m21_scale.DorianScale,
        "phrygian": m21_scale.PhrygianScale,
        "lydian": m21_scale.LydianScale,
        "mixolydian": m21_scale.MixolydianScale,
        "locrian": m21_scale.LocrianScale,
        "whole_tone": m21_scale.WholeToneScale,
        "chromatic": m21_scale.ChromaticScale,
    }
    constructor = constructors.get(scale)
    if constructor is None:
        return m21_scale.AbstractScale(tonic=tonic)
    return constructor(tonic)
