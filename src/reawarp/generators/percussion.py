"""Convert mathematical rhythm structures into deterministic drum events.

The break lane deliberately uses phrase-level grammar rather than independent
per-step probabilities. A stable 16-step reference pattern is repeated, then a
small number of bounded mutations are introduced at phrase boundaries.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from reawarp.config import GenerationConfig
from reawarp.composition.patterns import pattern_for_section, relate_patterns
from reawarp.composition.director import CompositionPlan, build_composition_plan, section_for_time
from reawarp.core.random_streams import derive_seed
from reawarp.mathematics.rhythms import euclidean_rhythm
from reawarp.mathematics.sequences import fibonacci, logistic_map, primes


@dataclass(frozen=True, slots=True)
class PercussionEvent:
    lane: str
    step: int
    time: float
    velocity: float
    pan: float = 0.0
    kind: str | None = None
    pattern_style: str | None = None

    def to_dict(self) -> dict[str, int | float | str | None]:
        return asdict(self)


# step, voice, selection priority, base velocity, pan.
# The first four events in each grammar establish the metric reference.
BREAK_PATTERNS: dict[str, tuple[tuple[int, str, float, float, float], ...]] = {
    "broken_funk": (
        (0, "kick", 1.00, 0.96, 0.00),
        (4, "snare", 0.99, 0.88, 0.00),
        (8, "kick", 0.97, 0.91, 0.00),
        (12, "snare", 0.98, 0.90, 0.00),
        (7, "kick", 0.76, 0.62, 0.00),
        (2, "hat", 0.61, 0.42, -0.22),
        (10, "hat", 0.59, 0.40, 0.22),
        (14, "hat", 0.57, 0.38, -0.18),
        (6, "hat", 0.48, 0.34, 0.18),
        (15, "snare", 0.40, 0.32, 0.00),
    ),
    "half_time": (
        (0, "kick", 1.00, 0.96, 0.00),
        (8, "snare", 0.99, 0.90, 0.00),
        (10, "kick", 0.94, 0.78, 0.00),
        (4, "snare", 0.88, 0.62, 0.00),
        (14, "hat", 0.65, 0.42, 0.20),
        (6, "hat", 0.62, 0.40, -0.20),
        (2, "hat", 0.58, 0.36, 0.18),
        (12, "hat", 0.55, 0.34, -0.18),
        (15, "snare", 0.40, 0.30, 0.00),
        (7, "kick", 0.36, 0.28, 0.00),
    ),
    "straight": (
        (0, "kick", 1.00, 0.95, 0.00),
        (4, "snare", 0.99, 0.87, 0.00),
        (8, "kick", 0.98, 0.90, 0.00),
        (12, "snare", 0.97, 0.88, 0.00),
        (2, "hat", 0.70, 0.42, -0.22),
        (6, "hat", 0.68, 0.40, 0.22),
        (10, "hat", 0.66, 0.39, -0.18),
        (14, "hat", 0.64, 0.38, 0.18),
        (7, "kick", 0.40, 0.30, 0.00),
        (15, "snare", 0.34, 0.28, 0.00),
    ),
    "sparse": (
        (0, "kick", 1.00, 0.96, 0.00),
        (4, "snare", 0.98, 0.84, 0.00),
        (8, "kick", 0.97, 0.88, 0.00),
        (12, "snare", 0.96, 0.86, 0.00),
        (10, "kick", 0.58, 0.52, 0.00),
        (6, "hat", 0.52, 0.33, -0.20),
        (14, "hat", 0.50, 0.32, 0.20),
        (2, "hat", 0.46, 0.30, -0.16),
        (15, "hat", 0.32, 0.24, 0.16),
        (7, "snare", 0.28, 0.24, 0.00),
    ),
}

BREAK_STYLE_NAMES = tuple(BREAK_PATTERNS)


@dataclass(frozen=True, slots=True)
class DrumSectionPlan:
    section_index: int
    section_name: str
    start_bar: int
    end_bar: int
    kick_family: str
    snare_family: str
    hat_family: str
    relationship: str
    kick_steps: tuple[int, ...]
    snare_steps: tuple[int, ...]
    hat_steps: tuple[int, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _drum_section_function(name: str) -> str:
    token = name.upper()
    if any(part in token for part in ("INTRO", "SIGNAL", "ORIGIN", "SEED_OBJECT")):
        return "intro"
    if any(part in token for part in ("FOUNDATION", "CONSTRUCTION", "ESTABLISH", "EXPOSITION")):
        return "establishment"
    if any(part in token for part in ("UPLIFT", "SURGE", "RAMP", "PICKUP")):
        return "uplift"
    if any(part in token for part in ("PEAK", "COLLISION", "OVERLOAD", "ARRIVAL", "CLIMAX")):
        return "arrival"
    if any(part in token for part in ("NULL", "VOID", "SILENCE", "SUSPENSION")):
        return "void"
    if any(part in token for part in ("DROP", "BREAKDOWN", "WITHDRAWAL", "EXPOSE", "DECOMPRESSION")):
        return "drop"
    if any(part in token for part in ("CONTRAST", "COUNTER", "SCENE_B")):
        return "contrast"
    if any(part in token for part in ("RETURN", "REPRISE", "RECAP", "REASSEMBLY")):
        return "return"
    if any(part in token for part in ("RESIDUE", "AFTERSHOCK", "AFTERIMAGE", "UNRAVEL", "CODA", "OUTRO", "FADE")):
        return "residue"
    if any(part in token for part in ("DEVELOP", "ORBIT", "DRIFT", "MUTATION", "EXPANSION")):
        return "development"
    return "continuation"


def _family_for_role(function: str, role: str, anchor_family: str) -> str:
    """Choose a role pattern family from formal function, preserving a return anchor."""
    choices = {
        "intro": {
            "kick": ("sparse", "omission"),
            "snare": ("omission", "sparse"),
            "hat": ("phase_shadow", "offbeat_cells"),
        },
        "establishment": {
            "kick": (anchor_family,),
            "snare": ("half_time", "broken_funk"),
            "hat": ("offbeat_cells", "phase_shadow"),
        },
        "continuation": {
            "kick": (anchor_family, "broken_regularity"),
            "snare": ("half_time", "ghost_break"),
            "hat": ("offbeat_cells", "rotating_cycle"),
        },
        "development": {
            "kick": ("asymmetric_5", "interlock_a", "rotating_cycle", anchor_family),
            "snare": ("ghost_break", "asymmetric_7", "interlock_b"),
            "hat": ("offbeat_cells", "cross_accent", "phase_shadow"),
        },
        "uplift": {
            "kick": ("ratchet", "cross_accent", "rotating_cycle"),
            "snare": ("ghost_break", "cross_accent", "asymmetric_7"),
            "hat": ("dense_cloud", "irregular_burst", "ratchet"),
        },
        "arrival": {
            "kick": ("cross_accent", "broken_funk", "ratchet"),
            "snare": ("ghost_break", "broken_regularity", "cross_accent"),
            "hat": ("dense_cloud", "irregular_burst", "offbeat_cells"),
        },
        "drop": {
            "kick": ("omission", "sparse"),
            "snare": ("omission", "sparse"),
            "hat": ("phase_shadow", "sparse", "offbeat_cells"),
        },
        "void": {
            "kick": ("omission",),
            "snare": ("omission",),
            "hat": ("omission",),
        },
        "contrast": {
            "kick": ("half_time", "asymmetric_7"),
            "snare": ("asymmetric_5", "clave_displaced"),
            "hat": ("rotating_cycle", "phase_shadow", "offbeat_cells"),
        },
        "return": {
            "kick": (anchor_family,),
            "snare": ("half_time", "broken_funk"),
            "hat": ("offbeat_cells", "phase_shadow"),
        },
        "residue": {
            "kick": ("sparse", "omission"),
            "snare": ("omission", "sparse"),
            "hat": ("phase_shadow", "sparse"),
        },
    }
    options = choices.get(function, choices["continuation"])[role]
    return options[0] if len(options) == 1 else options[0]


def build_drum_part_plan(
    config: GenerationConfig,
    composition_plan: CompositionPlan,
) -> tuple[DrumSectionPlan, ...]:
    """Create linked kick/snare/hat grammars for every formal section.

    Section families evolve in relation to the formal role. Returns recall the
    opening anchor family; cycle drift and fills are applied later at bar scale.
    """
    if not config.pattern_follow_structure:
        return ()
    anchor_family = config.pattern_family
    plans: list[DrumSectionPlan] = []
    for section in composition_plan.sections:
        function = _drum_section_function(section.name)
        kick_family = _family_for_role(function, "kick", anchor_family)
        snare_family = _family_for_role(function, "snare", anchor_family)
        hat_family = _family_for_role(function, "hat", anchor_family)

        def role_steps(role: str, family: str) -> tuple[int, ...]:
            seed = derive_seed(
                config.seed,
                f"drum-section:{section.index}:{section.name}:{role}:{family}",
            )
            rng = np.random.default_rng(seed)
            density = float(np.clip(
                section.density * (0.55 + 0.45 * config.drum_change_intensity),
                0.08, 1.0,
            ))
            variation = float(np.clip(
                config.composition_variation * config.drum_change_intensity,
                0.0, 1.0,
            ))
            return pattern_for_section(
                family,
                section_index=section.index,
                section_name=section.name,
                variation=variation,
                density=density,
                rng=rng,
            )

        kick_steps = role_steps("kick", kick_family)
        snare_seed = derive_seed(
            config.seed, f"drum-relate:{section.index}:snare:{config.pattern_relationship}"
        )
        snare_rng = np.random.default_rng(snare_seed)
        snare_steps = role_steps("snare", snare_family)
        kick_steps, snare_steps = relate_patterns(
            kick_steps, snare_steps,
            relationship=config.pattern_relationship,
            cycle_steps=16,
        )
        hat_steps = role_steps("hat", hat_family)
        # Hats act as the upper surface: use the role's own family but avoid
        # needless doubling of every kick accent when using complementary modes.
        if config.pattern_relationship in {"interlock", "counter_accent", "call_response"}:
            hat_steps = tuple(step for step in hat_steps if step not in set(kick_steps))
        if function == "establishment":
            anchor_family = kick_family
        plans.append(DrumSectionPlan(
            section_index=section.index,
            section_name=section.name,
            start_bar=section.start_bar,
            end_bar=section.end_bar,
            kick_family=kick_family,
            snare_family=snare_family,
            hat_family=hat_family,
            relationship=config.pattern_relationship,
            kick_steps=tuple(sorted(set(kick_steps))),
            snare_steps=tuple(sorted(set(snare_steps))),
            hat_steps=tuple(sorted(set(hat_steps))),
        ))
    return tuple(plans)


def _build_section_aware_drum_events(
    config: GenerationConfig,
    composition_plan: CompositionPlan,
    rngs: dict[str, np.random.Generator],
    drum_plan: tuple[DrumSectionPlan, ...],
) -> dict[str, list[PercussionEvent]]:
    """Render section-aware role patterns with controlled cycle-level evolution."""
    result: dict[str, list[PercussionEvent]] = {"kick": [], "snare": [], "hat": []}
    step_seconds = config.sixteenth_seconds
    cycle_bars = int(config.drum_part_cycle_bars)
    intensity = float(config.drum_change_intensity)
    function_by_section = {
        item.section_index: _drum_section_function(item.section_name) for item in drum_plan
    }
    for plan in drum_plan:
        function = function_by_section[plan.section_index]
        section_rng = np.random.default_rng(
            derive_seed(config.seed, f"drum-cycle:{plan.section_index}:{plan.section_name}")
        )
        for bar in range(plan.start_bar, plan.end_bar):
            if bar * 16 * step_seconds >= config.duration:
                continue
            cycle_index = (bar - plan.start_bar) // cycle_bars
            # A very small phase walk stops the pattern becoming a static bar
            # copy while preserving its original accents and role relationship.
            drift_limit = int(round(intensity * 2.0))
            drift = 0
            if cycle_index and drift_limit:
                drift = int(round(
                    np.sin((cycle_index + 1) * 1.61803398875 + plan.section_index) * drift_limit
                ))
            ending_bar = bar == plan.end_bar - 1
            for role, base_steps, family in (
                ("kick", plan.kick_steps, plan.kick_family),
                ("snare", plan.snare_steps, plan.snare_family),
                ("hat", plan.hat_steps, plan.hat_family),
            ):
                steps = sorted({(step + drift) % 16 for step in base_steps})
                if ending_bar and intensity > 0.35 and function in {"development", "uplift", "arrival", "contrast"}:
                    # One concise transition gesture: add only one or two
                    # upper-role events to prepare the next formal state.
                    if role == "hat":
                        fill = (13, 14, 15) if function in {"uplift", "arrival"} else (11, 15)
                        steps = sorted(set(steps) | set(fill[:1 + int(intensity > 0.72)]))
                    elif role == "snare" and function in {"uplift", "arrival"}:
                        steps = sorted(set(steps) | {15})

                for pos, position in enumerate(steps):
                    absolute_step = bar * 16 + position
                    time_seconds = absolute_step * step_seconds
                    if time_seconds >= config.duration:
                        continue
                    if role == "kick":
                        velocity = float(np.clip(
                            0.50 + 0.22 * composition_plan.sections[plan.section_index].energy
                            + (0.12 if position == 0 else 0.0)
                            + section_rng.uniform(-0.055, 0.055),
                            0.22, 0.92,
                        ))
                        kind, pan = "synth_kick", 0.0
                    elif role == "snare":
                        anchor = position in (4, 8, 12)
                        velocity = float(np.clip(
                            (0.48 if anchor else 0.28)
                            + 0.16 * composition_plan.sections[plan.section_index].energy
                            + section_rng.uniform(-0.07, 0.07),
                            0.12, 0.84,
                        ))
                        kind, pan = "noise_snare", 0.0
                    else:
                        velocity = float(np.clip(
                            0.12 + 0.17 * composition_plan.sections[plan.section_index].instability
                            + section_rng.uniform(-0.035, 0.035),
                            0.06, 0.42,
                        ))
                        pan = float(np.clip(np.sin(absolute_step * 0.31) * 0.18, -0.24, 0.24))
                        kind = "metal_noise"
                    result[role].append(PercussionEvent(
                        role, absolute_step, time_seconds, velocity, pan, kind, family
                    ))
    return result


def _mutate_break_bar(
        hits: list[tuple[int, str, float, float, float]],
        rng: np.random.Generator,
        variation: float,
        anchors: set[int],
) -> list[tuple[int, str, float, float, float]]:
    """Apply one or two local, grid-preserving phrase mutations."""
    result = list(hits)
    if variation <= 0.0 or float(rng.random()) >= variation:
        return result

    # Variation acts as an actual probability, not just a label. High values
    # can permit a second local edit; low values preserve the learned phrase.
    mutation_count = 1 + int(float(rng.random()) < max(0.0, (variation - 0.5) * 2.0))
    ghost_steps = (1, 3, 5, 9, 11, 13, 15)

    for _ in range(mutation_count):
        operation = float(rng.random())
        occupied = {item[0] for item in result}
        movable = [
            index for index, item in enumerate(result)
            if item[0] not in anchors
        ]

        if operation < 0.52 and movable:
            # Move a single non-anchor event by one sixteenth, never off-grid.
            index = int(rng.choice(movable))
            step, kind, priority, velocity, pan = result[index]
            destinations = [value for value in (step - 1, step + 1)
                            if 0 <= value < 16 and value not in occupied]
            if destinations:
                result[index] = (
                    int(rng.choice(destinations)), kind, priority, velocity, pan
                )
        elif operation < 0.78 and len(result) > 4 and movable:
            # Remove one ornament, never one of the four metric anchors.
            del result[int(rng.choice(movable))]
        elif len(result) < 8:
            # Add one quiet offbeat voice; density remains hard-capped.
            available = [step for step in ghost_steps if step not in occupied]
            if available:
                step = int(rng.choice(available))
                kind = "hat" if float(rng.random()) < 0.78 else "snare"
                pan = -0.18 if step % 4 == 1 else 0.18
                result.append((step, kind, 0.25, 0.26, pan))

    return sorted(result, key=lambda item: item[0])


def _build_break_events(
        config: GenerationConfig,
        rng: np.random.Generator,
        step_count: int,
        composition_plan: CompositionPlan | None = None,
) -> list[PercussionEvent]:
    """Build repeated 16-step break phrases with bounded bar-end mutations."""
    style = config.break_style
    if style == "auto":
        style = str(rng.choice(BREAK_STYLE_NAMES))
    template = BREAK_PATTERNS[style]

    # Pattern-family adaptation is deliberately opt-in through the global
    # structural-variation control. With zero variation, preserve the original
    # exact phrase template and density contract byte-for-byte.
    if composition_plan is None:
        composition_plan = build_composition_plan(
            duration_seconds=config.duration, bpm=config.bpm, seed=config.seed,
            structure=config.structure, energy=config.composition_energy,
            variation=config.composition_variation, flow=config.composition_flow,
            pattern_family=config.pattern_family,
            pattern_relationship=config.pattern_relationship,
        )

    step_seconds = config.sixteenth_seconds
    bar_count = (step_count + 15) // 16
    events: list[PercussionEvent] = []

    previous_section_index = -1
    cycle_phrase: list[tuple[int, str, float, float, float]] | None = None
    cycle_section_index = -1
    for bar in range(bar_count):
        section = section_for_time(composition_plan, bar * 4.0 * 60.0 / config.bpm)
        target_count = 4 + int(round(float(config.break_density) * 4.0))
        selected = sorted(
            sorted(template, key=lambda item: item[2], reverse=True)[:target_count],
            key=lambda item: item[0],
        )
        cycle_start = bar % int(config.break_cycle_bars) == 0
        section_changed = section.index != cycle_section_index

        # Legacy break variation remains phrase-local. Structural pattern
        # switching is a separate opt-in and happens only at cycle boundaries.
        if cycle_phrase is None or (
            cycle_start and config.pattern_follow_structure and section_changed
        ):
            cycle_phrase = list(selected)
            cycle_section_index = section.index
            if config.pattern_follow_structure:
                family_steps = pattern_for_section(
                    config.pattern_family,
                    section_index=section.index,
                    section_name=section.name,
                    variation=config.composition_variation,
                    density=float(section.density),
                    rng=rng,
                )
                companion_family = config.pattern_family
                if companion_family == "interlock_a":
                    companion_family = "interlock_b"
                elif companion_family == "interlock_b":
                    companion_family = "interlock_a"
                elif companion_family == "broken_funk":
                    companion_family = "offbeat_cells"
                elif companion_family == "straight":
                    companion_family = "clave_displaced"
                companion_seed = derive_seed(
                    config.seed,
                    f"pattern-companion:{section.index}:{companion_family}:{config.pattern_relationship}",
                )
                companion_rng = np.random.default_rng(companion_seed)
                companion_base = pattern_for_section(
                    companion_family,
                    section_index=section.index + 1,
                    section_name=section.name,
                    variation=config.composition_variation,
                    density=float(section.density),
                    rng=companion_rng,
                )
                companion_steps, family_steps = relate_patterns(
                    family_steps, companion_base,
                    relationship=config.pattern_relationship,
                    cycle_steps=16,
                )
                if len(family_steps) >= 2:
                    anchors = [item for item in cycle_phrase if item[0] in {0, 4, 8, 12}]
                    ornaments = [item for item in cycle_phrase if item[0] not in {0, 4, 8, 12}]
                    remapped = []
                    selected_steps = (
                        companion_steps
                        if config.pattern_relationship in {"shadow", "call_response", "counter_accent"}
                        else family_steps
                    )
                    for index, item in enumerate(ornaments):
                        if index >= len(selected_steps):
                            break
                        _step, kind, priority, velocity, pan = item
                        remapped.append((selected_steps[index], kind, priority, velocity, pan))
                    cycle_phrase = sorted(anchors + remapped, key=lambda item: item[0])
        previous_section_index = section.index

        is_cycle_end = (bar + 1) % int(config.break_cycle_bars) == 0
        # Mutate only the closing bar of a cycle; do not carry this one-off
        # edit forward into the next cycle. The base phrase repeats by design.
        render_hits = list(cycle_phrase or selected)
        if is_cycle_end and config.break_variation > 0.0:
            anchor_steps = {
                step for step, _kind, priority, _velocity, _pan in template
                if priority >= 0.88
            }
            render_hits = _mutate_break_bar(
                render_hits, rng, float(config.break_variation), anchor_steps
            )

        for step_in_bar, kind, _priority, base_velocity, pan in render_hits:
            absolute_step = bar * 16 + step_in_bar
            time_seconds = absolute_step * step_seconds
            if absolute_step >= step_count or time_seconds >= config.duration:
                continue
            events.append(PercussionEvent(
                "break",
                absolute_step,
                time_seconds,
                float(np.clip(base_velocity, 0.12, 1.0)),
                float(pan),
                kind,
                style,
            ))

    return sorted(events, key=lambda event: (event.step, event.kind or ""))


def build_percussion_events(
        config: GenerationConfig,
        rngs: dict[str, np.random.Generator],
        composition_plan: CompositionPlan | None = None,
) -> dict[str, list[PercussionEvent]]:
    """Build related percussion lanes, optionally evolving them by formal section."""
    if composition_plan is None:
        composition_plan = build_composition_plan(
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
    if config.pattern_follow_structure:
        drum_plan = build_drum_part_plan(config, composition_plan)
        lane_events = _build_section_aware_drum_events(
            config, composition_plan, rngs, drum_plan
        )
    else:
        # Preserve the original sparse, slowly rotating generator as a manual
        # alternative. The default path now evolves all three percussion roles.
        step_seconds = config.sixteenth_seconds
        step_count = int(np.ceil(config.duration / step_seconds))
        complexity = config.complexity
        lane_events: dict[str, list[PercussionEvent]] = {
            "kick": [], "snare": [], "hat": []
        }
        kick_rng, snare_rng, hat_rng = rngs["kick"], rngs["snare"], rngs["hat"]
        sparse_kick_pulses = 2 + int(round(complexity * 1.4))
        sparse_snare_pulses = 1 + int(round(complexity * 0.9))
        sparse_hat_pulses = 2 + int(round(complexity * 2.0))
        for step in range(step_count):
            time_seconds = step * step_seconds
            if time_seconds >= config.duration:
                continue
            bar, position = divmod(step, 16)
            kick_rotation = (bar * (1 + int(complexity * 2))) % 16
            kick_hit = euclidean_rhythm(
                sparse_kick_pulses, 16, rotation=kick_rotation
            )[position]
            if not kick_hit and position in (3, 7, 11, 15):
                kick_hit = bool(kick_rng.random() < 0.018 + complexity * 0.035)
            if kick_hit:
                velocity = float(kick_rng.uniform(0.53, 0.78))
                if position == 0:
                    velocity = min(0.88, velocity + 0.10)
                lane_events["kick"].append(
                    PercussionEvent("kick", step, time_seconds, velocity, 0.0, "synth_kick")
                )
            snare_rotation = 4 if bar % 2 == 0 else 12
            snare_hit = position == snare_rotation
            ghost_snare = position in (6, 14) and snare_rng.random() < complexity * 0.025
            if snare_hit or ghost_snare:
                velocity = float(
                    snare_rng.uniform(0.16, 0.30)
                    if ghost_snare else snare_rng.uniform(0.38, 0.62)
                )
                lane_events["snare"].append(
                    PercussionEvent("snare", step, time_seconds, velocity, 0.0, "noise_snare")
                )
            hat_pattern = euclidean_rhythm(
                sparse_hat_pulses, 16, rotation=(bar * 3 + 2) % 16
            )
            hat_probability = 0.015 + complexity * 0.025
            if hat_pattern[position] and hat_rng.random() < 0.62 or hat_rng.random() < hat_probability:
                velocity = float(hat_rng.uniform(0.10, 0.24))
                pan = float(np.clip(np.sin(step * 0.31) * 0.16, -0.22, 0.22))
                lane_events["hat"].append(
                    PercussionEvent("hat", step, time_seconds, velocity, pan, "metal_noise")
                )

    lane_events["break"] = _build_break_events(
        config, rngs["break"], int(np.ceil(config.duration / config.sixteenth_seconds)),
        composition_plan,
    )
    return lane_events
