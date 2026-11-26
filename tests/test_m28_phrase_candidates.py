from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest

from reawarp.composition.phrases import (
    MotifFamily,
    MotifIdentity,
    PhraseBoundary,
    PhrasePlan,
    PhraseSpan,
    branch_phrase_candidate,
    build_phrase_candidate_batch,
    continue_evolving,
    freeze_phrase_candidate,
    phrase_context_events,
    restore_phrase_base,
)
from reawarp.score import MusicalEvent, Score, TempoMap


def _score():
    events = (
        MusicalEvent(
            event_id="a-1", voice_id="lead", onset_beats=Fraction(0),
            duration_beats=Fraction(1, 2), kind="note", pitch=60,
        ),
        MusicalEvent(
            event_id="a-2", voice_id="lead", onset_beats=Fraction(3, 2),
            duration_beats=Fraction(1, 4), kind="note", pitch=64,
        ),
        MusicalEvent(
            event_id="b-1", voice_id="kick", onset_beats=Fraction(11, 2),
            duration_beats=Fraction(1, 4), kind="hit",
        ),
    )
    score = Score(title="M28 irregular phrase", tempo_map=TempoMap.constant(120), events=events)
    family = MotifFamily(
        family_id="motif-A",
        versions=(MotifIdentity("motif-A"),),
    )
    plan = PhrasePlan(phrases=(
        PhraseSpan(
            phrase_id="phrase-A", start_beats=Fraction(0), end_beats=Fraction(5, 2),
            function="presentation", state="open", motif_ids=("motif-A",),
            roles=("lead",), internal_cycles=(Fraction(5, 4),),
            boundaries=(
                PhraseBoundary(Fraction(0), "phrase_start"),
                PhraseBoundary(Fraction(5, 2), "phrase_end"),
            ),
            event_ids=("a-1", "a-2"),
        ),
        PhraseSpan(
            phrase_id="phrase-silence", start_beats=Fraction(5, 2),
            end_beats=Fraction(5), function="suspension", state="fragmentary",
        ),
        PhraseSpan(
            phrase_id="phrase-B", start_beats=Fraction(5), end_beats=Fraction(8),
            function="response", state="closed", roles=("kick",), event_ids=("b-1",),
        ),
    ), motif_families=(family,))
    return plan.attach_to_score(score)


def test_phrase_spans_support_irregular_rational_lengths_and_custom_functions():
    score = _score()
    plan = PhrasePlan.from_score(score)
    phrase = plan.phrases[0]
    assert phrase.start_beats == Fraction(0)
    assert phrase.end_beats == Fraction(5, 2)
    assert phrase.duration_beats == Fraction(5, 2)
    assert phrase.internal_cycles == (Fraction(5, 4),)
    assert phrase.state == "open"
    custom = PhraseSpan(
        phrase_id="custom", start_beats=Fraction(8), end_beats=Fraction(25, 3),
        function="ritual", custom_function="ritual",
    )
    assert custom.function == "ritual"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"start_beats": Fraction(-1), "end_beats": Fraction(1)},
        {"start_beats": Fraction(1), "end_beats": Fraction(1)},
        {"start_beats": Fraction(0), "end_beats": Fraction(2), "state": "infinite"},
    ],
)
def test_phrase_span_rejects_invalid_time_and_state(kwargs):
    base = {
        "phrase_id": "bad", "start_beats": Fraction(0),
        "end_beats": Fraction(1), "function": "presentation",
    }
    base.update(kwargs)
    with pytest.raises(ValueError):
        PhraseSpan(**base)


def test_silent_or_omitted_phrase_is_valid_and_has_no_implicit_events():
    plan = PhrasePlan.from_score(_score())
    silence = next(item for item in plan.phrases if item.phrase_id == "phrase-silence")
    assert silence.is_silent
    assert silence.event_ids == ()


def test_phrase_plan_validates_event_identity_and_round_trips_score(tmp_path):
    score = _score()
    plan = PhrasePlan.from_score(score)
    restored_plan = PhrasePlan.from_dict(plan.to_dict())
    assert restored_plan == plan

    path = score.save(tmp_path / "phrase-score.json")
    restored_score = Score.load(path)
    assert PhrasePlan.from_score(restored_score) == plan
    assert restored_score.metadata["m28_phrase_plan_fingerprint"] == score.metadata[
        "m28_phrase_plan_fingerprint"
    ]

    broken = replace(
        score,
        metadata={
            **score.metadata,
            "m28_phrase_plan": {
                **score.metadata["m28_phrase_plan"],
                "phrases": [
                    {
                        **score.metadata["m28_phrase_plan"]["phrases"][0],
                        "event_ids": ["missing-event"],
                    },
                    *score.metadata["m28_phrase_plan"]["phrases"][1:],
                ],
            },
        },
    )
    with pytest.raises(ValueError, match="missing Score event"):
        PhrasePlan.from_score(broken)


