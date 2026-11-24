"""Composition director timing, deterministic structure, and boundary tests."""
import pytest

from reawarp.composition.director import STRUCTURES, build_composition_plan, section_for_time
from reawarp.composition.patterns import PatternEvent, evolve_phrase, pattern_for_section, relate_patterns
import numpy as np


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


@pytest.mark.parametrize("bpm", [60.0, 137.0, 220.0])
def test_short_render_sections_never_extend_outside_audio(bpm):
    plan = build_composition_plan(
        duration_seconds=5.0, bpm=bpm, seed=211, structure="evolving"
    )
    assert plan.sections[0].start_seconds == 0.0
    assert plan.sections[-1].end_seconds == pytest.approx(5.0)
    for section in plan.sections:
        assert 0.0 <= section.start_seconds <= section.end_seconds <= 5.0
    for left, right in zip(plan.sections, plan.sections[1:]):
        assert left.end_seconds == pytest.approx(right.start_seconds)



def test_new_composition_presets_are_available_and_cover_three_minutes():
    for preset in ("classical_arc", "sonata_mutation", "free_jazz",
                   "free_jazz_episodic", "autechre_like", "minimal_variation", "hybrid"):
        plan = build_composition_plan(
            duration_seconds=180, bpm=137, seed="m8", structure=preset, flow="preset"
        )
        assert plan.sections[0].start_seconds == 0.0
        assert plan.sections[-1].end_seconds == pytest.approx(180.0)
        assert all(a.end_seconds == pytest.approx(b.start_seconds)
                   for a, b in zip(plan.sections, plan.sections[1:]))


@pytest.mark.parametrize("flow", ["preset", "mix", "mutate"])
def test_structure_flows_are_deterministic(flow):
    kwargs = dict(duration_seconds=90, bpm=123, seed=17,
                  structure="classical_arc", flow=flow, variation=.75)
    assert build_composition_plan(**kwargs) == build_composition_plan(**kwargs)


def test_pattern_grammar_is_section_aware_and_deterministic():
    args = dict(family="ghost_break", section_index=2, section_name="DEVELOPMENT",
                variation=.8, density=.8)
    a = pattern_for_section(**args, rng=np.random.default_rng(11))
    b = pattern_for_section(**args, rng=np.random.default_rng(11))
    assert a == b
    sparse = pattern_for_section(
        "ghost_break", section_index=0, section_name="SUSPENSION",
        variation=0.0, density=1.0, rng=np.random.default_rng(11),
    )
    assert len(sparse) < len(a)


def test_pattern_relationships_support_interlock_and_shadow():
    a, b = relate_patterns((0, 4, 8), (0, 4, 8, 12), relationship="interlock")
    assert b == (12,)
    a, b = relate_patterns((0, 4, 8, 12), (), relationship="shadow")
    assert b != a


@pytest.mark.parametrize("transform", [
    "identity", "retrograde", "inversion", "augmentation",
    "diminution", "fragment", "reorder", "displace",
])
def test_motif_transformations_are_deterministic_and_bounded(transform):
    events = tuple(PatternEvent(step, velocity=.7, pitch_offset=step-4) for step in (0, 3, 7, 12))
    kwargs = dict(transform=transform, amount=.6, cycle_steps=16)
    first = evolve_phrase(events, rng=np.random.default_rng(4), **kwargs)
    second = evolve_phrase(events, rng=np.random.default_rng(4), **kwargs)
    assert first == second
    assert all(event.step >= 0 for event in first)



def test_composition_plan_persists_pattern_family_and_relationship():
    plan = build_composition_plan(
        duration_seconds=90, bpm=129, seed=220,
        structure="autechre_like", pattern_family="asymmetric_7",
        pattern_relationship="shadow",
    )
    data = plan.to_dict()
    assert data["pattern_family"] == "asymmetric_7"
    assert data["pattern_relationship"] == "shadow"
