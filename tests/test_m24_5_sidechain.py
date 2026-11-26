from __future__ import annotations

import os

import numpy as np
import pytest

from reawarp.fx_routing import (
    FX_ROUTING_SCHEMA_VERSION,
    default_fx_routing,
    normalise_fx_routing,
    render_fx_routing,
)
from reawarp.sidechain import (
    SidechainRoute,
    normalise_sidechain_routes,
    render_sidechain_gain_envelope,
)


def _route(**overrides):
    values = {
        "route_id": "kick_ducks_texture",
        "source_stem": "kick",
        "target_stem": "texture",
        "detector_mode": "peak",
        "threshold_db": -24.0,
        "ratio": 12.0,
        "max_reduction_db": 12.0,
        "attack_ms": 2.0,
        "release_ms": 90.0,
        "hysteresis_db": 2.0,
        "control_rate_hz": 1_000.0,
    }
    values.update(overrides)
    return values


def _kick_pulse(frames: int = 8_000) -> np.ndarray:
    signal = np.zeros((frames, 1), dtype=np.float32)
    signal[800:840, 0] = 0.8
    signal[2_400:2_440, 0] = 0.6
    return signal


def test_sidechain_route_is_bounded_and_rejects_invalid_relationships():
    valid = SidechainRoute.from_mapping(_route())
    assert valid.source_stem == "kick"
    assert valid.target_stem == "texture"
    assert normalise_sidechain_routes([_route()], ("kick", "texture"), 8_000)[0]["route_id"] == valid.route_id

    with pytest.raises(ValueError, match="different stems"):
        SidechainRoute.from_mapping(_route(target_stem="kick"))
    with pytest.raises(ValueError, match="unknown source stem"):
        normalise_sidechain_routes([_route(source_stem="missing")], ("kick", "texture"), 8_000)
    with pytest.raises(ValueError, match="duplicate sidechain route_id"):
        normalise_sidechain_routes([_route(), _route()], ("kick", "texture"), 8_000)
    with pytest.raises(ValueError, match="more than 32"):
        normalise_sidechain_routes(
            [_route(route_id=f"route_{index}") for index in range(33)],
            ("kick", "texture"), 8_000,
        )
    with pytest.raises(ValueError, match="threshold_db"):
        SidechainRoute.from_mapping(_route(threshold_db=1.0))


def test_schema_v3_migrates_to_v4_and_retains_sidechain_settings():
    legacy = default_fx_routing(("kick", "texture"))
    legacy["schema_version"] = 3
    legacy["sidechains"] = [_route()]
    migrated = normalise_fx_routing(legacy, ("kick", "texture"), 8_000)
    assert migrated["schema_version"] == FX_ROUTING_SCHEMA_VERSION == 4
    assert migrated["sidechains"] == [SidechainRoute.from_mapping(_route()).to_dict()]

    without_extension = normalise_fx_routing(
        {"schema_version": 3, "routing_mode": "role_auto", "stems": {}, "buses": {}},
        ("kick", "texture"), 8_000,
    )
    assert without_extension["sidechains"] == []


def test_peak_detector_creates_repeatable_smoothed_gain_and_respects_limits():
    source = _kick_pulse()
    before = source.copy()
    gain_a, summary_a = render_sidechain_gain_envelope(
        source, len(source), 8_000, _route()
    )
    gain_b, summary_b = render_sidechain_gain_envelope(
        source, len(source), 8_000, _route()
    )
    np.testing.assert_array_equal(gain_a, gain_b)
    np.testing.assert_array_equal(source, before)
    assert gain_a.shape == (len(source),)
    assert np.isfinite(gain_a).all()
    assert float(np.min(gain_a)) >= 10.0 ** (-24.0 / 20.0)
    assert float(np.min(gain_a[800:1_200])) < 0.5
    assert float(gain_a[1_100]) < float(gain_a[1_700])
    assert summary_a == summary_b
    assert summary_a["max_reduction_db"] <= 12.0
    assert summary_a["max_reduction_db"] > 6.0
    assert 0.0 < summary_a["active_fraction"] < 1.0


def test_silent_detector_does_not_trigger_and_rms_mode_is_supported():
    silence = np.zeros((2_000, 2), dtype=np.float32)
    gain, summary = render_sidechain_gain_envelope(
        silence, len(silence), 8_000, _route(detector_mode="rms")
    )
    np.testing.assert_array_equal(gain, np.ones(len(silence), dtype=np.float32))
    assert summary["active_fraction"] == 0.0
    assert summary["detector_peak_dbfs"] == -240.0


def test_fx_routing_applies_sidechain_before_target_insert_and_sends_without_mutation():
    frames = 8_000
    kick = _kick_pulse(frames)
    texture = np.full((frames, 1), 0.2, dtype=np.float32)
    kick_before, texture_before = kick.copy(), texture.copy()
    routing = default_fx_routing(("kick", "texture"))
    routing["sidechains"] = [_route()]
    result, metadata = render_fx_routing(
        {"kick": kick, "texture": texture},
        8_000,
        routing,
        include_audition_audio=True,
    )
    target = result["texture"][:, 0]
    assert target[100] == pytest.approx(0.2)
    assert float(np.min(target[800:1_200])) < 0.1
    assert target[1_100] < target[1_700]
    assert metadata["sidechain_summaries"][0]["bypassed"] is False
    assert metadata["meters"]["sidechain"]["kick_ducks_texture"]["max_reduction_db"] > 6.0
    assert "sidechain_gain" in metadata["audition_audio"]
    np.testing.assert_array_equal(kick, kick_before)
    np.testing.assert_array_equal(texture, texture_before)


def test_muted_or_solo_excluded_detector_source_cannot_duck_target():
    frames = 2_000
    kick = np.zeros((frames, 1), dtype=np.float32)
    kick[200:240] = 0.9
    texture = np.full((frames, 1), 0.15, dtype=np.float32)
    routing = default_fx_routing(("kick", "texture"))
    routing["stems"]["kick"]["mute"] = True
    routing["sidechains"] = [_route()]
    result, metadata = render_fx_routing(
        {"kick": kick, "texture": texture}, 8_000, routing
    )
    np.testing.assert_allclose(result["texture"], texture, atol=1e-7)
    assert metadata["sidechain_summaries"][0]["bypassed"] is True
    assert metadata["sidechain_summaries"][0]["bypass_reason"] == "source muted or excluded by solo"


def test_fx_routing_editor_can_add_and_remove_a_sidechain_route():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from reawarp.ui.pages.fx_routing import FXRoutingEditor

    app = QApplication.instance() or QApplication([])
    editor = FXRoutingEditor()
    editor.set_stems(("kick", "texture"), 8_000)
    editor.sidechain_source.setCurrentIndex(editor.sidechain_source.findData("kick"))
    editor.sidechain_target.setCurrentIndex(editor.sidechain_target.findData("texture"))
    editor.sidechain_save_button.click()
    routes = editor.routing()["sidechains"]
    assert len(routes) == 1
    route_id = routes[0]["route_id"]
    editor.sidechain_choice.setCurrentIndex(editor.sidechain_choice.findData(route_id))
    editor.sidechain_remove_button.click()
    assert editor.routing()["sidechains"] == []
    editor.close()
    app.processEvents()
