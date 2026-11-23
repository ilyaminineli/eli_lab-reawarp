"""Integer and modular rhythm generators."""

from __future__ import annotations


def euclidean_rhythm(pulses: int, steps: int, rotation: int = 0) -> list[bool]:
    """Return a balanced Euclidean rhythm using a modular/Bresenham construction."""
    if steps < 1:
        raise ValueError("steps must be positive")
    if not 0 <= pulses <= steps:
        raise ValueError("pulses must be between zero and steps")
    if pulses == 0:
        pattern = [False] * steps
    else:
        pattern = [((index * pulses) % steps) < pulses for index in range(steps)]
    shift = rotation % steps
    if shift:
        pattern = pattern[-shift:] + pattern[:-shift]
    return pattern


def rotate_pattern(pattern: list[bool], amount: int) -> list[bool]:
    if not pattern:
        return []
    shift = amount % len(pattern)
    return pattern[-shift:] + pattern[:-shift] if shift else list(pattern)
