from reawarp.composition.director import build_composition_plan


def test_composition_plan_is_deterministic_and_covers_exact_duration():
    kwargs = {
        "duration_seconds": 24.0,
        "bpm": 120.0,
        "seed": 211,
        "structure": "autechre_like",
        "energy": 0.62,
        "variation": 0.45,
        "flow": "mutate",
        "pattern_family": "asymmetric_7",
        "pattern_relationship": "interlock",
    }
    first = build_composition_plan(**kwargs)
    second = build_composition_plan(**kwargs)

    assert first.to_dict() == second.to_dict()
    assert first.sections[0].start_seconds == 0.0
    assert first.sections[-1].end_seconds == 24.0
    for left, right in zip(first.sections, first.sections[1:]):
        assert left.end_seconds == right.start_seconds
        assert left.end_bar == right.start_bar


def test_composition_plan_rejects_invalid_controls():
    import pytest

    with pytest.raises(ValueError):
        build_composition_plan(
            duration_seconds=24.0, bpm=120.0, seed=1, energy=1.5
        )
