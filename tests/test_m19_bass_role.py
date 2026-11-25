from fractions import Fraction

import pytest

from reawarp.score import (
    BassRoleConfig,
    BassRolePlan,
    EqualTemperamentTuning,
    MusicalEvent,
    Score,
    SonorityBoundary,
    VoiceLeadingPlanConfig,
    plan_bass_role,
    plan_sonority_sequence,
)


def _boundaries():
    return (
        SonorityBoundary(
            "phrase-a-1", "0", "2", section_id="A", phrase_id="a",
            pitches=(48, 55, 60), bass_pitch=36, voice_count=3,
        ),
        SonorityBoundary(
            "phrase-a-2", "2", "2", section_id="A", phrase_id="a",
            pitches=(50, 57, 62), bass_pitch=38, voice_count=3,
        ),
        SonorityBoundary(
            "phrase-b-1", "4", "4", section_id="B", phrase_id="b",
            pitches=(51, 58, 63), bass_pitch=39, voice_count=3,
        ),
    )


def _kicks(*positions):
    return tuple(
        MusicalEvent(
            event_id=f"kick-{index}",
            voice_id="kick",
            onset_beats=Fraction(str(position)),
            duration_beats=Fraction(1, 4),
            kind="hit",
            velocity=0.9,
            tags=("percussion", "kick"),
        )
        for index, position in enumerate(positions)
    )


def test_pedal_is_a_sustained_independent_anchor_and_density_can_mute_it():
    plan = plan_bass_role(
        _boundaries(), EqualTemperamentTuning(),
        config=BassRoleConfig(mode="pedal", density=1, movement_range=0),
    )
    assert len(plan.events) == 1
    assert plan.events[0].pitch == 36
    assert plan.events[0].onset_beats == 0
    assert plan.events[0].duration_beats == 8
    assert plan.events[0].tags[-1] == "pedal"

    silent = plan_bass_role(
        _boundaries(), EqualTemperamentTuning(),
        config=BassRoleConfig(mode="pedal", density=0),
    )
    assert silent.events == ()


def test_kick_locked_mode_uses_actual_score_kick_events_and_requires_them():
    kicks = _kicks(0, 1, 3, 4, 6)
    plan = plan_bass_role(
        _boundaries(), EqualTemperamentTuning(),
        config=BassRoleConfig(mode="kick_locked", density=1),
        kick_events=kicks,
    )
    assert [item.onset_beats for item in plan.events] == [
        item.onset_beats for item in kicks
    ]
    assert plan.kick_event_ids == tuple(item.event_id for item in kicks)
    assert all(item.parameters["kick_event_id"] for item in plan.events)
    assert all(item.parameters["pattern"] == "kick_locked" for item in plan.events)

    with pytest.raises(ValueError, match="requires kick_events"):
        plan_bass_role(
            _boundaries(), EqualTemperamentTuning(),
            config=BassRoleConfig(mode="kick_locked"),
        )


def test_syncopated_ostinato_owns_its_grid_and_is_repeatable():
    config = BassRoleConfig(
        mode="syncopated_ostinato",
        density=1,
        steps_per_bar=8,
        syncopation=0.8,
        seed="offbeat",
        register_min=28,
        register_max=56,
        movement_range=4,
    )
    first = plan_bass_role(_boundaries(), EqualTemperamentTuning(), config=config)
    repeated = plan_bass_role(_boundaries(), EqualTemperamentTuning(), config=config)
    assert first == repeated
    assert len(first.events) > 8
    assert any(
        item.onset_beats.denominator not in {1, 2, 4}
        for item in first.events
    )
    assert all(28 <= item.pitch <= 56 for item in first.events)
    assert all(abs(item.pitch - item.parameters["pitch_anchor"]) <= 4 for item in first.events)


def test_melodic_and_ostinato_grids_continue_through_sonority_changes_inside_a_phrase():
    boundaries = (
        SonorityBoundary(
            "a", "0", "3/2", section_id="A", phrase_id="long",
            pitches=(48, 55), bass_pitch=36, voice_count=2,
        ),
        SonorityBoundary(
            "b", "3/2", "5/2", section_id="A", phrase_id="long",
            pitches=(50, 57), bass_pitch=38, voice_count=2,
        ),
    )
    melodic = plan_bass_role(
        boundaries, EqualTemperamentTuning(),
        config=BassRoleConfig(
            mode="melodic", density=1, steps_per_bar=4,
            note_duration_beats="1/4",
        ),
    )
    assert [item.onset_beats for item in melodic.events] == [
        Fraction(0), Fraction(1), Fraction(2), Fraction(3)
    ]
    assert [item.parameters["boundary_id"] for item in melodic.events] == [
        "a", "a", "b", "b"
    ]

    ostinato = plan_bass_role(
        boundaries, EqualTemperamentTuning(),
        config=BassRoleConfig(
            mode="syncopated_ostinato", density=1, steps_per_bar=4,
            syncopation=0,
        ),
    )
    assert [item.onset_beats for item in ostinato.events] == [
        Fraction(0), Fraction(1), Fraction(2), Fraction(3)
    ]


