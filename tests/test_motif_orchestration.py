from dataclasses import replace

import numpy as np
import pytest

from reawarp import GenerationConfig
from reawarp.composition.director import build_composition_plan
from reawarp.composition.motifs import (
    build_motif_plan,
    build_motif_role_accents,
    render_motif_events,
    transform_motif,
)
from reawarp.composition.orchestration import (
    ROLE_NAMES,
    build_section_orchestration_plan,
    build_transition_plan,
    render_role_envelope,
    role_activity_at_time,
)
from reawarp.composition.phrase import build_phrase_directives
from reawarp.generators.melody import build_melody_events


def _build(config):
    composition = build_composition_plan(
        duration_seconds=config.duration,
        bpm=config.bpm,
        seed=config.seed,
        structure=config.structure,
        energy=config.composition_energy,
        variation=config.composition_variation,
        flow=config.composition_flow,
        pattern_family=config.pattern_family,
        pattern_relationship=config.pattern_relationship,
    )
    phrases = build_phrase_directives(composition.sections)
    melody = build_melody_events(config, np.random.default_rng(271))
    return composition, phrases, melody


def test_motif_identity_transformations_and_return_are_deterministic():
    config = GenerationConfig(
        duration=60.0,
        bpm=120.0,
        seed="m15-motif-anchor",
        structure="uplift_drop_return",
        complexity=0.38,
    )
    composition, phrases, melody = _build(config)

    first = build_motif_plan(
        melody, composition, phrases, bpm=config.bpm, seed=config.seed
    )
    second = build_motif_plan(
        melody, composition, phrases, bpm=config.bpm, seed=config.seed
    )

    assert first is not None and second is not None
    assert first.to_dict() == second.to_dict()
    assert first.anchor.motif_id.startswith("motif-")
    assert len(first.anchor.notes) >= 2
    assert all(instance.motif_id == first.anchor.motif_id for instance in first.instances)

    returned = [
        instance for instance in first.instances
        if instance.function == "return"
    ]
    assert returned
    assert all(instance.operation == "return" for instance in returned)
    assert all(instance.notes == first.anchor.notes for instance in returned)

    augmented, augmented_steps = transform_motif(first.anchor, "augmentation")
    diminished, diminished_steps = transform_motif(first.anchor, "diminution")
    inverted, inverted_steps = transform_motif(first.anchor, "inversion")
    fragmented, fragmented_steps = transform_motif(first.anchor, "fragmentation")

    assert augmented_steps == first.anchor.phrase_steps * 2
    assert all(note.step % 2 == 0 for note in augmented)
    assert diminished_steps == max(8, first.anchor.phrase_steps // 2)
    assert inverted_steps == first.anchor.phrase_steps
    assert [
        note.midi_note for note in inverted
    ] == [
        2 * first.anchor.pitch_center - note.midi_note
        for note in first.anchor.notes
    ]
    assert fragmented_steps == first.anchor.phrase_steps
    assert 1 <= len(fragmented) <= len(first.anchor.notes)
    assert transform_motif(first.anchor, "return")[0] == first.anchor.notes

    events = render_motif_events(
        first, bpm=config.bpm, duration_seconds=config.duration
    )
    assert events
    assert all(event.motif_id == first.anchor.motif_id for event in events)
    for event in events:
        section = next(
            item for item in composition.sections
            if item.start_bar * 16 <= event.step < item.end_bar * 16
        )
        assert section.start_bar * 16 <= event.step < section.end_bar * 16


def test_same_motif_drives_quiet_hat_shadows_and_call_response_snare():
    config = GenerationConfig(
        duration=60.0,
        bpm=120.0,
        seed="m15-cross-role",
        structure="free_jazz_episodic",
        complexity=0.42,
    )
    composition, phrases, melody = _build(config)
    motif = build_motif_plan(
        melody, composition, phrases, bpm=config.bpm, seed=config.seed
    )
    assert motif is not None

    accents = build_motif_role_accents(
        motif, bpm=config.bpm, duration_seconds=config.duration
    )
    assert accents
    assert any(item.role == "hat" and item.motif_relation == "shadow" for item in accents)
    assert any(item.role == "snare" and item.motif_relation == "response" for item in accents)
    assert all(item.motif_id == motif.anchor.motif_id for item in accents)
    assert all(
        0 <= item.step < int(np.ceil(config.duration / config.sixteenth_seconds))
        for item in accents
    )


def test_role_axes_are_independent_and_transition_windows_are_bar_bounded():
    config = GenerationConfig(
        duration=60.0,
        bpm=120.0,
        seed="m15-role-axes",
        structure="uplift_drop_return",
    )
    composition, phrases, melody = _build(config)
    motif = build_motif_plan(
        melody, composition, phrases, bpm=config.bpm, seed=config.seed
    )
    baseline = build_section_orchestration_plan(
        composition, phrases, config, motif
    )
    altered = replace(
        config,
        rhythmic_syncopation=1.0,
        melodic_activity=0.12,
        tonal_brightness=0.9,
        spatial_intent=0.8,
    )
    changed = build_section_orchestration_plan(
        composition, phrases, altered, motif
    )

    assert len(baseline) == len(composition.sections)
    assert all(
        {role.role for role in section.roles} == set(ROLE_NAMES)
        for section in baseline
    )
    for left, right in zip(baseline, changed, strict=True):
        assert right.role("hat").activity > left.role("hat").activity
        assert right.role("melody").activity < left.role("melody").activity
        assert right.role("kick").activity == pytest.approx(left.role("kick").activity)
        assert right.role("snare").activity == pytest.approx(left.role("snare").activity)
        assert right.role("melody").brightness != pytest.approx(
            left.role("melody").brightness
        )
        assert right.role("ambience").space_intent != pytest.approx(
            left.role("ambience").space_intent
        )

    transitions = build_transition_plan(composition, phrases)
    assert transitions
    for transition in transitions:
        source = composition.sections[transition.source_section]
        assert transition.start_bar >= source.start_bar
        assert transition.boundary_bar == source.end_bar
        assert transition.start_seconds >= source.start_seconds
        assert transition.end_seconds == pytest.approx(source.end_seconds)
        assert transition.end_seconds > transition.start_seconds

    envelope = render_role_envelope(
        "ambience", config.frame_count, config.sample_rate,
        composition, baseline, transitions,
    )
    assert envelope.shape == (config.frame_count,)
    assert np.isfinite(envelope).all()
    assert np.all((envelope >= 0.0) & (envelope <= 1.35))
    active_transition = transitions[0]
    sample_time = (active_transition.start_seconds + active_transition.end_seconds) / 2.0
    assert 0.0 <= role_activity_at_time(
        "ambience", sample_time, composition, baseline, transitions
    ) <= 1.35


def test_invalid_motif_operation_is_rejected():
    config = GenerationConfig(
        duration=24.0, bpm=120.0, seed="m15-invalid-operation"
    )
    composition, phrases, melody = _build(config)
    motif = build_motif_plan(
        melody, composition, phrases, bpm=config.bpm, seed=config.seed
    )
    assert motif is not None
    with pytest.raises(ValueError, match="unknown motif transformation"):
        transform_motif(motif.anchor, "randomise_everything")
