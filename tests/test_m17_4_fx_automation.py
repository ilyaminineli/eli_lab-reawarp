from fractions import Fraction

import numpy as np
import pytest

from reawarp import (
    AutomationLane,
    AutomationPoint,
    MusicalEvent,
    ReawarpEngine,
    Score,
    TempoMap,
    TempoPoint,
    attach_fx_automation_to_score,
    score_to_fx_automation,
)
from reawarp.fx_automation import (
    fx_automation_registry,
    fx_automation_to_score_lanes,
    normalise_fx_automation,
)
import reawarp.fx_routing as fx_routing
from reawarp.fx_routing import default_fx_routing, render_fx_routing


def _payload():
    return {
        "schema_version": 1,
        "lanes": {
            "bus.space.wet": [
                {"beat": 0, "value": 0.18, "curve": "hold"},
                {"beat": 2, "value": 0.72, "curve": "smooth"},
                {"beat": 4, "value": 0.25, "curve": "linear"},
            ],
            "bus.echo.wet": [
                {"beat": 0.5, "value": 0.0, "curve": "linear"},
                {"beat": 3.5, "value": 0.6, "curve": "hold"},
            ],
            "stem.kick.insert_wet": [
                {"beat": 0, "value": 0.0, "curve": "linear"},
                {"beat": 1, "value": 0.9, "curve": "smooth"},
                {"beat": 4, "value": 0.2, "curve": "hold"},
            ],
            "stem.kick.send.space": [
                {"beat": 0, "value": 0.1, "curve": "linear"},
                {"beat": 2, "value": 0.55, "curve": "hold"},
            ],
            "stem.kick.send.echo": [
                {"beat": 0, "value": 0.0, "curve": "hold"},
                {"beat": 4, "value": 0.3, "curve": "linear"},
            ],
        },
    }


def _score(*, bpm=120.0, duration_seconds=2.0):
    return Score(
        title="M17.4 FX migration fixture",
        tempo_map=TempoMap.constant(bpm),
        events=(
            MusicalEvent(
                event_id="kick-a",
                voice_id="kick",
                onset_beats=Fraction(0),
                duration_beats=Fraction(4),
                kind="hit",
                velocity=0.5,
                seed=17,
            ),
        ),
        metadata={
            "render_stems": ["kick"],
            "sample_rate": 1000,
            "frame_count": int(duration_seconds * 1000),
            "duration_seconds": duration_seconds,
        },
    )


def test_m13_json_round_trips_without_losing_per_point_curves_or_targets():
    source = normalise_fx_automation(_payload(), ["kick"])
    score = attach_fx_automation_to_score(_score(), source)
    restored = score_to_fx_automation(score, ["kick"])

    assert restored == source
    assert {lane.target_id for lane in score.automation} == set(source["lanes"])
    insert = next(lane for lane in score.automation if lane.target_id == "stem.kick.insert_wet")
    assert [point.interpolation_to_next for point in insert.points] == [
        "linear", "smooth", "step",
    ]
    # Score JSON retains the extra segment field while remaining schema v1.
    assert Score.from_dict(score.to_dict()).to_dict() == score.to_dict()


def test_m13_segment_curves_are_evaluated_on_score_tempo_map_and_frame_clock():
    tempo = TempoMap((
        TempoPoint(Fraction(0), 120.0, "linear"),
        TempoPoint(Fraction(8), 60.0, "step"),
    ))
    score = Score(
        title="M17.4 tempo-ramp fixture",
        tempo_map=tempo,
        events=(
            MusicalEvent(
                event_id="kick",
                voice_id="kick",
                onset_beats=Fraction(0),
                duration_beats=Fraction(8),
                kind="hit",
            ),
        ),
        metadata={"render_stems": ["kick"], "sample_rate": 48_000, "duration_seconds": 7.0},
    )
    payload = {
        "schema_version": 1,
        "lanes": {
            "bus.space.wet": [
                {"beat": 0, "value": 0.0, "curve": "smooth"},
                {"beat": 8, "value": 1.0, "curve": "hold"},
            ],
        },
    }
    result = ReawarpEngine().render_score(score, fx_automation=payload)
    frame_at_4_beats = result.controls.timeline.beat_to_frame(Fraction(4))

    assert result.controls.value_at_frame("bus.space.wet", frame_at_4_beats) == pytest.approx(0.5)
    assert result.controls.value_at_frame("bus.space.wet", 0) == pytest.approx(0.0)
    assert "bus.space.wet" in result.controls.target_ids


