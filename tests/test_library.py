"""Tests for the M6 local sample and stem library."""

from __future__ import annotations

import numpy as np
import pytest

from reawarp import GenerationConfig, ReawarpEngine
from reawarp.export.wav import write_wav
from reawarp.library import SampleLibrary, analyze_audio_file


def _pulse_audio(sample_rate: int, duration: float, interval: float) -> np.ndarray:
    audio = np.zeros(int(sample_rate * duration), dtype=np.float32)
    burst_length = max(64, int(sample_rate * 0.075))
    window = np.hanning(burst_length).astype(np.float32)
    tone_time = np.arange(burst_length, dtype=np.float32) / sample_rate
    burst = (0.65 * np.sin(2.0 * np.pi * 140.0 * tone_time) * window).astype(np.float32)
    for onset in np.arange(0.12, duration - 0.05, interval):
        start = int(round(onset * sample_rate))
        end = min(len(audio), start + burst_length)
        audio[start:end] += burst[:end - start]
    return np.clip(audio, -0.95, 0.95)


def test_audio_features_capture_timbre_and_repeating_rhythm(tmp_path):
    sample_rate = 22_050
    source = _pulse_audio(sample_rate, 4.0, 0.5)
    path = write_wav(tmp_path / "pulse_break.wav", source, sample_rate, 16)

    source_info, features = analyze_audio_file(path)

    assert source_info["source_sample_rate"] == sample_rate
    assert source_info["channels"] == 2
    assert features.duration_seconds == pytest.approx(4.0, abs=1.0 / sample_rate)
    assert features.peak > 0.1
    assert features.rms > 0.01
    assert features.spectral_centroid_hz > 0.0
    assert 0.0 <= features.spectral_flatness <= 1.0
    assert features.onset_count >= 3
    assert features.onset_density_per_second > 0.0
    assert len(features.rhythm_histogram) == 16
    assert sum(features.rhythm_histogram) == pytest.approx(1.0)


def test_index_search_similarity_and_idempotent_reindex(tmp_path):
    sample_rate = 22_050
    kick = write_wav(
        tmp_path / "kick_pulse.wav",
        _pulse_audio(sample_rate, 3.0, 0.5),
        sample_rate,
        16,
    )
    snare_audio = np.random.default_rng(9).standard_normal(sample_rate * 3).astype(np.float32) * 0.08
    snare = write_wav(tmp_path / "noise_snare.wav", snare_audio, sample_rate, 16)
    tone_time = np.arange(sample_rate * 3, dtype=np.float32) / sample_rate
    steady_audio = (0.12 * np.sin(2.0 * np.pi * 220.0 * tone_time)).astype(np.float32)
    steady = write_wav(tmp_path / "steady_tone.wav", steady_audio, sample_rate, 16)

    with SampleLibrary(":memory:") as library:
        first = library.index_file(
            kick, role="kick", tags=("idm", "percussion"),
            metadata={"source": "test-fixture"},
        )
        repeated = library.index_file(
            kick, role="kick", tags=("idm", "percussion"),
            metadata={"source": "test-fixture"},
        )
        other = library.index_file(snare, role="snare", tags=("noise", "percussion"))
        tonal = library.index_file(steady, role="pad", tags=("tonal",))

        assert first.asset_id == repeated.asset_id
        assert first.sha256 == repeated.sha256
        assert len(library.search(role="kick")) == 1
        assert len(library.search(tags=("percussion",))) == 2
        similar = library.search(similar_to=first.asset_id, limit=2)
        assert similar[0].asset_id == first.asset_id
        assert similar[0].similarity == pytest.approx(1.0)
        assert other.asset_id != first.asset_id
        assert library.search(query="noise_snare")[0].asset_id == other.asset_id
        tonal_match = library.search(similar_to=tonal.asset_id, limit=3)
        assert tonal_match[0].asset_id == tonal.asset_id
        assert tonal_match[0].similarity == pytest.approx(1.0)


def test_collections_create_add_show_and_remove(tmp_path):
    sample_rate = 22_050
    path_a = write_wav(
        tmp_path / "a.wav", _pulse_audio(sample_rate, 2.0, 0.4), sample_rate, 16
    )
    path_b = write_wav(
        tmp_path / "b.wav", _pulse_audio(sample_rate, 2.0, 0.6), sample_rate, 16
    )

    with SampleLibrary(":memory:") as library:
        first = library.index_file(path_a)
        second = library.index_file(path_b)
        collection_id = library.create_collection("IDM Cuts", "Selected break material")
        assert collection_id == library.create_collection("idm cuts", "Updated description")
        assert library.add_to_collection("IDM Cuts", [first.asset_id, second.asset_id]) == 2
        assert len(library.collection_assets("idm cuts")) == 2
        assert library.collections()[0]["description"] == "Updated description"
        assert library.remove_from_collection("IDM Cuts", [first.asset_id]) == 1
        assert [asset.asset_id for asset in library.collection_assets("IDM Cuts")] == [
            second.asset_id
        ]


def test_project_indexing_builds_stem_assets_and_variation_genealogy(tmp_path):
    engine = ReawarpEngine()
    config = GenerationConfig(
        duration=5.0, sample_rate=22_050, seed=684, complexity=0.45
    )
    base_project = engine.generate(config)
    base_dir = base_project.export(tmp_path / "base-project")
    variant_project = engine.generate_variant(config, "kick", variation=3)
    variant_dir = variant_project.export(tmp_path / "kick-variation")

    with SampleLibrary(":memory:") as library:
        # Indexing the child first must still attach it when its root arrives later.
        variant = library.index_project(variant_dir)
        base = library.index_project(base_dir)

        assert base["family_id"] == variant["family_id"]
        genealogy = library.genealogy(base["family_id"])
        assert len(genealogy) == 2
        assert genealogy[0]["variation_stem"] is None
        assert genealogy[1]["variation_stem"] == "kick"
        assert genealogy[1]["variation_index"] == 3
        assert genealogy[1]["parent_project_id"] == base["project_id"]
        assert len(library.search(asset_type="stem")) == len(base_project.stems) + len(variant_project.stems)
        assert library.search(asset_type="stem", role="ambience")
