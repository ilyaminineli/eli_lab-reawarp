from __future__ import annotations

from fractions import Fraction

import numpy as np
import pytest

from reawarp.composition.phrases import PhrasePlan, PhraseSpan as M28PhraseSpan
from reawarp.composition.transitions import (
    TRANSITION_TYPES,
    TransitionPhase,
    TransitionPlan,
    compile_transition_plans,
    transition_marker_events,
    transition_plans_from_score,
)
from reawarp.score import MusicalEvent, OrchestrationPlan, Score
from reawarp.score.orchestration_intent import PhraseSpan as M20PhraseSpan
from reawarp.score.render import ScoreRenderer


def _plan(
    *,
    transition_id: str = "bridge-a-to-b",
    transition_type: str = "motif_bridge",
    start="6",
    prepare_end="8",
    change_end="9",
    end="11",
    changed=("roles", "register"),
    preserved=("rhythm", "motif"),
):
    return TransitionPlan(
        transition_id=transition_id,
        source_phrase_id="phrase-a",
        target_phrase_id="phrase-b",
        transition_type=transition_type,
        phases=(
            TransitionPhase(
                "preparation", Fraction(start), Fraction(prepare_end),
                "Expose the outgoing phrase before changing the scene",
            ),
            TransitionPhase(
                "change", Fraction(prepare_end), Fraction(change_end),
                "Commit the target scene at one rational beat",
            ),
            TransitionPhase(
                "arrival", Fraction(change_end), Fraction(end),
                "Let the new state become legible",
            ),
        ),
        changed_dimensions=changed,
        preserved_dimensions=preserved,
        participating_roles=("melody", "texture"),
        source_state={"melody": {"register": 0}, "texture": {"active": False}},
        target_state={"melody": {"register": 12}, "texture": {"active": True}},
        seed_name="section-bridge:phrase-a:phrase-b",
        seed=2718,
        motif_bridge_id="motif-family-a",
        rationale="Carry one recognisable motif into a changed orchestral role",
    )


def _m28_score():
    events = (
        MusicalEvent(
            "phrase-a-note", "melody", Fraction(1), Fraction(1),
            kind="note", pitch=60,
        ),
        MusicalEvent(
            "phrase-b-note", "melody", Fraction(9), Fraction(1),
            kind="note", pitch=72,
        ),
    )
    score = Score(title="M30 transition fixture", events=events)
    phrases = PhrasePlan(phrases=(
        M28PhraseSpan(
            "phrase-a", 0, 8, "presentation",
            roles=("melody",), event_ids=("phrase-a-note",),
        ),
        M28PhraseSpan(
            "phrase-b", 8, 16, "arrival",
            roles=("melody", "texture"), event_ids=("phrase-b-note",),
        ),
    ))
    return phrases.attach_to_score(score)


def test_transition_plan_roundtrip_preserves_exact_rational_phase_boundaries():
    source = _plan(start="19/3", prepare_end="8", change_end="25/3", end="12")
    restored = TransitionPlan.from_dict(source.to_dict())

    assert restored == source
    assert restored.start_beats == Fraction(19, 3)
    assert restored.change_beat == Fraction(8)
    assert restored.end_beats == Fraction(12)
    assert restored.duration_beats == Fraction(17, 3)
    assert restored.to_dict() == source.to_dict()


def test_transition_phase_order_contiguity_and_dimensions_are_validated():
    broken = _plan().to_dict()
    broken["phases"] = [
        {"phase": "preparation", "start_beats": "6", "end_beats": "8"},
        {"phase": "change", "start_beats": "17/2", "end_beats": "9"},
        {"phase": "arrival", "start_beats": "9", "end_beats": "11"},
    ]
    with pytest.raises(ValueError, match="meet at one exact beat"):
        TransitionPlan.from_dict(broken)

    with pytest.raises(ValueError, match="cannot be both changed and preserved"):
        _plan(changed=("rhythm",), preserved=("rhythm",))

    with pytest.raises(ValueError, match="unsupported transition dimensions"):
        _plan(changed=("hidden_quality_score",))

    with pytest.raises(ValueError, match="requires preparation, change and arrival"):
        TransitionPlan(
            transition_id="missing-arrival",
            source_phrase_id="phrase-a",
            target_phrase_id="phrase-b",
            transition_type="subtractive",
            phases=(
                TransitionPhase("preparation", 6, 8),
                TransitionPhase("change", 8, 9),
            ),
            changed_dimensions=("roles",),
            preserved_dimensions=(),
            participating_roles=("kick",),
            source_state={},
            target_state={},
            seed_name="test",
            seed=1,
        )


def test_transition_catalogue_covers_the_roadmap_types():
    assert TRANSITION_TYPES == {
        "additive", "subtractive", "filtered_registral",
        "rhythmic_displacement", "metric_reinterpretation",
        "fragmentation", "overlap", "silence", "false_return",
        "motif_bridge",
    }
    from dataclasses import replace

    with pytest.raises(ValueError, match="motif_bridge_id"):
        replace(_plan(transition_type="motif_bridge"), motif_bridge_id=None)