def test_score_control_bus_drives_insert_wet_automation_and_legacy_path_is_unchanged(monkeypatch):
    score = _score()
    result = ReawarpEngine().render_score(score, fx_automation={
        "schema_version": 1,
        "lanes": {
            "stem.kick.insert_wet": [
                {"beat": 0, "value": 0.0, "curve": "linear"},
                {"beat": 1, "value": 1.0, "curve": "linear"},
            ],
        },
    })
    dry = np.full((1000, 2), 0.4, dtype=np.float32)
    routing = default_fx_routing(["kick"])
    routing["stems"]["kick"]["insert"] = {
        "kind": "preset", "preset": "restrained_space",
        "wet": 0.0, "tail_seconds": 0.0,
    }

    def silent_wet(audio, sample_rate, *, preset=None, stages=None, wet=1.0, tail_seconds=0.0):
        return np.zeros_like(np.asarray(audio, dtype=np.float32))

    monkeypatch.setattr(fx_routing, "render_pyo_fx", silent_wet)
    processed, meta = render_fx_routing(
        {"kick": dry}, 1000, routing, controls=result.controls,
    )

    assert meta["automation_source"] == "score-control-bus"
    assert processed["kick"][0, 0] == pytest.approx(0.4)
    assert processed["kick"][250, 0] == pytest.approx(0.2, abs=0.01)
    assert processed["kick"][500, 0] == pytest.approx(0.0, abs=0.01)
    np.testing.assert_array_equal(dry, np.full((1000, 2), 0.4, dtype=np.float32))


def test_score_control_bus_opens_send_and_shared_return_automation(monkeypatch):
    score = _score()
    result = ReawarpEngine().render_score(score, fx_automation={
        "schema_version": 1,
        "lanes": {
            "stem.kick.send.space": [
                {"beat": 0, "value": 0.5, "curve": "hold"},
            ],
            "bus.space.wet": [
                {"beat": 0, "value": 0.65, "curve": "hold"},
            ],
        },
    })
    dry = np.full((1000, 2), 0.15, dtype=np.float32)
    routing = default_fx_routing(["kick"])
    routing["stems"]["kick"]["sends"]["space"] = 0.0
    routing["buses"]["space"]["wet"] = 0.0

    calls = []

    def pass_through(audio, sample_rate, *, preset=None, stages=None, wet=1.0, tail_seconds=0.0):
        calls.append((len(audio), preset, stages))
        return np.asarray(audio, dtype=np.float32).copy()

    monkeypatch.setattr(fx_routing, "render_pyo_fx", pass_through)
    processed, meta = render_fx_routing(
        {"kick": dry}, 1000, routing, controls=result.controls,
    )
    returns = meta["bus_returns_audio"]

    assert "space" in returns
    assert meta["active_send_stems_by_bus"]["space"] == ["kick"]
    assert np.max(np.abs(returns["space"])) > 0.0
    assert calls
    assert np.max(np.abs(processed["kick"])) == pytest.approx(0.15)


def test_control_bus_keeps_routing_default_until_first_automation_point(monkeypatch):
    score = _score()
    result = ReawarpEngine().render_score(score, fx_automation={
        "schema_version": 1,
        "lanes": {
            "stem.kick.insert_wet": [
                {"beat": 1, "value": 1.0, "curve": "hold"},
            ],
        },
    })
    dry = np.full((1000, 2), 0.4, dtype=np.float32)
    routing = default_fx_routing(["kick"])
    routing["stems"]["kick"]["insert"] = {
        "kind": "preset", "preset": "restrained_space",
        "wet": 0.25, "tail_seconds": 0.0,
    }

    monkeypatch.setattr(
        fx_routing,
        "render_pyo_fx",
        lambda audio, sample_rate, **kwargs: np.zeros_like(np.asarray(audio, dtype=np.float32)),
    )
    processed, _ = render_fx_routing(
        {"kick": dry}, 1000, routing, controls=result.controls,
    )

    assert processed["kick"][100, 0] == pytest.approx(0.3, abs=0.01)
    assert processed["kick"][500, 0] == pytest.approx(0.0, abs=0.01)


