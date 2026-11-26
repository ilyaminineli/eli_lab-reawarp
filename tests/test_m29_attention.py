from __future__ import annotations

from fractions import Fraction

import numpy as np
import pytest

from reawarp.score import (
    AttentionSpan, MusicalEvent, OrchestrationPlan, Score,
    inspect_attention_conflicts, inspect_attention_handoffs,
)
from reawarp.score.attention import (
    attention_conflict_id, apply_attention_gesture,
    apply_attention_gesture_to_event, build_attention_translation_check,
    estimate_attention_descriptors, record_attention_review,
    remove_attention_gesture,
)
from reawarp.score.render import ScoreRenderer


def test_attention_descriptors_are_versioned_and_legacy_plans_remain_readable():
    span = AttentionSpan(
        role="melody", start_beats=0, end_beats=7,
        depth="foreground", attention_role="motif",
        onset_density=0.8, transient_strength=0.4, sustain=0.6,
        spatial_position=-0.25, prominence=0.9,
        intentional_overlap_id="merge-01",
    )
    plan = OrchestrationPlan(attention=(span,), title="M29 descriptors")
    restored = OrchestrationPlan.from_dict(plan.to_dict())
    assert restored.attention == (span,)

    legacy = plan.to_dict()
    legacy["schema_version"] = 2
    legacy_span = dict(legacy["attention"][0])
    for key in (
        "attention_role", "onset_density", "transient_strength", "sustain",
        "spatial_position", "prominence", "intentional_overlap_id",
    ):
        legacy_span.pop(key)
    legacy["attention"] = [legacy_span]
    upgraded = OrchestrationPlan.from_dict(legacy)
    assert upgraded.attention[0].attention_role == "unassigned"
    assert upgraded.attention[0].onset_density is None

    with pytest.raises(ValueError, match="spatial_position"):
        AttentionSpan(
            role="melody", start_beats=0, end_beats=4, depth="foreground",
            spatial_position=1.2,
        )
    with pytest.raises(ValueError, match="semantic attention role"):
        AttentionSpan(
            role="melody", start_beats=0, end_beats=4, depth="foreground",
            attention_role="lead-is-the-only-role",
        )


def test_attention_inspector_explains_register_spectrum_transient_and_stereo_evidence():
    plan = OrchestrationPlan(attention=(
        AttentionSpan(
            role="melody", start_beats=0, end_beats=6, depth="foreground",
            attention_role="motif", register_low=48, register_high=76,
            spectral_band="mid", transient_strength=0.85, spatial_position=0.0,
        ),
        AttentionSpan(
            role="break", start_beats=2, end_beats=8, depth="midground",
            attention_role="counter_rhythm", register_low=64, register_high=84,
            spectral_band="mid", transient_strength=0.9, spatial_position=0.1,
        ),
    ))
    warnings = inspect_attention_conflicts(plan)
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning["kind"] == "attention_competition"
    assert warning["roles"] == ["melody", "break"]
    assert warning["start_beats"] == "2"
    assert warning["end_beats"] == "6"
    assert warning["register_overlap"] is True
    assert warning["spectral_overlap"] is True
    assert warning["transient_competition"] is True
    assert warning["stereo_proximity"] is True
    assert warning["heuristic_only"] is True
    assert "overlapping register ranges" in warning["evidence"]
    assert "shared spectral zone: mid" in warning["evidence"]

    intentional = OrchestrationPlan(attention=tuple(
        __import__("dataclasses").replace(item, intentional_overlap_id="designed-fusion")
        for item in plan.attention
    ))
    assert inspect_attention_conflicts(intentional) == ()


def test_attention_handoff_is_reported_only_when_sides_meet_exactly():
    valid = OrchestrationPlan(attention=(
        AttentionSpan("melody", 0, Fraction(13, 2), "foreground", handoff_id="h1"),
        AttentionSpan("texture", Fraction(13, 2), 12, "foreground", handoff_id="h1"),
    ))
    warnings = inspect_attention_handoffs(valid)
    assert warnings == ({
        "kind": "atomic_handoff", "handoff_id": "h1",
        "roles": ["melody", "texture"], "boundary_beats": "13/2",
        "valid": True, "heuristic_only": False,
    },)

    incomplete = OrchestrationPlan(attention=(
        AttentionSpan("melody", 0, 4, "foreground", handoff_id="h2"),
        AttentionSpan("texture", 5, 8, "foreground", handoff_id="h2"),
    ))
    warning, = inspect_attention_handoffs(incomplete)
    assert warning["kind"] == "non_atomic_handoff"
    assert "exact beat boundary" in warning["reason"]