def test_compilation_attaches_four_markers_and_one_atomic_scene_change():
    score = _m28_score()
    base_events = score.events
    plan = _plan()

    compiled = compile_transition_plans(score, (plan,))
    assert score.events == base_events
    assert compiled.metadata["m28_phrase_plan"] == score.metadata["m28_phrase_plan"]
    assert compiled.metadata["m30_transition_plans"] == [plan.to_dict()]
    assert transition_plans_from_score(compiled) == (plan,)

    markers = [
        event for event in compiled.events
        if event.parameters.get("m30_transition_marker", {}).get("transition_id")
        == plan.transition_id
    ]
    assert [item.parameters["m30_transition_marker"]["phase"] for item in markers] == [
        "preparation", "change", "arrival", "complete",
    ]
    assert [item.onset_beats for item in markers] == [
        Fraction(6), Fraction(8), Fraction(9), Fraction(11),
    ]
    commits = [
        item for item in markers
        if item.parameters["m30_transition_marker"]["atomic_scene_commit"]
    ]
    assert len(commits) == 1
    assert commits[0].onset_beats == Fraction(8)
    assert commits[0].parameters["m30_transition_marker"]["scene_state"] == {
        "melody": {"register": 12}, "texture": {"active": True},
    }
    assert commits[0].parameters["m30_transition_marker"]["participating_roles"] == [
        "melody", "texture",
    ]


def test_compilation_is_idempotent_and_replacement_owns_only_its_markers():
    score = _m28_score()
    original_other_event = score.events[0]
    plan = _plan()
    first = compile_transition_plans(score, (plan,))
    second = compile_transition_plans(first, (plan,))

    assert second.to_dict() == first.to_dict()
    assert sum(
        event.parameters.get("m30_transition_marker", {}).get("transition_id")
        == plan.transition_id
        for event in second.events
    ) == 4

    changed = _plan(
        transition_id=plan.transition_id,
        transition_type="subtractive",
        start="5",
        prepare_end="8",
        change_end="10",
        end="12",
        changed=("density",),
        preserved=("motif", "meter"),
    )
    replaced = compile_transition_plans(first, (changed,))
    assert transition_plans_from_score(replaced) == (changed,)
    assert replaced.events[0] == original_other_event
    assert sum(
        event.parameters.get("m30_transition_marker", {}).get("transition_id")
        == plan.transition_id
        for event in replaced.events
    ) == 4

    with pytest.raises(ValueError, match="transition plan already exists"):
        compile_transition_plans(first, (changed,), replace_existing=False)


def test_compilation_rejects_missing_phrases_and_out_of_phrase_spans():
    score = _m28_score()
    missing = TransitionPlan.from_dict({
        **_plan().to_dict(),
        "source_phrase_id": "not-a-phrase",
    })
    with pytest.raises(ValueError, match="unknown source phrase"):
        compile_transition_plans(score, (missing,))

    outside = _plan(start="4", prepare_end="8", change_end="9", end="17")
    with pytest.raises(ValueError, match="arrival must extend into its target phrase"):
        compile_transition_plans(score, (outside,))


def test_m20_orchestration_phrase_model_remains_a_supported_compile_source():
    plan = OrchestrationPlan(
        phrases=(
            M20PhraseSpan("phrase-a", 0, 8, "establishment"),
            M20PhraseSpan("phrase-b", 8, 16, "arrival"),
        ),
    )
    score = Score(title="M20 transition fallback", orchestration_plan=plan.to_dict())

    compiled = compile_transition_plans(score, (_plan(),))
    assert transition_plans_from_score(compiled)[0].transition_id == "bridge-a-to-b"
    assert len([event for event in compiled.events if event.kind == "marker"]) == 4


def test_transition_markers_are_silent_in_score_renderer():
    compiled = compile_transition_plans(_m28_score(), (_plan(),))
    markers_only = Score(
        title="M30 marker-only render",
        tempo_map=compiled.tempo_map,
        meter_map=compiled.meter_map,
        events=tuple(event for event in compiled.events if event.kind == "marker"),
        metadata=compiled.metadata,
    )
    rendered = ScoreRenderer().render(markers_only, 100, frame_count=1200)

    assert rendered.schedule
    assert not rendered.stems
    np.testing.assert_array_equal(
        rendered.render_master(), np.zeros((1200, 2), dtype=np.float32)
    )


def test_score_roundtrip_keeps_transition_contract_and_markers(tmp_path):
    compiled = compile_transition_plans(_m28_score(), (_plan(),))
    path = compiled.save(tmp_path / "m30-transition-score.json")
    restored = Score.load(path)

    assert restored.to_dict() == compiled.to_dict()
    assert transition_plans_from_score(restored) == (_plan(),)
