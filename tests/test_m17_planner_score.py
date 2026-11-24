from fractions import Fraction

import numpy as np
import pytest

from reawarp.config import GenerationConfig
from reawarp.core.random_streams import RandomStreams
from reawarp.generators.melody import build_melody_events
from reawarp.generators.percussion import build_percussion_events
from reawarp.composition.director import build_composition_plan
from reawarp.score.planner import (
    melody_to_score_events,
    percussion_to_score_events,
    score_from_planner_events,
    score_to_legacy_grid_events,
)


def _generated():
    config = GenerationConfig(
        duration=8.0, bpm=137.0, seed=20261124,
        include_melody=True, include_texture=False, include_ambience=False,
        pattern_follow_structure=True,
    )
    composition = build_composition_plan(
        duration_seconds=config.duration, bpm=config.bpm, seed=config.seed,
        structure=config.structure, energy=config.composition_energy,
        variation=config.composition_variation, flow=config.composition_flow,
        pattern_family=config.pattern_family, pattern_relationship=config.pattern_relationship,
    )
    streams = RandomStreams(config.seed)
    drum_rngs = {
        role: streams.get(f'{role}_pattern')
        for role in ('kick', 'snare', 'hat', 'break')
    }
    drums = build_percussion_events(config, drum_rngs, composition)
    melody = build_melody_events(config, streams.get('melody_pattern'))
    seeds = {
        f'{role}_pattern': streams.seed_for(f'{role}_pattern')
        for role in ('kick', 'snare', 'hat', 'break', 'melody')
    }
    return config, drums, melody, seeds


def test_percussion_score_adapter_uses_step_not_legacy_seconds():
    _config, drums, _melody, seeds = _generated()
    direct = percussion_to_score_events(drums, seed_streams=seeds)
    assert direct
    for event in direct:
        assert event.onset_beats == Fraction(event.parameters['step'], 4)
        assert event.onset_beats.denominator in (1, 2, 4)
        assert event.parameters['planner'] == 'percussion'
        assert event.seed is not None


def test_melody_score_adapter_retains_pitch_motif_and_grid_onsets():
    config, _drums, melody, seeds = _generated()
    direct = melody_to_score_events(
        melody, bpm=config.bpm, seed=seeds['melody_pattern']
    )
    assert direct
    for event in direct:
        assert event.kind == 'note'
        assert event.pitch is not None and event.frequency_hz is not None
        assert event.onset_beats * 4 == int(event.onset_beats * 4)
        assert event.parameters['planner'] == 'melody'
        assert event.seed == seeds['melody_pattern']


def test_planner_score_is_deterministic_and_compatibility_view_uses_score_clock():
    config, drums, melody, seeds = _generated()
    first = score_from_planner_events(
        percussion=drums, melody=melody, bpm=config.bpm, seed_streams=seeds
    )
    second = score_from_planner_events(
        percussion=drums, melody=melody, bpm=config.bpm, seed_streams=seeds
    )
    assert first.to_dict() == second.to_dict()
    assert first.metadata['score_origin'] == 'canonical_planner_events'
    legacy = score_to_legacy_grid_events(first)
    assert {'kick', 'snare', 'hat', 'break', 'melody'} <= set(legacy)
    for voice, records in legacy.items():
        matching = [event for event in first.events if event.voice_id == voice]
        assert len(records) == len(matching)
        for record, event in zip(records, matching):
            assert record['step'] == event.onset_beats * 4
            assert record['time'] == pytest.approx(
                float(event.onset_beats) * 60.0 / config.bpm
            )


def test_score_projection_refuses_non_grid_events():
    from reawarp.score import MusicalEvent, Score
    score = Score(events=(
        MusicalEvent(
            event_id='off-grid', voice_id='melody',
            onset_beats=Fraction(1, 3), duration_beats=Fraction(1, 2),
            kind='note', pitch=60,
        ),
    ))
    try:
        score_to_legacy_grid_events(score)
    except ValueError as exc:
        assert 'non-sixteenth' in str(exc)
    else:
        raise AssertionError('off-grid event should not be projected')