def test_score_event_descriptor_estimates_are_symbolic_and_preserve_authored_values():
    events = (
        MusicalEvent(
            "melody-1", "melody", 0, Fraction(1, 2), kind="note",
            pitch=60, velocity=0.7, parameters={"pan": 0.6},
        ),
        MusicalEvent(
            "melody-2", "melody", 1, Fraction(1, 2), kind="note",
            pitch=64, velocity=0.9,
        ),
        MusicalEvent(
            "kick-1", "kick", Fraction(1, 2), Fraction(1, 8),
            kind="hit", velocity=0.8,
        ),
    )
    spans = (
        AttentionSpan("melody", 0, 2, "foreground", attention_role="motif"),
        AttentionSpan("kick", 0, 2, "background", attention_role="anchor"),
    )
    estimated = estimate_attention_descriptors(events, spans)
    melody, kick = estimated
    assert melody.onset_density == pytest.approx(1.0)
    assert melody.register_low == 60
    assert melody.register_high == 64
    assert melody.sustain == pytest.approx(0.5)
    assert melody.prominence == pytest.approx(0.8)
    assert melody.spatial_position == pytest.approx(0.6)
    assert kick.transient_strength == pytest.approx(0.8)

    authored = AttentionSpan(
        "melody", 0, 2, "foreground", attention_role="motif",
        prominence=0.3, register_low=36,
    )
    retained, = estimate_attention_descriptors(events, (authored,), fill_missing=True)
    assert retained.prominence == pytest.approx(0.3)
    assert retained.register_low == 36


def test_human_review_is_persisted_with_conflict_and_plan_provenance():
    plan = OrchestrationPlan(attention=(
        AttentionSpan("melody", 0, 4, "foreground", spectral_band="mid"),
        AttentionSpan("break", 1, 3, "background", spectral_band="mid"),
    ))
    score = Score(orchestration_plan=plan.to_dict())
    warning, = inspect_attention_conflicts(plan)
    first_id = attention_conflict_id(warning)
    second_id = attention_conflict_id(dict(warning))
    assert first_id == second_id

    updated = record_attention_review(
        score, warning, disposition="masked",
        notes="The masking is deliberate; it fuses the two sources.",
    )
    assert "m29_attention_reviews" not in score.metadata
    record = updated.metadata["m29_attention_reviews"][first_id]
    assert record["disposition"] == "masked"
    assert record["notes"].startswith("The masking is deliberate")
    assert record["plan_fingerprint"]
    with pytest.raises(ValueError, match="disposition"):
        record_attention_review(score, warning, disposition="perfect")



def test_attention_gestures_are_score_native_reversible_and_rational_span_scoped():
    source = Score(
        events=(
            MusicalEvent(
                "melody-note", "melody", Fraction(1, 4), 1, kind="note",
                pitch=60, velocity=0.8,
                parameters={"gate_duration_beats": "1/2", "pan": 0.6},
            ),
            MusicalEvent(
                "melody-outside", "melody", 3, 1, kind="note",
                pitch=67, velocity=0.8,
            ),
            MusicalEvent(
                "kick-anchor", "kick", 0, Fraction(1, 8),
                kind="hit", velocity=0.9, tags=("anchor",),
            ),
        ),
        metadata={"keep": True},
    )
    focused = apply_attention_gesture(
        source, role="melody", start_beats=Fraction(1, 4),
        end_beats=Fraction(9, 4), action="focus",
        register_shift_semitones=3,
    )
    assert source.metadata == {"keep": True}
    source_by_id = {event.event_id: event for event in source.events}
    assert source_by_id["melody-note"].pitch == 60
    records = focused.metadata["m29_attention_gestures"]
    assert len(records) == 1
    assert records[0]["start_beats"] == "1/4"
    assert records[0]["end_beats"] == "9/4"
    assert records[0]["register_shift_semitones"] == 3

    from reawarp.score.attention import apply_attention_gesture_to_event

    transformed = apply_attention_gesture_to_event(
        source_by_id["melody-note"], records
    )
    assert transformed.pitch == pytest.approx(63)
    assert transformed.articulation == "legato"
    assert Fraction(transformed.parameters["gate_duration_beats"]) == Fraction(27, 50)
    assert transformed.parameters["pan"] == pytest.approx(0.6)
    assert transformed.parameters["m29_pan_factor"] == pytest.approx(0.45)
    assert transformed.parameters["m29_spatial_width_factor"] == pytest.approx(0.82)
    assert transformed.parameters["m29_attention_action"] == "focus"

    outside = apply_attention_gesture_to_event(source_by_id["melody-outside"], records)
    assert outside is source_by_id["melody-outside"]
    protected = apply_attention_gesture_to_event(
        source_by_id["kick-anchor"],
        apply_attention_gesture(
            source, role="kick", start_beats=0, end_beats=2,
            action="recede",
        ).metadata["m29_attention_gestures"],
    )
    assert protected is not None
    assert protected.voice_id == "kick"

    restored = remove_attention_gesture(
        focused, role="melody", start_beats="1/4", end_beats="9/4"
    )
    assert "m29_attention_gestures" not in restored.metadata
    assert restored.events == source.events
    assert restored.metadata["keep"] is True
    with pytest.raises(ValueError, match="focus or recede"):
        apply_attention_gesture(
            source, role="melody", start_beats=0, end_beats=2,
            action="boost",
        )
    with pytest.raises(ValueError, match="within -24..24"):
        apply_attention_gesture(
            source, role="melody", start_beats=0, end_beats=2,
            action="focus", register_shift_semitones=25,
        )


