"""Production synthesis adapters for the frame-scheduled score renderer.

These callbacks reuse Reawarp's existing instrument catalogue. Every event gets
an independent event-derived RNG, so rendering order and neighbouring voices
cannot advance a shared random stream.
"""

from __future__ import annotations

import hashlib
from fractions import Fraction

import numpy as np

from reawarp.config import GenerationConfig
from reawarp.core.random_streams import derive_seed
from reawarp.score.automation import AutomationControlBus
from reawarp.score.events import MusicalEvent
from reawarp.score.render import ScheduledScoreEvent, ScoreVoiceRenderer
from reawarp.synthesis.instruments import (
    _one_pole_lowpass,
    render_extended_note,
    render_fm_note,
    render_hat,
    render_kick,
    render_snare,
    render_subtractive_note,
    render_synthetic_percussion,
)
from reawarp.synthesis.profiles import (
    AUTO_HAT_PROFILES,
    AUTO_KICK_PROFILES,
    AUTO_MELODY_PROFILES,
    AUTO_SNARE_PROFILES,
    HAT_PROFILES,
    KICK_PROFILES,
    MELODY_PROFILES,
    SNARE_PROFILES,
    SUBTRACTIVE_VOICES,
    select_profile_name,
)


def _event_rng(
    event: MusicalEvent, fallback_seed: int | str, renderer_id: str
) -> np.random.Generator:
    """Derive a private deterministic stream from the score event identity."""
    root = event.seed if event.seed is not None else fallback_seed
    payload = f"reawarp:score-voice:v1:{root}:{event.event_id}:{event.voice_id}:{renderer_id}".encode(
        "utf-8"
    )
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return np.random.default_rng(int.from_bytes(digest, "little", signed=False))


def _fit_frames(signal: np.ndarray, frames: int) -> np.ndarray:
    """Fit a mono voice result to the exact score event span without resampling."""
    audio = np.asarray(signal, dtype=np.float32).reshape(-1)
    if len(audio) == frames:
        return audio
    if len(audio) > frames:
        return audio[:frames].copy()
    result = np.zeros(frames, dtype=np.float32)
    result[: len(audio)] = audio
    return result


