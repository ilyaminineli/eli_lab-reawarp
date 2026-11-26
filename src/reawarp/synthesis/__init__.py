"""Procedural synthesis instruments, ambient beds, and voice profile catalogues."""

from reawarp.synthesis.ambience import render_ambience
from reawarp.synthesis.sound_object import (
    EnvelopeSpec,
    HybridRenderResult,
    HybridVoiceRenderer,
    SoundObjectLayer,
    SoundObjectPatch,
    SoundObjectSource,
    TransformationRecord,
    build_envelope_curve,
    derive_sound_object_seed,
    register_sound_object_automation_targets,
    render_additive_partial_voice,
    render_modal_resonator_bank,
    resample_audio_non_destructive,
    sound_object_automation_targets,
    build_score_sound_object_renderer,
    sound_object_editor_model,
)
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
    "EnvelopeSpec",
    "HybridRenderResult",
    "HybridVoiceRenderer",
    "SoundObjectLayer",
    "SoundObjectPatch",
    "SoundObjectSource",
    "TransformationRecord",
    "build_envelope_curve",
    "derive_sound_object_seed",
    "register_sound_object_automation_targets",
    "render_additive_partial_voice",
    "render_modal_resonator_bank",
    "resample_audio_non_destructive",
    "sound_object_automation_targets",
    "build_score_sound_object_renderer",
    "sound_object_editor_model",
]
