from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
import zipfile

import numpy as np

from reawarp.config import GenerationConfig
from reawarp.core.project import ReawarpProject
from reawarp.export.project_archive import export_project_package
from reawarp.fx_automation import normalise_fx_automation
from reawarp.fx_routing import default_fx_routing
from reawarp.score.events import MusicalEvent
from reawarp.score.model import Score


def _package_project() -> ReawarpProject:
    config = GenerationConfig(
        duration=5.0,
        sample_rate=22_050,
        seed=211,
        include_melody=False,
        include_texture=False,
        include_ambience=False,
    )
    frames = config.frame_count
    stems = {
        "kick": np.zeros((frames, 2), dtype=np.float32),
        "melody": np.zeros((frames, 2), dtype=np.float32),
    }
    stems["kick"][0] = (0.25, 0.25)
    stems["melody"][0] = (0.05, -0.05)
    score = Score(
        title="M26 handoff",
        events=(
            MusicalEvent(
                event_id="kick-1", voice_id="kick", onset_beats=0,
                duration_beats=Fraction(1, 4), kind="hit", velocity=0.8,
            ),
            MusicalEvent(
                event_id="melody-1", voice_id="melody", onset_beats=0,
                duration_beats=1, kind="note", pitch=69, velocity=0.7,
            ),
        ),
        metadata={
            "sample_rate": config.sample_rate,
            "duration_seconds": config.duration,
            "frame_count": frames,
            "render_stems": list(stems),
        },
    )
    return ReawarpProject(
        config=config, sample_rate=config.sample_rate,
        stems=stems, score=score,
    )


def test_complete_project_zip_contains_midi_and_reopens(tmp_path: Path):
    project = _package_project()
    destination = tmp_path / "full-project.zip"
    empty_automation = normalise_fx_automation(
        {"schema_version": 1, "lanes": {}}, tuple(project.stems)
    )
    output = export_project_package(
        project,
        destination,
        master_audio=project.render_master(),
        fx_routing=default_fx_routing(tuple(project.stems)),
        fx_automation=empty_automation,
        mix_data={"schema_version": 1, "description": "complete package test"},
        include_midi=True,
    )

    assert output.is_file()
    assert zipfile.is_zipfile(output)
    extracted = tmp_path / "unpacked"
    extracted.mkdir()
    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())
        assert {
            "PACKAGE_README.md", "manifest.json", "project.json", "score.json",
            "events.json", "master.wav", "stems/kick.wav", "stems/melody.wav",
            "mix.json", "fx_routing.json", "fx_automation.json",
            "midi/score.mid",
        } <= names
        voice_files = [name for name in names if name.startswith("midi/voices/") and name.endswith(".mid")]
        assert len(voice_files) == 2
        archive.extractall(extracted)

    manifest = json.loads((extracted / "manifest.json").read_text(encoding="utf-8"))
    inventory = {item["path"] for item in manifest["file_inventory"]}
    assert "midi/score.mid" in inventory
    assert all(name in inventory for name in voice_files)
    assert json.loads((extracted / "project.json").read_text(encoding="utf-8"))["export"]["midi"] is True

    reopened = ReawarpProject.load(extracted)
    assert set(reopened.stems) == {"kick", "melody"}
    assert reopened.frame_count == project.frame_count
