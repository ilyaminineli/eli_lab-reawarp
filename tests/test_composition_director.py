"""Tests for deterministic M7 composition planning."""

import pytest

from reawarp.composition.director import STRUCTURES, build_composition_plan, section_for_time


@pytest.mark.parametrize("structure", list(STRUCTURES))
def test_structure_boundaries_cover_exact_duration(structure):
    plan = build_composition_plan(
        duration_seconds=45.0, bpm=137.0, seed="formal-seed",
        structure=structure, energy=0.66, variation=0.8,
    )
    assert plan.sections[0].start_seconds == 0.0
    assert plan.sections[-1].end_seconds == pytest.approx(45.0)
    for left, right in zip(plan.sections, plan.sections[1:]):
        assert left.end_seconds == pytest.approx(right.start_seconds)
        assert left.duration_seconds > 0.0
        assert 0.0 <= left.energy <= 1.0
        assert 0.0 <= left.density <= 1.0
        assert 0.0 <= left.space <= 1.0


def test_plan_is_deterministic_and_variation_changes_section_lengths():
    first = build_composition_plan(
        duration_seconds=45, bpm=120, seed=211, structure="evolving", variation=0.0
    )
    repeat = build_composition_plan(
        duration_seconds=45, bpm=120, seed=211, structure="evolving", variation=0.0
    )
    varied = build_composition_plan(
        duration_seconds=45, bpm=120, seed=211, structure="evolving", variation=1.0
    )
    assert first == repeat
    assert [s.duration_seconds for s in first.sections] != [s.duration_seconds for s in varied.sections]


def test_section_lookup_clamps_and_respects_boundaries():
    plan = build_composition_plan(
        duration_seconds=20, bpm=135, seed=1, structure="episodic", variation=0
    )
    assert section_for_time(plan, -1).index == 0
    assert section_for_time(plan, 20).index == len(plan.sections) - 1
    for section in plan.sections:
        assert section_for_time(plan, section.start_seconds).index == section.index


def test_invalid_parameters_are_rejected():
    with pytest.raises(ValueError):
        build_composition_plan(duration_seconds=20, bpm=120, seed=1, structure="other")
    with pytest.raises(ValueError):
        build_composition_plan(duration_seconds=20, bpm=120, seed=1, energy=1.1)
