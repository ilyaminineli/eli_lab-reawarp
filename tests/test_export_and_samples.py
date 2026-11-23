import json
import wave

import numpy as np
import pytest

from reawarp import GenerationConfig, ReawarpEngine
from reawarp.export.wav import write_wav
from reawarp.samples.io import read_sample


def test_24_bit_wav_export_round_trips_with_soundfile(tmp_path):
    sf = pytest.importorskip("soundfile")
    audio = np.zeros((2048, 2), dtype=np.float32)
    audio[:, 0] = np.linspace(-0.8, 0.8, 2048)
    audio[:, 1] = np.sin(np.linspace(0, 8 * np.pi, 2048)) * 0.5
    path = write_wav(tmp_path / "test24.wav", audio, 48_000, 24)
    loaded, sr = sf.read(path, dtype="float32", always_2d=True)
    assert sr == 48_000
    assert loaded.shape == audio.shape
    assert np.max(np.abs(loaded - audio)) < 2e-6


def test_sample_reader_pcm_wav_without_external_dependencies(tmp_path):
    audio = np.linspace(-0.7, 0.7, 512, dtype=np.float32)
    path = write_wav(tmp_path / "sample.wav", audio, 22_050, 16)
    loaded = read_sample(path, 44_100)
    assert loaded.dtype == np.float32
    assert len(loaded) == 1024
    assert np.max(np.abs(loaded)) <= 1.0


def test_project_export_writes_stems_master_and_metadata(tmp_path):
    config = GenerationConfig(duration=5, sample_rate=22_050, seed=44)
    project = ReawarpEngine().generate(config)
    output = project.export(tmp_path / "loop", bit_depth=24)
    assert (output / "master.wav").is_file()
    assert (output / "stems" / "kick.wav").is_file()
    project_data = json.loads((output / "project.json").read_text(encoding="utf-8"))
    events_data = json.loads((output / "events.json").read_text(encoding="utf-8"))
    assert project_data["sample_rate"] == 22_050
    assert "kick" in project_data["stems"]
    assert len(events_data["events"]) == len(project.events)
    score_data = json.loads((output / "score.json").read_text(encoding="utf-8"))
    assert score_data["format"] == "eli_lab_reawarp_score"
    assert len(score_data["events"]) == len(project.events)
    with wave.open(str(output / "master.wav"), "rb") as wav:
        assert wav.getframerate() == 22_050
        assert wav.getsampwidth() == 3
        assert wav.getnchannels() == 2


def test_custom_sample_is_added_as_independent_stem(tmp_path):
    sample = np.zeros(2048, dtype=np.float32)
    sample[0:256] = np.sin(np.linspace(0, 8 * np.pi, 256)) * 0.7
    sample_path = write_wav(tmp_path / "custom_snare.wav", sample, 22_050, 24)
    config = GenerationConfig(
        duration=5,
        sample_rate=22_050,
        seed=99,
        sample_paths={"snare": str(sample_path)},
    )
    project = ReawarpEngine().generate(config)
    assert "sample_snare" in project.stems
    assert np.max(np.abs(project.stems["sample_snare"])) > 0.0
    assert project.metadata["sample_sources"]["snare"]["trigger_count"] > 0
