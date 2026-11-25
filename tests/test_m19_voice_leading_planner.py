import pytest

from reawarp.score import (
    Score,
    SonorityBoundary,
    SonoritySequencePlan,
    VoiceLeadingConstraints,
    VoiceLeadingPlanConfig,
    VoiceLeadingPreferences,
    VoiceLeadingWeights,
    VoiceRoleTarget,
    EqualTemperamentTuning,
    plan_sonority_sequence,
)


def _fixed_boundaries():
    return (
        SonorityBoundary(
            "intro-a", "0", "4", section_id="intro", phrase_id="a",
            pitches=(48, 55, 60), voice_count=3,
        ),
        SonorityBoundary(
            "intro-b", "4", "4", section_id="intro", phrase_id="b",
            pitches=(50, 55, 62), voice_count=3,
        ),
        SonorityBoundary(
            "break-a", "8", "4", section_id="break", phrase_id="a",
            pitches=(51, 57, 64), voice_count=3,
        ),
    )


def test_sequence_plan_is_deterministic_and_tracks_phrase_boundaries():
    config = VoiceLeadingPlanConfig(
        voice_ids=("bass", "mid", "lead"),
        seed="sequence-seed",
    )
    first = plan_sonority_sequence(
        _fixed_boundaries(), EqualTemperamentTuning(), config=config,
    )
    repeated = plan_sonority_sequence(
        _fixed_boundaries(), EqualTemperamentTuning(), config=config,
    )

    assert first == repeated
    assert first.voice_ids == ("bass", "mid", "lead")
    assert len(first.voicings) == 3
    assert len(first.transitions) == 2
    assert first.transitions[1].source_section_id == "intro"
    assert first.transitions[1].target_section_id == "break"
    assert first.transitions[1].source_phrase_id == "b"
    assert first.transitions[1].target_phrase_id == "a"
    assert first.sonorities[0].transform_parameters["section_id"] == "intro"
    assert first.sonorities[0].transform_parameters["phrase_id"] == "a"


def test_sequence_planner_generates_missing_sonorities_from_boundaries():
    boundaries = (
        SonorityBoundary(
            "generated-a", "0", "4", section_id="verse", phrase_id="p1",
            voice_count=3, minimum_pitch=48, maximum_pitch=66,
            minimum_spacing=3, maximum_spacing=10, temperature=0,
        ),
        SonorityBoundary(
            "generated-b", "4", "4", section_id="verse", phrase_id="p2",
            voice_count=3, minimum_pitch=48, maximum_pitch=66,
            minimum_spacing=3, maximum_spacing=10, temperature=0,
        ),
    )
    plan = plan_sonority_sequence(
        boundaries, EqualTemperamentTuning(),
        config=VoiceLeadingPlanConfig(seed=918),
    )
    assert all(len(item.pitches) == 3 for item in plan.sonorities)
    assert plan.sonorities[0].transform == "generated"
    assert plan.sonorities[0].transform_parameters["generation_seed"] != 918
    assert all(
        3 <= right - left <= 10
        for item in plan.sonorities
        for left, right in zip(item.pitches, item.pitches[1:])
    )


def test_motion_style_preferences_are_inspectable_and_independent():
    contrary = plan_sonority_sequence(
        (
            SonorityBoundary("a", "0", "1", pitches=(48, 60, 72), voice_count=3),
            SonorityBoundary("b", "1", "1", pitches=(55, 65, 70), voice_count=3),
        ),
        EqualTemperamentTuning(),
        config=VoiceLeadingPlanConfig(
            preferences=VoiceLeadingPreferences(
                motion_styles=("contrary",), crossing="neutral",
            ),
            constraints=VoiceLeadingConstraints(allow_voice_crossing=False),
        ),
    )
    assert "contrary" in contrary.transitions[0].motion_types
    assert dict(contrary.transitions[0].cost_components)["contrary_preference"] > 0

    oblique = plan_sonority_sequence(
        (
            SonorityBoundary("c", "0", "1", pitches=(48, 60, 72), voice_count=3),
            SonorityBoundary("d", "1", "1", pitches=(48, 62, 76), voice_count=3),
        ),
        EqualTemperamentTuning(),
        config=VoiceLeadingPlanConfig(
            preferences=VoiceLeadingPreferences(
                motion_styles=("oblique",), retain_common_tones=True,
            ),
        ),
    )
    assert "oblique" in oblique.transitions[0].motion_types
    assert dict(oblique.transitions[0].cost_components)["common_tone"] < 0


