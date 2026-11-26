from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest

from reawarp.composition.phrases import (
    MOTIF_DIMENSIONS,
    MotifFamily,
    MotifIdentity,
    MotifTransformation,
    PhrasePlan,
    PhraseSpan,
)
from reawarp.composition.section_memory import (
    MemoryExpectation,
    ReturnOpportunity,
    SectionMemory,
    SectionState,
    TrajectorySummary,
    attach_section_memory,
    section_memory_from_score,
)
from reawarp.score import MusicalEvent, Score, TempoMap


def _score() -> Score:
    events = (
        MusicalEvent(
            event_id="a-note", voice_id="lead", onset_beats=Fraction(1),
            duration_beats=Fraction(1, 4), kind="note", pitch=60,
        ),
        MusicalEvent(
            event_id="b-note", voice_id="drums", onset_beats=Fraction(5),
            duration_beats=Fraction(1, 4), kind="hit",
        ),
        MusicalEvent(
            event_id="c-note", voice_id="lead", onset_beats=Fraction(9),
            duration_beats=Fraction(1, 4), kind="note", pitch=64,
        ),
    )
    score = Score(
        title="M30 section memory",
        tempo_map=TempoMap.constant(120),
        events=events,
    )
    phrases = PhrasePlan(
        phrases=(
            PhraseSpan(
                phrase_id="phrase-A", start_beats=Fraction(0), end_beats=Fraction(4),
                function="presentation", parent_section_id="section-A",
                motif_ids=("motif-A",), roles=("lead",), event_ids=("a-note",),
            ),
            PhraseSpan(
                phrase_id="phrase-B", start_beats=Fraction(4), end_beats=Fraction(8),
                function="departure", parent_section_id="section-B",
                motif_ids=("motif-B",), roles=("drums",), event_ids=("b-note",),
            ),
            PhraseSpan(
                phrase_id="phrase-C", start_beats=Fraction(8), end_beats=Fraction(12),
                function="reprise", parent_section_id="section-C",
                motif_ids=("motif-A",), roles=("lead",), event_ids=("c-note",),
            ),
        ),
        motif_families=(
            MotifFamily("motif-A", (MotifIdentity("motif-A"),)),
            MotifFamily("motif-B", (MotifIdentity("motif-B"),)),
        ),
    )
    return phrases.attach_to_score(score)


def _transform() -> MotifTransformation:
    return MotifTransformation(
        transformation_id="motif-A-v1-to-v2",
        motif_id="motif-A",
        source_version=1,
        target_version=2,
        operation="transposition",
        changed_dimensions=("pitch",),
        preserved_dimensions=tuple(
            item for item in MOTIF_DIMENSIONS if item != "pitch"
        ),
        amount={"semitones": 3},
    )


def _states() -> tuple[SectionState, SectionState, SectionState]:
    first = SectionState(
        section_id="section-A",
        start_beats=Fraction(0),
        end_beats=Fraction(4),
        phrase_ids=("phrase-A",),
        motif_ids=("motif-A",),
        roles=("lead",),
        transformations=(_transform(),),
        energy=TrajectorySummary.from_values((0.2, 0.4, 0.5, 0.3)),
        density=TrajectorySummary.from_values((0.1, 0.2, 0.25)),
        unresolved_expectations=(
            MemoryExpectation(
                expectation_id="expect-A-return",
                kind="motif_return",
                subject_id="motif-A",
                opened_at_beats=Fraction(7, 2),
                description="Leave the anchor recognisable but unresolved.",
            ),
        ),
        return_opportunities=(
            ReturnOpportunity(
                motif_id="motif-A",
                source_section_id="section-A",
                reason="The anchor is established but can return in altered form.",
                source_version=2,
                transformation_ids=("motif-A-v1-to-v2",),
                allowed_transformations=("transposition", "fragmentation"),
            ),
        ),
    )
    second = SectionState(
        section_id="section-B",
        start_beats=Fraction(4),
        end_beats=Fraction(8),
        phrase_ids=("phrase-B",),
        motif_ids=("motif-B",),
        roles=("drums",),
        resolved_expectation_ids=("expect-A-return",),
        return_opportunities=(
            ReturnOpportunity(
                motif_id="motif-B",
                source_section_id="section-B",
                reason="The counter-material may recur as a response.",
            ),
        ),
    )
    third = SectionState(
        section_id="section-C",
        start_beats=Fraction(8),
        end_beats=Fraction(12),
        phrase_ids=("phrase-C",),
        motif_ids=("motif-A",),
        roles=("lead",),
    )
    return first, second, third


