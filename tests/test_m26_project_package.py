from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from reawarp.config import GenerationConfig
from reawarp.core.project import ReawarpProject
from reawarp.export.project_archive import export_project_package
from reawarp.export.wav import read_wav
from reawarp.score.events import MusicalEvent
from reawarp.score.model import Score
from fractions import Fraction


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
        title="M26 手渡し / test",
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


def test_delivery_folder_contains_only_readme_master_stems_and_midi(tmp_path: Path):
    project = _package_project()
    originals = {name: audio.copy() for name, audio in project.stems.items()}
    master = project.render_master()
    destination = tmp_path / "M26_Delivery"

    output = export_project_package(
        project,
        destination,
        master_audio=master,
        bit_depth=24,
        include_midi=True,
        fx_render_status="rendered",
    )

    assert output == destination
    assert output.is_dir()
    files = {
        item.relative_to(output).as_posix()
        for item in output.rglob("*")
        if item.is_file()
    }
    assert {
        "README.md",
        "master.wav",
        "stems/kick.wav",
        "stems/melody.wav",
        "midi/score.mid",
    } <= files
    voice_files = {
        item for item in files
        if item.startswith("midi/voices/") and item.endswith(".mid")
    }
    assert len(voice_files) == 2
    assert all(not item.startswith("assets/") for item in files)
    assert not any(item in files for item in {
        "project.json", "score.json", "events.json", "manifest.json",
        "fx_routing.json", "fx_automation.json", "mix.json",
    })
    assert not list(tmp_path.glob("*.zip"))

    readme = (output / "README.md").read_text(encoding="utf-8")
    assert "M26 手渡し / test" in readme
    assert "final routed mix" in readme
    assert "original aligned dry generation stems" in readme
    assert "no copied source samples" in readme

    exported_master, sample_rate = read_wav(output / "master.wav")
    assert sample_rate == project.sample_rate
    assert exported_master.shape == master.shape
    for name, original in originals.items():
        exported_stem, stem_rate = read_wav(output / "stems" / f"{name}.wav")
        assert stem_rate == project.sample_rate
        assert exported_stem.shape == original.shape
        np.testing.assert_allclose(project.stems[name], original)

    midi_score = Score.from_midi(output / "midi" / "score.mid")
    assert midi_score.title == "M26 手渡し / test"


def test_delivery_folder_readme_labels_dry_fx_fallback(tmp_path: Path):
    project = _package_project()
    output = export_project_package(
        project,
        tmp_path / "Dry_Fallback",
        master_audio=project.render_master(),
        fx_render_status="dry_fallback",
    )
    readme = (output / "README.md").read_text(encoding="utf-8")
    assert "FX rendering failed" in readme
    assert "No effects are claimed as rendered" in readme


def test_delivery_folder_does_not_overwrite_existing_directory(tmp_path: Path):
    project = _package_project()
    destination = tmp_path / "Existing"
    destination.mkdir()
    marker = destination / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        export_project_package(
            project, destination, master_audio=project.render_master()
        )

    assert marker.read_text(encoding="utf-8") == "keep"


def test_delivery_folder_cancellation_leaves_no_partial_output(tmp_path: Path):
    class CancelImmediately:
        @staticmethod
        def is_set() -> bool:
            return True

    project = _package_project()
    destination = tmp_path / "Cancelled"
    with pytest.raises(RuntimeError, match="cancelled"):
        export_project_package(
            project,
            destination,
            master_audio=project.render_master(),
            cancel_event=CancelImmediately(),
        )
    assert not destination.exists()
