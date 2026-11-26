"""Deterministic mathematical sequences used as musical control sources."""

from __future__ import annotations

import math

import numpy as np


def fibonacci(count: int) -> list[int]:
    if count < 0:
        raise ValueError("count cannot be negative")
    values: list[int] = []
    a, b = 0, 1
    for _ in range(count):
        values.append(a)
        a, b = b, a + b
    return values


def primes(count: int) -> list[int]:
    """Return the first count primes using a simple expanding sieve."""
    if count < 0:
        raise ValueError("count cannot be negative")
    if count == 0:
        return []
    limit = max(
        16, int(count * (math.log(count + 1) + math.log(math.log(count + 2)))) + 16
    )
    while True:
        sieve = np.ones(limit + 1, dtype=bool)
        sieve[:2] = False
        for number in range(2, int(math.sqrt(limit)) + 1):
            if sieve[number]:
                sieve[number * number :: number] = False
        result = np.flatnonzero(sieve).tolist()
        if len(result) >= count:
            return [int(value) for value in result[:count]]
        limit *= 2


def logistic_map(
    count: int,
    r: float = 3.91,
    x0: float = 0.217,
    transient: int = 32,
) -> np.ndarray:
    """Generate a bounded logistic-map trajectory in [0, 1]."""
    if count < 0:
        raise ValueError("count cannot be negative")
    if not 0.0 < r <= 4.0:
        raise ValueError("r must be in (0, 4]")
    if not 0.0 < x0 < 1.0:
        raise ValueError("x0 must be in (0, 1)")
    x = float(x0)
    values: list[float] = []
    for index in range(count + max(0, transient)):
        x = r * x * (1.0 - x)
        if index >= transient:
            values.append(x)
    return np.asarray(values, dtype=np.float64)


def lissajous(
    count: int,
    a: int = 3,
    b: int = 5,
    phase: float = math.pi / 3.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Return normalized x/y coordinates sampled along a Lissajous curve."""
    if count < 0:
        raise ValueError("count cannot be negative")
    if count == 0:
        empty = np.empty(0, dtype=np.float64)
        return empty, empty.copy()
    t = np.linspace(0.0, 2.0 * math.pi, count, endpoint=False, dtype=np.float64)
    return np.sin(a * t + phase), np.sin(b * t)


def modular_sequence(
    count: int, modulus: int, multiplier: int = 5, offset: int = 1
) -> list[int]:
    if count < 0:
        raise ValueError("count cannot be negative")
    if modulus < 1:
        raise ValueError("modulus must be positive")
    return [((index * multiplier) + offset) % modulus for index in range(count)]


def random_walk(
    count: int,
    rng: np.random.Generator,
    start: float = 0.5,
    step_size: float = 0.18,
    lower: float = 0.0,
    upper: float = 1.0,
) -> np.ndarray:
    if count < 0:
        raise ValueError("count cannot be negative")
    if lower >= upper:
        raise ValueError("lower must be less than upper")
    if step_size < 0:
        raise ValueError("step_size cannot be negative")
    result = np.empty(count, dtype=np.float64)
    value = float(np.clip(start, lower, upper))
    for index in range(count):
        value = float(np.clip(value + rng.uniform(-step_size, step_size), lower, upper))
        result[index] = value
    return result
