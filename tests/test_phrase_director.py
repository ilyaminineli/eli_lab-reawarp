from reawarp.composition.director import build_composition_plan
from reawarp.composition.phrase import build_phrase_directives


def _plan(structure):
    return build_composition_plan(
        duration_seconds=90.0,
        bpm=120.0,
        seed="phrase-test",
        structure=structure,
        energy=0.62,
        variation=0.35,
        flow="preset",
    )


def test_iro_metamorphosis_has_recognisable_phrase_arc_and_exact_duration():
    first = _plan("iro_metamorphosis")
    second = _plan("iro_metamorphosis")
    assert first.to_dict() == second.to_dict()
    assert first.sections[0].start_seconds == 0.0
    assert first.sections[-1].end_seconds == 90.0
    names = [section.name for section in first.sections]
    assert names == [
        "SIGNAL_INTRO", "CONSTRUCTION", "ORBIT", "UPLIFT", "COLLISION",
        "OVERLOAD", "NULL_DROP", "AFTERSHOCK", "UNRAVEL", "FALSE_RETURN",
        "RESIDUE_CODA",
    ]
    assert all(section.end_bar - section.start_bar >= 1 for section in first.sections)
    assert [section.start_bar for section in first.sections] == sorted(
        section.start_bar for section in first.sections
    )
    assert sum(section.end_bar - section.start_bar for section in first.sections) == 45


def test_phrase_directives_distinguish_uplift_arrival_drop_and_void():
    plan = _plan("uplift_drop_return")
    phrases = build_phrase_directives(plan.sections)
    by_name = {section.name: phrase for section, phrase in zip(plan.sections, phrases)}

    assert by_name["UPLIFT_A"].function == "uplift"
    assert by_name["ARRIVAL_PEAK"].function == "arrival"
    assert by_name["DROP_VOID"].function == "silence"
    assert by_name["DROP_VOID"].kick_activity == 0.0
    assert by_name["DROP_VOID"].snare_activity == 0.0
    assert by_name["UPLIFT_A"].transition_in == "pickup"
    assert by_name["ARRIVAL_PEAK"].anchor_strength > by_name["UPLIFT_A"].anchor_strength


def test_drop_keeps_a_residue_but_true_void_does_not():
    plan = _plan("uplift_drop_return")
    phrases = build_phrase_directives(plan.sections)
    by_name = {section.name: phrase for section, phrase in zip(plan.sections, phrases)}
    drop = by_name["DROP_VOID"]
    # DROP_VOID is deliberately a true void; the separate aftershock residue
    # returns afterwards with a different function and nonzero activity.
    aftershock = by_name["REBUILD"]
    assert drop.function == "silence"
    assert aftershock.function in {"development", "return"}
    assert aftershock.high_activity > 0.0
    assert aftershock.ambience_activity > 0.0


def test_two_movement_plan_contains_a_designed_intermovement_void():
    plan = _plan("two_movement")
    phrases = build_phrase_directives(plan.sections)
    assert any(item.function == "silence" for item in phrases)
    assert plan.sections[0].start_bar == 0
    assert plan.sections[-1].end_seconds == 90.0
