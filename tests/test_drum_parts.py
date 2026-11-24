import numpy as np

from reawarp.composition.director import build_composition_plan
from reawarp.config import GenerationConfig
from reawarp.generators.percussion import build_drum_part_plan, build_percussion_events


def _config(**overrides):
    values = {
        "duration": 90.0,
        "bpm": 120.0,
        "sample_rate": 22_050,
        "seed": "section-drum-test",
        "structure": "iro_metamorphosis",
        "pattern_follow_structure": True,
        "pattern_family": "broken_funk",
        "pattern_relationship": "interlock",
        "drum_change_intensity": 0.72,
        "drum_part_cycle_bars": 2,
        "include_melody": False,
        "include_texture": False,
        "include_ambience": False,
    }
    values.update(overrides)
    return GenerationConfig(**values)


def test_drum_part_plan_evolves_roles_by_formal_function_and_recalls_anchor():
    config = _config()
    plan = build_composition_plan(
        duration_seconds=config.duration,
        bpm=config.bpm,
        seed=config.seed,
        structure=config.structure,
        energy=config.composition_energy,
        variation=config.composition_variation,
        flow=config.composition_flow,
        pattern_family=config.pattern_family,
        pattern_relationship=config.pattern_relationship,
    )
    drum_plan = build_drum_part_plan(config, plan)
    assert len(drum_plan) == len(plan.sections)
    assert len({item.kick_family for item in drum_plan}) >= 3
    assert len({item.snare_family for item in drum_plan}) >= 3
    assert len({item.hat_family for item in drum_plan}) >= 3
    establishment = next(item for item in drum_plan if item.section_name == "CONSTRUCTION")
    returned = next(item for item in drum_plan if item.section_name == "FALSE_RETURN")
    assert returned.kick_family == establishment.kick_family
    assert returned.kick_steps == establishment.kick_steps
    assert all(item.end_bar > item.start_bar for item in drum_plan)


def test_same_seed_produces_same_role_events_and_section_plan():
    config = _config()
    plan = build_composition_plan(
        duration_seconds=config.duration, bpm=config.bpm, seed=config.seed,
        structure=config.structure, energy=config.composition_energy,
        variation=config.composition_variation, flow=config.composition_flow,
        pattern_family=config.pattern_family, pattern_relationship=config.pattern_relationship,
    )
    drum_plan = build_drum_part_plan(config, plan)

    def render_events():
        rngs = {
            role: np.random.default_rng(index + 10)
            for index, role in enumerate(("kick", "snare", "hat", "break"))
        }
        return build_percussion_events(config, rngs, plan, drum_plan=drum_plan)

    first = render_events()
    second = render_events()
    assert first == second
    assert first["kick"]
    assert first["snare"]
    assert first["hat"]
    assert len({event.pattern_style for event in first["kick"]}) >= 3


def test_manual_static_drum_mode_remains_available():
    config = _config(pattern_follow_structure=False)
    plan = build_composition_plan(
        duration_seconds=config.duration, bpm=config.bpm, seed=config.seed,
        structure=config.structure, energy=config.composition_energy,
        variation=config.composition_variation, flow=config.composition_flow,
        pattern_family=config.pattern_family, pattern_relationship=config.pattern_relationship,
    )
    assert build_drum_part_plan(config, plan) == ()
    rngs = {
        role: np.random.default_rng(index + 20)
        for index, role in enumerate(("kick", "snare", "hat", "break"))
    }
    events = build_percussion_events(config, rngs, plan)
    assert events["kick"] and events["snare"] and events["hat"]