def test_section_state_and_memory_round_trip_with_exact_beats():
    first, second, _ = _states()
    memory = SectionMemory(states=(first, second), capacity=4)
    restored = SectionMemory.from_dict(memory.to_dict())

    assert restored == memory
    assert restored.states[0].start_beats == Fraction(0)
    assert restored.states[0].end_beats == Fraction(4)
    assert restored.states[0].energy.sample_count == 4
    assert restored.states[0].transformations == (_transform(),)


def test_memory_is_bounded_and_evicts_the_oldest_state_deterministically():
    first, second, third = _states()
    memory = SectionMemory(capacity=2)
    memory = memory.append(first).append(second).append(third)

    assert [item.section_id for item in memory.states] == ["section-B", "section-C"]
    assert memory.latest == third
    assert memory.previous_section("section-C") == second
    assert memory.recurrence_count("motif-A") == 1
    assert memory.recurrence_count("motif-A", within=1) == 1


def test_append_is_idempotent_and_only_the_latest_section_can_be_revised():
    first, second, _ = _states()
    memory = SectionMemory(capacity=4).append(first).append(second)
    assert memory.append(second) is memory

    revised = replace(second, revision=2, rationale="A human review refined this summary.")
    updated = memory.append(revised)
    assert updated.latest == revised
    assert len(updated.states) == 2

    with pytest.raises(ValueError, match="higher revision"):
        memory.append(replace(second, rationale="Same revision, different content."))
    with pytest.raises(ValueError, match="newest section"):
        memory.append(replace(first, revision=2))


def test_memory_rejects_overlap_backwards_time_and_over_capacity_payloads():
    first, second, _ = _states()
    with pytest.raises(ValueError, match="chronological"):
        SectionMemory(states=(second, first), capacity=4)
    with pytest.raises(ValueError, match="follow"):
        SectionMemory(capacity=4).append(second).append(
            replace(first, section_id="earlier")
        )
    with pytest.raises(ValueError, match="more states"):
        SectionMemory(states=(first, second), capacity=1)
    with pytest.raises(ValueError, match="capacity"):
        SectionMemory(capacity=65)


def test_queries_find_last_motif_role_recurrence_and_transformation_lineage():
    first, second, third = _states()
    memory = SectionMemory(states=(first, second, third), capacity=4)

    assert memory.last_used_motif("motif-A") == third
    assert memory.last_used_role("drums") == second
    assert memory.recurrence_count("motif-A") == 2
    assert memory.transformation_history("motif-A") == (_transform(),)
    assert memory.previous_section("section-B") == first
    assert memory.previous_section("section-A") is None
    assert memory.previous_section() == third
    with pytest.raises(KeyError, match="unknown section"):
        memory.previous_section("missing")


def test_expectations_are_resolved_by_later_sections_and_returns_close_on_recall():
    first, second, third = _states()
    before_recall = SectionMemory(states=(first, second), capacity=4)

    assert before_recall.unresolved_expectations == ()
    assert {item.motif_id for item in before_recall.return_opportunities} == {
        "motif-A", "motif-B"
    }

    after_recall = before_recall.append(third)
    assert after_recall.last_used_motif("motif-A") == third
    assert {item.motif_id for item in after_recall.return_opportunities} == {"motif-B"}


