from __future__ import annotations

from threading import Event

import numpy as np
import pytest

import reawarp.fx_routing as fx
from reawarp.fx_routing import (
    FX_ROUTING_SCHEMA_VERSION,
    FXRenderCancelledError,
    default_fx_routing,
    measure_signal,
    normalise_fx_routing,
    render_fx_routing,
    render_master_with_returns,
    role_aware_fx_routing,
)


def _dry(frames: int = 64):
    return {
        "kick": np.full((frames, 2), 0.1, dtype=np.float32),
        "snare": np.full((frames, 2), 0.1, dtype=np.float32),
        "hats": np.full((frames, 2), 0.1, dtype=np.float32),
        "synthetic_break": np.full((frames, 2), 0.1, dtype=np.float32),
        "melody": np.full((frames, 2), 0.1, dtype=np.float32),
        "noise_texture": np.full((frames, 2), 0.1, dtype=np.float32),
        "ambience": np.full((frames, 2), 0.1, dtype=np.float32),
        "mystery": np.full((frames, 2), 0.1, dtype=np.float32),
    }


def test_role_aware_defaults_assign_effects_without_manual_per_stem_sends():
    stems = _dry(32)
    routing = role_aware_fx_routing(tuple(stems))
    assert routing["schema_version"] == FX_ROUTING_SCHEMA_VERSION
    assert routing["routing_mode"] == "role_auto"
    assert routing["stems"]["kick"]["insert"]["kind"] == "bypass"
    assert routing["stems"]["kick"]["sends"] == {"space": 0.0, "echo": 0.0}
    for role in ("snare", "hats", "synthetic_break", "melody", "noise_texture"):
        assert routing["stems"][role]["insert"]["kind"] == "preset"
        assert sum(routing["stems"][role]["sends"].values()) > 0.0
    assert routing["stems"]["ambience"]["sends"]["space"] > 0
    assert routing["stems"]["mystery"]["insert"]["kind"] == "bypass"
    assert routing["stems"]["mystery"]["sends"] == {"space": 0.0, "echo": 0.0}


def test_v1_routing_migrates_to_v2_without_changing_manual_values():
    legacy = {
        "schema_version": 1,
        "master_wet": 0.82,
        "stems": {
            "kick": {
                "insert": {"kind": "bypass"},
                "sends": {"space": 0.12, "echo": 0.04},
            },
        },
        "buses": {
            "space": {"chain": "restrained_space", "wet": 0.25, "tail_seconds": 2.0},
            "echo": {"chain": "tape_echo", "wet": 0.18, "tail_seconds": 1.5},
        },
    }
    migrated = normalise_fx_routing(legacy, ("kick",), 48_000)
    assert migrated["schema_version"] == 2
    assert migrated["routing_mode"] == "manual"
    assert migrated["stems"]["kick"]["sends"] == {"space": 0.12, "echo": 0.04}
    assert migrated["stems"]["kick"]["send_taps"] == {
        "space": "post_insert_post_fader",
        "echo": "post_insert_post_fader",
    }
    assert migrated["master_wet"] == pytest.approx(0.82)


def test_four_send_taps_select_pre_post_insert_and_fader_contributions(monkeypatch):
    source = np.full((32, 2), 0.1, dtype=np.float32)
    calls = []

    def insert(audio, sample_rate, *, preset=None, stages=None, wet=1.0, tail_seconds=0.0):
        calls.append((preset, stages))
        tail = np.full((8, 2), 0.2, dtype=np.float32)
        return np.concatenate((np.asarray(audio, dtype=np.float32) * 2.0, tail))

    monkeypatch.setattr(fx, "render_pyo_fx", insert)
    tap_expected = {
        "pre_insert_pre_fader": 0.1,
        "pre_insert_post_fader": 0.05,
        "post_insert_pre_fader": 0.2,
        "post_insert_post_fader": 0.1,
    }
    for tap, expected in tap_expected.items():
        route = default_fx_routing(("melody",))
        route["stems"]["melody"]["insert"] = {
            "kind": "preset", "preset": "restrained_space",
            "wet": 1.0, "tail_seconds": 0.01,
        }
        route["stems"]["melody"]["sends"]["space"] = 1.0
        route["stems"]["melody"]["send_taps"]["space"] = tap
        route["buses"]["space"]["wet"] = 0.0
        processed, meta = render_fx_routing(
            {"melody": source}, 1_000, route,
            mix_controls={"melody": {"gain": 0.5, "pan": 0.0}},
            include_audition_audio=True,
        )
        contribution = meta["audition_audio"]["sends"]["melody"]["space"]
        assert contribution[0, 0] == pytest.approx(expected, abs=1e-6)
        assert processed["melody"].shape[0] == 40
        assert meta["send_semantics"]["tap_points"] == [
            "pre_insert_pre_fader", "pre_insert_post_fader",
            "post_insert_pre_fader", "post_insert_post_fader",
        ]
    assert calls


