"""Headless smoke tests for the optional M4 desktop application."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication

from reawarp import GenerationConfig, ReawarpEngine
from reawarp.ui.main_window import MainWindow
from reawarp.ui.visualization import AudioPreview


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def test_main_window_exposes_generator_config_and_three_m4_workspaces(qt_app):
    window = MainWindow()
    config = window._read_config()
    assert config.bpm == 137
    assert config.duration == 24
    assert config.structure == "evolving"
    assert config.composition_energy == pytest.approx(0.62)
    assert config.composition_variation == pytest.approx(0.45)
    assert window.duration.maximum() == 45
    assert window.duration.maximum() == 45
    assert config.sample_rate == 48_000
    assert config.complexity == pytest.approx(0.68)
    assert config.break_style == "broken_funk"
    assert config.break_density == pytest.approx(0.50)
    assert config.break_variation == pytest.approx(0.25)
    assert config.break_cycle_bars == 2
    assert config.include_ambience is True
    assert config.ambience_level == pytest.approx(0.16)
    assert window.tabs.count() == 3
    assert [window.tabs.tabText(i) for i in range(3)] == [
        "GENERATOR", "BREAK LAB", "STEM MIXER"
    ]
    window.close()


def test_preview_renders_waveform_spectrogram_and_slice_markers(qt_app):
    preview = AudioPreview()
    sample_rate = 8_000
    time = np.arange(4_096, dtype=np.float32) / sample_rate
    audio = np.sin(2 * np.pi * 220 * time).astype(np.float32)
    preview.set_audio(audio, sample_rate, markers=[1_024, 2_048])
    assert preview._duration == pytest.approx(len(audio) / sample_rate)
    assert len(preview.marker_items) == 2
    assert preview.spectrum_item.image is not None
    preview.close()


def test_mixer_mute_does_not_modify_rendered_stem_buffers(qt_app):
    window = MainWindow()
    project = ReawarpEngine().generate(
        GenerationConfig(duration=5.0, sample_rate=22_050, seed=391, complexity=0.4)
    )
    window.project = project
    window._rebuild_mixer()
    original = {name: stem.copy() for name, stem in project.stems.items()}
    window._mix_rows["kick"].mute.setChecked(True)
    mixed = window._render_mix()
    assert mixed is not None
    assert mixed.shape == (project.frame_count, 2)
    assert np.all(np.isfinite(mixed))
    assert np.array_equal(project.stems["kick"], original["kick"])
    window.close()
