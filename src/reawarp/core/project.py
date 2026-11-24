"""In-memory generation result and synchronized stem export."""

from __future__ import annotations

import json
import math
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
            "application_version": "0.12.0",
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

    @classmethod
    def load(cls, directory: str | Path) -> "ReawarpProject":
        """Reopen and validate a complete exported project folder."""
        from reawarp.export.wav import read_wav
        from reawarp.score.model import Score

        root = Path(directory).expanduser()
        record = json.loads((root / "project.json").read_text(encoding="utf-8"))
        if not isinstance(record, dict) or record.get("schema_version") != 1:
            raise ValueError("unsupported or invalid Reawarp project schema")
        if record.get("application") != "eli_lab-reawarp":
            raise ValueError("directory is not a Reawarp project")
        export_options = record.get("export", {})
        if not isinstance(export_options, dict) or not export_options.get("stems", True):
            raise ValueError("project export does not contain source stems")

        config_data = record.get("config")
        config = GenerationConfig.from_dict(config_data)
        sample_rate = int(record.get("sample_rate", 0))
        frame_count = int(record.get("frame_count", 0))
        if sample_rate <= 0 or frame_count <= 0:
            raise ValueError("project sample rate and frame count must be positive")
        if config.sample_rate != sample_rate or config.frame_count != frame_count:
            raise ValueError("project timing does not match its generation configuration")
        duration = float(record.get("duration_seconds", -1.0))
        expected_duration = frame_count / float(sample_rate)
        if not math.isfinite(duration) or not math.isclose(
                duration, expected_duration, rel_tol=0.0, abs_tol=1.0 / sample_rate
        ):
            raise ValueError("project duration does not match its frame count")

        stem_names = record.get("stems")
        if not isinstance(stem_names, list) or not stem_names:
            raise ValueError("project does not list any source stems")
        if len(stem_names) != len(set(stem_names)):
            raise ValueError("project stem names must be unique")

        stems: dict[str, np.ndarray] = {}
        safe_characters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for name in stem_names:
            if (
                not isinstance(name, str)
                or not name
                or name in {".", ".."}
                or any(character not in safe_characters for character in name)
            ):
                raise ValueError(f"invalid project stem name: {name!r}")
            audio, stem_rate = read_wav(root / "stems" / f"{name}.wav")
            if stem_rate != sample_rate:
                raise ValueError(f"stem {name!r} uses a different sample rate")
            if len(audio) != frame_count:
                raise ValueError(f"stem {name!r} is not aligned to the project frame count")
            if not np.isfinite(audio).all():
                raise ValueError(f"stem {name!r} contains non-finite samples")
            stems[name] = audio

        event_record = json.loads((root / "events.json").read_text(encoding="utf-8"))
        if not isinstance(event_record, dict) or event_record.get("schema_version") != 1:
            raise ValueError("unsupported or invalid project event schema")
        events = event_record.get("events")
        if not isinstance(events, list) or any(not isinstance(item, dict) for item in events):
            raise ValueError("project events must be a list of JSON objects")

        metadata = record.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("project metadata must be a JSON object")
        score = Score.load(root / "score.json")
        if int(score.metadata.get("sample_rate", 0)) != sample_rate:
            raise ValueError("project score sample rate does not match the audio stems")
        if list(score.metadata.get("render_stems", [])) != list(stem_names):
            raise ValueError("project score stem list does not match project.json")

        return cls(
            config=config,
            sample_rate=sample_rate,
            stems=stems,
            events=events,
            metadata=metadata,
        )