def test_parallel_preference_rewards_similar_motion():
    plan = plan_sonority_sequence(
        (
            SonorityBoundary("a", "0", "1", pitches=(48, 60, 72), voice_count=3),
            SonorityBoundary("b", "1", "1", pitches=(54, 66, 78), voice_count=3),
        ),
        EqualTemperamentTuning(),
        config=VoiceLeadingPlanConfig(
            weights=VoiceLeadingWeights(
                motion=0, leap=0, common_tone_bonus=0, parallel_motion=3,
            ),
            preferences=VoiceLeadingPreferences(
                motion_styles=("parallel",), crossing="neutral",
                retain_common_tones=False,
            ),
            constraints=VoiceLeadingConstraints(allow_voice_crossing=False),
        ),
    )
    transition = plan.transitions[0]
    assert "parallel" in transition.motion_types
    assert dict(transition.cost_components)["parallel_preference"] == pytest.approx(0)


def test_deliberate_crossing_can_be_preferred_and_hard_limited():
    crossing_plan = plan_sonority_sequence(
        (
            SonorityBoundary("a", "0", "1", pitches=(48, 60), voice_count=2),
            SonorityBoundary("b", "1", "1", pitches=(50, 62), voice_count=2),
        ),
        EqualTemperamentTuning(),
        config=VoiceLeadingPlanConfig(
            weights=VoiceLeadingWeights(
                motion=0, leap=0, common_tone_bonus=0,
                crossing=0, deliberate_crossing_bonus=20,
            ),
            preferences=VoiceLeadingPreferences(crossing="prefer"),
        ),
    )
    assert crossing_plan.transitions[0].crossed_pairs == (("voice-1", "voice-2"),)
    assert dict(crossing_plan.transitions[0].cost_components)["deliberate_crossing"] < 0

    with pytest.raises(ValueError, match="conflicts"):
        no_crossing = VoiceLeadingPlanConfig(
            preferences=VoiceLeadingPreferences(crossing="prefer"),
            constraints=VoiceLeadingConstraints(allow_voice_crossing=False),
        )
        plan_sonority_sequence(
            (
                SonorityBoundary("c", "0", "1", pitches=(48, 60), voice_count=2),
                SonorityBoundary("d", "1", "1", pitches=(50, 62), voice_count=2),
            ),
            EqualTemperamentTuning(),
            config=no_crossing,
        )


def test_role_targets_and_hard_registers_are_explicit():
    boundaries = (
        SonorityBoundary(
            "a", "0", "1", pitches=(48, 60), voice_count=2,
            voice_roles=(
                VoiceRoleTarget(
                    "bass", "bass", preferred_pitch=48, register_min=40, register_max=52,
                ),
                VoiceRoleTarget(
                    "lead", "lead", preferred_pitch=72, register_min=68, register_max=80,
                ),
            ),
        ),
        SonorityBoundary(
            "b", "1", "1", pitches=(50, 72), voice_count=2,
            voice_roles=(
                VoiceRoleTarget(
                    "bass", "bass", preferred_pitch=50, register_min=40, register_max=54,
                ),
                VoiceRoleTarget(
                    "lead", "lead", preferred_pitch=74, register_min=68, register_max=82,
                ),
            ),
        ),
    )
    plan = plan_sonority_sequence(
        boundaries, EqualTemperamentTuning(),
        config=VoiceLeadingPlanConfig(voice_ids=("bass", "lead")),
    )
    assert plan.voicings[0] == (48.0, 60.0)
    assert plan.voicings[1][0] <= 54
    assert plan.voicings[1][1] >= 68
    assert dict(plan.transitions[0].cost_components)["target_role"] >= 0

    impossible = (
        SonorityBoundary(
            "x", "0", "1", pitches=(60, 72), voice_count=2,
            voice_roles=(
                VoiceRoleTarget("bass", "bass", register_min=36, register_max=48),
                VoiceRoleTarget("lead", "lead", register_min=72, register_max=84),
            ),
        ),
    )
    with pytest.raises(ValueError, match="hard role-register"):
        plan_sonority_sequence(
            impossible, EqualTemperamentTuning(),
            config=VoiceLeadingPlanConfig(
                voice_ids=("bass", "lead"),
                constraints=VoiceLeadingConstraints(hard_role_registers=True),
            ),
        )