def _control_curve(
    controls: AutomationControlBus,
    target_id: str,
    scheduled: ScheduledScoreEvent,
    sample_rate: int,
    default: float,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Interpolate a control lane and its active mask at its declared control rate."""
    if target_id not in controls.target_ids or scheduled.duration_frames <= 0:
        return None
    step = controls.recommended_step_frames(target_id)
    if step is None:
        raise ValueError(
            f"event-clock target {target_id!r} cannot be sampled as a continuous voice curve"
        )
    sampled = controls.sample(
        target_id,
        scheduled.start_frame,
        scheduled.end_frame,
        step_frames=step,
        default_value=default,
        event_id=scheduled.event.event_id,
    )
    if not len(sampled.frames):
        return None
    frames = np.arange(scheduled.start_frame, scheduled.end_frame, dtype=np.float64)
    values = np.interp(frames, sampled.frames, sampled.values).astype(np.float32)
    active_samples = (
        np.ones(len(sampled.frames), dtype=bool)
        if sampled.active is None
        else np.asarray(sampled.active, dtype=bool)
    )
    sample_indices = np.searchsorted(sampled.frames, frames, side="right") - 1
    sample_indices = np.clip(sample_indices, 0, len(active_samples) - 1)
    active = active_samples[sample_indices]
    return values, active


def _event_control_value(
    controls: AutomationControlBus,
    target_id: str,
    scheduled: ScheduledScoreEvent,
    default: float | None = None,
) -> float | None:
    """Resolve one event-scoped parameter, preserving profile defaults when inactive."""
    if target_id not in controls.target_ids:
        return default
    value, active = controls.value_and_active_for_context(
        target_id,
        scheduled.start_frame,
        event_id=scheduled.event.event_id,
        default_value=default,
    )
    return float(value) if active else default


def _apply_musical_controls(
    signal: np.ndarray,
    scheduled: ScheduledScoreEvent,
    sample_rate: int,
    controls: AutomationControlBus,
) -> np.ndarray:
    """Apply scoped synthesis gain and cutoff/resonance lanes to a mono voice."""
    audio = np.asarray(signal, dtype=np.float32).reshape(-1).copy()
    if not len(audio):
        return audio
    cutoff = _control_curve(controls, "synth.cutoff", scheduled, sample_rate, 0.0)
    if cutoff is not None:
        cutoff_values, cutoff_active = cutoff
        if np.any(cutoff_active):
            # The inactive region is explicitly passed through: a role-scoped
            # cutoff on the lead must not filter bass or percussion events.
            bypass_cutoff = max(100.0, float(sample_rate) * 0.45)
            safe_cutoff = np.where(cutoff_active, cutoff_values, bypass_cutoff)
            filtered = _one_pole_lowpass(audio, sample_rate, safe_cutoff)
            filtered = np.where(cutoff_active, filtered, audio)
            resonance = _control_curve(
                controls, "synth.resonance", scheduled, sample_rate, 0.0
            )
            if resonance is None:
                audio = filtered
            else:
                resonance_values, resonance_active = resonance
                resonance_values = np.where(resonance_active, resonance_values, 0.0)
                amount = np.clip(resonance_values, 0.0, 1.0)
                audio = filtered + (audio - filtered) * amount
    gain = _control_curve(controls, "synth.gain", scheduled, sample_rate, 1.0)
    if gain is not None:
        gain_values, gain_active = gain
        audio *= np.where(gain_active, np.clip(gain_values, 0.0, 1.0), 1.0)
    return np.asarray(audio, dtype=np.float32)


def _select_profile(
    configured: str,
    catalogue: dict,
    automatic_choices: tuple[str, ...],
    root_seed: int | str,
    role: str,
) -> str:
    """Resolve automatic profile choice once per role, not once per callback."""
    if configured != "auto":
        if configured not in catalogue:
            raise ValueError(f"unknown {role} synthesis profile: {configured}")
        return configured
    rng = np.random.default_rng(derive_seed(root_seed, f"score-voice-profile:{role}"))
    return select_profile_name("auto", catalogue, rng, auto_choices=automatic_choices)


def _melody_renderer(config: GenerationConfig) -> ScoreVoiceRenderer:
    if config.synth_palette == "subtractive":
        catalogue = SUBTRACTIVE_VOICES
        choices = AUTO_MELODY_PROFILES
    else:
        catalogue = MELODY_PROFILES
        choices = tuple(
            name
            for name in MELODY_PROFILES
            if name
            in {"soft_keys", "glass_bell", "soft_pluck", "reed_pad", "wood_mallet"}
        )
    selected_profile = _select_profile(
        config.melody_profile, catalogue, choices, config.seed, "melody"
    )

    def render(
        scheduled: ScheduledScoreEvent,
        sample_rate: int,
        controls: AutomationControlBus,
    ) -> np.ndarray:
        event = scheduled.event
        parameters = event.parameters
        frequency = event.frequency_hz
        if frequency is None and event.pitch is not None:
            frequency = 440.0 * (2.0 ** ((float(event.pitch) - 69.0) / 12.0))
        if frequency is None or float(frequency) <= 0:
            raise ValueError(
                f"melody event {event.event_id!r} needs a positive frequency"
            )
        pitch_lane = (
            controls.value_for_context(
                "synth.pitch",
                scheduled.start_frame,
                event_id=event.event_id,
                default_value=0.0,
            )
            if "synth.pitch" in controls.target_ids
            else 0.0
        )
        register = float(
            parameters.get("register_semitones", config.melody_register_semitones)
        )
        frequency = float(frequency) * (2.0 ** ((register + pitch_lane) / 12.0))
        gate_value = parameters.get("gate_duration_beats")
        if gate_value is None:
            gate_frames = scheduled.duration_frames
        else:
            gate_start_frame = scheduled.start_frame
            try:
                gate_beats = Fraction(str(gate_value))
                _event_start, gate_end_frame = controls.timeline.beat_span_to_frames(
                    event.onset_beats, gate_beats
                )
                gate_frames = max(1, gate_end_frame - gate_start_frame)
            except (TypeError, ValueError, ZeroDivisionError):
                gate_frames = scheduled.duration_frames
        gate_seconds = gate_frames / float(sample_rate)
        attack_seconds = _event_control_value(controls, "synth.attack", scheduled)
        decay_seconds = _event_control_value(controls, "synth.decay", scheduled)
        release_seconds = _event_control_value(controls, "synth.release", scheduled)
        vibrato_depth = (
            _event_control_value(controls, "synth.modulation.depth", scheduled, 0.0)
            or 0.0
        )
        vibrato_rate = (
            _event_control_value(controls, "synth.modulation.rate", scheduled, 5.0)
            or 0.0
        )
        vibrato_depth_semitones = float(np.clip(vibrato_depth, 0.0, 1.0)) * 0.5
        vibrato_rate_hz = float(np.clip(vibrato_rate, 0.0, 40.0))
        wavetable_position = _event_control_value(
            controls, "synth.wavetable.position", scheduled
        )
        partial_balance = _event_control_value(
            controls, "synth.partial.balance", scheduled
        )
        grain_size_ms = _event_control_value(controls, "synth.grain.size", scheduled)
        grain_position = _event_control_value(
            controls, "synth.grain.position", scheduled
        )
        grain_density_hz = _event_control_value(
            controls, "synth.grain.density", scheduled
        )
        rng = _event_rng(event, config.seed, "melody")
        brightness = float(
            np.clip(parameters.get("brightness", config.tonal_brightness), 0.0, 1.0)
        )
        instability = float(
            np.clip(
                parameters.get("instability", config.arrangement_instability), 0.0, 1.0
            )
        )
        if config.synth_palette == "subtractive":
            profile = str(parameters.get("synthesis_profile") or selected_profile)
            audio = render_subtractive_note(
                frequency,
                sample_rate,
                rng,
                duration=gate_seconds,
                velocity=1.0,
                profile=profile,
                brightness=brightness,
                instability=instability,
                attack_seconds=attack_seconds,
                decay_seconds=decay_seconds,
                release_seconds=release_seconds,
                vibrato_depth_semitones=vibrato_depth_semitones,
                vibrato_rate_hz=vibrato_rate_hz,
            )
        elif config.synth_palette in {"hybrid", "fm"}:
            profile = str(parameters.get("synthesis_profile") or selected_profile)
            audio = render_fm_note(
                frequency,
                sample_rate,
                rng,
                duration=gate_seconds,
                velocity=1.0,
                profile=profile,
                brightness=brightness,
                instability=instability,
                attack_seconds=attack_seconds,
                decay_seconds=decay_seconds,
                release_seconds=release_seconds,
                vibrato_depth_semitones=vibrato_depth_semitones,
                vibrato_rate_hz=vibrato_rate_hz,
            )
        else:
            audio = render_extended_note(
                frequency,
                sample_rate,
                rng,
                duration=gate_seconds,
                velocity=1.0,
                palette=config.synth_palette,
                brightness=brightness,
                instability=instability,
                attack_seconds=attack_seconds,
                decay_seconds=decay_seconds,
                release_seconds=release_seconds,
                vibrato_depth_semitones=vibrato_depth_semitones,
                vibrato_rate_hz=vibrato_rate_hz,
                wavetable_position=wavetable_position,
                partial_balance=partial_balance,
                grain_size_ms=grain_size_ms,
                grain_position=grain_position,
                grain_density_hz=grain_density_hz,
            )
        audio = _fit_frames(audio, scheduled.duration_frames)
        return _apply_musical_controls(audio, scheduled, sample_rate, controls)

    return render


def _percussion_renderer(
    role: str,
    config: GenerationConfig,
    selected_profile: str | dict[str, str],
) -> ScoreVoiceRenderer:
    def render(
        scheduled: ScheduledScoreEvent,
        sample_rate: int,
        controls: AutomationControlBus,
    ) -> np.ndarray:
        event = scheduled.event
        parameters = event.parameters
        frames = scheduled.duration_frames
        if frames <= 0:
            return np.zeros(0, dtype=np.float32)
        source_kind = str(parameters.get("source_kind", "")).casefold()
        duration = frames / float(sample_rate)
        synth_gain = float(np.clip(parameters.get("synth_gain", 1.0), 0.0, 1.0))
        # Sample-only suppression is encoded by a prepared event's synth_gain=0.
        # Without a configured sample bank, preserve the legacy synth fallback.
        if synth_gain <= 0.0:
            return np.zeros(frames, dtype=np.float32)

        rng = _event_rng(event, config.seed, f"percussion:{role}")
        if role == "break":
            subrole = (
                source_kind if source_kind in {"kick", "snare", "hat"} else "snare"
            )
            selected = (
                selected_profile.get(subrole, "909_crack")
                if isinstance(selected_profile, dict)
                else selected_profile
            )
            profile = str(parameters.get("sound_profile") or selected)
            if subrole == "kick":
                audio = render_kick(
                    sample_rate,
                    rng,
                    1.0,
                    duration=duration,
                    amp_decay=0.16,
                    profile=profile if profile in KICK_PROFILES else "909_punch",
                )
            elif subrole == "snare":
                audio = render_snare(
                    sample_rate,
                    rng,
                    1.0,
                    duration=duration,
                    profile=profile if profile in SNARE_PROFILES else "909_crack",
                )
            else:
                audio = render_hat(
                    sample_rate,
                    rng,
                    1.0,
                    duration=duration,
                    profile=profile if profile in HAT_PROFILES else "closed",
                )
        else:
            profile = str(parameters.get("sound_profile") or selected_profile)
            synthetic = config.percussion_synthesis in {"minimal", "extended"} or bool(
                parameters.get("synthesis_voice")
            )
            if synthetic:
                defaults = {
                    "kick": (
                        "soft_kick"
                        if config.percussion_synthesis == "minimal"
                        else "dry_thump"
                    ),
                    "snare": (
                        "paper_snare"
                        if config.percussion_synthesis == "minimal"
                        else "muted_rim"
                    ),
                    "hat": (
                        "noise_hat"
                        if config.percussion_synthesis == "minimal"
                        else "metal_tick"
                    ),
                }
                voice = str(parameters.get("synthesis_voice") or defaults[role])
                pitch_hz = parameters.get("pitch_hz")
                if pitch_hz is None:
                    if role == "kick" and profile in KICK_PROFILES:
                        pitch_hz = KICK_PROFILES[profile].end_frequency
                    elif role == "snare" and profile in SNARE_PROFILES:
                        pitch_hz = SNARE_PROFILES[profile].body_frequency
                    elif role == "hat" and profile in HAT_PROFILES:
                        pitch_hz = HAT_PROFILES[profile].partials[0][0]
                if pitch_hz is not None:
                    pitch_hz = float(pitch_hz) * float(
                        parameters.get("synthesis_pitch_ratio", 1.0)
                    )
                synth_duration = {"kick": 0.19, "snare": 0.17, "hat": 0.085}[role]
                audio = render_synthetic_percussion(
                    voice,
                    sample_rate,
                    rng,
                    duration=synth_duration,
                    velocity=1.0,
                    pitch_hz=None if pitch_hz is None else float(pitch_hz),
                )
            elif role == "kick":
                audio = render_kick(
                    sample_rate, rng, 1.0, duration=duration, profile=profile
                )
            elif role == "snare":
                audio = render_snare(
                    sample_rate, rng, 1.0, duration=duration, profile=profile
                )
            else:
                audio = render_hat(
                    sample_rate, rng, 1.0, duration=duration, profile=profile
                )

        scale = float(parameters.get("synthesis_velocity_scale", 1.0))
        if role == "break":
            scale *= {"kick": 0.82, "snare": 0.78, "hat": 0.90}.get(subrole, 1.0)
        audio = _fit_frames(audio, frames) * np.float32(synth_gain * scale)
        if "synth.gain" in controls.target_ids:
            audio = _apply_musical_controls(audio, scheduled, sample_rate, controls)
        return audio

    return render


def build_production_voice_renderers(
    config: GenerationConfig,
) -> dict[str, ScoreVoiceRenderer]:
    """Build deterministic production callbacks for all event-backed score voices.

    Melodic callbacks retain the selected subtractive/FM/extended synthesis family.
    Percussion callbacks retain role-specific profile voices. Imported sample
    triggers and break-slice callbacks are composed by score_samples.py; only the
    explicit sample source mode suppresses the corresponding synthesis hit.
    """
    renderers: dict[str, ScoreVoiceRenderer] = {}
    if config.include_melody:
        renderers["melody"] = _melody_renderer(config)
    for role, configured, catalogue, choices in (
        ("kick", config.kick_profile, KICK_PROFILES, AUTO_KICK_PROFILES),
        ("snare", config.snare_profile, SNARE_PROFILES, AUTO_SNARE_PROFILES),
        ("hat", config.hat_profile, HAT_PROFILES, AUTO_HAT_PROFILES),
    ):
        selected = _select_profile(configured, catalogue, choices, config.seed, role)
        renderers[role] = _percussion_renderer(role, config, selected)
    break_profiles = {
        "kick": _select_profile(
            config.kick_profile,
            KICK_PROFILES,
            AUTO_KICK_PROFILES,
            config.seed,
            "break_kick",
        ),
        "snare": _select_profile(
            config.snare_profile,
            SNARE_PROFILES,
            AUTO_SNARE_PROFILES,
            config.seed,
            "break_snare",
        ),
        "hat": _select_profile(
            config.hat_profile,
            HAT_PROFILES,
            AUTO_HAT_PROFILES,
            config.seed,
            "break_hat",
        ),
    }
    renderers["break"] = _percussion_renderer("break", config, break_profiles)
    return renderers
