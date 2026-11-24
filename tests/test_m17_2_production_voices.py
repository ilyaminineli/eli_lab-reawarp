from fractions import Fraction

import numpy as np
import pytest

from reawarp import (
    AutomationLane, AutomationPoint, GenerationConfig, MusicalEvent, ReawarpEngine, Score,
    build_production_voice_renderers,
)
from reawarp.generators.melody import MelodyEvent
from reawarp.generators.percussion import PercussionEvent
from reawarp.score.planner import score_from_planner_events


def _melody_event():
    return MelodyEvent(
        step=4, time=0.001, frequency=440.0, midi_note=69, duration=0.24,
        velocity=0.73, pan=-0.2, source_x=0.15, source_y=-0.25,
        motif_id='test-motif', motif_transform='retrograde', phrase_index=2,
    )


@pytest.mark.parametrize(
    'palette',
    ['subtractive', 'hybrid', 'fm', 'additive', 'modal', 'inharmonic', 'granular', 'physical'],
)
def test_production_melody_voice_families_render_from_scheduled_score(palette):
    config = GenerationConfig(
        bpm=137.0, duration=5.0, sample_rate=22_050, seed='m17-2-melody',
        synth_palette=palette, include_melody=True, include_texture=False,
        include_ambience=False,
    )
    score = score_from_planner_events(
        melody=[_melody_event()], bpm=config.bpm, seed_streams={'melody_pattern': 99},
    )
    event = score.events[0]
    gate = Fraction(event.parameters['gate_duration_beats'])
    assert event.duration_beats > gate
    assert event.parameters['release_seconds'] == pytest.approx(0.28)

    first = ReawarpEngine().render_score(score, config=config)
    second = ReawarpEngine().render_score(score, config=config)
    assert first.frame_count == second.frame_count
    assert first.stems['melody'].shape == (first.frame_count, 2)
    np.testing.assert_array_equal(first.stems['melody'], second.stems['melody'])
    assert np.isfinite(first.stems['melody']).all()
    assert np.max(np.abs(first.stems['melody'])) > 1e-6


def test_percussion_and_synthetic_break_voices_use_specialist_scheduled_adapters():
    bpm = 120.0
    percussion = {
        'kick': [PercussionEvent('kick', 0, 99.0, 0.84, 0.0, 'synth_kick', 'test')],
        'snare': [PercussionEvent('snare', 4, -5.0, 0.62, -0.1, 'noise_snare', 'test')],
        'hat': [PercussionEvent('hat', 8, 1.0, 0.31, 0.2, 'metal_noise', 'test')],
        'break': [
            PercussionEvent('break', 12, 0.0, 0.58, 0.0, 'kick', 'test'),
            PercussionEvent('break', 13, 0.0, 0.46, -0.2, 'snare', 'test'),
            PercussionEvent('break', 14, 0.0, 0.25, 0.2, 'hat', 'test'),
        ],
    }
    score = score_from_planner_events(
        percussion=percussion, bpm=bpm,
        seed_streams={
            'kick_pattern': 11, 'snare_pattern': 12, 'hat_pattern': 13, 'break_pattern': 14,
        },
    )
    config = GenerationConfig(
        bpm=bpm, duration=5.0, sample_rate=22_050, seed='m17-2-drums',
        include_melody=False, include_texture=False, include_ambience=False,
        percussion_synthesis='extended', percussion_source_mode='synth',
    )
    renderers = build_production_voice_renderers(config)
    assert {'kick', 'snare', 'hat', 'break'} <= set(renderers)
    result = ReawarpEngine().render_score(score, config=config)
    assert {'kick', 'snare', 'hat', 'break'} <= set(result.stems)
    for stem in result.stems.values():
        assert stem.shape == (result.frame_count, 2)
        assert np.isfinite(stem).all()
        assert np.max(np.abs(stem)) > 1e-6

    # The deliberately incorrect legacy `time` values above must not affect score scheduling.
    kick = next(item for item in result.schedule if item.event.voice_id == 'kick')
    snare = next(item for item in result.schedule if item.event.voice_id == 'snare')
    assert kick.start_frame == 0
    assert snare.start_frame == 11_025


def test_score_voice_automation_uses_shared_control_bus_and_changes_audio():
    config = GenerationConfig(
        bpm=120.0, duration=5.0, sample_rate=22_050, seed='m17-2-controls',
        synth_palette='subtractive', include_melody=True, include_texture=False,
        include_ambience=False,
    )
    base = score_from_planner_events(melody=[_melody_event()], bpm=config.bpm)
    event = base.events[0]
    automated = Score(
        title='M17.2 automated voice',
        tempo_map=base.tempo_map,
        meter_map=base.meter_map,
        events=base.events,
        automation=(
            AutomationLane(
                'synth.cutoff',
                (AutomationPoint(Fraction(0), 900.0), AutomationPoint(Fraction(8), 240.0)),
                unit='Hz', time_basis='beats', interpolation='linear',
                minimum=20.0, maximum=18_000.0,
            ),
            AutomationLane(
                'synth.gain',
                (AutomationPoint(Fraction(0), 0.45),),
                unit='normalized', time_basis='beats', interpolation='step',
                minimum=0.0, maximum=1.0,
            ),
        ),
    )
    dry = ReawarpEngine().render_score(base, config=config).stems['melody']
    wet = ReawarpEngine().render_score(automated, config=config).stems['melody']
    assert dry.shape == wet.shape
    assert np.isfinite(wet).all()
    assert not np.array_equal(dry, wet)


def test_explicit_voice_renderers_cannot_be_combined_with_production_config():
    config = GenerationConfig(
        duration=5.0, include_melody=False, include_texture=False, include_ambience=False,
    )
    score = Score(events=(
        MusicalEvent(
            event_id='hit', voice_id='kick', onset_beats=0, duration_beats=Fraction(1, 2),
            kind='hit',
        ),
    ))
    with pytest.raises(ValueError, match='either production config or explicit voice_renderers'):
        ReawarpEngine().render_score(
            score, config=config, voice_renderers={'kick': lambda *args: np.zeros(1)},
        )
