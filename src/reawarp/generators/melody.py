"""Geometric and nonlinear melodic event generation."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np

from reawarp.config import GenerationConfig
from reawarp.mathematics.sequences import lissajous, logistic_map


@dataclass(frozen=True, slots=True)
class MelodyEvent:
    step: int
    time: float
    frequency: float
    midi_note: int
    duration: float
    velocity: float
    pan: float
    source_x: float
    source_y: float

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)


def midi_to_frequency(note: float, reference: float = 440.0) -> float:
    return reference * (2.0 ** ((float(note) - 69.0) / 12.0))


def build_melody_events(
    config: GenerationConfig,
    rng: np.random.Generator,
) -> list[MelodyEvent]:
    if not config.include_melody:
        return []
    step_seconds = config.sixteenth_seconds
    step_count = max(1, int(np.ceil(config.duration / step_seconds)))
    complexity = config.complexity
    count = max(10, int(config.duration * (1.8 + complexity * 1.6)))
    x_values, y_values = lissajous(count, a=3, b=5, phase=math.pi / 3.0 + complexity * 0.4)
    chaos = logistic_map(count, r=3.78 + 0.18 * complexity, x0=0.311)
    pitch_offsets = np.asarray([-12, -5, -1, 0, 2, 7, 11, 14, 19], dtype=int)
    events: list[MelodyEvent] = []
    base_note = 48 + int(round((complexity - 0.5) * 8.0))

    for index in range(count):
        normalized_time = index / max(1, count - 1)
        geometric_offset = int(round(x_values[index] * (1.0 + complexity * 2.0)))
        step = int(np.clip(round(normalized_time * (step_count - 1)) + geometric_offset, 0, step_count - 1))
        if index > 0 and step <= events[-1].step:
            continue
        if chaos[index] < (0.09 + (1.0 - complexity) * 0.10) and index not in (0, count - 1):
            continue
        pitch_index = int(
            np.clip(round((x_values[index] + 1.0) * 0.5 * (len(pitch_offsets) - 1)), 0, len(pitch_offsets) - 1)
        )
        midi_note = int(base_note + pitch_offsets[pitch_index])
        if y_values[index] > 0.84 and rng.random() < complexity * 0.55:
            midi_note += 12
        elif y_values[index] < -0.84 and rng.random() < complexity * 0.40:
            midi_note -= 12
        duration = float(np.clip(
            0.12 + (y_values[index] + 1.0) * 0.5 * (0.42 + complexity * 0.28),
            0.10,
            0.88,
        ))
        velocity = float(np.clip(0.38 + 0.45 * chaos[index] + rng.uniform(-0.08, 0.08), 0.18, 0.95))
        pan = float(np.clip(x_values[index] * 0.58, -0.75, 0.75))
        time = step * step_seconds
        if time >= config.duration:
            continue
        events.append(
            MelodyEvent(
                step=step,
                time=time,
                frequency=midi_to_frequency(midi_note),
                midi_note=midi_note,
                duration=min(duration, config.duration - time),
                velocity=velocity,
                pan=pan,
                source_x=float(x_values[index]),
                source_y=float(y_values[index]),
            )
        )
    return events
