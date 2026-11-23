"""Convert Euclidean, modular, and nonlinear sequences into drum events."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from reawarp.config import GenerationConfig
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

    def to_dict(self) -> dict[str, int | float | str | None]:
        return asdict(self)


def build_percussion_events(
        config: GenerationConfig,
        rngs: dict[str, np.random.Generator],
) -> dict[str, list[PercussionEvent]]:
    """Build four related but independently controlled percussion lanes."""
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

        prime_accent = (step + 1) in prime_values
        fib_accent = (step % 21) in fib_values
        break_probability = 0.12 + complexity * 0.36
        break_hit = bool(break_rng.random() < break_probability)
        if prime_accent:
            break_hit = break_hit or bool(break_rng.random() < 0.42 + complexity * 0.20)
        if fib_accent:
            break_hit = break_hit or bool(break_rng.random() < 0.25 + complexity * 0.18)
        if break_hit:
            selector = float(break_rng.random())
            if selector < 0.37:
                kind = "kick"
            elif selector < 0.70:
                kind = "snare"
            else:
                kind = "hat"
            velocity = float(break_rng.uniform(0.28, 0.82))
            pan = float(break_rng.uniform(-0.65, 0.65))
            lane_events["break"].append(
                PercussionEvent("break", step, step * step_seconds, velocity, pan, kind)
            )

    return lane_events
