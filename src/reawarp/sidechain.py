"""Bounded, deterministic offline sidechain envelope routing.

The detector always reads an immutable source stem before inserts and faders.
Its gain envelope is applied to a different target stem before that target's
insert and sends. This is a one-way control relationship, not a signal graph.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np


def _number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    return result


@dataclass(frozen=True, slots=True)
class SidechainRoute:
    """One source-detector to target-gain relationship."""

    route_id: str
    source_stem: str
    target_stem: str
    detector_mode: str = "peak"
    threshold_db: float = -24.0
    ratio: float = 8.0
    max_reduction_db: float = 9.0
    attack_ms: float = 2.0
    release_ms: float = 120.0
    hysteresis_db: float = 1.5
    control_rate_hz: float = 1_000.0

    def __post_init__(self) -> None:
        if not self.route_id.strip() or len(self.route_id) > 96:
            raise ValueError("sidechain route_id must contain 1–96 characters")
        if not self.source_stem.strip() or not self.target_stem.strip():
            raise ValueError("sidechain source_stem and target_stem cannot be empty")
        if self.source_stem == self.target_stem:
            raise ValueError("sidechain source and target must be different stems")
        if self.detector_mode not in {"peak", "rms"}:
            raise ValueError("sidechain detector_mode must be peak or rms")
        _number(self.threshold_db, "sidechain threshold_db", -96.0, 0.0)
        _number(self.ratio, "sidechain ratio", 1.0, 20.0)
        _number(self.max_reduction_db, "sidechain max_reduction_db", 0.0, 24.0)
        _number(self.attack_ms, "sidechain attack_ms", 0.1, 500.0)
        _number(self.release_ms, "sidechain release_ms", 1.0, 5_000.0)
        _number(self.hysteresis_db, "sidechain hysteresis_db", 0.0, 24.0)
        _number(self.control_rate_hz, "sidechain control_rate_hz", 50.0, 2_000.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "source_stem": self.source_stem,
            "target_stem": self.target_stem,
            "detector_mode": self.detector_mode,
            "threshold_db": float(self.threshold_db),
            "ratio": float(self.ratio),
            "max_reduction_db": float(self.max_reduction_db),
            "attack_ms": float(self.attack_ms),
            "release_ms": float(self.release_ms),
            "hysteresis_db": float(self.hysteresis_db),
            "control_rate_hz": float(self.control_rate_hz),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SidechainRoute":
        allowed = {
            "route_id", "source_stem", "target_stem", "detector_mode",
            "threshold_db", "ratio", "max_reduction_db", "attack_ms",
            "release_ms", "hysteresis_db", "control_rate_hz",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError("unknown sidechain field(s): " + ", ".join(sorted(map(str, unknown))))
        return cls(
            route_id=str(value.get("route_id", "")),
            source_stem=str(value.get("source_stem", "")),
            target_stem=str(value.get("target_stem", "")),
            detector_mode=str(value.get("detector_mode", "peak")),
            threshold_db=_number(value.get("threshold_db", -24.0), "sidechain threshold_db", -96.0, 0.0),
            ratio=_number(value.get("ratio", 8.0), "sidechain ratio", 1.0, 20.0),
            max_reduction_db=_number(value.get("max_reduction_db", 9.0), "sidechain max_reduction_db", 0.0, 24.0),
            attack_ms=_number(value.get("attack_ms", 2.0), "sidechain attack_ms", 0.1, 500.0),
            release_ms=_number(value.get("release_ms", 120.0), "sidechain release_ms", 1.0, 5_000.0),
            hysteresis_db=_number(value.get("hysteresis_db", 1.5), "sidechain hysteresis_db", 0.0, 24.0),
            control_rate_hz=_number(value.get("control_rate_hz", 1_000.0), "sidechain control_rate_hz", 50.0, 2_000.0),
        )


def normalise_sidechain_routes(
    payload: Sequence[Mapping[str, Any]] | None,
    stem_names: Sequence[str],
    sample_rate: int,
) -> list[dict[str, Any]]:
    """Validate a bounded list of one-way detector-to-target routes."""
    if payload is None:
        payload = ()
    if isinstance(payload, (str, bytes)) or not isinstance(payload, Sequence):
        raise ValueError("sidechains must be an array of route objects")
    if len(payload) > 32:
        raise ValueError("sidechains cannot contain more than 32 routes")
    names = set(stem_names)
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(payload):
        if not isinstance(raw, Mapping):
            raise ValueError(f"sidechain route {index} must be an object")
        route = SidechainRoute.from_mapping(raw)
        if route.route_id in seen:
            raise ValueError(f"duplicate sidechain route_id: {route.route_id}")
        seen.add(route.route_id)
        if route.source_stem not in names:
            raise ValueError(f"sidechain {route.route_id!r} references unknown source stem {route.source_stem!r}")
        if route.target_stem not in names:
            raise ValueError(f"sidechain {route.route_id!r} references unknown target stem {route.target_stem!r}")
        if route.control_rate_hz > float(sample_rate):
            raise ValueError("sidechain control_rate_hz cannot exceed the sample rate")
        result.append(route.to_dict())
    return result


def render_sidechain_gain_envelope(
    source_audio: np.ndarray,
    frames: int,
    sample_rate: int,
    settings: Mapping[str, Any] | SidechainRoute,
    *,
    cancel_event: Any | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Create a smooth, linked-channel gain envelope from a source stem.

    Peak/RMS detection is evaluated on short control blocks. Attack/release
    smoothing and threshold hysteresis are applied to the requested reduction;
    linear interpolation then produces a sample-aligned gain curve.
    """
    route = settings if isinstance(settings, SidechainRoute) else SidechainRoute.from_mapping(settings)
    if isinstance(sample_rate, bool) or int(sample_rate) <= 0:
        raise ValueError("sidechain sample_rate must be positive")
    if isinstance(frames, bool) or int(frames) < 0:
        raise ValueError("sidechain frames must be non-negative")
    frames = int(frames)
    sample_rate = int(sample_rate)
    if route.control_rate_hz > float(sample_rate):
        raise ValueError("sidechain control_rate_hz cannot exceed the sample rate")
    source = np.asarray(source_audio, dtype=np.float32)
    if source.ndim == 1:
        source = source[:, None]
    if source.ndim != 2 or source.shape[1] not in {1, 2}:
        raise ValueError("sidechain source audio must be mono or stereo")
    if len(source) != frames:
        raise ValueError("sidechain source and target stems must have the same frame count")
    if not np.isfinite(source).all():
        raise ValueError("sidechain source audio contains non-finite samples")
    if frames == 0 or route.max_reduction_db <= 0.0:
        return np.ones(frames, dtype=np.float32), {
            "route_id": route.route_id,
            "source_stem": route.source_stem,
            "target_stem": route.target_stem,
            "max_reduction_db": 0.0,
            "mean_reduction_db": 0.0,
            "active_fraction": 0.0,
            "detector_peak_dbfs": -240.0,
            "control_rate_hz_actual": 0.0,
        }

    hop = max(1, int(round(sample_rate / route.control_rate_hz)))
    block_count = int(math.ceil(frames / hop))
    padded_frames = block_count * hop
    if padded_frames != frames:
        source = np.pad(source, ((0, padded_frames - frames), (0, 0)))
    blocks = source.reshape(block_count, hop, source.shape[1]).astype(np.float64, copy=False)
    if route.detector_mode == "peak":
        levels = np.max(np.abs(blocks), axis=(1, 2))
    else:
        levels = np.sqrt(np.mean(np.square(blocks), axis=(1, 2)))
    detector_db = 20.0 * np.log10(np.maximum(levels, 1e-12))

    attack_coefficient = 1.0 - math.exp(
        -(hop / float(sample_rate)) / (route.attack_ms / 1_000.0)
    )
    release_coefficient = 1.0 - math.exp(
        -(hop / float(sample_rate)) / (route.release_ms / 1_000.0)
    )
    reduction = np.zeros(block_count, dtype=np.float32)
    active = np.zeros(block_count, dtype=bool)
    held = False
    current = 0.0
    ratio_factor = 1.0 - 1.0 / route.ratio
    for index, detector_level in enumerate(detector_db):
        if cancel_event is not None and index % 2_048 == 0 and cancel_event.is_set():
            raise InterruptedError("sidechain render cancelled")
        if not held and detector_level >= route.threshold_db:
            held = True
        elif held and detector_level < route.threshold_db - route.hysteresis_db:
            held = False
        active[index] = held
        requested = 0.0
        if held:
            requested = min(
                route.max_reduction_db,
                max(0.0, float(detector_level) - route.threshold_db) * ratio_factor,
            )
        coefficient = attack_coefficient if requested > current else release_coefficient
        current += coefficient * (requested - current)
        reduction[index] = current

    control_frames = np.arange(block_count, dtype=np.float64) * float(hop)
    control_gain = np.power(10.0, -reduction.astype(np.float64) / 20.0)
    gain = np.interp(
        np.arange(frames, dtype=np.float64),
        control_frames,
        control_gain,
    ).astype(np.float32)
    summary = {
        "route_id": route.route_id,
        "source_stem": route.source_stem,
        "target_stem": route.target_stem,
        "max_reduction_db": float(np.max(reduction)) if len(reduction) else 0.0,
        "mean_reduction_db": float(np.mean(reduction)) if len(reduction) else 0.0,
        "active_fraction": float(np.mean(active)) if len(active) else 0.0,
        "detector_peak_dbfs": float(np.max(detector_db)) if len(detector_db) else -240.0,
        "control_rate_hz_actual": float(sample_rate / hop),
    }
    return np.ascontiguousarray(gain, dtype=np.float32), summary


__all__ = [
    "SidechainRoute",
    "normalise_sidechain_routes",
    "render_sidechain_gain_envelope",
]