def test_score_attachment_round_trip_and_event_preservation(tmp_path):
    score = _score()
    first, second, _ = _states()
    memory = SectionMemory(states=(first, second), capacity=3)
    attached = attach_section_memory(score, memory)

    assert [item.to_dict() for item in attached.events] == [
        item.to_dict() for item in score.events
    ]
    assert section_memory_from_score(attached) == memory

    path = attached.save(tmp_path / "section-memory-score.json")
    reopened = Score.load(path)
    assert section_memory_from_score(reopened) == memory
    assert PhrasePlan.from_score(reopened) == PhrasePlan.from_score(score)


def test_score_attachment_rejects_unknown_or_out_of_section_phrase_references():
    score = _score()
    unknown = SectionState(
        section_id="section-X", start_beats=Fraction(0), end_beats=Fraction(4),
        phrase_ids=("no-such-phrase",),
    )
    with pytest.raises(ValueError, match="unknown Score phrase"):
        attach_section_memory(score, SectionMemory(states=(unknown,)))

    misplaced = SectionState(
        section_id="section-A", start_beats=Fraction(1), end_beats=Fraction(4),
        phrase_ids=("phrase-A",),
    )
    with pytest.raises(ValueError, match="falls outside"):
        attach_section_memory(score, SectionMemory(states=(misplaced,)))


def test_memory_fingerprint_detects_manual_metadata_tampering():
    score = _score()
    first, _, _ = _states()
    attached = attach_section_memory(score, SectionMemory(states=(first,)))
    tampered = replace(
        attached,
        metadata={
            **attached.metadata,
            "m30_section_memory": {
                **attached.metadata["m30_section_memory"],
                "capacity": 5,
            },
        },
    )
    with pytest.raises(ValueError, match="fingerprint"):
        section_memory_from_score(tampered)


def test_expectation_must_open_inside_section_and_return_owner_must_match():
    with pytest.raises(ValueError, match="open within"):
        SectionState(
            section_id="bad", start_beats=Fraction(0), end_beats=Fraction(2),
            unresolved_expectations=(
                MemoryExpectation("late", "resolution", "cadence", Fraction(3)),
            ),
        )
    with pytest.raises(ValueError, match="owning source section"):
        SectionState(
            section_id="section-A", start_beats=Fraction(0), end_beats=Fraction(2),
            return_opportunities=(
                ReturnOpportunity("motif-A", "another-section"),
            ),
        )


def test_trajectory_summary_is_compact_normalized_and_validated():
    summary = TrajectorySummary.from_values((0.1, 0.5, 0.9))
    assert summary.start == pytest.approx(0.1)
    assert summary.end == pytest.approx(0.9)
    assert summary.mean == pytest.approx(0.5)
    assert summary.minimum == pytest.approx(0.1)
    assert summary.maximum == pytest.approx(0.9)
    assert summary.standard_deviation > 0
    with pytest.raises(ValueError, match="zero to one"):
        TrajectorySummary.from_values((0.2, 1.2))
    with pytest.raises(ValueError, match="cannot exceed"):
        TrajectorySummary(2, 0.2, 0.5, 0.8, 0.9, 0.1)


def test_section_memory_accepts_m20_orchestration_phrase_references():
    from reawarp.score.orchestration_intent import (
        OrchestrationPlan,
        PhraseSpan as OrchestrationPhraseSpan,
    )

    plan = OrchestrationPlan(
        phrases=(
            OrchestrationPhraseSpan(
                phrase_id="m20-phrase",
                start_beats=Fraction(2),
                end_beats=Fraction(6),
                section_id="m20-section",
            ),
        ),
    )
    score = Score(
        title="M20-backed section memory",
        tempo_map=TempoMap.constant(120),
        orchestration_plan=plan.to_dict(),
    )
    state = SectionState(
        section_id="m20-section",
        start_beats=Fraction(2),
        end_beats=Fraction(6),
        phrase_ids=("m20-phrase",),
        roles=("lead",),
    )
    memory = SectionMemory(states=(state,), capacity=2)

    assert section_memory_from_score(attach_section_memory(score, memory)) == memory
