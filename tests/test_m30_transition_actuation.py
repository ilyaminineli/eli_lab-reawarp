from __future__ import annotations

from fractions import Fraction

import pytest

from reawarp.composition.phrases import PhrasePlan, PhraseSpan as M28PhraseSpan
from reawarp.composition.transitions import (
    TransitionPhase,
    TransitionPlan,
    compile_transition_plans,
    transition_actuation_at,
)
from reawarp.score import MusicalEvent, Score


def _score():
    source = MusicalEvent(
        "a-note", "lead", Fraction(1), Fraction(1), kind="note", pitch=60,
    )
    target = MusicalEvent(
        "b-note", "lead", Fraction(9), Fraction(1), kind="note", pitch=72,
    )
    score = Score(title="M30 actuation fixture", events=(source, target))
    phrases = PhrasePlan(phrases=(
        M28PhraseSpan(
            "phrase-a", 0, 8, "presentation",
            roles=("lead",), event_ids=("a-note",),
        ),
        M28PhraseSpan(
            "phrase-b", 8, 16, "arrival",
            roles=("lead",), event_ids=("b-note",),
        ),
    ))
    return phrases.attach_to_score(score)


def _plan():
    return TransitionPlan(
        transition_id="scene-a-to-b",
        source_phrase_id="phrase-a",
        target_phrase_id="phrase-b",
        transition_type="additive",
        phases=(
            TransitionPhase("preparation", 6, 8, "Prepare the new layer"),
            TransitionPhase("change", 8, 9, "Commit the complete scene"),
            TransitionPhase("arrival", 9, 11, "Establish the new state"),
        ),
        changed_dimensions=("roles", "density"),
        preserved_dimensions=("motif",),
        participating_roles=("lead", "texture"),
        source_state={"texture": {"active": False}, "lead": {"register": 0}},
        target_state={"texture": {"active": True}, "lead": {"register": 12}},
        seed_name="scene-a-to-b",
        seed=42,
    )


def test_transition_actuation_resolves_exact_phase_and_atomic_scene_boundary():
    score = compile_transition_plans(_score(), (_plan(),))

    assert transition_actuation_at(score, 5) == ()

    preparation = transition_actuation_at(score, Fraction(7))[0]
    assert preparation.phase == "preparation"
    assert preparation.atomic_scene_commit is False
    assert preparation.scene_state == _plan().source_state

    commit = transition_actuation_at(score, Fraction(8))[0]
    assert commit.phase == "change"
    assert commit.atomic_scene_commit is True
    assert commit.scene_state == _plan().target_state
    assert commit.participating_roles == ("lead", "texture")

    arrival = transition_actuation_at(score, Fraction(10))[0]
    assert arrival.phase == "arrival"
    assert arrival.atomic_scene_commit is False
    assert arrival.scene_state == _plan().target_state

    complete = transition_actuation_at(score, Fraction(11))[0]
    assert complete.phase == "complete"
    assert complete.scene_state == _plan().target_state


def test_transition_actuation_rejects_invalid_score_and_negative_beats():
    with pytest.raises(TypeError, match="Score"):
        transition_actuation_at(object(), 1)
    with pytest.raises(ValueError, match="non-negative"):
        transition_actuation_at(_score(), -1)
