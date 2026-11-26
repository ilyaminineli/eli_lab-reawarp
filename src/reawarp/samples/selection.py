"""Feature-guided, deterministic selection from role-specific sample banks."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

# Targets are perceptual intentions, not genre presets. Values are normalized
# brightness, level, noisiness and transient density, respectively.
_PHRASE_TARGETS: dict[str, tuple[float, float, float, float]] = {
    "introduction": (0.28, 0.24, 0.28, 0.22),
    "establishment": (0.42, 0.45, 0.34, 0.38),
    "continuation": (0.48, 0.50, 0.42, 0.42),
    "development": (0.66, 0.58, 0.62, 0.60),
    "uplift": (0.78, 0.72, 0.66, 0.76),
    "arrival": (0.88, 0.82, 0.62, 0.80),
    "drop": (0.30, 0.25, 0.30, 0.24),
    "silence": (0.12, 0.12, 0.12, 0.08),
    "contrast": (0.82, 0.48, 0.72, 0.64),
    "false_return": (0.45, 0.34, 0.42, 0.30),
    "transition": (0.70, 0.58, 0.68, 0.72),
    "residue": (0.24, 0.19, 0.26, 0.16),
    "outro": (0.18, 0.14, 0.20, 0.12),
}

_FEATURE_WEIGHTS = (0.36, 0.30, 0.18, 0.16)


def _clamp01(value: float) -> float:
    return float(np.clip(float(value), 0.0, 1.0))


def _feature_vector(entry: Mapping[str, Any]) -> tuple[float, float, float, float]:
    """Normalize the library's descriptors without assuming every field exists."""
    raw = entry.get("features")
    features = raw if isinstance(raw, Mapping) else {}
    centroid = features.get("spectral_centroid_hz")
    rms_dbfs = features.get("rms_dbfs")
    flatness = features.get("spectral_flatness")
    onset_density = features.get("onset_density_per_second")

    brightness = (
        _clamp01(np.log(max(100.0, float(centroid)) / 100.0) / np.log(160.0))
        if centroid is not None
        else 0.5
    )
    level = _clamp01((float(rms_dbfs) + 48.0) / 42.0) if rms_dbfs is not None else 0.5
    noisiness = _clamp01(float(flatness)) if flatness is not None else 0.5
    transient_density = (
        _clamp01(float(onset_density) / 12.0) if onset_density is not None else 0.5
    )
    return brightness, level, noisiness, transient_density


def _feature_distance(
    entry: Mapping[str, Any],
    target: tuple[float, float, float, float],
) -> float:
    vector = _feature_vector(entry)
    return sum(
        weight * abs(value - target_value)
        for weight, value, target_value in zip(
            _FEATURE_WEIGHTS, vector, target, strict=True
        )
    )


def select_sample_variant(
    bank: Sequence[Mapping[str, Any]],
    *,
    role: str,
    phrase_function: str,
    seed: int,
    anchor_index: int = 0,
    previous_index: int | None = None,
    intensity: float = 0.68,
) -> int:
    """Choose a sample variant by phrase function and indexed audio features.

    The same inputs always return the same index. Returns recall the established
    anchor. False returns choose the closest non-anchor alternative. When a bank
    has no indexed descriptors, the deterministic seed still rotates material.
    """
    if not bank:
        raise ValueError("sample bank cannot be empty")
    count = len(bank)
    anchor = int(np.clip(anchor_index, 0, count - 1))
    if count == 1 or intensity <= 0.0:
        return anchor
    if phrase_function == "return":
        return anchor

    rng = np.random.default_rng(int(seed) & 0xFFFFFFFF)
    candidates = [index for index in range(count) if index != anchor]
    if not candidates:
        return anchor

    if phrase_function == "false_return":
        # A false return should resemble the anchor without duplicating it.
        reference = _feature_vector(bank[anchor])

        def anchor_distance(index: int) -> float:
            vector = _feature_vector(bank[index])
            return sum(
                weight * abs(value - target)
                for weight, value, target in zip(
                    _FEATURE_WEIGHTS, vector, reference, strict=True
                )
            )

        return min(candidates, key=lambda index: (anchor_distance(index), index))

    target = _PHRASE_TARGETS.get(phrase_function, _PHRASE_TARGETS["continuation"])
    if phrase_function == "contrast" and previous_index is not None:
        previous_vector = _feature_vector(
            bank[int(np.clip(previous_index, 0, count - 1))]
        )
        target = (
            1.0 - previous_vector[0],
            0.5,
            1.0 - previous_vector[2],
            1.0 - previous_vector[3],
        )

    distances = np.asarray(
        [_feature_distance(bank[index], target) for index in candidates],
        dtype=np.float64,
    )
    # Greater intensity makes stronger use of feature affinity and is more
    # willing to leave the anchor. Lower intensity favours nearby material.
    temperature = 0.08 + (1.0 - _clamp01(intensity)) * 0.34
    weights = np.exp(-(distances - float(np.min(distances))) / temperature)
    if previous_index in candidates and intensity >= 0.55 and len(candidates) > 1:
        previous_position = candidates.index(int(previous_index))
        weights[previous_position] *= 0.35
    weights /= max(float(weights.sum()), 1e-12)
    return int(rng.choice(np.asarray(candidates, dtype=np.int64), p=weights))