def test_fx_controls_and_legacy_json_are_mutually_exclusive_and_rate_matched(monkeypatch):
    result = ReawarpEngine().render_score(
        _score(), fx_automation={
            "schema_version": 1,
            "lanes": {"bus.space.wet": [{"beat": 0, "value": 0.3, "curve": "hold"}]},
        },
    )
    dry = {"kick": np.zeros((1000, 2), dtype=np.float32)}
    routing = default_fx_routing(["kick"])

    with pytest.raises(ValueError, match="either legacy automation JSON or score controls"):
        render_fx_routing(
            dry, 1000, routing, automation={"schema_version": 1, "lanes": {}},
            controls=result.controls,
        )
    with pytest.raises(ValueError, match="sample rate"):
        render_fx_routing(dry, 2000, routing, controls=result.controls)


def test_fx_target_registry_is_typed_and_rejects_out_of_range_values():
    registry = fx_automation_registry(["kick"])
    assert registry.resolve("stem.kick.insert_wet").domain == "fx"
    lane = AutomationLane(
        "stem.kick.send.space",
        (AutomationPoint(Fraction(0), 1.2),),
        unit="normalized",
        minimum=0.0,
        maximum=1.0,
    )
    with pytest.raises(ValueError, match="exceeds target maximum"):
        registry.validate_lane(lane)


def test_score_control_bus_from_m18_sources_drives_insert_send_and_return_wet(monkeypatch):
    from reawarp import AutomationModulation, AutomationSource, ScoreRenderer

    source = AutomationSource(
        "route-open", "phrase_curve", Fraction(0), Fraction(4),
        parameters={"values": [1.0, 1.0]},
    )
    score = Score(
        events=(
            MusicalEvent(
                "kick-hit", "kick", Fraction(0), Fraction(1, 4),
                kind="hit", parameters={"source_kind": "kick"},
            ),
        ),
        automation_sources=(source,),
        modulations=(
            AutomationModulation(
                "route-open", "stem.kick.insert_wet", amount=1.0,
                polarity="unipolar", mode="add", minimum=0.0, maximum=1.0,
                base_value=0.0,
            ),
            AutomationModulation(
                "route-open", "stem.kick.send.space", amount=0.7,
                polarity="unipolar", mode="add", minimum=0.0, maximum=1.0,
                base_value=0.0,
            ),
            AutomationModulation(
                "route-open", "bus.space.wet", amount=0.6,
                polarity="unipolar", mode="add", minimum=0.0, maximum=1.0,
                base_value=0.0,
            ),
        ),
    )
    registry = fx_automation_registry(["kick"])
    controls = ScoreRenderer().render(
        score, 1_000, automation_registry=registry
    ).controls
    audio = np.full((1000, 2), 0.2, dtype=np.float32)
    routing = default_fx_routing(["kick"])
    routing["stems"]["kick"]["insert"] = {
        "kind": "preset", "preset": "restrained_space",
        "wet": 0.0, "tail_seconds": 0.0,
    }
    routing["stems"]["kick"]["sends"]["space"] = 0.0
    routing["buses"]["space"]["wet"] = 0.0
    calls = []

    def pass_through(signal, sample_rate, **kwargs):
        calls.append(np.asarray(signal).copy())
        return np.asarray(signal, dtype=np.float32).copy()

    monkeypatch.setattr(fx_routing, "render_pyo_fx", pass_through)
    processed, metadata = render_fx_routing(
        {"kick": audio}, 1_000, routing, controls=controls,
    )

    assert metadata["automation_source"] == "score-control-bus"
    assert "space" in metadata["bus_returns_audio"]
    assert metadata["active_send_stems_by_bus"]["space"] == ["kick"]
    assert processed["kick"].shape == audio.shape
    assert len(calls) >= 2