def test_independent_cycle_keeps_global_phase_across_phrase_boundaries():
    boundaries = (
        SonorityBoundary("a", "0", "4", pitches=(48, 55), bass_pitch=36, voice_count=2),
        SonorityBoundary("b", "4", "4", pitches=(50, 57), bass_pitch=38, voice_count=2),
    )
    plan = plan_bass_role(
        boundaries, EqualTemperamentTuning(),
        config=BassRoleConfig(
            mode="independent_cycle",
            cycle_beats="5/2",
            cycle_pulses=3,
            density=1,
            note_duration_beats="1/4",
        ),
    )
    onsets = [item.onset_beats for item in plan.events]
    assert Fraction(25, 6) in onsets
    assert Fraction(4, 1) not in onsets
    assert len(onsets) > 6


def test_melodic_bass_has_independent_pitch_motion_bounded_by_register_and_range():
    plan = plan_bass_role(
        _boundaries(), EqualTemperamentTuning(),
        config=BassRoleConfig(
            mode="melodic",
            density=1,
            steps_per_bar=4,
            register_min=30,
            register_max=48,
            movement_range=5,
        ),
    )
    pitches = [item.pitch for item in plan.events]
    assert len(set(pitches)) > 1
    assert all(30 <= pitch <= 48 for pitch in pitches)
    assert all(
        abs(item.pitch - item.parameters["pitch_anchor"]) <= 5
        for item in plan.events
    )


def test_punctuation_gestures_are_emitted_only_at_phrase_ends():
    plan = plan_bass_role(
        _boundaries(), EqualTemperamentTuning(),
        config=BassRoleConfig(
            mode="punctuation",
            density=1,
            note_duration_beats="1/4",
            register_min=30,
            register_max=60,
            movement_range=12,
        ),
    )
    assert len(plan.events) == 4
    assert [item.onset_beats for item in plan.events] == [
        Fraction(3), Fraction(7, 2), Fraction(7), Fraction(15, 2)
    ]
    assert {item.parameters["phrase_id"] for item in plan.events} == {"a", "b"}
    assert all(item.tags[-1] == "punctuation" for item in plan.events)


def test_kick_relationship_can_align_avoid_or_interlock():
    boundaries = (
        SonorityBoundary(
            "a", "0", "2", pitches=(48, 55), bass_pitch=36, voice_count=2,
        ),
    )
    kicks = _kicks(0, 1)
    aligned = plan_bass_role(
        boundaries, EqualTemperamentTuning(), kick_events=kicks,
        config=BassRoleConfig(
            mode="melodic", density=1, kick_relationship="align",
            kick_tolerance_beats="1/8",
        ),
    )
    assert [item.onset_beats for item in aligned.events] == [Fraction(0), Fraction(1)]

    avoided = plan_bass_role(
        boundaries, EqualTemperamentTuning(), kick_events=kicks,
        config=BassRoleConfig(
            mode="melodic", density=1, kick_relationship="avoid",
            kick_tolerance_beats="1/8",
        ),
    )
    assert all(item.onset_beats not in {Fraction(0), Fraction(1)} for item in avoided.events)

    interlocked = plan_bass_role(
        boundaries, EqualTemperamentTuning(), kick_events=kicks,
        config=BassRoleConfig(
            mode="melodic", density=1, kick_relationship="interlock",
            kick_tolerance_beats="1/8",
            interlock_offset_beats="1/4",
        ),
    )
    assert Fraction(1, 4) in [item.onset_beats for item in interlocked.events]
    assert Fraction(5, 4) in [item.onset_beats for item in interlocked.events]


def test_cadence_avoidance_can_avoid_roots_and_repeated_phrase_ends():
    boundaries = (
        SonorityBoundary(
            "a", "0", "2", section_id="A", phrase_id="one",
            pitches=(48, 55), bass_pitch=36, voice_count=2,
        ),
        SonorityBoundary(
            "b", "2", "2", section_id="A", phrase_id="two",
            pitches=(48, 55), bass_pitch=36, voice_count=2,
        ),
    )
    kicks = _kicks(1, 3)
    root_avoided = plan_bass_role(
        boundaries, EqualTemperamentTuning(), kick_events=kicks,
        config=BassRoleConfig(
            mode="kick_locked", density=1, cadence_avoidance="root",
            cadence_window_beats="1",
            movement_range=6,
        ),
    )
    assert root_avoided.events[-1].pitch != 38

    repeat_avoided = plan_bass_role(
        boundaries, EqualTemperamentTuning(), kick_events=kicks,
        config=BassRoleConfig(
            mode="kick_locked", density=1, cadence_avoidance="repeat",
            cadence_window_beats="1",
            movement_range=6,
        ),
    )
    assert repeat_avoided.events[-1].pitch != repeat_avoided.events[0].pitch


