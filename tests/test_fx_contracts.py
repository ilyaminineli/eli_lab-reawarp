import numpy as np
import pytest

from reawarp.fx_automation import automation_envelope, normalise_fx_automation
from reawarp.fx_routing import default_fx_routing, render_fx_routing


def test_default_routing_is_dry_and_preserves_source_buffers():
    dry = {
        "kick": np.full((128, 2), 0.1, dtype=np.float32),
        "melody": np.full((128, 2), -0.05, dtype=np.float32),
    }
    original = {name: audio.copy() for name, audio in dry.items()}
    routing = default_fx_routing(tuple(dry))

    processed, metadata = render_fx_routing(dry, 48_000, routing)

    assert set(processed) == set(dry)
    assert not metadata["rendered_returns"]
    for name in dry:
        np.testing.assert_array_equal(dry[name], original[name])
        np.testing.assert_array_equal(processed[name], original[name])


def test_automation_envelope_is_beat_addressed_and_deterministic():
    points = [
        {"beat": 0, "value": 0.0, "curve": "linear"},
        {"beat": 1, "value": 0.5, "curve": "smooth"},
        {"beat": 2, "value": 0.0, "curve": "hold"},
    ]
    first = automation_envelope(
        points, frames=1001, sample_rate=1000, bpm=120, default_value=0.0
    )
    second = automation_envelope(
        points, frames=1001, sample_rate=1000, bpm=120, default_value=0.0
    )

    np.testing.assert_array_equal(first, second)
    assert first[0] == pytest.approx(0.0)
    assert first[500] == pytest.approx(0.5)
    assert first[1000] == pytest.approx(0.0)


def test_automation_validation_rejects_duplicate_points_and_unknown_targets():
    with pytest.raises(ValueError):
        normalise_fx_automation(
            {
                "schema_version": 1,
                "lanes": {
                    "bus.space.wet": [
                        {"beat": 0, "value": 0.0},
                        {"beat": 0, "value": 1.0},
                    ]
                },
            },
            ["kick"],
        )
    with pytest.raises(ValueError):
        normalise_fx_automation(
            {"schema_version": 1, "lanes": {"stem.unknown.send.echo": [
                {"beat": 0, "value": 0.1}
            ]}},
            ["kick"],
        )
