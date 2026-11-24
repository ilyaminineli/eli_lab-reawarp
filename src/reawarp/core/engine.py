"""Offline-first Reawarp synthesis coordinator."""

from __future__ import annotations

import hashlib
import math
from time import perf_counter
from pathlib import Path
from typing import Any

import numpy as np

from reawarp.composition.director import build_composition_plan, section_for_time
from reawarp.config import GenerationConfig
from reawarp.core.project import ReawarpProject
from reawarp.core.random_streams import RandomStreams, derive_seed
from reawarp.generators.melody import build_melody_events
from reawarp.generators.percussion import build_percussion_events
from reawarp.samples.io import read_sample
from reawarp.synthesis.ambience import render_ambience
from reawarp.synthesis.instruments import (
    render_extended_note,
    render_hat,
    render_kick,
    render_noise_texture,
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
from reawarp.transforms.analysis import auto_slice
from reawarp.transforms.pipeline import apply_break_transforms


class ReawarpEngine:
    """Generate deterministic musical material and render synchronized stereo stems."""

    VERSION = "0.8.0"

    def generate_variant(
            self,
            config: GenerationConfig,
            stem: str,
            variation: int = 1,
            *,
            base_project: ReawarpProject | None = None,
    ) -> ReawarpProject:
        """Regenerate one layer and optionally merge it into a frozen base project."""
        variant = self.generate(config, regenerate=stem, variation=variation)
        if base_project is None:
            return variant
        if base_project.config != config:
            raise ValueError("base_project configuration must match")
        if stem not in base_project.stems or stem not in variant.stems:
            raise ValueError(f"layer {stem!r} is not present in both projects")
        merged_stems = dict(base_project.stems)
        merged_stems[stem] = variant.stems[stem]
        target_lane = self._event_lane_for_stem(stem)
        merged_events = [event for event in base_project.events if event.get("lane") != target_lane]
        merged_events.extend(event for event in variant.events if event.get("lane") == target_lane)
        merged_events.sort(
            key=lambda event: (float(event.get("time", 0.0)), str(event.get("lane", "")))
        )
        metadata = dict(base_project.metadata)
        metadata["variation"] = {"stem": stem, "index": variation}
        metadata["variation_parent_seed"] = config.seed
        gains = dict(base_project.metadata.get("stem_headroom_gains", {}))
        gains[stem] = variant.metadata.get("stem_headroom_gains", {}).get(stem, 1.0)
        metadata["stem_headroom_gains"] = gains
        metadata["event_count"] = len(merged_events)
        metadata["seed_streams"] = dict(variant.metadata.get("seed_streams", {}))
        metadata["sample_trigger_seed_streams"] = dict(
            variant.metadata.get("sample_trigger_seed_streams", {})
        )
        metadata["sample_sources"] = dict(variant.metadata.get("sample_sources", {}))
        if stem.startswith("sample_"):
            role = stem.removeprefix("sample_")
            source_records = dict(metadata["sample_sources"])
            if role in source_records:
                role_record = dict(source_records[role])
                role_record["trigger_count"] = sum(
                    event.get("lane") == stem for event in merged_events
                )
                source_records[role] = role_record
                metadata["sample_sources"] = source_records
        return ReawarpProject(
            config=config, sample_rate=base_project.sample_rate,
            stems=merged_stems, events=merged_events, metadata=metadata,
        )

    @staticmethod
    def _event_lane_for_stem(stem: str) -> str:
        return {"hats": "hat", "synthetic_break": "break"}.get(stem, stem)

    def generate(
            self,
            config: GenerationConfig | None = None,
            *,
            regenerate: str | None = None,
            variation: int = 1,
            **overrides: Any,
    ) -> ReawarpProject:
        if config is None:
            config = GenerationConfig(**overrides)
        elif overrides:
            raise TypeError("pass either a GenerationConfig or keyword overrides, not both")

        if variation < 1:
            raise ValueError("variation must be a positive integer")
        total_started = perf_counter()
        stream_groups = {
            "kick": ("kick_pattern", "kick_synthesis", "kick_profile"),
            "snare": ("snare_pattern", "snare_synthesis", "snare_profile"),
            "hats": ("hat_pattern", "hat_synthesis", "hat_profile"),
            "synthetic_break": ("break_pattern", "break_synthesis", "break_profile", "break_processing"),
            "melody": ("melody_pattern", "melody_synthesis", "melody_profile"),
            "noise_texture": ("texture_synthesis",),
            "ambience": ("ambience_synthesis",),
        }
        sample_stream_groups = {
            "sample_kick": ("kick_pattern",),
            "sample_snare": ("snare_pattern",),
            "sample_hat": ("hat_pattern",),
            "sample_break": ("break_pattern", "break_processing"),
        }
        if regenerate is not None and regenerate not in stream_groups and regenerate not in sample_stream_groups:
            raise ValueError(f"unknown stem for regeneration: {regenerate}")
        seed_overrides = {}
        sample_seed_overrides = {}
        if regenerate in stream_groups:
            for stream_name in stream_groups[regenerate]:
                seed_overrides[stream_name] = derive_seed(
                    config.seed, f"variation:{regenerate}:{variation}:{stream_name}"
                )
        elif regenerate in sample_stream_groups:
            for stream_name in sample_stream_groups[regenerate]:
                sample_seed_overrides[stream_name] = derive_seed(
                    config.seed, f"variation:{regenerate}:{variation}:{stream_name}"
                )

        frame_count = config.frame_count
        sample_rate = config.sample_rate
        plan_started = perf_counter()
        composition_plan = build_composition_plan(
            duration_seconds=config.duration,
            bpm=config.bpm,
            seed=config.seed,
            structure=config.structure,
            energy=config.composition_energy,
            variation=config.composition_variation,
            flow=config.composition_flow,
            pattern_family=config.pattern_family,
            pattern_relationship=config.pattern_relationship,
        )
        from reawarp.composition.phrase import build_phrase_directives
        phrase_directives = build_phrase_directives(composition_plan.sections)

        def phrase_at_time(time_seconds: float):
            for directive in phrase_directives:
                start = directive.start_bar * (240.0 / config.bpm)
                end = directive.end_bar * (240.0 / config.bpm)
                if start <= time_seconds < end:
                    return directive
            return phrase_directives[0] if time_seconds < 0 else phrase_directives[-1]

        composition_plan_seconds = perf_counter() - plan_started
        event_generation_started = perf_counter()
        sample_streams = RandomStreams(config.seed, seed_overrides=sample_seed_overrides)
        streams = RandomStreams(config.seed, seed_overrides=seed_overrides)
        stems: dict[str, np.ndarray] = {}
        event_records: list[dict[str, Any]] = []

        def new_stem(name: str) -> np.ndarray:
            audio = np.zeros((frame_count, 2), dtype=np.float32)
            stems[name] = audio
            return audio

        def place_mono(
                target: np.ndarray,
                signal: np.ndarray,
                start_seconds: float,
                pan: float = 0.0,
        ) -> None:
            start = max(0, int(round(start_seconds * sample_rate)))
            if start >= frame_count or signal.size == 0:
                return
            count = min(int(signal.size), frame_count - start)
            angle = (float(np.clip(pan, -1.0, 1.0)) + 1.0) * (math.pi / 4.0)
            left_gain, right_gain = math.cos(angle), math.sin(angle)
            mono_signal = np.asarray(signal, dtype=np.float32).reshape(-1)
            target[start: start + count, 0] += mono_signal[:count] * left_gain
            target[start: start + count, 1] += mono_signal[:count] * right_gain

        def place_sample(
                target: np.ndarray,
                sample: np.ndarray,
                start_seconds: float,
                velocity: float,
                pan: float,
        ) -> None:
            shaped = sample * float(np.clip(velocity, 0.0, 1.0)) * 0.72
            place_mono(target, shaped, start_seconds, pan)

        percussion_rngs = {
            "kick": streams.get("kick_pattern"),
            "snare": streams.get("snare_pattern"),
            "hat": streams.get("hat_pattern"),
            "break": streams.get("break_pattern"),
        }
        percussion = build_percussion_events(config, percussion_rngs, composition_plan)
        # Imported sample overlays keep their own baseline trigger score. A
        # procedural lane variation must not mutate a separate sample stem.
        sample_trigger_patterns = build_percussion_events(config, {
            "kick": sample_streams.get("kick_pattern"),
            "snare": sample_streams.get("snare_pattern"),
            "hat": sample_streams.get("hat_pattern"),
            "break": sample_streams.get("break_pattern"),
        }, composition_plan)
        melody_events = build_melody_events(config, streams.get("melody_pattern"))

        # Phrase function modifies event activity as a separate composition
        # layer. The event patterns keep their own deterministic streams; no
        # new randomness is introduced when a role enters a drop/void.
        role_activity = {
            "kick": "kick_activity",
            "snare": "snare_activity",
            "hat": "high_activity",
            "break": "event_activity",
        }
        activity_defaults = {"kick": 0.72, "snare": 0.58, "hat": 0.50, "break": 0.46}
        for role, events in percussion.items():
            activity_name = role_activity[role]
            for event in events:
                directive = phrase_at_time(float(event.time))
                activity = float(getattr(directive, activity_name))
                if directive.function == "silence" or activity <= 0.0:
                    event.velocity = 0.0
                else:
                    event.velocity *= min(1.0, activity / activity_defaults[role])
        for event in melody_events:
            directive = phrase_at_time(float(event.time))
            activity = float(directive.melody_activity)
            if directive.function == "silence" or activity <= 0.0:
                event.velocity = 0.0
            else:
                event.velocity *= min(1.0, activity / 0.55)

        event_generation_seconds = perf_counter() - event_generation_started
        synthesis_started = perf_counter()

        kick_stem = new_stem("kick")
        snare_stem = new_stem("snare")
        hat_stem = new_stem("hats")
        break_stem = new_stem("synthetic_break")

        kick_profile = select_profile_name(
            config.kick_profile, KICK_PROFILES, streams.get("kick_profile"),
            auto_choices=AUTO_KICK_PROFILES,
        )
        synthetic_percussion = config.percussion_synthesis in {"minimal", "extended"}
        for event in percussion["kick"]:
            if not section_for_time(composition_plan, event.time).kick:
                continue
            profile = kick_profile
            if synthetic_percussion:
                signal = render_synthetic_percussion(
                    "soft_kick" if config.percussion_synthesis == "minimal" else "dry_thump",
                    sample_rate, streams.get("kick_synthesis"),
                    velocity=event.velocity, duration=0.19,
                    pitch_hz=KICK_PROFILES[profile].end_frequency,
                )
            else:
                signal = render_kick(
                    sample_rate, streams.get("kick_synthesis"), event.velocity, profile=profile
                )
            place_mono(kick_stem, signal, event.time, event.pan)
            record = event.to_dict()
            record["sound_profile"] = profile
            event_records.append(record)

        snare_profile = select_profile_name(
            config.snare_profile, SNARE_PROFILES, streams.get("snare_profile"),
            auto_choices=AUTO_SNARE_PROFILES,
        )
        for event in percussion["snare"]:
            section = section_for_time(composition_plan, event.time)
            if section.density < 0.14 and event.velocity < 0.70:
                continue
            profile = snare_profile
            if synthetic_percussion:
                signal = render_synthetic_percussion(
                    "paper_snare" if config.percussion_synthesis == "minimal" else "muted_rim",
                    sample_rate, streams.get("snare_synthesis"),
                    velocity=event.velocity, duration=0.17,
                    pitch_hz=SNARE_PROFILES[profile].body_frequency,
                )
            else:
                signal = render_snare(
                    sample_rate, streams.get("snare_synthesis"), event.velocity, profile=profile
                )
            place_mono(snare_stem, signal, event.time, event.pan)
            record = event.to_dict()
            record["sound_profile"] = profile
            event_records.append(record)

        hat_profile = select_profile_name(
            config.hat_profile, HAT_PROFILES, streams.get("hat_profile"),
            auto_choices=AUTO_HAT_PROFILES,
        )
        for event in percussion["hat"]:
            section = section_for_time(composition_plan, event.time)
            if streams.get("section_ornaments").random() > section.percussion_density_scale:
                continue
            profile = hat_profile
            if synthetic_percussion:
                signal = render_synthetic_percussion(
                    "noise_hat" if config.percussion_synthesis == "minimal" else "metal_tick",
                    sample_rate, streams.get("hat_synthesis"),
                    velocity=event.velocity, duration=0.085,
                    pitch_hz=HAT_PROFILES[profile].partials[0][0],
                )
            else:
                signal = render_hat(
                    sample_rate, streams.get("hat_synthesis"), event.velocity, profile=profile
                )
            place_mono(hat_stem, signal, event.time, event.pan)
            record = event.to_dict()
            record["sound_profile"] = profile
            event_records.append(record)

        break_profile_rng = streams.get("break_profile")
        break_profiles = {
            "kick": select_profile_name(
                config.kick_profile, KICK_PROFILES, break_profile_rng,
                auto_choices=AUTO_KICK_PROFILES,
            ),
            "snare": select_profile_name(
                config.snare_profile, SNARE_PROFILES, break_profile_rng,
                auto_choices=AUTO_SNARE_PROFILES,
            ),
            "hat": select_profile_name(
                config.hat_profile, HAT_PROFILES, break_profile_rng,
                auto_choices=AUTO_HAT_PROFILES,
            ),
        }
        for event in percussion["break"]:
            section = section_for_time(composition_plan, event.time)
            if event.kind == "kick" and not section.kick:
                continue
            if event.kind != "kick" and section.density < 0.16:
                continue
            break_rng = streams.get("break_synthesis")
            if event.kind == "kick":
                profile = break_profiles["kick"]
                signal = render_kick(
                    sample_rate,
                    break_rng,
                    event.velocity * 0.82,
                    duration=0.31,
                    amp_decay=0.16,
                    profile=profile,
                )
            elif event.kind == "snare":
                profile = break_profiles["snare"]
                signal = render_snare(
                    sample_rate, break_rng, event.velocity * 0.78, duration=0.22, profile=profile
                )
            else:
                profile = break_profiles["hat"]
                signal = render_hat(
                    sample_rate, break_rng, event.velocity * 0.9, duration=0.075, profile=profile
                )
            place_mono(break_stem, signal, event.time, event.pan)
            record = event.to_dict()
            record["sound_profile"] = profile
            event_records.append(record)

        melody_profile: str | None = None
        if config.include_melody:
            if config.synth_palette == "subtractive":
                melody_profile = select_profile_name(
                    config.melody_profile,
                    SUBTRACTIVE_VOICES,
                    streams.get("melody_profile"),
                    auto_choices=AUTO_MELODY_PROFILES,
                )
            else:
                melody_profile = select_profile_name(
                    config.melody_profile,
                    MELODY_PROFILES,
                    streams.get("melody_profile"),
                    auto_choices=AUTO_MELODY_PROFILES,
                )
            melody_stem = new_stem("melody")
            for event in melody_events:
                section = section_for_time(composition_plan, event.time)
                if not section.melody:
                    continue
                effective_frequency = event.frequency * (2.0 ** (section.motif_register_semitones / 12.0))
                if config.synth_palette == "subtractive":
                    signal = render_subtractive_note(
                        effective_frequency, sample_rate, streams.get("melody_synthesis"),
                        duration=event.duration, velocity=event.velocity,
                        profile=melody_profile, brightness=section.brightness,
                        instability=section.instability,
                    )
                else:
                    signal = render_extended_note(
                        effective_frequency, sample_rate, streams.get("melody_synthesis"),
                        duration=event.duration, velocity=event.velocity,
                        palette=config.synth_palette, brightness=section.brightness,
                        instability=section.instability,
                    )
                place_mono(melody_stem, signal, event.time, event.pan)
                record = event.to_dict()
                record.update({
                    "lane": "melody",
                    "kind": f"{config.synth_palette}_synth_note",
                    "synthesis_profile": melody_profile,
                })
                event_records.append(record)

        if config.include_texture:
            texture_stem = new_stem("noise_texture")
            texture = render_noise_texture(
                frame_count,
                sample_rate,
                streams.get("texture_synthesis"),
                amount=0.055 + config.complexity * 0.045,
            )
            delayed = (
                np.concatenate((np.zeros(97, dtype=np.float32), texture[:-97]))
                if len(texture) > 97 else texture
            )
            texture_gain = np.zeros(frame_count, dtype=np.float32)
            for section in composition_plan.sections:
                start = max(0, int(round(section.start_seconds * sample_rate)))
                end = min(frame_count, int(round(section.end_seconds * sample_rate)))
                if end > start and section.texture:
                    texture_gain[start:end] = 0.45 + 0.55 * section.density
            texture_stem[:, 0] += texture * texture_gain * 0.72
            texture_stem[:, 1] += delayed * texture_gain * 0.72
            event_records.append({
                "lane": "noise_texture",
                "time": 0.0,
                "duration": config.duration,
                "kind": "coloured_noise",
            })

        if config.include_ambience:
            ambience_stem = new_stem("ambience")
            # Keep the ambience pitch anchor independent of the melody lane,
            # so regenerating melody cannot alter an unrelated stem.
            root_frequency = 55.0 * (
                    2.0 ** ((derive_seed(config.seed, "ambience_root") % 24) / 12.0)
            )
            ambience_stem[:] = render_ambience(
                frame_count,
                sample_rate,
                streams.get("ambience_synthesis"),
                root_frequency=root_frequency,
                amount=config.ambience_level,
            )
            ambience_gain = np.zeros(frame_count, dtype=np.float32)
            for section in composition_plan.sections:
                start = max(0, int(round(section.start_seconds * sample_rate)))
                end = min(frame_count, int(round(section.end_seconds * sample_rate)))
                if end > start and section.ambience:
                    ambience_gain[start:end] = section.space
            ambience_stem *= ambience_gain[:, None]
            event_records.append({
                "lane": "ambience",
                "time": 0.0,
                "duration": config.duration,
                "kind": "harmonic_ambient_bed",
                "root_frequency": root_frequency,
                "amount": config.ambience_level,
            })

        sample_manifest: dict[str, dict[str, Any]] = {}
        for role, sample_path in config.sample_paths.items():
            path = Path(sample_path).expanduser()
            sample = read_sample(path, sample_rate)
            source_frame_count = int(len(sample))
            sample_digest = hashlib.sha256(path.read_bytes()).hexdigest()
            applied_transforms: list[str] = []
            if role == "break" and config.break_transforms:
                sample = apply_break_transforms(
                    sample,
                    sample_rate,
                    config.break_transforms,
                    sample_streams.get("break_processing"),
                    bpm=config.bpm,
                    slice_count=config.break_slice_count,
                    stutter_repeats=config.break_stutter_repeats,
                    dropout_probability=config.break_dropout_probability,
                    pitch_semitones=config.break_pitch_semitones,
                    stretch_factor=config.break_time_stretch,
                    gate_rate_hz=config.break_gate_rate_hz,
                    gate_duty=config.break_gate_duty,
                    grain_size_ms=config.break_grain_size_ms,
                    grain_density=config.break_grain_density,
                    freeze_position=config.break_spectral_freeze_position,
                )
                applied_transforms = list(config.break_transforms)
            sample_stem = new_stem(f"sample_{role}")
            role_metadata = dict(config.sample_metadata.get(role, {}))
            triggers = sample_trigger_patterns[role]
            if role == "kick":
                triggers = [
                    event for event in triggers
                    if section_for_time(composition_plan, event.time).kick
                ]
            elif role == "break":
                triggers = [
                    event for event in triggers
                    if (
                        section_for_time(composition_plan, event.time).kick
                        if event.kind == "kick"
                        else section_for_time(composition_plan, event.time).density >= 0.16
                    )
                ]
            elif role == "snare":
                triggers = [event for event in triggers if
                            section_for_time(composition_plan, event.time).density >= 0.14 or event.velocity >= 0.70]
            elif role == "hat":
                sample_ornaments = sample_streams.get("section_ornaments")
                triggers = [event for event in triggers if
                            sample_ornaments.random() <= section_for_time(composition_plan,
                                                                          event.time).percussion_density_scale]
            slice_ranges: list[tuple[int, int]] = []
            source_bars = 1
            if role == "break":
                detected = auto_slice(
                    sample, sample_rate, max_slices=config.break_slice_count
                )
                slice_ranges = [(item.start, item.end) for item in detected]
                if len(slice_ranges) < 2:
                    # Smooth/tonal files still need a usable rhythmic slicing grid.
                    requested = min(config.break_slice_count, max(2, len(sample) // 128))
                    boundaries = np.linspace(0, len(sample), requested + 1).round().astype(int)
                    slice_ranges = [
                        (int(left), int(right))
                        for left, right in zip(boundaries[:-1], boundaries[1:])
                        if right > left
                    ]

            ordered_triggers = sorted(triggers, key=lambda event: event.time)
            for trigger_index, event in enumerate(ordered_triggers):
                record = {
                    "lane": f"sample_{role}",
                    "sample_metadata": role_metadata,
                    "source_lane": role,
                    "time": event.time,
                    "step": event.step,
                    "velocity": event.velocity,
                    "pan": event.pan,
                    "kind": "sample_trigger",
                    "pattern_style": event.pattern_style,
                    "transforms": applied_transforms,
                }
                if role == "break" and slice_ranges:
                    # Map the event's 16-step slot to the corresponding transient
                    # region. The same bar repeats the same slice map; phrase
                    # mutations change event positions without random clip overlap.
                    bar_frames = max(1, int(round(sample_rate * 240.0 / config.bpm)))
                    source_bars = max(1, int(round(len(sample) / bar_frames)))
                    source_slot = ((event.step // 16) % source_bars) * 16 + (event.step % 16)
                    slice_index = min(
                        len(slice_ranges) - 1,
                        int(source_slot * len(slice_ranges) / (source_bars * 16)),
                    )
                    frame_start, frame_end = slice_ranges[slice_index]
                    segment = sample[frame_start:frame_end].copy()
                    # Never let one triggered slice spill into the next event.
                    # This keeps the imported break lane rhythmically articulated
                    # even when the detected source region has a long decay.
                    if trigger_index + 1 < len(ordered_triggers):
                        next_start = int(round(
                            ordered_triggers[trigger_index + 1].time * sample_rate
                        ))
                        current_start = int(round(event.time * sample_rate))
                        max_length = max(1, next_start - current_start)
                        segment = segment[:max_length]
                    fade_frames = min(
                        int(round(sample_rate * 0.002)), len(segment) // 2
                    )
                    if fade_frames > 0:
                        fade_in = np.linspace(
                            0.0, 1.0, fade_frames, endpoint=False, dtype=np.float32
                        )
                        fade_out = np.linspace(
                            1.0, 0.0, fade_frames, endpoint=False, dtype=np.float32
                        )
                        segment[:fade_frames] *= fade_in
                        segment[-fade_frames:] *= fade_out
                    place_sample(sample_stem, segment, event.time, event.velocity, event.pan)
                    record.update({
                        "slice_index": slice_index,
                        "source_frame_start": frame_start,
                        "source_frame_end": frame_end,
                        "rendered_frames": int(len(segment)),
                        "trimmed_to_next_trigger": (
                                trigger_index + 1 < len(ordered_triggers)
                                and len(segment) < frame_end - frame_start
                        ),
                    })
                else:
                    place_sample(sample_stem, sample, event.time, event.velocity, event.pan)
                event_records.append(record)

            sample_manifest[role] = {
                "path": str(path.resolve()),
                "sha256": sample_digest,
                "source": role_metadata,
                "frames_after_resampling": source_frame_count,
                "frames_after_processing": int(len(sample)),
                "duration_after_processing": len(sample) / float(sample_rate),
                "trigger_count": len(triggers),
                "transforms": applied_transforms,
                "source_pack": role_metadata.get("pack"),
                "source_family": role_metadata.get("family"),
                "source_articulation": role_metadata.get("articulation"),
                "slice_count": len(slice_ranges) if role == "break" else None,
                "source_bars": source_bars if role == "break" else None,
                "trigger_mode": "transient_slices" if role == "break" else "one_shot",
            }

        synthesis_and_buffer_seconds = perf_counter() - synthesis_started
        headroom_started = perf_counter()
        peak_ceiling = 10.0 ** (-1.0 / 20.0)
        stem_headroom_gains: dict[str, float] = {}
        for stem_name, stem_audio in stems.items():
            stem_peak = float(np.max(np.abs(stem_audio))) if stem_audio.size else 0.0
            stem_gain = min(1.0, peak_ceiling / stem_peak) if stem_peak > 0.0 else 1.0
            if stem_gain < 1.0:
                stem_audio *= stem_gain
            stem_headroom_gains[stem_name] = stem_gain
        headroom_seconds = perf_counter() - headroom_started

        event_records.sort(
            key=lambda event: (float(event.get("time", 0.0)), str(event.get("lane", "")))
        )
        metadata = {
            "algorithm_version": self.VERSION,
            "variation": {"stem": regenerate, "index": variation} if regenerate else None,
            "seed_streams": {
                name: streams.seed_for(name)
                for name in (
                    "kick_pattern", "snare_pattern", "hat_pattern", "break_pattern",
                    "kick_synthesis", "snare_synthesis", "hat_synthesis", "break_synthesis",
                    "kick_profile", "snare_profile", "hat_profile", "break_profile",
                    "section_ornaments",
                    "break_processing",
                    "melody_pattern", "melody_synthesis", "melody_profile",
                    "texture_synthesis", "ambience_synthesis",
                )
            },
            "sample_trigger_seed_streams": {
                name: sample_streams.seed_for(name)
                for name in ("kick_pattern", "snare_pattern", "hat_pattern", "break_pattern", "break_processing")
            },
            "generator_families": {
                "percussion": "euclidean + prime-indexed mutation + logistic control",
                "composition_director": f"seeded formal section plan ({config.structure}/{config.composition_flow})",
                "synthetic_break": "stochastic event grammar with profile-based kick/snare/hat resynthesis",
                "melody": f"3:5 Lissajous curve + logistic-map contour + {config.synth_palette} synthesis palette",
                "texture": "coloured noise with low-frequency amplitude modulation",
                "ambience": "harmonic partial cloud + filtered noise + slow stereo drift",
                "phrase_grammar": "shared phrase functions attenuate role activity; independent role streams remain separate",
                "break_processing": list(config.break_transforms),
            },
            "synthesis_profiles": {
                "kick": config.kick_profile,
                "snare": config.snare_profile,
                "hat": config.hat_profile,
                "melody": melody_profile,
                "palette": config.synth_palette,
                "available_palettes": ["hybrid", "fm", "additive", "modal", "inharmonic", "granular", "physical"],
                "extended_melody_voices": ["inharmonic_mallet", "metallic_fm", "dark_formant", "soft_spectral_pad"],
                "catalogue_counts": {
                    "kick": len(KICK_PROFILES),
                    "snare": len(SNARE_PROFILES),
                    "hat": len(HAT_PROFILES),
                },
            },
            "composition_plan": composition_plan.to_dict(),
            "phrase_directives": [item.to_dict() for item in phrase_directives],
            "synth_palette": config.synth_palette,
            "break_rhythm": {
                "style": next(
                    (
                        event.pattern_style for event in percussion["break"]
                        if event.pattern_style is not None
                    ),
                    config.break_style,
                ),
                "density": config.break_density,
                "variation": config.break_variation,
                "cycle_bars": config.break_cycle_bars,
                "grid": "16-step bar; events remain grid-locked",
            },
            "sample_sources": sample_manifest,
            "event_count": len(event_records),
            "stem_headroom_gains": stem_headroom_gains,
            "performance": {
                "composition_plan_seconds": composition_plan_seconds,
                "event_generation_seconds": event_generation_seconds,
                "synthesis_and_buffer_seconds": synthesis_and_buffer_seconds,
                "headroom_seconds": headroom_seconds,
            },
        }
        metadata["performance"]["total_engine_seconds"] = perf_counter() - total_started
        return ReawarpProject(
            config=config,
            sample_rate=sample_rate,
            stems=stems,
            events=event_records,
            metadata=metadata,
        )
