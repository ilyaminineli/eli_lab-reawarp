from __future__ import annotations

from fractions import Fraction

import numpy as np
import pytest

from reawarp.fx_routing import default_fx_routing, render_fx_routing
from reawarp.score import MusicalEvent, Score, TempoMap
from reawarp.score.attention import build_attention_send_envelope
from reawarp.score.render import build_score_control_bus
from reawarp.score.time import TempoPoint


def _score_controls(sample_rate: int, *, ramped_tempo: bool = False):
    tempo = (
        TempoMap((
            TempoPoint(Fraction(0), 120.0, "linear"),
            TempoPoint(Fraction(8), 60.0, "step"),
        ))
        if ramped_tempo else TempoMap.constant(120.0)
    )
    score = Score(
        title="M29 phrase-aware send fixture",
        tempo_map=tempo,
        events=(
            MusicalEvent(
                event_id="melody-note",
                voice_id="melody",
                onset_beats=Fraction(0),
                duration_beats=Fraction(1),
                kind="note",
                pitch=60,
            ),
        ),
    )
    return build_score_control_bus(score, sample_rate)


def _gesture(role: str = "melody", action: str = "focus", start="0", end="8"):
    return {
        "schema_version": 1,
        "gesture_id": f"{role}-{action}-{start}-{end}",
        "role": role,
        "start_beats": str(start),
        "end_beats": str(end),
        "action": action,
        "register_shift_semitones": 0.0,
    }


def test_focus_and_recede_shape_space_and_echo_with_eased_phrase_edges():
    controls = _score_controls(100)
    focus = [_gesture()]
    space = build_attention_send_envelope(
        focus, role="melody", bus="space",
        timeline=controls.timeline, frames=401,
    )
    echo = build_attention_send_envelope(
        focus, role="melody", bus="echo",
        timeline=controls.timeline, frames=401,
    )

    assert space[0] == pytest.approx(1.0)
    assert 0.62 < space[36] < 1.0
    assert space[200] == pytest.approx(0.62)
    assert echo[200] == pytest.approx(0.72)
    assert 0.62 < space[364] < 1.0
    assert space[400] == pytest.approx(1.0)

    recede = [_gesture(action="recede")]
    receded_space = build_attention_send_envelope(
        recede, role="melody", bus="space",
        timeline=controls.timeline, frames=401,
    )
    receded_echo = build_attention_send_envelope(
        recede, role="melody", bus="echo",
        timeline=controls.timeline, frames=401,
    )
    assert receded_space[200] == pytest.approx(1.38)
    assert receded_echo[200] == pytest.approx(1.20)
    assert receded_space[0] == pytest.approx(1.0)
    assert receded_space[400] == pytest.approx(1.0)


def test_nested_phrase_gesture_blends_to_its_enclosing_instruction():
    controls = _score_controls(100)
    gestures = [
        _gesture(action="focus", start="0", end="8"),
        _gesture(action="recede", start="2", end="6"),
    ]
    envelope = build_attention_send_envelope(
        gestures, role="melody", bus="space",
        timeline=controls.timeline, frames=401,
    )

    assert envelope[100] == pytest.approx(0.62)
    assert envelope[200] == pytest.approx(1.38)
    assert envelope[300] == pytest.approx(0.62)


def test_phrase_curve_uses_score_tempo_map_and_protects_low_frequency_roles():
    controls = _score_controls(100, ramped_tempo=True)
    gesture = [_gesture(action="recede")]
    boundary = controls.timeline.beat_to_frame(Fraction(4))
    envelope = build_attention_send_envelope(
        gesture, role="melody", bus="space",
        timeline=controls.timeline, frames=controls.timeline.beat_to_frame(8) + 1,
    )
    assert envelope[boundary] == pytest.approx(1.38)

    for protected in ("kick", "bass", "sub", "sub_bass", "low_frequency"):
        protected_envelope = build_attention_send_envelope(
            [_gesture(role=protected, action="recede")],
            role=protected,
            bus="space",
            timeline=controls.timeline,
            frames=64,
        )
        np.testing.assert_array_equal(protected_envelope, np.ones(64, dtype=np.float32))


def test_attention_send_validates_bus_and_requires_score_timeline():
    controls = _score_controls(100)
    with pytest.raises(ValueError, match="space or echo"):
        build_attention_send_envelope(
            [_gesture()], role="melody", bus="reverb",
            timeline=controls.timeline, frames=10,
        )
    with pytest.raises(TypeError, match="Score render timeline"):
        build_attention_send_envelope(
            [_gesture()], role="melody", bus="space",
            timeline=object(), frames=10,
        )


def test_fx_router_composes_gesture_with_existing_send_without_touching_direct_stem():
    controls = _score_controls(100)
    source = np.full((401, 2), 0.1, dtype=np.float32)
    routing = default_fx_routing(("melody",))
    routing["stems"]["melody"]["insert"] = {
        "kind": "bypass", "wet": 0.0, "tail_seconds": 0.0,
    }
    routing["stems"]["melody"]["sends"] = {"space": 0.5, "echo": 0.4}
    routing["buses"]["space"]["wet"] = 0.0
    routing["buses"]["echo"]["wet"] = 0.0

    processed, metadata = render_fx_routing(
        {"melody": source},
        100,
        routing,
        controls=controls,
        attention_gestures=[_gesture()],
        include_audition_audio=True,
    )
    np.testing.assert_array_equal(processed["melody"], source)
    sends = metadata["audition_audio"]["sends"]["melody"]
    assert sends["space"][0, 0] == pytest.approx(0.05)
    assert sends["space"][200, 0] == pytest.approx(0.031)
    assert sends["echo"][200, 0] == pytest.approx(0.0288)


def test_fx_router_clamps_receded_send_and_requires_score_timeline():
    controls = _score_controls(100)
    source = np.full((401, 2), 0.1, dtype=np.float32)
    routing = default_fx_routing(("melody",))
    routing["stems"]["melody"]["insert"] = {
        "kind": "bypass", "wet": 0.0, "tail_seconds": 0.0,
    }
    routing["stems"]["melody"]["sends"] = {"space": 0.9, "echo": 0.7}
    routing["buses"]["space"]["wet"] = 0.0
    routing["buses"]["echo"]["wet"] = 0.0

    _, metadata = render_fx_routing(
        {"melody": source},
        100,
        routing,
        controls=controls,
        attention_gestures=[_gesture(action="recede")],
        include_audition_audio=True,
    )
    sends = metadata["audition_audio"]["sends"]["melody"]
    assert sends["space"][200, 0] == pytest.approx(0.1)
    assert sends["echo"][200, 0] == pytest.approx(0.084)

    with pytest.raises(ValueError, match="Score control bus timeline"):
        render_fx_routing(
            {"melody": source},
            100,
            routing,
            attention_gestures=[_gesture(action="recede")],
        )
