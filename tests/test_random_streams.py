import numpy as np

from reawarp.core.random_streams import RandomStreams, derive_seed


def test_seed_derivation_is_stable_and_namespaced():
    assert derive_seed(1234, "kick") == derive_seed(1234, "kick")
    assert derive_seed(1234, "kick") != derive_seed(1234, "snare")
    assert derive_seed(1234, "kick") != derive_seed(4321, "kick")


def test_named_streams_are_reproducible_and_independent():
    first = RandomStreams("fixture-seed")
    second = RandomStreams("fixture-seed")

    # Consuming a different amount of the kick stream must not advance melody.
    first.get("kick").random(100)
    melody_a = first.get("melody").random(32)
    melody_b = second.get("melody").random(32)

    np.testing.assert_array_equal(melody_a, melody_b)


def test_seed_override_changes_only_the_named_stream():
    baseline = RandomStreams(77)
    changed = RandomStreams(77, seed_overrides={"kick": 999})

    assert baseline.seed_for("kick") != changed.seed_for("kick")
    assert baseline.seed_for("melody") == changed.seed_for("melody")
    assert not np.array_equal(baseline.get("kick").random(8), changed.get("kick").random(8))
