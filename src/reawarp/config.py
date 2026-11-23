"""Validated, serializable generation settings."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class GenerationConfig:
    bpm: float = 137.0
    duration: float = 12.0
    sample_rate: int = 48_000
    seed: int | str = 20261123
    complexity: float = 0.68
    include_melody: bool = True
    include_texture: bool = True
    sample_paths: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 60.0 <= float(self.bpm) <= 220.0:
            raise ValueError("bpm must be between 60 and 220")
        if not 5.0 <= float(self.duration) <= 20.0:
            raise ValueError("duration must be between 5 and 20 seconds")
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

    @property
    def frame_count(self) -> int:
        return int(round(self.duration * self.sample_rate))

    @property
    def sixteenth_seconds(self) -> float:
        return 60.0 / float(self.bpm) / 4.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["sample_paths"] = {role: str(Path(path)) for role, path in self.sample_paths.items()}
        return data
