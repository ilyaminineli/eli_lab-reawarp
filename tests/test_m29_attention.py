from __future__ import annotations

from fractions import Fraction

import numpy as np
import pytest

from reawarp.score import (
    AttentionSpan, MusicalEvent, OrchestrationPlan, Score,
    inspect_attention_conflicts, inspect_attention_handoffs,
)
from reawarp.score.attention import (
    attention_conflict_id, build_attention_translation_check,
    estimate_attention_descriptors, record_attention_review,
)


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
