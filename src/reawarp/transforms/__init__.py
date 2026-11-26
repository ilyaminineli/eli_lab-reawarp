"""Break sample analysis and transformation tools."""

from reawarp.transforms.analysis import (
    AudioSlice,
    auto_slice,
    detect_transients,
    slice_audio,
)
from reawarp.transforms.effects import (
    dropout,
    gate_audio,
    granular_resynthesis,
    pitch_shift,
    rearrange_slices,
    reverse_audio,
    spectral_freeze,
    stutter,
    time_stretch,
)
from reawarp.transforms.pipeline import BREAK_TRANSFORMS, apply_break_transforms

__all__ = [
    "AudioSlice",
    "BREAK_TRANSFORMS",
    "apply_break_transforms",
    "auto_slice",
    "detect_transients",
    "dropout",
    "gate_audio",
    "granular_resynthesis",
    "pitch_shift",
    "rearrange_slices",
    "reverse_audio",
    "slice_audio",
    "spectral_freeze",
    "stutter",
    "time_stretch",
]
