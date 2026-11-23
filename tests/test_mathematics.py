import numpy as np
import pytest

from reawarp.mathematics.rhythms import euclidean_rhythm
from reawarp.mathematics.sequences import fibonacci, lissajous, logistic_map, primes


def test_euclidean_rhythm_has_requested_pulse_count():
    for steps in (8, 12, 16, 23):
        for pulses in range(steps + 1):
            pattern = euclidean_rhythm(pulses, steps)
            assert len(pattern) == steps
            assert sum(pattern) == pulses


def test_euclidean_rhythm_rotation_preserves_pulses():
    pattern = euclidean_rhythm(5, 16, rotation=7)
    assert len(pattern) == 16
    assert sum(pattern) == 5


def test_fibonacci_and_primes():
    assert fibonacci(8) == [0, 1, 1, 2, 3, 5, 8, 13]
    assert primes(8) == [2, 3, 5, 7, 11, 13, 17, 19]
    assert primes(0) == []


def test_logistic_map_is_bounded_and_deterministic():
    first = logistic_map(100, r=3.9, x0=0.2)
    second = logistic_map(100, r=3.9, x0=0.2)
    assert np.array_equal(first, second)
    assert np.all((first >= 0.0) & (first <= 1.0))


def test_lissajous_returns_normalized_coordinates():
    x, y = lissajous(64)
    assert x.shape == y.shape == (64,)
    assert np.max(np.abs(x)) <= 1.0
    assert np.max(np.abs(y)) <= 1.0


def test_invalid_euclidean_parameters_raise():
    with pytest.raises(ValueError):
        euclidean_rhythm(17, 16)
