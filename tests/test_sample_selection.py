from reawarp.samples.selection import select_sample_variant


def _bank():
    return [
        {"features": {"spectral_centroid_hz": 650.0, "rms_dbfs": -24.0, "spectral_flatness": 0.12, "onset_density_per_second": 3.0}},
        {"features": {"spectral_centroid_hz": 8800.0, "rms_dbfs": -11.0, "spectral_flatness": 0.76, "onset_density_per_second": 11.0}},
        {"features": {"spectral_centroid_hz": 4200.0, "rms_dbfs": -19.0, "spectral_flatness": 0.88, "onset_density_per_second": 8.0}},
        {"features": {"spectral_centroid_hz": 1400.0, "rms_dbfs": -27.0, "spectral_flatness": 0.08, "onset_density_per_second": 2.0}},
    ]


def test_feature_guided_selection_is_deterministic_and_leaves_anchor():
    bank = _bank()
    first = select_sample_variant(bank, role="kick", phrase_function="development", seed=211, anchor_index=0, previous_index=0, intensity=0.9)
    second = select_sample_variant(bank, role="kick", phrase_function="development", seed=211, anchor_index=0, previous_index=0, intensity=0.9)
    assert first == second
    assert first in {1, 2, 3}


def test_return_recalls_anchor_and_false_return_uses_an_alternative():
    bank = _bank()
    returned = select_sample_variant(bank, role="snare", phrase_function="return", seed=312, anchor_index=0, previous_index=2, intensity=1.0)
    false_return = select_sample_variant(bank, role="snare", phrase_function="false_return", seed=312, anchor_index=0, previous_index=2, intensity=1.0)
    assert returned == 0
    assert false_return != 0


def test_contrast_is_reproducible():
    bank = _bank()
    first = select_sample_variant(bank, role="hat", phrase_function="contrast", seed=901, anchor_index=0, previous_index=1, intensity=0.85)
    second = select_sample_variant(bank, role="hat", phrase_function="contrast", seed=901, anchor_index=0, previous_index=1, intensity=0.85)
    assert first == second
