import numpy as np

from reawarp import GenerationConfig
from reawarp.generators.melody import build_melody_events
from reawarp.mathematics.theory import SCALE_STEPS, get_scale_pitch_classes, scale_midi_notes


def test_pitch_collections_are_root_transposed_and_valid():
    c_major = get_scale_pitch_classes(0, "major")
    a_minor = get_scale_pitch_classes(9, "natural_minor")
    assert c_major == (0, 2, 4, 5, 7, 9, 11)
    assert a_minor == (0, 2, 4, 5, 7, 9, 11)
    assert len(SCALE_STEPS) >= 15
    assert all(0 <= note <= 127 for note in scale_midi_notes(60, "dorian"))


def test_melody_events_obey_selected_pitch_field():
    config = GenerationConfig(
        duration=12.0,
        bpm=120.0,
        seed="theory-pitch-test",
        melody_scale="hirajoshi",
        melody_root=9,
    )
    events = build_melody_events(config, np.random.default_rng(11))
    allowed = set(get_scale_pitch_classes(9, "hirajoshi"))
    assert events
    assert all(event.midi_note % 12 in allowed for event in events)
