"""In-memory generation result and synchronized stem export."""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from reawarp.config import GenerationConfig
from reawarp.export.wav import write_wav


@dataclass(slots=True)
class ReawarpProject:
    config: GenerationConfig
    sample_rate: int
    stems: dict[str, np.ndarray]
    events: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def frame_count(self) -> int:
        return next(iter(self.stems.values())).shape[0] if self.stems else self.config.frame_count

    @property
    def duration(self) -> float:
        return self.frame_count / float(self.sample_rate)

    def to_score(self, *, title: str | None = None):
        """Return the synthesizer-independent symbolic score for this render."""
        from reawarp.score.conversion import project_to_score

        return project_to_score(self, title=title)

    def render_master(self) -> np.ndarray:
        if not self.stems:
            return np.zeros((self.config.frame_count, 2), dtype=np.float32)
        master = np.zeros_like(next(iter(self.stems.values())), dtype=np.float32)
        for stem in self.stems.values():
            master += stem
        peak = float(np.max(np.abs(master))) if master.size else 0.0
        ceiling = 10.0 ** (-1.0 / 20.0)
        if peak > ceiling:
            master *= ceiling / peak
        return np.clip(master, -1.0, 1.0).astype(np.float32, copy=False)

    def export(
            self,
            directory: str | Path,
            *,
            bit_depth: int = 24,
            include_stems: bool = True,
            include_master: bool = True,
    ) -> Path:
        output = Path(directory).expanduser()
        output.mkdir(parents=True, exist_ok=True)
        if include_stems:
            stem_directory = output / "stems"
            stem_directory.mkdir(parents=True, exist_ok=True)
            for name, audio in self.stems.items():
                write_wav(stem_directory / f"{name}.wav", audio, self.sample_rate, bit_depth)
        if include_master:
            write_wav(output / "master.wav", self.render_master(), self.sample_rate, bit_depth)

        project_record = {
            "schema_version": 1,
            "application": "eli_lab-reawarp",
            "application_version": "0.10.0",
            "python_version": platform.python_version(),
            "sample_rate": self.sample_rate,
            "duration_seconds": self.duration,
            "frame_count": self.frame_count,
            "config": self.config.to_dict(),
            "metadata": self.metadata,
            "stems": list(self.stems),
            "export": {"bit_depth": bit_depth, "master": include_master, "stems": include_stems},
        }
        (output / "project.json").write_text(
            json.dumps(project_record, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (output / "events.json").write_text(
            json.dumps({"schema_version": 1, "events": self.events}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self.to_score().save(output / "score.json")
        return output