def test_candidate_batches_are_deterministic_and_leave_base_untouched():
    score = _score()
    before = score.to_dict()
    kwargs = {
        "count": 5, "root_seed": "m28-deterministic",
        "variation_ladder": "moderate", "batch_id": "stable-batch",
    }
    first = build_phrase_candidate_batch(score, "phrase-A", **kwargs)
    second = build_phrase_candidate_batch(score, "phrase-A", **kwargs)
    assert [item.candidate_id for item in first.candidates] == [
        item.candidate_id for item in second.candidates
    ]
    assert [item.seed for item in first.candidates] == [
        item.seed for item in second.candidates
    ]
    assert [item.operation for item in first.candidates] == [
        item.operation for item in second.candidates
    ]
    for left, right in zip(first.candidates, second.candidates, strict=True):
        assert left.candidate_score.to_dict() == right.candidate_score.to_dict()
        assert set(left.transformation.changed_dimensions).isdisjoint(
            left.transformation.preserved_dimensions
        )
        assert set(left.transformation.changed_dimensions) | set(
            left.transformation.preserved_dimensions
        ) == {
            "pitch", "rhythm", "timbre", "envelope", "register", "sample", "spatial", "silence",
        }
    assert score.to_dict() == before


def test_no_change_is_an_explicit_valid_candidate_for_repetition():
    score = _score()
    batch = build_phrase_candidate_batch(
        score, "phrase-A", count=1, root_seed=1,
        operations=("no_change",), batch_id="repeat-without-change",
    )
    candidate = batch.candidates[0]
    assert candidate.operation == "no_change"
    assert candidate.transformation.changed_dimensions == ()
    assert len(candidate.transformation.preserved_dimensions) == 8
    assert [
        event.to_dict() for event in candidate.candidate_score.events
    ] == [
        event.to_dict() for event in score.events
    ]


def test_candidate_context_lists_predecessor_and_successor_without_rendering():
    score = _score()
    contexts = phrase_context_events(score, "phrase-silence")
    assert contexts["solo"] == ()
    assert [event.event_id for event in contexts["after_predecessor"]] == ["a-1", "a-2"]
    assert [event.event_id for event in contexts["before_successor"]] == ["b-1"]


def test_freeze_blocks_continue_branch_preserves_unrelated_events_and_restore_is_reversible():
    score = _score()
    batch = build_phrase_candidate_batch(
        score, "phrase-A", count=1, root_seed=42,
        operations=("transposition",), batch_id="freeze-me",
    )
    candidate = batch.candidates[0]
    frozen, record = freeze_phrase_candidate(
        score, candidate, selection_note="The contour remains recognisable.",
    )
    assert record["candidate_id"] == candidate.candidate_id
    assert record["selection_note"] == "The contour remains recognisable."
    assert frozen.metadata["m28_phrase_freezes"]["phrase-A"]["frozen_event_ids"] == list(
        candidate.target_event_ids
    )
    with pytest.raises(ValueError, match="frozen"):
        continue_evolving(frozen, "phrase-A", root_seed=9)

    unrelated_before = {
        event.event_id: event.to_dict()
        for event in frozen.events if event.event_id not in set(candidate.target_event_ids)
    }
    branch = branch_phrase_candidate(
        frozen, "phrase-A", branch_seed="branch-seed", count=2,
    )
    assert len(branch.candidates) == 2
    assert all(
        item.base_score_fingerprint == branch.base_score_fingerprint
        for item in branch.candidates
    )
    unrelated_after = {
        event.event_id: event.to_dict()
        for event in frozen.events if event.event_id not in set(candidate.target_event_ids)
    }
    assert unrelated_before == unrelated_after

    edited_metadata = {**frozen.metadata, "unrelated_edit": {"kept": True}}
    edited = replace(frozen, metadata=edited_metadata)
    restored = restore_phrase_base(edited, "phrase-A")
    assert "phrase-A" not in restored.metadata["m28_phrase_freezes"]
    assert restored.metadata["unrelated_edit"] == {"kept": True}
    for event_id in candidate.source_event_ids:
        frozen_event = next(item for item in score.events if item.event_id == event_id)
        restored_event = next(item for item in restored.events if item.event_id == event_id)
        assert restored_event.to_dict() == frozen_event.to_dict()


