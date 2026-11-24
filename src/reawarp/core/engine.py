"""Offline-first Reawarp synthesis coordinator."""

from __future__ import annotations

import hashlib
import math
from dataclasses import replace
from time import perf_counter
from pathlib import Path
from typing import Any, Mapping

import numpy as np

from reawarp.composition.director import build_composition_plan, section_for_time
from reawarp.composition.motifs import (
    build_motif_plan, build_motif_role_accents, render_motif_events,
)
from reawarp.composition.orchestration import (
    build_section_orchestration_plan,
    build_transition_plan,
    render_role_envelope,
    role_activity_at_time,
    role_intent_at_time,
    shape_role_events,
)
from reawarp.config import GenerationConfig
from reawarp.core.project import ReawarpProject
from reawarp.core.random_streams import RandomStreams, derive_seed
from reawarp.generators.melody import build_melody_events
from reawarp.generators.percussion import (
    PercussionEvent, build_drum_part_plan, build_percussion_events,
)
from reawarp.samples.io import read_sample
from reawarp.samples.selection import select_sample_variant
from reawarp.score.model import Score
from reawarp.score.render import ScoreRenderResult, ScoreRenderer
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
from reawarp.synthesis.score_voices import build_production_voice_renderers
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

    def render_score(
            self,
            score: Score,
            *,
            sample_rate: int | None = None,
            frame_count: int | None = None,
            voice_renderers: dict[str, Any] | None = None,
            config: GenerationConfig | None = None,
            fx_automation: Mapping[str, Any] | None = None,
    ) -> ScoreRenderResult:
        """Render a canonical score using the shared frame-accurate score core."""
        if config is not None and voice_renderers is not None:
            raise ValueError("pass either production config or explicit voice_renderers, not both")
        rate = (
            int(config.sample_rate if config is not None else score.metadata.get("sample_rate", 48_000))
            if sample_rate is None else int(sample_rate)
        )
        fx_stem_names = tuple(score.metadata.get("render_stems", ()))
        if not fx_stem_names:
            fx_stem_names = tuple(sorted({
                event.voice_id for event in score.events
                if event.voice_id != "sample_break"
            }))
        if fx_automation is not None:
            from reawarp.fx_automation import attach_fx_automation_to_score

            score = attach_fx_automation_to_score(
                score, fx_automation, fx_stem_names
            )
        from reawarp.fx_automation import fx_automation_registry

        automation_registry = fx_automation_registry(fx_stem_names)
        if config is not None:
            from reawarp.synthesis.score_samples import prepare_score_sample_renderers

            render_config = (
                replace(config, sample_rate=rate)
                if int(config.sample_rate) != rate else config
            )
            prepared_samples = prepare_score_sample_renderers(score, render_config)
            score = prepared_samples.score
            production_renderers = build_production_voice_renderers(render_config)
            for role, sample_renderer in prepared_samples.voice_renderers.items():
                base_renderer = production_renderers.get(role)
                if base_renderer is None:
                    production_renderers[role] = sample_renderer
                    continue

                def render_combined(
                    scheduled, callback_rate, controls,
                    _base=base_renderer, _sample=sample_renderer,
                ):
                    if scheduled.event.kind == "trigger":
                        return _sample(scheduled, callback_rate, controls)
                    return _base(scheduled, callback_rate, controls)

                production_renderers[role] = render_combined
            voice_renderers = production_renderers
            if frame_count is None:
                frame_count = render_config.frame_count
        return ScoreRenderer().render(
            score,
            rate,
            frame_count=frame_count,
            voice_renderers=voice_renderers,
            automation_registry=automation_registry,
        )

    def plan_score(
            self,
            config: GenerationConfig | None = None,
            *,
            regenerate: str | None = None,
            variation: int = 1,
            **overrides: Any,
    ) -> Score:
        """Plan the complete symbolic composition without rendering audio."""
        if config is None:
            config = GenerationConfig(**overrides)
        elif overrides:
            raise TypeError("pass either a GenerationConfig or keyword overrides, not both")
        from reawarp.core.score_generation import build_score_generation_plan

        return build_score_generation_plan(
            config, regenerate=regenerate, variation=variation
        ).score

    def generate(
            self,
            config: GenerationConfig | None = None,
            *,
            regenerate: str | None = None,
            variation: int = 1,
            **overrides: Any,
    ) -> ReawarpProject:
        """Generate from a canonical Score, then render its scheduled events."""
        if config is None:
            config = GenerationConfig(**overrides)
        elif overrides:
            raise TypeError("pass either a GenerationConfig or keyword overrides, not both")
        if variation < 1:
            raise ValueError("variation must be a positive integer")

        from reawarp.core.score_generation import (
            build_score_generation_plan,
            score_to_legacy_project_events,
        )

        total_started = perf_counter()
        planning_started = perf_counter()
        plan = build_score_generation_plan(
            config, regenerate=regenerate, variation=variation
        )
        planning_seconds = perf_counter() - planning_started
        composition_plan_seconds = float(
            plan.timings.get("composition_plan_seconds", 0.0)
        )
        event_generation_seconds = float(
            plan.timings.get("event_generation_seconds", 0.0)
        )

        score_render_started = perf_counter()
        rendered = self.render_score(plan.score, config=config)
        score_render_seconds = perf_counter() - score_render_started
        canonical_score = rendered.score or plan.score

        frame_count = config.frame_count
        sample_rate = config.sample_rate
        stems: dict[str, np.ndarray] = {}
        stem_aliases = {"hat": "hats", "break": "synthetic_break"}
        for voice_id, audio in rendered.stems.items():
            stems[stem_aliases.get(voice_id, voice_id)] = np.asarray(
                audio, dtype=np.float32
            ).copy()

        # Keep the historical project stem contract even for an empty lane.
        required_stems = ["kick", "snare", "hats", "synthetic_break"]
        if config.include_melody:
            required_stems.append("melody")
        if config.include_texture:
            required_stems.append("noise_texture")
        if config.include_ambience:
            required_stems.append("ambience")
        if "break" in config.sample_paths:
            required_stems.append("sample_break")
        for name in required_stems:
            stems.setdefault(
                name, np.zeros((frame_count, 2), dtype=np.float32)
            )

        field_render_started = perf_counter()
        if config.include_texture:
            texture_envelope = render_role_envelope(
                "texture", frame_count, sample_rate,
                plan.composition_plan, plan.section_orchestration,
                plan.transition_plan,
            )
            texture = render_noise_texture(
                frame_count,
                sample_rate,
                plan.streams.get("texture_synthesis"),
                amount=0.055 + config.complexity * 0.045,
            )
            delayed = (
                np.concatenate((np.zeros(97, dtype=np.float32), texture[:-97]))
                if len(texture) > 97 else texture
            )
            stems["noise_texture"][:, 0] += texture * texture_envelope * 0.72
            stems["noise_texture"][:, 1] += delayed * texture_envelope * 0.72

        if config.include_ambience:
            ambience_envelope = render_role_envelope(
                "ambience", frame_count, sample_rate,
                plan.composition_plan, plan.section_orchestration,
                plan.transition_plan,
            )
            root_frequency = 55.0 * (
                2.0 ** ((derive_seed(config.seed, "ambience_root") % 24) / 12.0)
            )
            stems["ambience"][:] = render_ambience(
                frame_count,
                sample_rate,
                plan.streams.get("ambience_synthesis"),
                root_frequency=root_frequency,
                amount=config.ambience_level,
            )
            stems["ambience"] *= ambience_envelope[:, None]
        field_render_seconds = perf_counter() - field_render_started

        headroom_started = perf_counter()
        peak_ceiling = 10.0 ** (-1.0 / 20.0)
        stem_headroom_gains: dict[str, float] = {}
        for stem_name, audio in stems.items():
            peak = float(np.max(np.abs(audio))) if audio.size else 0.0
            gain = min(1.0, peak_ceiling / peak) if peak > 0.0 else 1.0
            if gain < 1.0:
                audio *= gain
            stem_headroom_gains[stem_name] = gain
        headroom_seconds = perf_counter() - headroom_started

        sample_schedule = canonical_score.metadata.get("sample_schedule", {})
        if not isinstance(sample_schedule, dict):
            sample_schedule = {}
        sample_sources = dict(sample_schedule.get("sources", {}))
        renderer_version = "reawarp-score-renderer/1.0.0"
        render_provenance = {
            "score_renderer_version": "1.0.0",
            "engine_algorithm_version": self.VERSION,
            "event_source": "Score.events",
            "event_timebase": (
                "rational quarter-note beats; frame placement resolved by RenderTimeline"
            ),
            "root_seed": config.seed,
            "sample_rate": sample_rate,
            "frame_count": frame_count,
            "duration_seconds": frame_count / float(sample_rate),
            "seed_streams": dict(canonical_score.metadata.get("seed_streams", {})),
            "generator_families": dict(canonical_score.metadata.get("generator_families", {})),
        }
        score_metadata = dict(canonical_score.metadata)
        score_metadata.update({
            "render_stems": list(stems),
            "renderer_version": renderer_version,
            "render_provenance": render_provenance,
            "stem_headroom_gains": stem_headroom_gains,
        })
        project_score = replace(canonical_score, metadata=score_metadata)
        project_events = score_to_legacy_project_events(project_score)

        synthesis_and_buffer_seconds = score_render_seconds + field_render_seconds
        performance = {
            "planning_seconds": planning_seconds,
            "composition_plan_seconds": composition_plan_seconds,
            "event_generation_seconds": event_generation_seconds,
            "score_render_seconds": score_render_seconds,
            "field_render_seconds": field_render_seconds,
            "synthesis_and_buffer_seconds": synthesis_and_buffer_seconds,
            "headroom_seconds": headroom_seconds,
            "total_engine_seconds": perf_counter() - total_started,
        }
        metadata = dict(project_score.metadata)
        metadata.update({
            "algorithm_version": self.VERSION,
            "renderer_version": renderer_version,
            "variation": {"stem": regenerate, "index": variation} if regenerate else None,
            "sample_sources": sample_sources,
            "sample_switch_summary": dict(sample_schedule.get("switch_summary", {})),
            "synthesis_profiles": {
                "kick": config.kick_profile,
                "snare": config.snare_profile,
                "hat": config.hat_profile,
                "melody": plan.melody_profile,
                "break": dict(plan.break_profiles),
                "section_profiles": {
                    role: {
                        section.name: plan.selected_profiles[role][section.index]
                        for section in plan.composition_plan.sections
                    }
                    for role in ("kick", "snare", "hat")
                },
                "palette": config.synth_palette,
                "percussion_source_mode": config.percussion_source_mode,
                "percussion_hybrid_architecture": config.percussion_hybrid_architecture,
                "percussion_sample_mix": config.percussion_sample_mix,
                "drum_sample_automation": config.drum_sample_automation,
                "sample_bank_sizes": {
                    role: int(record.get("bank_count", 0))
                    for role, record in sample_sources.items()
                },
                "melody_scale": config.melody_scale,
                "melody_root": config.melody_root,
            },
            "drum_source_mode": config.percussion_source_mode,
            "drum_hybrid_architecture": config.percussion_hybrid_architecture,
            "drum_sample_mix": config.percussion_sample_mix,
            "drum_sample_automation": config.drum_sample_automation,
            "synth_palette": config.synth_palette,
            "event_count": len(project_events),
            "stem_headroom_gains": stem_headroom_gains,
            "performance": performance,
        })
        score_metadata = dict(project_score.metadata)
        score_metadata.update({
            "event_count": len(project_events),
            "performance": performance,
        })
        project_score = replace(project_score, metadata=score_metadata)

        return ReawarpProject(
            config=config,
            sample_rate=sample_rate,
            stems=stems,
            events=project_events,
            metadata=metadata,
            score=project_score,
        )

    def generate_legacy(
            self,
            config: GenerationConfig | None = None,
            *,
            regenerate: str | None = None,
            variation: int = 1,
            **overrides: Any,
    ) -> ReawarpProject:
        """Run the pre-M17.5 renderer for reproducibility comparisons."""
        return self._generate_legacy(
            config, regenerate=regenerate, variation=variation, **overrides
        )

    def generate_variant(
            self,
            config: GenerationConfig,
            stem: str,
            variation: int = 1,
            *,
            base_project: ReawarpProject | None = None,
    ) -> ReawarpProject:
        """Regenerate one canonical score voice and merge it into a frozen project."""
        variant = self.generate(config, regenerate=stem, variation=variation)
        if base_project is None:
            return variant
        if base_project.config != config:
            raise ValueError("base_project configuration must match")
        if stem not in base_project.stems or stem not in variant.stems:
            raise ValueError(f"layer {stem!r} is not present in both projects")

        from reawarp.core.score_generation import score_to_legacy_project_events

        merged_stems = dict(base_project.stems)
        merged_stems[stem] = variant.stems[stem]
        target_voice = self._event_lane_for_stem(stem)
        base_score = base_project.to_score()
        variant_score = variant.to_score()
        merged_score_events = [
            event for event in base_score.events if event.voice_id != target_voice
        ]
        merged_score_events.extend(
            event for event in variant_score.events if event.voice_id == target_voice
        )

        metadata = dict(variant_score.metadata)
        gains = dict(base_project.metadata.get("stem_headroom_gains", {}))
        gains[stem] = variant.metadata.get("stem_headroom_gains", {}).get(stem, 1.0)
        metadata["stem_headroom_gains"] = gains
        metadata["variation"] = {"stem": stem, "index": variation}
        metadata["variation_parent_seed"] = config.seed
        merged_score = replace(
            variant_score, events=tuple(merged_score_events), metadata=metadata
        )
        merged_events = score_to_legacy_project_events(merged_score)

        project_metadata = dict(base_project.metadata)
        project_metadata.update({
            "variation": {"stem": stem, "index": variation},
            "variation_parent_seed": config.seed,
            "stem_headroom_gains": gains,
            "event_count": len(merged_events),
            "seed_streams": dict(variant.metadata.get("seed_streams", {})),
            "sample_trigger_seed_streams": dict(
                variant.metadata.get("sample_trigger_seed_streams", {})
            ),
            "sample_sources": dict(variant.metadata.get("sample_sources", {})),
            "sample_switch_summary": dict(
                variant.metadata.get("sample_switch_summary", {})
            ),
            "performance": dict(variant.metadata.get("performance", {})),
        })
        return ReawarpProject(
            config=config,
            sample_rate=base_project.sample_rate,
            stems=merged_stems,
            events=merged_events,
            metadata=project_metadata,
            score=merged_score,
        )

    @staticmethod
    def _event_lane_for_stem(stem: str) -> str:
        return {"hats": "hat", "synthetic_break": "break"}.get(stem, stem)

    def _generate_legacy(
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
        drum_plan = build_drum_part_plan(config, composition_plan)

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
                gain_scale: float = 1.0,
        ) -> None:
            shaped = (
                sample * float(np.clip(velocity, 0.0, 1.0))
                * float(np.clip(gain_scale, 0.0, 2.0)) * 0.72
            )
            place_mono(target, shaped, start_seconds, pan)

        percussion_rngs = {
            "kick": streams.get("kick_pattern"),
            "snare": streams.get("snare_pattern"),
            "hat": streams.get("hat_pattern"),
            "break": streams.get("break_pattern"),
        }
        percussion = build_percussion_events(
            config, percussion_rngs, composition_plan, drum_plan=drum_plan
        )
        # The motif source uses its own named stream. Regenerating the melody
        # can vary that stem without changing the rhythmic shadow carried by hats
        # and snare responses in the other stems.
        melody_variation_events = build_melody_events(config, streams.get("melody_pattern"))
        motif_anchor_streams = RandomStreams(config.seed)
        motif_source_events = build_melody_events(
            config, motif_anchor_streams.get("motif_anchor")
        )
        motif_plan = build_motif_plan(
            motif_source_events,
            composition_plan,
            phrase_directives,
            bpm=config.bpm,
            seed=config.seed,
        )
        melody_events = (
            render_motif_events(
                motif_plan, bpm=config.bpm, duration_seconds=config.duration
            )
            if motif_plan is not None else melody_variation_events
        )
        if motif_plan is not None and melody_variation_events:
            # Keep motif identity/rhythm fixed while allowing an isolated melody
            # regeneration to alter expressive velocity and stereo motion.
            melody_events = [
                replace(
                    event,
                    velocity=float(np.clip(
                        event.velocity * (
                            0.90 + 0.20 * melody_variation_events[index % len(melody_variation_events)].velocity
                        ),
                        0.0, 1.0,
                    )),
                    pan=float(np.clip(
                        event.pan * 0.86
                        + 0.14 * melody_variation_events[index % len(melody_variation_events)].pan,
                        -0.85, 0.85,
                    )),
                )
                for index, event in enumerate(melody_events)
            ]

        section_orchestration = build_section_orchestration_plan(
            composition_plan, phrase_directives, config, motif_plan
        )
        transition_plan = build_transition_plan(composition_plan, phrase_directives)
        if motif_plan is not None:
            for accent in build_motif_role_accents(
                motif_plan, bpm=config.bpm, duration_seconds=config.duration
            ):
                percussion[accent.role].append(PercussionEvent(
                    lane=accent.role,
                    step=accent.step,
                    time=accent.step * config.sixteenth_seconds,
                    velocity=accent.velocity,
                    pan=accent.pan,
                    kind=accent.kind,
                    pattern_style=accent.pattern_style,
                    motif_id=accent.motif_id,
                    motif_relation=accent.motif_relation,
                ))
        for role in percussion:
            percussion[role] = shape_role_events(
                role, percussion[role], composition_plan, section_orchestration,
                step_seconds=config.sixteenth_seconds, seed=config.seed,
            )

        # Continuous role envelopes consume the same section/transition plan
        # used by note and percussion events.
        texture_envelope = render_role_envelope(
            "texture", frame_count, sample_rate, composition_plan,
            section_orchestration, transition_plan,
        )
        ambience_envelope = render_role_envelope(
            "ambience", frame_count, sample_rate, composition_plan,
            section_orchestration, transition_plan,
        )

        activity_defaults = {
            "kick": 0.78, "snare": 0.66, "hat": 0.68, "break": 0.62,
        }
        phrase_shaped_percussion: dict[str, list[Any]] = {}
        for role, events in percussion.items():
            adjusted = []
            for event in events:
                activity = role_activity_at_time(
                    role, float(event.time), composition_plan,
                    section_orchestration, transition_plan,
                )
                velocity = (
                    float(event.velocity) * min(1.0, activity / activity_defaults[role])
                    if activity > 0.0 else 0.0
                )
                if velocity > 1e-7:
                    adjusted.append(replace(
                        event, velocity=float(np.clip(velocity, 0.0, 1.0))
                    ))
            phrase_shaped_percussion[role] = adjusted

        phrase_shaped_melody = []
        for event in melody_events:
            activity = role_activity_at_time(
                "melody", float(event.time), composition_plan,
                section_orchestration, transition_plan,
            )
            velocity = (
                float(event.velocity) * min(1.0, activity / 0.72)
                if activity > 0.0 else 0.0
            )
            if velocity > 1e-7:
                phrase_shaped_melody.append(
                    replace(event, velocity=float(np.clip(velocity, 0.0, 1.0)))
                )
        percussion = phrase_shaped_percussion
        melody_events = phrase_shaped_melody

        event_generation_seconds = perf_counter() - event_generation_started
        synthesis_started = perf_counter()

        kick_stem = new_stem("kick")
        snare_stem = new_stem("snare")
        hat_stem = new_stem("hats")
        break_stem = new_stem("synthetic_break")

        sample_manifest: dict[str, dict[str, Any]] = {}
        drum_sample_banks: dict[str, list[dict[str, Any]]] = {}
        sample_selection_cache: dict[tuple[str, int, int], int] = {}
        sample_switch_history: dict[str, list[dict[str, Any]]] = {
            role: [] for role in ("kick", "snare", "hat")
        }
        sample_variant_usage: dict[str, dict[str, int]] = {
            role: {} for role in ("kick", "snare", "hat")
        }
        current_sample_index = {role: 0 for role in ("kick", "snare", "hat")}

        for role in ("kick", "snare", "hat"):
            raw_entries = (
                [] if config.percussion_source_mode == "synth"
                else list(config.sample_banks.get(role, ()))
            )
            if not raw_entries and config.sample_paths.get(role) and config.percussion_source_mode != "synth":
                raw_entries = [{
                    "path": config.sample_paths[role],
                    "metadata": config.sample_metadata.get(role, {}),
                    "features": {},
                }]
            loaded_entries: list[dict[str, Any]] = []
            for raw_entry in raw_entries:
                path = Path(str(raw_entry.get("path", ""))).expanduser()
                if not path.is_file():
                    raise FileNotFoundError(f"{role} sample-bank file does not exist: {path}")
                audio = read_sample(path, sample_rate)
                metadata_source = dict(raw_entry.get("metadata") or {})
                features = dict(raw_entry.get("features") or {})
                digest = str(raw_entry.get("sha256") or hashlib.sha256(path.read_bytes()).hexdigest())
                loaded_entries.append({
                    "path": str(path.resolve()),
                    "audio": audio,
                    "sha256": digest,
                    "metadata": metadata_source,
                    "features": features,
                    "asset_id": str(raw_entry.get("asset_id") or digest[:16]),
                    "label": str(raw_entry.get("label") or path.name),
                    "duration_seconds": len(audio) / float(sample_rate),
                })
            if not loaded_entries and config.sample_paths.get(role):
                raise ValueError(f"{role} sample bank did not produce a usable source")
            if loaded_entries:
                drum_sample_banks[role] = loaded_entries
                anchor = loaded_entries[0]
                sample_manifest[role] = {
                    "path": anchor["path"],
                    "sha256": anchor["sha256"],
                    "source": anchor["metadata"],
                    "bank_count": len(loaded_entries),
                    "variants": [
                        {
                            "index": index,
                            "asset_id": entry["asset_id"],
                            "path": entry["path"],
                            "sha256": entry["sha256"],
                            "label": entry["label"],
                            "metadata": entry["metadata"],
                            "features": entry["features"],
                        }
                        for index, entry in enumerate(loaded_entries)
                    ],
                    "frames_after_resampling": int(len(anchor["audio"])),
                    "frames_after_processing": int(len(anchor["audio"])),
                    "duration_after_processing": anchor["duration_seconds"],
                    "trigger_count": 0,
                    "trigger_mode": "shared_drum_score",
                    "selection_mode": config.drum_sample_automation,
                    "hybrid_architecture": config.percussion_hybrid_architecture,
                    "switch_points": sample_switch_history[role],
                    "variant_usage": sample_variant_usage[role],
                }

        def select_role_sample(role: str, event: Any) -> dict[str, Any] | None:
            bank = drum_sample_banks.get(role)
            if not bank:
                return None
            if len(bank) == 1 or config.drum_sample_automation == "fixed":
                selected_index = 0
            else:
                section = section_for_time(composition_plan, float(event.time))
                directive = phrase_at_time(float(event.time))
                bar = int(np.floor(float(event.time) / max(240.0 / config.bpm, 1e-9)))
                cycle_index = max(0, (bar - section.start_bar) // int(config.drum_part_cycle_bars))
                function = directive.function
                mode = config.drum_sample_automation
                if mode == "section":
                    key = (role, section.index, -1)
                    should_switch = function not in {
                        "introduction", "establishment", "return", "silence", "outro"
                    }
                elif mode == "cycle":
                    key = (role, section.index, cycle_index)
                    should_switch = function not in {
                        "introduction", "establishment", "return", "silence", "outro"
                    }
                else:
                    key = (role, section.index, cycle_index)
                    should_switch = function in {
                        "development", "uplift", "arrival", "contrast", "transition", "false_return"
                    }
                    if function in {"introduction", "establishment"}:
                        should_switch = False
                if function == "return":
                    selected_index = 0
                    sample_selection_cache[key] = 0
                elif not should_switch:
                    selected_index = current_sample_index[role]
                elif key in sample_selection_cache:
                    selected_index = sample_selection_cache[key]
                else:
                    switch_seed = derive_seed(
                        config.seed,
                        f"sample-switch:{role}:{section.index}:{cycle_index}:{function}",
                    )
                    selected_index = select_sample_variant(
                        bank,
                        role=role,
                        phrase_function=function,
                        seed=switch_seed,
                        anchor_index=0,
                        previous_index=current_sample_index[role],
                        intensity=config.drum_change_intensity,
                    )
                    sample_selection_cache[key] = selected_index

                previous_index = current_sample_index[role]
                current_sample_index[role] = int(selected_index)
                if selected_index != previous_index:
                    switch_record = {
                        "time": float(event.time),
                        "bar": bar + 1,
                        "section": section.name,
                        "function": function,
                        "from_index": int(previous_index),
                        "to_index": int(selected_index),
                        "asset_id": bank[selected_index]["asset_id"],
                        "label": bank[selected_index]["label"],
                    }
                    sample_switch_history[role].append(switch_record)
            entry = bank[int(selected_index)]
            usage = sample_variant_usage[role]
            usage[str(selected_index)] = usage.get(str(selected_index), 0) + 1
            return entry

        def percussion_source_levels(role: str, time_seconds: float) -> tuple[float, float]:
            """Return (synth gain, sample gain) for one role/section."""
            if role not in drum_sample_banks:
                return 1.0, 0.0
            mode = config.percussion_source_mode
            if mode == "synth":
                return 1.0, 0.0
            if mode == "sample":
                return 0.0, 1.0
            sample_mix = float(config.percussion_sample_mix)
            if mode == "automatic":
                function = phrase_at_time(time_seconds).function
                section_factor = {
                    "introduction": 0.35,
                    "establishment": 0.90,
                    "continuation": 0.78,
                    "development": 1.05,
                    "uplift": 1.18,
                    "arrival": 1.35,
                    "drop": 0.32,
                    "silence": 0.0,
                    "contrast": 1.08,
                    "return": 0.92,
                    "false_return": 0.58,
                    "transition": 0.72,
                    "residue": 0.30,
                    "outro": 0.24,
                }.get(function, 0.8)
                sample_mix = float(np.clip(sample_mix * section_factor, 0.0, 0.90))
            if config.percussion_hybrid_architecture == "transient_body":
                return 1.0, sample_mix
            # Full-layer and feature-guided hybrids use complementary gains.
            return 1.0 - sample_mix, sample_mix

        def place_role_sample(
            role: str,
            target: np.ndarray,
            event: Any,
            sample_gain: float,
            source_entry: dict[str, Any],
        ) -> None:
            source = source_entry["audio"]
            segment = source
            architecture = config.percussion_hybrid_architecture
            if architecture in {"transient_body", "feature_guided"} and config.percussion_source_mode != "sample":
                transient_ms = float(config.hybrid_transient_ms)
                if architecture == "feature_guided":
                    features = source_entry.get("features", {})
                    crest = float(features.get("crest_factor_db", 6.0))
                    transient_ms *= float(np.clip(0.72 + crest / 35.0, 0.65, 1.35))
                transient_frames = max(8, int(round(sample_rate * transient_ms / 1000.0)))
                segment = source[:min(len(source), transient_frames)].copy()
                fade_frames = min(max(2, int(round(sample_rate * 0.002))), len(segment) // 2)
                if fade_frames:
                    segment[:fade_frames] *= np.linspace(
                        0.0, 1.0, fade_frames, endpoint=False, dtype=np.float32
                    )
                    segment[-fade_frames:] *= np.linspace(
                        1.0, 0.0, fade_frames, endpoint=False, dtype=np.float32
                    )
            place_sample(
                target, segment, event.time,
                event.velocity * sample_gain, event.pan,
            )

        synthetic_percussion = (
            config.percussion_synthesis in {"minimal", "extended"}
            or config.percussion_hybrid_architecture == "feature_guided"
        )
        role_targets = {
            "kick": kick_stem,
            "snare": snare_stem,
            "hat": hat_stem,
        }
        profile_catalogues = {
            "kick": (config.kick_profile, KICK_PROFILES, AUTO_KICK_PROFILES),
            "snare": (config.snare_profile, SNARE_PROFILES, AUTO_SNARE_PROFILES),
            "hat": (config.hat_profile, HAT_PROFILES, AUTO_HAT_PROFILES),
        }
        section_profile_options = {
            "kick": {
                "intro": ("soft_round", "deep_sub"),
                "establishment": ("deep_sub", "909_punch"),
                "continuation": ("deep_sub", "rubber", "wooden"),
                "development": ("rubber", "wooden", "fm_bass", "broken_digital"),
                "uplift": ("909_punch", "rubber", "industrial"),
                "arrival": ("909_punch", "hard_click", "industrial"),
                "drop": ("short_pluck", "soft_round"),
                "silence": ("soft_round",),
                "contrast": ("wooden", "fm_bass", "laser"),
                "return": ("deep_sub", "909_punch"),
                "false_return": ("soft_round", "rubber"),
                "transition": ("wooden", "short_pluck"),
                "residue": ("soft_round", "long_tail"),
                "outro": ("soft_round", "long_tail"),
            },
            "snare": {
                "intro": ("soft_brush", "tonal"),
                "establishment": ("acoustic", "909_crack"),
                "continuation": ("acoustic", "tonal"),
                "development": ("tonal", "soft_brush", "noise_burst"),
                "uplift": ("909_crack", "acoustic"),
                "arrival": ("909_crack", "industrial", "tonal"),
                "drop": ("soft_brush", "tonal"),
                "silence": ("soft_brush",),
                "contrast": ("tonal", "soft_brush", "industrial"),
                "return": ("acoustic", "909_crack"),
                "false_return": ("tonal", "soft_brush"),
                "transition": ("909_crack", "tonal"),
                "residue": ("soft_brush", "tonal"),
                "outro": ("soft_brush",),
            },
            "hat": {
                "intro": ("dark", "closed"),
                "establishment": ("closed", "dark"),
                "continuation": ("closed", "open", "dark"),
                "development": ("dark", "open", "digital"),
                "uplift": ("open", "metallic"),
                "arrival": ("metallic", "digital", "noisy"),
                "drop": ("dark", "closed"),
                "silence": ("dark",),
                "contrast": ("open", "metallic", "dark"),
                "return": ("closed", "dark"),
                "false_return": ("dark", "open"),
                "transition": ("metallic", "open"),
                "residue": ("dark", "closed"),
                "outro": ("dark",),
            },
        }

        def build_section_profiles(role: str) -> dict[int, str]:
            configured, catalogue, auto_choices = profile_catalogues[role]
            section_choices: dict[int, str] = {}
            anchor_profile: str | None = None
            for section in composition_plan.sections:
                function = phrase_at_time(section.start_seconds).function
                if function == "return" and anchor_profile is not None:
                    section_choices[section.index] = anchor_profile
                    continue
                choices = section_profile_options[role].get(function, auto_choices)
                profile_rng = np.random.default_rng(
                    derive_seed(config.seed, f"section-profile:{role}:{section.index}:{function}")
                )
                selected = select_profile_name(
                    configured, catalogue, profile_rng, auto_choices=choices
                )
                section_choices[section.index] = selected
                if function == "establishment":
                    anchor_profile = selected
            return section_choices

        selected_profiles = {
            role: build_section_profiles(role) for role in ("kick", "snare", "hat")
        }
        for role in ("kick", "snare", "hat"):
            target = role_targets[role]
            synthesis_rng = streams.get(f"{role}_synthesis")
            for event in percussion[role]:
                if event.velocity <= 1e-7:
                    continue
                section = section_for_time(composition_plan, event.time)
                if role == "kick" and not section.kick:
                    continue
                if role == "snare" and section.density < 0.14 and event.velocity < 0.70:
                    continue
                if (
                    role == "hat"
                    and event.motif_relation != "shadow"
                    and streams.get("section_ornaments").random() > section.percussion_density_scale
                ):
                    continue

                source_entry = (
                    None if config.percussion_source_mode == "synth"
                    else select_role_sample(role, event)
                )
                synth_gain, sample_gain = percussion_source_levels(role, event.time)
                if source_entry is None:
                    sample_gain = 0.0
                profile = selected_profiles[role][section.index]
                signal: np.ndarray | None = None
                guidance: dict[str, float] = {}
                feature_pitch_ratio = 1.0
                feature_velocity = 1.0
                feature_voice: str | None = None
                if source_entry is not None and config.percussion_hybrid_architecture == "feature_guided":
                    features = source_entry.get("features", {})
                    centroid = float(features.get("spectral_centroid_hz", 3_000.0))
                    flatness = float(features.get("spectral_flatness", 0.35))
                    onset_density = float(features.get("onset_density_per_second", 4.0))
                    brightness = float(np.clip(
                        np.log(max(100.0, centroid) / 100.0) / np.log(160.0), 0.0, 1.0
                    ))
                    transient_density = float(np.clip(onset_density / 12.0, 0.0, 1.0))
                    feature_pitch_ratio = float(2.0 ** ((brightness - 0.5) * 4.0 / 12.0))
                    feature_velocity = float(np.clip(
                        0.88 + 0.18 * transient_density, 0.84, 1.08
                    ))
                    if role == "kick":
                        feature_voice = "dry_thump" if flatness >= 0.30 else "soft_kick"
                    elif role == "snare":
                        feature_voice = "muted_rim" if flatness < 0.28 else "paper_snare"
                    else:
                        feature_voice = "metal_tick" if centroid >= 5_500.0 else "noise_hat"
                    guidance = {
                        "spectral_centroid_hz": centroid,
                        "spectral_flatness": float(np.clip(flatness, 0.0, 1.0)),
                        "onset_density_per_second": onset_density,
                        "brightness": brightness,
                        "transient_density": transient_density,
                        "pitch_ratio": feature_pitch_ratio,
                        "velocity_scale": feature_velocity,
                    }

                if synth_gain > 1e-7:
                    velocity = float(np.clip(
                        event.velocity * synth_gain * feature_velocity, 0.0, 1.0
                    ))
                    if role == "kick":
                        if synthetic_percussion:
                            voice = feature_voice or (
                                "soft_kick" if config.percussion_synthesis == "minimal" else "dry_thump"
                            )
                            signal = render_synthetic_percussion(
                                voice,
                                sample_rate, synthesis_rng,
                                velocity=velocity, duration=0.19,
                                pitch_hz=KICK_PROFILES[profile].end_frequency * feature_pitch_ratio,
                            )
                        else:
                            signal = render_kick(
                                sample_rate, synthesis_rng, velocity, profile=profile
                            )
                    elif role == "snare":
                        if synthetic_percussion:
                            voice = feature_voice or (
                                "paper_snare" if config.percussion_synthesis == "minimal" else "muted_rim"
                            )
                            signal = render_synthetic_percussion(
                                voice,
                                sample_rate, synthesis_rng,
                                velocity=velocity, duration=0.17,
                                pitch_hz=SNARE_PROFILES[profile].body_frequency * feature_pitch_ratio,
                            )
                        else:
                            signal = render_snare(
                                sample_rate, synthesis_rng, velocity, profile=profile
                            )
                    else:
                        if synthetic_percussion:
                            voice = feature_voice or (
                                "noise_hat" if config.percussion_synthesis == "minimal" else "metal_tick"
                            )
                            signal = render_synthetic_percussion(
                                voice,
                                sample_rate, synthesis_rng,
                                velocity=velocity, duration=0.085,
                                pitch_hz=HAT_PROFILES[profile].partials[0][0] * feature_pitch_ratio,
                            )
                        else:
                            signal = render_hat(
                                sample_rate, synthesis_rng, velocity, profile=profile
                            )
                    place_mono(target, signal, event.time, event.pan)

                if sample_gain > 1e-7 and source_entry is not None:
                    place_role_sample(role, target, event, sample_gain, source_entry)

                record = event.to_dict()
                record["section_name"] = section.name
                record["phrase_function"] = phrase_at_time(event.time).function
                record["sound_profile"] = profile if synth_gain > 1e-7 else None
                record["source_mix"] = {
                    "mode": config.percussion_source_mode,
                    "architecture": config.percussion_hybrid_architecture,
                    "synth_gain": synth_gain,
                    "sample_gain": sample_gain,
                    "sample_variant_index": (
                        next(
                            (
                                index for index, entry in enumerate(drum_sample_banks.get(role, []))
                                if source_entry is not None and entry["asset_id"] == source_entry["asset_id"]
                            ),
                            None,
                        )
                    ),
                }
                if source_entry is not None:
                    metadata = source_entry["metadata"]
                    record["sample_metadata"] = {
                        key: metadata[key]
                        for key in (
                            "provider", "role", "relative_path", "source_name",
                            "family", "articulation", "asset_type",
                        )
                        if key in metadata
                    }
                    record["sample_source"] = {
                        "asset_id": source_entry["asset_id"],
                        "path": source_entry["path"],
                        "sha256": source_entry["sha256"],
                        "label": source_entry["label"],
                        "variant_index": record["source_mix"]["sample_variant_index"],
                    }
                if guidance:
                    record["synthesis_guidance"] = guidance
                event_records.append(record)
        for role, bank in drum_sample_banks.items():
            sample_manifest[role]["trigger_count"] = sum(
                1 for event in event_records
                if event.get("lane") == role
                and event.get("source_mix", {}).get("sample_gain", 0.0) > 0.0
            )
            sample_manifest[role]["switch_points"] = sample_switch_history[role]
            sample_manifest[role]["variant_usage"] = sample_variant_usage[role]
            sample_manifest[role]["final_variant_count"] = len({
                event.get("sample_source", {}).get("asset_id")
                for event in event_records
                if event.get("lane") == role and event.get("sample_source")
            })

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
            if event.velocity <= 1e-7:
                continue
            section = section_for_time(composition_plan, event.time)
            if event.kind == "kick" and not section.kick:
                continue
            if event.kind != "kick" and section.density < 0.16:
                continue
            break_activity = role_activity_at_time(
                "break", event.time, composition_plan,
                section_orchestration, transition_plan,
            )
            if break_activity <= 1e-7:
                continue
            velocity = float(event.velocity * min(1.0, break_activity / 0.62))
            if velocity <= 1e-7:
                continue
            break_rng = streams.get("break_synthesis")
            if event.kind == "kick":
                profile = break_profiles["kick"]
                signal = render_kick(
                    sample_rate,
                    break_rng,
                    velocity * 0.82,
                    duration=0.31,
                    amp_decay=0.16,
                    profile=profile,
                )
            elif event.kind == "snare":
                profile = break_profiles["snare"]
                signal = render_snare(
                    sample_rate, break_rng, velocity * 0.78, duration=0.22, profile=profile
                )
            else:
                profile = break_profiles["hat"]
                signal = render_hat(
                    sample_rate, break_rng, velocity * 0.9, duration=0.075, profile=profile
                )
            place_mono(break_stem, signal, event.time, event.pan)
            record = event.to_dict()
            record["velocity"] = velocity
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
                if event.velocity <= 1e-7 or not section.melody:
                    continue
                intent = role_intent_at_time(
                    "melody", event.time, composition_plan, section_orchestration
                )
                effective_frequency = event.frequency * (
                    2.0 ** (intent.register_semitones / 12.0)
                )
                melodic_instability = float(np.clip(
                    0.62 * config.arrangement_instability
                    + 0.38 * section.instability,
                    0.0, 1.0,
                ))
                if config.synth_palette == "subtractive":
                    signal = render_subtractive_note(
                        effective_frequency, sample_rate, streams.get("melody_synthesis"),
                        duration=event.duration, velocity=event.velocity,
                        profile=melody_profile, brightness=intent.brightness,
                        instability=melodic_instability,
                    )
                else:
                    signal = render_extended_note(
                        effective_frequency, sample_rate, streams.get("melody_synthesis"),
                        duration=event.duration, velocity=event.velocity,
                        palette=config.synth_palette, brightness=intent.brightness,
                        instability=melodic_instability,
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
            texture_gain = texture_envelope
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
            ambience_stem *= ambience_envelope[:, None]
            event_records.append({
                "lane": "ambience",
                "time": 0.0,
                "duration": config.duration,
                "kind": "harmonic_ambient_bed",
                "root_frequency": root_frequency,
                "amount": config.ambience_level,
            })

        for role, sample_path in config.sample_paths.items():
            if role in {"kick", "snare", "hat"}:
                continue
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
            triggers = percussion[role]
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
                "shared_drum_score": True,
                "break_processing": sample_streams.seed_for("break_processing"),
                "motif_anchor": motif_anchor_streams.seed_for("motif_anchor"),
            },
            "generator_families": {
                "percussion": (
                    "section-aware role grammars with stable anchor, linked kick/snare/hat "
                    "families, phrase-boundary transition gestures"
                    if config.pattern_follow_structure
                    else "sparse Euclidean core with bar-rotating accents"
                ),
                "drum_arrangement": "shared formal-section plan drives both sample and synthesis layers",
                "drum_source_mode": config.percussion_source_mode,
                "drum_sample_automation": config.drum_sample_automation,
                "hybrid_architecture": config.percussion_hybrid_architecture,
                "composition_director": f"seeded formal section plan ({config.structure}/{config.composition_flow})",
                "synthetic_break": "stochastic event grammar with profile-based kick/snare/hat resynthesis",
                "melody": (
                    f"persistent {motif_plan.anchor.motif_id} motif + section transformations + "
                    f"{config.synth_palette} synthesis palette"
                    if motif_plan is not None else
                    f"3:5 Lissajous curve + logistic-map contour + {config.synth_palette} synthesis palette"
                ),
                "texture": "coloured noise with low-frequency amplitude modulation",
                "ambience": "harmonic partial cloud + filtered noise + slow stereo drift",
                "phrase_grammar": "shared phrase functions control section role intent and bar-aligned transitions",
                "motif_system": "stable source identity with deterministic phrase transformations and cross-role rhythm shadows",
                "orchestration": "seven independent role intents with separate activity, density, syncopation, register, brightness and space axes",
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
                "percussion_source_mode": config.percussion_source_mode,
                "percussion_hybrid_architecture": config.percussion_hybrid_architecture,
                "percussion_sample_mix": config.percussion_sample_mix,
                "drum_sample_automation": config.drum_sample_automation,
                "sample_bank_sizes": {
                    role: len(bank) for role, bank in drum_sample_banks.items()
                },
                "melody_scale": config.melody_scale,
                "melody_root": config.melody_root,
            },
            "composition_plan": composition_plan.to_dict(),
            "phrase_directives": [item.to_dict() for item in phrase_directives],
            "motif_plan": motif_plan.to_dict() if motif_plan is not None else None,
            "section_orchestration": [item.to_dict() for item in section_orchestration],
            "transition_gestures": [item.to_dict() for item in transition_plan],
            "composition_axes": {
                "arrangement_density": config.arrangement_density,
                "rhythmic_syncopation": config.rhythmic_syncopation,
                "arrangement_instability": config.arrangement_instability,
                "melodic_activity": config.melodic_activity,
                "melody_register_semitones": config.melody_register_semitones,
                "tonal_brightness": config.tonal_brightness,
                "spatial_intent": config.spatial_intent,
            },
            "drum_arrangement": [item.to_dict() for item in drum_plan],
            "drum_section_profiles": {
                role: {
                    section.name: selected_profiles[role][section.index]
                    for section in composition_plan.sections
                }
                for role in ("kick", "snare", "hat")
            },
            "drum_source_mode": config.percussion_source_mode,
            "drum_hybrid_architecture": config.percussion_hybrid_architecture,
            "drum_sample_mix": config.percussion_sample_mix,
            "drum_sample_automation": config.drum_sample_automation,
            "sample_switch_summary": {
                role: {
                    "bank_count": len(drum_sample_banks.get(role, [])),
                    "switch_count": len(sample_switch_history[role]),
                    "variant_usage": dict(sample_variant_usage[role]),
                    "switch_points": list(sample_switch_history[role]),
                }
                for role in ("kick", "snare", "hat")
            },
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
