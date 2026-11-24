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
from reawarp.composition.director import section_for_time
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
) -> list[PercussionEvent]:
    """Build repeated 16-step break phrases with bounded bar-end mutations."""
    style = config.break_style
    if style == "auto":
        style = str(rng.choice(BREAK_STYLE_NAMES))
    template = BREAK_PATTERNS[style]

    # The selected structure governs how the break grammar evolves across
    # sections. Keep the original event vocabulary and metric anchors, but
    # adapt the phrase steps to the selected composition family.
    target_count = 4 + int(round(float(config.break_density) * 4.0))
    selected = sorted(
        sorted(template, key=lambda item: item[2], reverse=True)[:target_count],
        key=lambda item: item[0],
    )
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

    for bar in range(bar_count):
        section = section_for_time(composition_plan, bar * 4.0 * 60.0 / config.bpm)
        family_steps = pattern_for_section(
            config.pattern_family,
            section_index=section.index,
            section_name=section.name,
            variation=config.composition_variation,
            density=float(section.density),
            rng=rng,
        )
        # Derive a related companion phrase. A deterministic offset stream
        # avoids sharing the main pattern's exact event set except for unison.
        companion_seed = int(rng.integers(0, 2**32 - 1))
        companion_rng = np.random.default_rng(companion_seed)
        companion_base = pattern_for_section(
            config.pattern_family,
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
        # Remap secondary hits into the chosen pattern family, retaining the
        # four structural break anchors from the selected break style.
        bar_hits = list(selected)
        if len(family_steps) >= 2:
            anchors = [item for item in bar_hits if item[0] in {0, 4, 8, 12}]
            ornaments = [item for item in bar_hits if item[0] not in {0, 4, 8, 12}]
            remapped = []
            selected_steps = companion_steps if config.pattern_relationship in {"shadow", "call_response", "counter_accent"} else family_steps
            for index, item in enumerate(ornaments):
                if index >= len(selected_steps):
                    break
                step, kind, priority, velocity, pan = item
                remapped.append((selected_steps[index], kind, priority, velocity, pan))
            bar_hits = sorted(anchors + remapped, key=lambda item: item[0])
        is_phrase_end = (bar + 1) % int(config.break_cycle_bars) == 0
        if is_phrase_end and config.break_variation > 0.0:
            anchor_steps = {
                step for step, _kind, priority, _velocity, _pan in template
                if priority >= 0.88
            }
            bar_hits = _mutate_break_bar(
                bar_hits, rng, float(config.break_variation), anchor_steps
            )

        for step_in_bar, kind, _priority, base_velocity, pan in bar_hits:
            absolute_step = bar * 16 + step_in_bar
            time_seconds = absolute_step * step_seconds
            if absolute_step >= step_count or time_seconds >= config.duration:
                continue
            velocity = float(base_velocity)
            if is_phrase_end and config.break_variation > 0.0:
                spread = 0.10 * float(config.break_variation)
                velocity *= float(rng.uniform(1.0 - spread, 1.0 + spread))
            events.append(PercussionEvent(
                "break",
                absolute_step,
                time_seconds,
                float(np.clip(velocity, 0.12, 1.0)),
                float(pan),
                kind,
                style,
            ))

    return sorted(events, key=lambda event: (event.step, event.kind or ""))


def build_percussion_events(
        config: GenerationConfig,
        rngs: dict[str, np.random.Generator],
) -> dict[str, list[PercussionEvent]]:
    """Build four related percussion lanes with independent control streams."""
    step_seconds = config.sixteenth_seconds
    step_count = int(np.ceil(config.duration / step_seconds))
    complexity = config.complexity

    lane_events: dict[str, list[PercussionEvent]] = {
        "kick": [], "snare": [], "hat": [], "break": []
    }
    kick_rng, snare_rng = rngs["kick"], rngs["snare"]
    hat_rng, break_rng = rngs["hat"], rngs["break"]
    chaos = logistic_map(step_count, r=3.72 + 0.25 * complexity, x0=0.193)
    prime_values = set(primes(max(32, step_count // 3 + 8)))
    fib_values = set(fibonacci(18))

    for step in range(step_count):
        if step * step_seconds >= config.duration:
            continue
        bar, position = divmod(step, 16)
        local_rotation = (bar * (1 + int(complexity * 3))) % 16

        kick_pulses = min(7, 3 + int(round(complexity * 2)))
        kick_pattern = euclidean_rhythm(kick_pulses, 16, rotation=local_rotation)
        kick_hit = kick_pattern[position]
        if not kick_hit and (step + 1) in prime_values:
            kick_hit = bool(kick_rng.random() < 0.05 + complexity * 0.22)
        if kick_hit:
            velocity = float(kick_rng.uniform(0.74, 0.98))
            if position == 0:
                velocity = min(1.0, velocity + 0.1)
            if kick_rng.random() < complexity * 0.20:
                velocity *= float(kick_rng.uniform(0.45, 0.72))
            lane_events["kick"].append(
                PercussionEvent("kick", step, step * step_seconds, velocity, 0.0, "synth_kick")
            )

        snare_rotation = (4 + bar * 3 + int(chaos[step] * 4)) % 16
        snare_pulses = 3 + int(complexity > 0.55)
        snare_hit = euclidean_rhythm(snare_pulses, 16, rotation=snare_rotation)[position]
        ghost_snare = (
                position in (2, 6, 10, 14)
                and snare_rng.random() < complexity * 0.16
        )
        if snare_hit or ghost_snare:
            velocity = float(
                snare_rng.uniform(0.48, 0.82)
                if ghost_snare else snare_rng.uniform(0.72, 1.0)
            )
            lane_events["snare"].append(
                PercussionEvent("snare", step, step * step_seconds, velocity, 0.0, "noise_snare")
            )

        hat_pulses = min(16, 8 + int(round(complexity * 6)))
        hat_pattern = euclidean_rhythm(hat_pulses, 16, rotation=(bar * 5 + 1) % 16)
        if hat_pattern[position] or hat_rng.random() < complexity * 0.12:
            velocity = float(hat_rng.uniform(0.16, 0.54))
            if position in (0, 4, 8, 12):
                velocity *= 0.65
            pan = float(np.clip(np.sin(step * 0.71) * (0.18 + complexity * 0.42), -0.7, 0.7))
            lane_events["hat"].append(
                PercussionEvent("hat", step, step * step_seconds, velocity, pan, "metal_noise")
            )

    lane_events["break"] = _build_break_events(config, break_rng, step_count)
    return lane_events