def test_auxiliary_returns_are_wet_only_metered_and_extend_the_master(monkeypatch):
    source = np.full((64, 2), 0.1, dtype=np.float32)
    seen_stages = []

    def fx_render(audio, sample_rate, *, preset=None, stages=None, wet=1.0, tail_seconds=0.0):
        seen_stages.append(tuple(dict(stage) for stage in (stages or ())))
        input_audio = np.asarray(audio, dtype=np.float32)
        tail = np.full((16, input_audio.shape[1]), 0.005, dtype=np.float32)
        return np.concatenate((input_audio * 0.4, tail))

    monkeypatch.setattr(fx, "render_pyo_fx", fx_render)
    route = default_fx_routing(("snare",))
    route["stems"]["snare"]["sends"]["space"] = 0.5
    route["buses"]["space"]["wet"] = 0.5
    processed_a, metadata_a = render_fx_routing(
        {"snare": source}, 8_000, route, include_audition_audio=True,
    )
    processed_b, metadata_b = render_fx_routing(
        {"snare": source}, 8_000, route,
    )
    returns = metadata_a["bus_returns_audio"]["space"]
    assert processed_a["snare"].shape == source.shape
    assert returns.shape == (80, 2)
    assert returns[0, 0] == pytest.approx(0.01, abs=1e-6)
    assert returns[-1, 0] == pytest.approx(0.0025, abs=1e-6)
    assert all(stage["mix"] == pytest.approx(1.0) for stage in seen_stages[-1])
    assert metadata_a["tails"]["space"]["tail_frames"] == 16
    assert metadata_a["latency"]["space"]["frames"] == 0
    assert metadata_a["meters"]["direct"]["snare"]["peak_dbfs"] > -30
    assert metadata_a["meters"]["sends"]["snare"]["space"]["rms_dbfs"] > -30
    assert metadata_a["meters"]["returns"]["space"]["rms_dbfs"] > -60
    np.testing.assert_array_equal(source, np.full((64, 2), 0.1, dtype=np.float32))
    master_a = render_master_with_returns(processed_a, metadata_a["bus_returns_audio"])
    master_b = render_master_with_returns(processed_b, metadata_b["bus_returns_audio"])
    np.testing.assert_array_equal(master_a, master_b)
    assert len(master_a) == 80


def test_mute_solo_and_post_fader_send_gain_are_applied_in_the_routing_pass(monkeypatch):
    def passthrough(audio, sample_rate, **kwargs):
        return np.asarray(audio, dtype=np.float32).copy()

    monkeypatch.setattr(fx, "render_pyo_fx", passthrough)
    stems = {
        "snare": np.full((32, 2), 0.2, dtype=np.float32),
        "hats": np.full((32, 2), 0.1, dtype=np.float32),
    }
    route = default_fx_routing(tuple(stems))
    for name in stems:
        route["stems"][name]["sends"]["space"] = 1.0
        route["buses"]["space"]["wet"] = 0.0
    _, meta = render_fx_routing(
        stems, 8_000, route,
        mix_controls={
            "snare": {"gain": 0.5, "pan": 0.0, "mute": True, "solo": False},
            "hats": {"gain": 0.25, "pan": 0.0, "mute": False, "solo": True},
        },
        include_audition_audio=True,
    )
    sends = meta["audition_audio"]["sends"]
    assert not np.any(sends["snare"]["space"])
    assert sends["hats"]["space"][0, 0] == pytest.approx(0.025)
    assert meta["active_send_stems_by_bus"]["space"] == ["hats"]


def test_mono_silence_and_signal_meters_remain_finite():
    mono = np.zeros(128, dtype=np.float32)
    route = default_fx_routing(("kick",))
    processed, metadata = render_fx_routing({"kick": mono}, 8_000, route)
    assert processed["kick"].shape == (128, 1)
    assert metadata["meters"]["direct"]["kick"]["rms_dbfs"] == -240.0
    meter = measure_signal(mono, sample_rate=8_000)
    assert meter["peak_dbfs"] == -240.0
    assert meter["crest_factor_db"] == 0.0
    assert np.isfinite(list(meter.values())[1:]).all()


def test_cancellable_fx_render_stops_before_processing(monkeypatch):
    cancel = Event()
    cancel.set()
    with pytest.raises(FXRenderCancelledError, match="cancelled"):
        render_fx_routing(
            {"kick": np.zeros((64, 2), dtype=np.float32)},
            48_000, default_fx_routing(("kick",)), cancel_event=cancel,
        )


def test_pre_fader_send_can_leave_muted_track_silent_but_ignores_fader_gain(monkeypatch):
    def passthrough(audio, sample_rate, **kwargs):
        return np.asarray(audio, dtype=np.float32).copy()

    monkeypatch.setattr(fx, "render_pyo_fx", passthrough)
    signal = np.full((32, 2), 0.2, dtype=np.float32)
    route = default_fx_routing(("melody",))
    route["stems"]["melody"]["sends"]["space"] = 1.0
    route["stems"]["melody"]["send_taps"]["space"] = "pre_insert_pre_fader"
    route["buses"]["space"]["wet"] = 0.0
    _, metadata = render_fx_routing(
        {"melody": signal}, 8_000, route,
        mix_controls={"melody": {"gain": 0.1, "pan": 0.5, "mute": False, "solo": False}},
        include_audition_audio=True,
    )
    send = metadata["audition_audio"]["sends"]["melody"]["space"]
    assert send[0, 0] == pytest.approx(0.2)
    assert send[0, 1] == pytest.approx(0.2)