def test_attention_recede_event_thinning_is_deterministic_and_never_drops_anchor():
    source = Score(events=tuple(
        MusicalEvent(
            f"hat-{index:02d}", "hat", Fraction(index, 4), Fraction(1, 8),
            kind="hit", velocity=0.5,
        )
        for index in range(40)
    ) + (
        MusicalEvent(
            "kick-anchor", "kick", 0, Fraction(1, 8),
            kind="hit", velocity=0.9, tags=("anchor",),
        ),
    ))
    score = apply_attention_gesture(
        source, role="hat", start_beats=0, end_beats=12, action="recede"
    )
    gestures = score.metadata["m29_attention_gestures"]
    outcomes = [
        apply_attention_gesture_to_event(event, gestures)
        for event in source.events
    ]
    repeated = [
        apply_attention_gesture_to_event(event, gestures)
        for event in source.events
    ]
    assert [
        None if event is None else event.event_id for event in outcomes
    ] == [
        None if event is None else event.event_id for event in repeated
    ]
    hat_results = [
        outcome for event, outcome in zip(source.events, outcomes)
        if event.voice_id == "hat"
    ]
    assert any(outcome is None for outcome in hat_results)
    assert any(outcome is not None for outcome in hat_results)
    kick_gesture = apply_attention_gesture(
        source, role="kick", start_beats=0, end_beats=2, action="recede"
    )
    kick = next(event for event in source.events if event.event_id == "kick-anchor")
    protected_kick = apply_attention_gesture_to_event(
        kick, kick_gesture.metadata["m29_attention_gestures"]
    )
    assert protected_kick is not None
    assert protected_kick.voice_id == "kick"


def test_score_renderer_executes_attention_gesture_on_render_copy_only():
    source = Score(events=(
        MusicalEvent(
            "lead-note", "melody", 0, 1, kind="note",
            pitch=60, velocity=0.8,
        ),
    ), metadata={"sample_rate": 8_000})
    focused = apply_attention_gesture(
        source, role="melody", start_beats=0, end_beats=2,
        action="focus", register_shift_semitones=2,
    )

    def stereo_voice(scheduled, sample_rate, controls):
        del sample_rate, controls
        return np.tile(
            np.asarray([[1.0, -1.0]], dtype=np.float32),
            (scheduled.duration_frames, 1),
        )

    result = ScoreRenderer().render(
        focused, 8_000, frame_count=8_000,
        voice_renderers={"melody": stereo_voice},
    )
    assert result.schedule[0].event.pitch == pytest.approx(62)
    assert result.schedule[0].event.parameters["m29_attention_gesture_id"]
    assert np.max(np.abs(result.stems["melody"])) == pytest.approx(0.8 * 0.82)
    source_note = next(event for event in source.events if event.event_id == "lead-note")
    assert source_note.pitch == 60
    assert "m29_attention_gestures" not in source.metadata


def test_translation_checks_are_non_destructive_audition_copies():
    source = np.asarray([
        [0.25, -0.25],
        [0.5, 0.5],
        [-0.5, 0.5],
    ], dtype=np.float32)
    original = source.copy()

    mono = build_attention_translation_check(source, "mono")
    assert mono.shape == source.shape
    np.testing.assert_allclose(mono[:, 0], [0.0, 0.5, 0.0])
    np.testing.assert_array_equal(mono[:, 0], mono[:, 1])

    quiet = build_attention_translation_check(source, "low_volume")
    np.testing.assert_allclose(quiet, source * 0.1, atol=1e-7)
    np.testing.assert_array_equal(source, original)
    assert not np.shares_memory(source, mono)
    assert not np.shares_memory(source, quiet)

    mono_copy = build_attention_translation_check(np.asarray([0.1, -0.1]), "mono")
    assert mono_copy.shape == (2, 2)

    with pytest.raises(ValueError, match="unsupported"):
        build_attention_translation_check(source, "stereo")
