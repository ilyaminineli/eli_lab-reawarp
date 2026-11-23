"""Validated, serializable generation settings."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from reawarp.synthesis.profiles import HAT_PROFILES, KICK_PROFILES, MELODY_PROFILES, SNARE_PROFILES
from reawarp.transforms.pipeline import BREAK_TRANSFORMS


@dataclass(frozen=True, slots=True)
class GenerationConfig:
    bpm: float = 137.0
    duration: float = 24.0
    sample_rate: int = 48_000
    seed: int | str = 20261123
    complexity: float = 0.68
    include_melody: bool = True
    include_texture: bool = True
    include_ambience: bool = True
    ambience_level: float = 0.16
    sample_paths: dict[str, str] = field(default_factory=dict)
    kick_profile: str = "auto"
    snare_profile: str = "auto"
    hat_profile: str = "auto"
    melody_profile: str = "auto"
    break_style: str = "broken_funk"
    break_density: float = 0.50
    break_variation: float = 0.25
    break_cycle_bars: int = 2
    break_transforms: tuple[str, ...] = ()
    break_slice_count: int = 16
    break_stutter_repeats: int = 4
    break_dropout_probability: float = 0.18
    break_pitch_semitones: float = 0.0
    break_time_stretch: float = 1.0
    break_gate_rate_hz: float = 8.0
    break_gate_duty: float = 0.62
    break_grain_size_ms: float = 80.0
    break_grain_density: float = 1.5
    break_spectral_freeze_position: float = 0.25

    def __post_init__(self) -> None:
        if not 60.0 <= float(self.bpm) <= 220.0:
            raise ValueError("bpm must be between 60 and 220")
        if not 5.0 <= float(self.duration) <= 45.0:
            raise ValueError("duration must be between 5 and 45 seconds")
        if not 22_050 <= int(self.sample_rate) <= 192_000:
            raise ValueError("sample_rate must be between 22050 and 192000 Hz")
        if not 0.0 <= float(self.complexity) <= 1.0:
            raise ValueError("complexity must be between 0.0 and 1.0")
        allowed_roles = {"kick", "snare", "hat", "break"}
        unknown = set(self.sample_paths) - allowed_roles
        if unknown:
            raise ValueError(f"unsupported sample roles: {', '.join(sorted(unknown))}")
        for role, path in self.sample_paths.items():
            if not str(path).strip():
                raise ValueError(f"sample path for {role} cannot be empty")

        if self.kick_profile != "auto" and self.kick_profile not in KICK_PROFILES:
            raise ValueError(f"unknown kick profile: {self.kick_profile}")
        if self.snare_profile != "auto" and self.snare_profile not in SNARE_PROFILES:
            raise ValueError(f"unknown snare profile: {self.snare_profile}")
        if self.hat_profile != "auto" and self.hat_profile not in HAT_PROFILES:
            raise ValueError(f"unknown hi-hat profile: {self.hat_profile}")
        if self.melody_profile != "auto" and self.melody_profile not in MELODY_PROFILES:
            raise ValueError(f"unknown melody profile: {self.melody_profile}")
        if self.break_style not in {
            "auto", "broken_funk", "half_time", "straight", "sparse"
        }:
            raise ValueError("unknown break style")
        if not 0.0 <= float(self.break_density) <= 1.0:
            raise ValueError("break_density must be between 0.0 and 1.0")
        if not 0.0 <= float(self.break_variation) <= 1.0:
            raise ValueError("break_variation must be between 0.0 and 1.0")
        if int(self.break_cycle_bars) not in (1, 2, 4):
            raise ValueError("break_cycle_bars must be 1, 2, or 4")
        if not 0.0 <= float(self.ambience_level) <= 1.0:
            raise ValueError("ambience_level must be between 0.0 and 1.0")

        transforms = tuple(self.break_transforms)
        unknown_transforms = set(transforms) - set(BREAK_TRANSFORMS)
        if unknown_transforms:
            raise ValueError(
                f"unsupported break transforms: {', '.join(sorted(unknown_transforms))}"
            )
        object.__setattr__(self, "break_transforms", transforms)
        if not 2 <= int(self.break_slice_count) <= 128:
            raise ValueError("break_slice_count must be between 2 and 128")
        if not 2 <= int(self.break_stutter_repeats) <= 32:
            raise ValueError("break_stutter_repeats must be between 2 and 32")
        if not 0.0 <= float(self.break_dropout_probability) <= 1.0:
            raise ValueError("break_dropout_probability must be between zero and one")
        if not -24.0 <= float(self.break_pitch_semitones) <= 24.0:
            raise ValueError("break_pitch_semitones must be between -24 and 24")
        if not 0.25 <= float(self.break_time_stretch) <= 4.0:
            raise ValueError("break_time_stretch must be between 0.25 and 4.0")
        if not 0.1 <= float(self.break_gate_rate_hz) <= 100.0:
            raise ValueError("break_gate_rate_hz must be between 0.1 and 100")
        if not 0.05 <= float(self.break_gate_duty) <= 1.0:
            raise ValueError("break_gate_duty must be between 0.05 and 1.0")
        if not 5.0 <= float(self.break_grain_size_ms) <= 1000.0:
            raise ValueError("break_grain_size_ms must be between 5 and 1000 ms")
        if not 0.25 <= float(self.break_grain_density) <= 4.0:
            raise ValueError("break_grain_density must be between 0.25 and 4.0")
        if not 0.0 <= float(self.break_spectral_freeze_position) <= 1.0:
            raise ValueError("break_spectral_freeze_position must be between zero and one")

    @property
    def frame_count(self) -> int:
        return int(round(self.duration * self.sample_rate))

    @property
    def sixteenth_seconds(self) -> float:
        return 60.0 / float(self.bpm) / 4.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["sample_paths"] = {role: str(Path(path)) for role, path in self.sample_paths.items()}
        data["break_transforms"] = list(self.break_transforms)
        return data