def test_freezing_rejects_stale_candidate_and_second_freeze():
    score = _score()
    candidate = build_phrase_candidate_batch(
        score, "phrase-A", count=1, root_seed=2,
        operations=("no_change",), batch_id="stale-check",
    ).candidates[0]
    changed = replace(score, title="New revision")
    with pytest.raises(ValueError, match="stale"):
        freeze_phrase_candidate(changed, candidate)

    frozen, _ = freeze_phrase_candidate(score, candidate)
    with pytest.raises(ValueError, match="already frozen"):
        freeze_phrase_candidate(frozen, candidate)


def test_project_archive_round_trip_retains_phrase_plan_and_freeze(tmp_path):
    from reawarp import GenerationConfig, ReawarpEngine, ReawarpProject

    config = GenerationConfig(
        duration=5.0, sample_rate=22_050, seed="m28-archive",
        include_melody=False, include_texture=False, include_ambience=False,
    )
    project = ReawarpEngine().generate(config)
    score = project.to_score()
    end = max((event.end_beats for event in score.events), default=Fraction(0))
    if end <= 0:
        pytest.skip("generation produced no event-backed phrase material")
    ids = tuple(event.event_id for event in score.events if event.end_beats <= end)
    if not ids:
        pytest.skip("generation produced no phrase events")
    phrase = PhraseSpan(
        phrase_id="archive-phrase", start_beats=Fraction(0), end_beats=end,
        function="presentation", state="closed", event_ids=ids,
    )
    attached = PhrasePlan((phrase,)).attach_to_score(score)
    candidate = build_phrase_candidate_batch(
        attached, "archive-phrase", count=1, root_seed=22,
        operations=("no_change",), batch_id="archive-candidate",
    ).candidates[0]
    frozen, _ = freeze_phrase_candidate(attached, candidate, selection_note="archive")
    project = replace(project, score=frozen)
    output = project.export(tmp_path / "m28-project")
    reopened = ReawarpProject.load(output)
    assert PhrasePlan.from_score(reopened.to_score()) == PhrasePlan.from_score(frozen)
    assert reopened.to_score().metadata["m28_phrase_freezes"] == frozen.metadata[
        "m28_phrase_freezes"
    ]


def test_candidate_score_phrase_references_follow_transformed_event_ids():
    from reawarp.composition.phrases import phrase_context_events

    score = _score()
    candidate = build_phrase_candidate_batch(
        score, "phrase-A", count=1, root_seed=41,
        operations=("fragmentation",), batch_id="candidate-plan-binding",
    ).candidates[0]
    plan = PhrasePlan.from_score(candidate.candidate_score)
    phrase = next(item for item in plan.phrases if item.phrase_id == "phrase-A")
    assert phrase.event_ids == candidate.target_event_ids
    assert tuple(
        event.event_id for event in phrase_context_events(
            candidate.candidate_score, "phrase-A"
        )["solo"]
    ) == candidate.target_event_ids


def test_branch_candidate_can_be_frozen_without_losing_original_restore_point():
    score = _score()
    first = build_phrase_candidate_batch(
        score, "phrase-A", count=1, root_seed=51,
        operations=("transposition",), batch_id="first-freeze",
    ).candidates[0]
    frozen, first_record = freeze_phrase_candidate(score, first)
    branch = branch_phrase_candidate(
        frozen, "phrase-A", branch_seed="second-generation", count=1,
    )
    second = branch.candidates[0]
    advanced, second_record = freeze_phrase_candidate(
        frozen, second, selection_note="Second branch selected.",
    )
    assert second_record["parent_candidate_id"] == first.candidate_id
    assert second_record["source_events"] == first_record["source_events"]
    assert second_record["root_base_score_fingerprint"] == first.base_score_fingerprint
    restored = restore_phrase_base(advanced, "phrase-A")
    for event_id in first.source_event_ids:
        original = next(item for item in score.events if item.event_id == event_id)
        actual = next(item for item in restored.events if item.event_id == event_id)
        assert actual.to_dict() == original.to_dict()
