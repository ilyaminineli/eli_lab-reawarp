"""Composition director timing, deterministic structure, and boundary tests."""
import pytest

from reawarp.composition.director import STRUCTURES, build_composition_plan, section_for_time


@pytest.mark.parametrize("structure", list(STRUCTURES))
def test_structure_covers_exact_45_seconds_with_bar_aligned_transitions(structure):
    plan = build_composition_plan(
        duration_seconds=45.0, bpm=137.0, seed=211, structure=structure, variation=0.8
    )
    assert plan.sections[0].start_seconds == 0.0
    assert plan.sections[-1].end_seconds == pytest.approx(45.0)
    for left, right in zip(plan.sections, plan.sections[1:]):
        assert left.end_seconds == pytest.approx(right.start_seconds)
        assert right.start_bar == left.end_bar
    assert all(section.start_bar >= 0 for section in plan.sections)


def test_structure_plan_is_reproducible_for_a_fixed_seed():
    kwargs = dict(duration_seconds=45.0, bpm=137.0, seed="eli-lab", structure="episodic")
    assert build_composition_plan(**kwargs) == build_composition_plan(**kwargs)


def test_section_lookup_uses_half_open_time_intervals():
    plan = build_composition_plan(duration_seconds=45, bpm=137, seed=211)
    for section in plan.sections:
        assert section_for_time(plan, section.start_seconds).index == section.index
    assert section_for_time(plan, 45).index == plan.sections[-1].index


def test_unknown_structure_is_rejected():
    with pytest.raises(ValueError, match="unknown structure"):
        build_composition_plan(duration_seconds=12, bpm=137, seed=211, structure="random")