def test_hard_leap_constraint_and_intentional_high_friction_are_supported():
    boundaries = (
        SonorityBoundary("a", "0", "1", pitches=(48, 60), voice_count=2),
        SonorityBoundary("b", "1", "1", pitches=(50, 62), voice_count=2),
    )
    friction = plan_sonority_sequence(
        boundaries, EqualTemperamentTuning(),
        config=VoiceLeadingPlanConfig(
            weights=VoiceLeadingWeights(
                motion=4, leap=2, common_tone_bonus=0,
            ),
            constraints=VoiceLeadingConstraints(minimum_motion=4),
            preferences=VoiceLeadingPreferences(retain_common_tones=False),
        ),
    )
    assert friction.transitions[0].total_cost >= 16

    impossible = VoiceLeadingPlanConfig(
        constraints=VoiceLeadingConstraints(maximum_leap=1),
    )
    with pytest.raises(ValueError, match="hard constraints"):
        plan_sonority_sequence(
            boundaries, EqualTemperamentTuning(), config=impossible,
        )


def test_config_plan_and_score_round_trip():
    config = VoiceLeadingPlanConfig(
        weights=VoiceLeadingWeights(
            motion=1.2, leap=0.4, register_crossing=3.0, target_role=2.0,
            contrary_motion=0.8, oblique_motion=1.1, parallel_motion=0.7,
        ),
        constraints=VoiceLeadingConstraints(
            maximum_leap=9, minimum_motion=1, allow_voice_crossing=True,
            maximum_voice_crossings=1, minimum_common_tones=0,
            hard_role_registers=False,
        ),
        preferences=VoiceLeadingPreferences(
            motion_styles=("parallel", "contrary"), crossing="prefer",
        ),
        voice_ids=("low", "high"),
        beam_width=8,
        seed="round-trip",
    )
    assert VoiceLeadingPlanConfig.from_dict(config.to_dict()) == config

    boundaries = (
        SonorityBoundary("a", "0", "2", section_id="intro", phrase_id="one",
                         pitches=(48, 60), voice_count=2),
        SonorityBoundary("b", "2", "2", section_id="body", phrase_id="two",
                         pitches=(50, 62), voice_count=2),
    )
    plan = plan_sonority_sequence(boundaries, EqualTemperamentTuning(), config=config)
    assert SonoritySequencePlan.from_dict(plan.to_dict()) == plan

    score = plan.attach_to_score(Score(title="M19.3 plan"))
    restored_score = Score.from_dict(score.to_dict())
    restored_plan = SonoritySequencePlan.from_score(restored_score)
    assert restored_plan == plan
    assert restored_score.sonority_plan["format"] == "eli_lab_reawarp_sonority_sequence_plan"


def test_boundary_order_and_voice_count_are_validated():
    with pytest.raises(ValueError, match="in strictly increasing"):
        plan_sonority_sequence(
            (
                SonorityBoundary("a", "1", "1", pitches=(48, 60), voice_count=2),
                SonorityBoundary("b", "0", "1", pitches=(50, 62), voice_count=2),
            ),
            EqualTemperamentTuning(),
        )
    with pytest.raises(ValueError, match="same voice_count"):
        plan_sonority_sequence(
            (
                SonorityBoundary("a", "0", "1", pitches=(48, 60), voice_count=2),
                SonorityBoundary("b", "1", "1", pitches=(50, 62, 74), voice_count=3),
            ),
            EqualTemperamentTuning(),
        )
