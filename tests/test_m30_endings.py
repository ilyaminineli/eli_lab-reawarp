from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest

from reawarp.composition.endings import (
    ENDING_STRATEGIES,
    EndingDirector,
    EndingPlan,
    compile_ending_plans,
    ending_marker_events,
    ending_plans_from_score,
)
from reawarp.composition.section_memory import (
    MemoryExpectation,
    ReturnOpportunity,
    SectionMemory,
    SectionState,
    attach_section_memory,
)
from reawarp.score import MusicalEvent, Score


def _memory() -> SectionMemory:
    state = SectionState(
        section_id="section-A",
        start_beats=Fraction(0),
        end_beats=Fraction(8),
        motif_ids=("motif-A",),
        roles=("lead", "texture"),
        unresolved_expectations=(
            MemoryExpectation(
                "expect-cadence", "cadence", "tonic-return", Fraction(6),
                "The tonal arrival has been withheld",
            ),
        ),
        return_opportunities=(
            ReturnOpportunity(
                "motif-A", "section-A", "Hold the opening identity for the ending",
                allowed_transformations=("transposition", "fragmentation"),
            ),
        ),
    )
    return SectionMemory(states=(state,))


def _score() -> Score:
    note = MusicalEvent(
        "source-note", "lead", Fraction(1), Fraction(1),
        kind="note", pitch=60,
    )
    return attach_section_memory(
        Score(title="M30 ending fixture", events=(note,)),
        _memory(),
    )


def test_ending_catalogue_covers_the_roadmap_strategies():
    assert ENDING_STRATEGIES == {
        "delayed_return", "transformed_reprise", "interrupted_cadence",
        "residue", "dissolve", "hard_stop",
    }


def test_delayed_return_resolves_an_open_motif_return_without_random_choices():
    plan = EndingDirector.propose(
        _memory(),
        ending_id="return-A",
        strategy="delayed_return",
        start_beats=Fraction(28, 3),
        end_beats=Fraction(40, 3),
        motif_id="motif-A",
        participating_roles=("lead",),
    )
    assert plan.source_section_id == "section-A"
    assert plan.motif_id == "motif-A"
    assert plan.duration_beats == Fraction(4)
    assert plan.seed == 0
    assert EndingPlan.from_dict(plan.to_dict()) == plan


def test_transformed_reprise_obeys_the_return_opportunity_permissions():
    plan = EndingDirector.propose(
        _memory(),
        ending_id="reprise-A",
        strategy="transformed_reprise",
        start_beats=16,
        end_beats=20,
        motif_id="motif-A",
        transformation_ids=("transposition",),
        retained_material_ids=("A",),
    )
    assert plan.transformation_ids == ("transposition",)
    with pytest.raises(ValueError, match="not permitted"):
        EndingDirector.propose(
            _memory(),
            ending_id="reprise-invalid",
            strategy="transformed_reprise",
            start_beats=16,
            end_beats=20,
            motif_id="motif-A",
            transformation_ids=("retrograde",),
        )


def test_interrupted_cadence_must_reference_an_unresolved_expectation():
    plan = EndingDirector.propose(
        _memory(),
        ending_id="interrupted",
        strategy="interrupted_cadence",
        start_beats=16,
        end_beats=17,
        expectation_id="expect-cadence",
    )
    assert plan.expectation_id == "expect-cadence"
    with pytest.raises(ValueError, match="unresolved expectation"):
        EndingDirector.propose(
            _memory(),
            ending_id="interrupted-invalid",
            strategy="interrupted_cadence",
            start_beats=16,
            end_beats=17,
            expectation_id="already-resolved",
        )


def test_residue_dissolve_and_hard_stop_have_explicit_non_random_contracts():
    residue = EndingPlan(
        "residue", "residue", 20, 24, retained_material_ids=("A", "motif-A"),
    )
    dissolve = EndingPlan("dissolve", "dissolve", 24, 32, participating_roles=("texture",))
    stop = EndingDirector.propose(
        _memory(), ending_id="stop", strategy="hard_stop", start_beats=32,
    )
    assert residue.retained_material_ids == ("A", "motif-A")
    assert dissolve.duration_beats == 8
    assert stop.start_beats == stop.end_beats == Fraction(32)
    assert len(ending_marker_events(stop)) == 1
    with pytest.raises(ValueError, match="retained material"):
        EndingPlan("empty-residue", "residue", 20, 24)


def test_ending_markers_are_silent_and_carry_one_atomic_directive():
    plan = EndingPlan(
        "residue", "residue", 20, 24,
        retained_material_ids=("A", "C"),
        participating_roles=("lead", "texture"),
    )
    markers = ending_marker_events(plan)
    assert [item.onset_beats for item in markers] == [Fraction(20), Fraction(24)]
    assert all(item.kind == "marker" and item.velocity == 0 for item in markers)
    directive = markers[0].parameters["m30_ending_marker"]
    assert directive["atomic_directive"] is True
    assert directive["retained_material_ids"] == ["A", "C"]
    assert directive["strategy"] == "residue"


def test_score_compilation_roundtrip_and_replacement_preserve_unrelated_events(tmp_path):
    score = _score()
    source_events = tuple(event for event in score.events if event.kind != "marker")
    plan = EndingDirector.propose(
        _memory(),
        ending_id="return-A",
        strategy="delayed_return",
        start_beats=16,
        end_beats=20,
        motif_id="motif-A",
    )
    compiled = compile_ending_plans(score, (plan,))
    assert ending_plans_from_score(compiled) == (plan,)
    assert tuple(event for event in compiled.events if event.kind != "marker") == source_events
    assert compiled.metadata["m30_section_memory"] == score.metadata["m30_section_memory"]

    assert compile_ending_plans(compiled, (plan,)).to_dict() == compiled.to_dict()
    path = compiled.save(tmp_path / "m30-ending-score.json")
    reopened = Score.load(path)
    assert reopened.to_dict() == compiled.to_dict()
    assert ending_plans_from_score(reopened) == (plan,)

    updated = replace(plan, rationale="Selected after listening review")
    replaced = compile_ending_plans(compiled, (updated,))
    assert ending_plans_from_score(replaced) == (updated,)
    assert tuple(event for event in replaced.events if event.kind != "marker") == source_events


def test_score_compilation_rejects_closed_memory_relationships_and_bad_fingerprints():
    plan = EndingPlan(
        "return-A", "delayed_return", 16, 20,
        motif_id="motif-A", source_section_id="section-A",
    )
    no_return = SectionMemory(states=(
        SectionState(
            section_id="section-A",
            start_beats=0,
            end_beats=8,
            motif_ids=("motif-A",),
        ),
    ))
    score = attach_section_memory(Score(title="No open return"), no_return)
    with pytest.raises(ValueError, match="closed or unknown motif return"):
        compile_ending_plans(score, (plan,))

    compiled = compile_ending_plans(_score(), (plan,))
    corrupted = replace(
        compiled,
        metadata={
            **compiled.metadata,
            "m30_ending_plans": [
                {**compiled.metadata["m30_ending_plans"][0], "rationale": "tampered"}
            ],
        },
    )
    with pytest.raises(ValueError, match="fingerprint"):
        ending_plans_from_score(corrupted)


def test_unknown_strategies_and_inexact_hard_stops_are_rejected():
    with pytest.raises(ValueError, match="unsupported ending strategy"):
        EndingPlan("unknown", "fade forever", 1, 2)
    with pytest.raises(ValueError, match="one exact beat"):
        EndingPlan("bad-stop", "hard_stop", 1, 2)
