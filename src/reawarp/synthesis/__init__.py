"""Procedural synthesis instruments, ambient beds, and voice profile catalogues."""

from reawarp.synthesis.ambience import render_ambience
from reawarp.synthesis.profiles import (
    HAT_PROFILES,
    KICK_PROFILES,
    MELODY_PROFILES,
    SNARE_PROFILES,
)

__all__ = [
    "HAT_PROFILES",
    "KICK_PROFILES",
    "MELODY_PROFILES",
    "SNARE_PROFILES",
    "render_ambience",
]