def test_bass_plan_accepts_m19_3_sequence_plan_and_reuses_its_sonorities():
    sequence_plan = plan_sonority_sequence(
        _boundaries(), EqualTemperamentTuning(),
        config=VoiceLeadingPlanConfig(seed=55),
    )
    bass_plan = plan_bass_role(
        sequence_plan, EqualTemperamentTuning(),
        config=BassRoleConfig(mode="melodic", density=1, seed=55),
    )
    assert tuple(item.sonority_id for item in bass_plan.boundaries) == tuple(
        item.sonority_id for item in sequence_plan.sonorities
    )
    assert all(item.source_id in {b.sonority_id for b in sequence_plan.boundaries}
               for item in bass_plan.events)


def test_config_and_plan_round_trip_and_score_attachment():
    config = BassRoleConfig(
        mode="syncopated_ostinato",
        density=0.8,
        register_min=26,
        register_max=58,
        movement_range=9,
        kick_relationship="independent",
        cycle_beats="7/2",
        cycle_pulses=5,
        steps_per_bar=16,
        syncopation=0.9,
        cadence_avoidance="root",
        cadence_avoidance_amount=0.5,
        seed="bass-persistence",
    )
    assert BassRoleConfig.from_dict(config.to_dict()) == config

    plan = plan_bass_role(_boundaries(), EqualTemperamentTuning(), config=config)
    assert BassRolePlan.from_dict(plan.to_dict()) == plan
    score = plan.attach_to_score(Score(title="Bass plan persistence"))
    restored_score = Score.from_dict(score.to_dict())
    restored_plan = BassRolePlan.from_score(restored_score)
    assert restored_plan == plan
    assert restored_score.bass_plan["format"] == "eli_lab_reawarp_bass_role_plan"
    assert all(event.event_id in {item.event_id for item in restored_score.events}
               for event in restored_plan.events)
    assert restored_score.duration_beats == max(
        event.end_beats for event in restored_plan.events
    )


def test_reattaching_plan_replaces_old_bass_events_without_touching_other_events():
    other = MusicalEvent(
        event_id="melody-a", voice_id="melody", onset_beats=0,
        duration_beats=1, kind="note", pitch=72,
    )
    score = Score(events=(other,))
    first = plan_bass_role(
        _boundaries(), EqualTemperamentTuning(),
        config=BassRoleConfig(mode="pedal", density=1, seed=1),
    )
    attached = first.attach_to_score(score)
    second = plan_bass_role(
        _boundaries(), EqualTemperamentTuning(),
        config=BassRoleConfig(mode="pedal", density=1, seed=2),
    )
    replaced = second.attach_to_score(attached)
    assert [item.event_id for item in replaced.events if item.voice_id == "melody"] == ["melody-a"]
    assert len([item for item in replaced.events if item.voice_id == "bass"]) == 1
    assert BassRolePlan.from_score(replaced) == second


def test_kick_provenance_is_preserved_in_score_attachment():
    kicks = _kicks(0, 2, 4)
    plan = plan_bass_role(
        _boundaries(), EqualTemperamentTuning(),
        config=BassRoleConfig(mode="kick_locked", density=1),
        kick_events=kicks,
    )
    score = plan.attach_to_score(Score(events=kicks))
    restored = BassRolePlan.from_score(Score.from_dict(score.to_dict()))
    assert restored == plan
    assert set(restored.kick_event_ids) == {item.event_id for item in kicks}

    with pytest.raises(ValueError, match="kick provenance"):
        plan.attach_to_score(Score(title="Missing kick source"))


def test_bass_planner_rejects_invalid_boundaries_modes_and_kick_relations():
    with pytest.raises(ValueError, match="unsupported bass role mode"):
        BassRoleConfig(mode="chord_roots")
    with pytest.raises(ValueError, match="kick_locked mode requires"):
        BassRoleConfig(mode="kick_locked", kick_relationship="avoid")
    with pytest.raises(ValueError, match="register_min"):
        BassRoleConfig(register_min=60, register_max=60)
    with pytest.raises(ValueError, match="requires kick hit events"):
        plan_bass_role(
            _boundaries(), EqualTemperamentTuning(),
            config=BassRoleConfig(mode="melodic", kick_relationship="align"),
            kick_events=(),
        )
    clipped = plan_bass_role(
        (
            SonorityBoundary("a", "0", "4", pitches=(48,), bass_pitch=36, voice_count=1),
            SonorityBoundary("b", "2", "4", pitches=(50,), bass_pitch=38, voice_count=1),
        ),
        EqualTemperamentTuning(),
        config=BassRoleConfig(mode="melodic", density=1, steps_per_bar=4),
    )
    assert all(
        item.onset_beats < 2 or item.parameters["boundary_id"] == "b"
        for item in clipped.events
    )
