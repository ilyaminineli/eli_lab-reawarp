"""Score-first generation planning and legacy project-event projections.

The composition grammar still uses its established section and phrase planners.
Once those planners have made their decisions, every event-backed lane is stored
as a rational-beat MusicalEvent before audio rendering begins. Seconds are only
introduced later by the RenderTimeline, or when producing a legacy export view.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Any

import numpy as np

from reawarp.composition.director import build_composition_plan
from reawarp.composition.motifs import (
    build_motif_plan,
    build_motif_role_accents,
    render_motif_events,
)
from reawarp.composition.orchestration import (
    build_section_orchestration_plan,
    build_transition_plan,
    role_activity_at_time,
    role_intent_at_time,
    shape_role_events,
)
from reawarp.composition.phrase import build_phrase_directives
from reawarp.config import GenerationConfig
from reawarp.core.random_streams import RandomStreams, derive_seed
from reawarp.generators.melody import build_melody_events
from reawarp.generators.percussion import (
    PercussionEvent,
    build_drum_part_plan,
    build_percussion_events,
)
from reawarp.score.events import MusicalEvent
from reawarp.score.model import Score
from reawarp.score.planner import melody_to_score_events, percussion_to_score_events
from reawarp.score.time import MeterMap, TempoMap
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


@dataclass(slots=True)
class ScoreGenerationPlan:
    """Canonical score plus the specialist context needed by whole-field renderers."""

    score: Score
    composition_plan: Any
    phrase_directives: tuple[Any, ...]
    section_orchestration: tuple[Any, ...]
    transition_plan: tuple[Any, ...]
    streams: RandomStreams
    motif_plan: Any
    selected_profiles: dict[str, dict[int, str]]
    melody_profile: str | None
    break_profiles: dict[str, str]


def _profile_options() -> dict[str, dict[str, tuple[str, ...]]]:
    return {
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


def _seed_overrides(regenerate: str | None, variation: int, seed: int | str) -> dict[str, int]:
    groups = {
        "kick": ("kick_pattern", "kick_synthesis", "kick_profile"),
        "snare": ("snare_pattern", "snare_synthesis", "snare_profile"),
        "hats": ("hat_pattern", "hat_synthesis", "hat_profile"),
        "synthetic_break": (
            "break_pattern", "break_synthesis", "break_profile", "break_processing",
        ),
        "melody": ("melody_pattern", "melody_synthesis", "melody_profile"),
        "noise_texture": ("texture_synthesis",),
        "ambience": ("ambience_synthesis",),
        "sample_break": ("break_pattern", "break_processing"),
    }
    if regenerate is None:
        return {}
    if regenerate not in groups:
        raise ValueError(f"unknown stem for regeneration: {regenerate}")
    return {
        name: derive_seed(seed, f"variation:{regenerate}:{variation}:{name}")
        for name in groups[regenerate]
    }


def _section_at_time(composition_plan, time_seconds: float):
    for section in composition_plan.sections:
        if section.start_seconds <= time_seconds < section.end_seconds:
            return section
    return (
        composition_plan.sections[0]
        if time_seconds < 0 else composition_plan.sections[-1]
    )


def _phrase_at_time(phrase_directives, bpm: float, time_seconds: float):
    for directive in phrase_directives:
        start = directive.start_bar * (240.0 / bpm)
        end = directive.end_bar * (240.0 / bpm)
        if start <= time_seconds < end:
            return directive
    return phrase_directives[0] if time_seconds < 0 else phrase_directives[-1]


def _build_section_profiles(config, composition_plan, phrase_directives):
    catalogues = {
        "kick": (config.kick_profile, KICK_PROFILES, AUTO_KICK_PROFILES),
        "snare": (config.snare_profile, SNARE_PROFILES, AUTO_SNARE_PROFILES),
        "hat": (config.hat_profile, HAT_PROFILES, AUTO_HAT_PROFILES),
    }
    options = _profile_options()
    result: dict[str, dict[int, str]] = {}
    for role, (configured, catalogue, automatic) in catalogues.items():
        selected: dict[int, str] = {}
        anchor: str | None = None
        for section in composition_plan.sections:
            function = _phrase_at_time(
                phrase_directives, config.bpm, section.start_seconds
            ).function
            if function == "return" and anchor is not None:
                selected[section.index] = anchor
                continue
            choices = options[role].get(function, automatic)
            rng = np.random.default_rng(
                derive_seed(
                    config.seed,
                    f"section-profile:{role}:{section.index}:{function}",
                )
            )
            profile = select_profile_name(
                configured, catalogue, rng, auto_choices=choices
            )
            selected[section.index] = profile
            if function == "establishment":
                anchor = profile
        result[role] = selected
    return result


def build_score_generation_plan(
    config: GenerationConfig,
    *,
    regenerate: str | None = None,
    variation: int = 1,
) -> ScoreGenerationPlan:
    """Create the complete event-backed canonical score before any audio rendering."""
    if variation < 1:
        raise ValueError("variation must be a positive integer")
    seed_overrides = _seed_overrides(regenerate, variation, config.seed)
    streams = RandomStreams(config.seed, seed_overrides=seed_overrides)
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
    phrase_directives = tuple(build_phrase_directives(composition_plan.sections))
    drum_plan = build_drum_part_plan(config, composition_plan)

    percussion = build_percussion_events(
        config,
        {
            "kick": streams.get("kick_pattern"),
            "snare": streams.get("snare_pattern"),
            "hat": streams.get("hat_pattern"),
            "break": streams.get("break_pattern"),
        },
        composition_plan,
        drum_plan=drum_plan,
    )

    melody_variation_events = build_melody_events(
        config, streams.get("melody_pattern")
    )
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
        melody_events = [
            replace(
                event,
                velocity=float(np.clip(
                    event.velocity * (
                        0.90 + 0.20
                        * melody_variation_events[index % len(melody_variation_events)].velocity
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

    section_orchestration = tuple(build_section_orchestration_plan(
        composition_plan, phrase_directives, config, motif_plan
    ))
    transition_plan = tuple(build_transition_plan(
        composition_plan, phrase_directives
    ))
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

    activity_defaults = {
        "kick": 0.78, "snare": 0.66, "hat": 0.68, "break": 0.62,
    }
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
        percussion[role] = adjusted

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
    melody_events = phrase_shaped_melody

    selected_profiles = _build_section_profiles(
        config, composition_plan, phrase_directives
    )
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
    melody_profile = None
    if config.include_melody:
        if config.synth_palette == "subtractive":
            melody_catalogue = SUBTRACTIVE_VOICES
        else:
            melody_catalogue = MELODY_PROFILES
        melody_profile = select_profile_name(
            config.melody_profile,
            melody_catalogue,
            streams.get("melody_profile"),
            auto_choices=AUTO_MELODY_PROFILES,
        )

    # Build score events from the planners' exact sixteenth-grid positions.
    percussion_score = percussion_to_score_events(
        percussion, bpm=config.bpm,
        seed_streams={
            role: streams.seed_for(f"{role}_pattern")
            for role in ("kick", "snare", "hat", "break")
        },
    )
    source_by_role = {
        role: sorted(events, key=lambda item: (int(item.step), str(item.kind or "")))
        for role, events in percussion.items()
    }
    source_index = {role: 0 for role in source_by_role}
    scored_percussion = []
    for event in percussion_score:
        role = event.voice_id
        source = source_by_role[role][source_index[role]]
        source_index[role] += 1
        onset_seconds = float(Fraction(int(source.step), 4) * Fraction(60, 1) / Fraction(str(config.bpm)))
        section = _section_at_time(composition_plan, onset_seconds)
        phrase = _phrase_at_time(phrase_directives, config.bpm, onset_seconds)

        # Reapply the renderer-side role exclusions as score-planning decisions.
        if role == "kick" and not section.kick:
            continue
        if role == "snare" and section.density < 0.14 and source.velocity < 0.70:
            continue
        if (
            role == "hat" and source.motif_relation != "shadow"
            and streams.get("section_ornaments").random() > section.percussion_density_scale
        ):
            continue
        velocity = float(source.velocity)
        if role == "break":
            if source.kind == "kick" and not section.kick:
                continue
            if source.kind != "kick" and section.density < 0.16:
                continue
            break_activity = role_activity_at_time(
                "break", onset_seconds, composition_plan,
                section_orchestration, transition_plan,
            )
            velocity *= min(1.0, break_activity / 0.62)
            if velocity <= 1e-7:
                continue

        parameters = dict(event.parameters)
        parameters.update({
            "section_name": section.name,
            "phrase_function": phrase.function,
            "sound_profile": (
                selected_profiles[role][section.index]
                if role in selected_profiles else break_profiles.get(str(source.kind), "909_crack")
            ),
        })
        scored_percussion.append(replace(
            event,
            velocity=float(np.clip(velocity, 0.0, 1.0)),
            parameters=parameters,
        ))

    melody_score = melody_to_score_events(
        melody_events,
        bpm=config.bpm,
        seed=streams.seed_for("melody_pattern"),
        release_seconds=0.65,
    )
    scored_melody = []
    for event, source in zip(
        melody_score,
        sorted(melody_events, key=lambda item: (int(item.step), int(item.midi_note))),
        strict=True,
    ):
        onset_seconds = float(Fraction(int(source.step), 4) * Fraction(60, 1) / Fraction(str(config.bpm)))
        section = _section_at_time(composition_plan, onset_seconds)
        if not section.melody:
            continue
        intent = role_intent_at_time(
            "melody", onset_seconds, composition_plan, section_orchestration
        )
        instability = float(np.clip(
            0.62 * config.arrangement_instability
            + 0.38 * section.instability,
            0.0, 1.0,
        ))
        parameters = dict(event.parameters)
        parameters.update({
            "section_name": section.name,
            "phrase_function": _phrase_at_time(
                phrase_directives, config.bpm, onset_seconds
            ).function,
            "register_semitones": float(intent.register_semitones),
            "brightness": float(intent.brightness),
            "instability": instability,
            "synthesis_profile": melody_profile,
        })
        scored_melody.append(replace(event, parameters=parameters))

    events: list[MusicalEvent] = [*scored_percussion, *scored_melody]
    duration_beats = Fraction(
        str(config.duration * float(config.bpm) / 60.0)
    ).limit_denominator(15360)
    if config.include_texture:
        events.append(MusicalEvent(
            event_id="field-noise-texture",
            voice_id="noise_texture",
            onset_beats=Fraction(0),
            duration_beats=duration_beats,
            kind="marker",
            velocity=1.0,
            parameters={
                "legacy_lane": "noise_texture",
                "legacy_kind": "coloured_noise",
                "duration_seconds": config.duration,
            },
            tags=("field-renderer", "texture"),
        ))
    if config.include_ambience:
        root_frequency = 55.0 * (
            2.0 ** ((derive_seed(config.seed, "ambience_root") % 24) / 12.0)
        )
        events.append(MusicalEvent(
            event_id="field-ambience-bed",
            voice_id="ambience",
            onset_beats=Fraction(0),
            duration_beats=duration_beats,
            kind="marker",
            velocity=1.0,
            parameters={
                "legacy_lane": "ambience",
                "legacy_kind": "harmonic_ambient_bed",
                "duration_seconds": config.duration,
                "root_frequency": root_frequency,
                "amount": config.ambience_level,
            },
            tags=("field-renderer", "ambience"),
        ))

    stems = ["kick", "snare", "hats", "synthetic_break"]
    if config.include_melody:
        stems.append("melody")
    if config.include_texture:
        stems.append("noise_texture")
    if config.include_ambience:
        stems.append("ambience")
    if "break" in config.sample_paths:
        stems.append("sample_break")

    seed_stream_names = (
        "kick_pattern", "snare_pattern", "hat_pattern", "break_pattern",
        "kick_synthesis", "snare_synthesis", "hat_synthesis", "break_synthesis",
        "kick_profile", "snare_profile", "hat_profile", "break_profile",
        "section_ornaments", "melody_pattern", "melody_synthesis",
        "melody_profile", "texture_synthesis", "ambience_synthesis",
    )
    seed_streams = {
        name: streams.seed_for(name) for name in seed_stream_names
    }
    motif_plan_dict = motif_plan.to_dict() if motif_plan is not None else None
    composition_dict = composition_plan.to_dict()
    section_schedule = []
    for section in composition_plan.sections:
        function = _phrase_at_time(
            phrase_directives, config.bpm, section.start_seconds
        ).function
        section_schedule.append({
            "index": section.index,
            "name": section.name,
            "start_bar": section.start_bar,
            "end_bar": section.end_bar,
            "function": function,
        })
    metadata = {
        "score_origin": "score_first_generation",
        "planner_event_timebase": "rational_quarter_note_beats_from_sixteenth_grid",
        "algorithm_version": "0.8.0",
        "root_seed": config.seed,
        "variation": {"stem": regenerate, "index": variation} if regenerate else None,
        "sample_rate": int(config.sample_rate),
        "frame_count": int(config.frame_count),
        "duration_seconds": float(config.duration),
        "render_stems": stems,
        "seed_streams": seed_streams,
        "sample_trigger_seed_streams": {
            "shared_drum_score": True,
            "break_processing": derive_seed(config.seed, "score-break-processing"),
            "motif_anchor": motif_anchor_streams.seed_for("motif_anchor"),
        },
        "generator_families": {
            "percussion": (
                "section-aware role grammars with stable anchor, linked kick/snare/hat "
                "families, phrase-boundary transition gestures"
                if config.pattern_follow_structure
                else "sparse Euclidean core with bar-rotating accents"
            ),
            "drum_arrangement": "shared formal-section plan drives sample and synthesis layers",
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
        "composition_plan": composition_dict,
        "sample_section_schedule": section_schedule,
        "phrase_directives": [item.to_dict() for item in phrase_directives],
        "motif_plan": motif_plan_dict,
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
    }
    score = Score(
        title=f"Reawarp {config.seed}",
        ppq=960,
        tempo_map=TempoMap.constant(float(config.bpm)),
        meter_map=MeterMap(),
        events=tuple(events),
        metadata=metadata,
    )
    return ScoreGenerationPlan(
        score=score,
        composition_plan=composition_plan,
        phrase_directives=phrase_directives,
        section_orchestration=section_orchestration,
        transition_plan=transition_plan,
        streams=streams,
        motif_plan=motif_plan,
        selected_profiles=selected_profiles,
        melody_profile=melody_profile,
        break_profiles=break_profiles,
    )


def score_to_legacy_project_events(score: Score) -> list[dict[str, Any]]:
    """Project event dictionaries are a derived compatibility/export view of Score.events."""
    records: list[dict[str, Any]] = []
    for event in score.events:
        parameters = dict(event.parameters)
        onset_seconds = float(score.tempo_map.beat_to_seconds(event.onset_beats))
        step = parameters.get("step")
        if step is None and event.onset_beats * 4.denominator == 1:
            step = int(event.onset_beats * 4)
        base = {
            "time": onset_seconds,
            "step": step,
            "velocity": float(event.velocity),
            "pan": float(parameters.get("pan", 0.0)),
            "score_event_id": event.event_id,
        }
        if event.kind == "marker":
            record = {
                **base,
                "lane": str(parameters.get("legacy_lane", event.voice_id)),
                "kind": str(parameters.get("legacy_kind", "marker")),
                **{
                    key: value for key, value in parameters.items()
                    if key not in {"legacy_lane", "legacy_kind", "duration_seconds"}
                },
                "duration": float(parameters.get("duration_seconds", 0.0)),
            }
            records.append(record)
            continue
        if event.kind == "trigger":
            role = str(parameters.get("sample_role", event.voice_id))
            lane = "sample_break" if role == "break" else f"sample_{role}"
            records.append({
                **base,
                "lane": lane,
                "source_lane": role,
                "kind": "sample_trigger",
                "sample_metadata": dict(parameters.get("sample_metadata", {})),
                "sample_source": {
                    "asset_id": event.source_id,
                    "path": parameters.get("sample_path"),
                    "sha256": parameters.get("sample_sha256"),
                    "label": parameters.get("sample_label"),
                    "variant_index": parameters.get("sample_variant_index"),
                },
                "transforms": list(parameters.get("break_transforms", [])),
                "slice_index": parameters.get("break_slice_index"),
                "source_frame_start": parameters.get("break_source_frame_start"),
                "source_frame_end": parameters.get("break_source_frame_end"),
                "rendered_frames": None,
                "trimmed_to_next_trigger": True if role == "break" else False,
            })
            continue

        if event.kind == "note":
            gate_beats = parameters.get("gate_duration_beats")
            if gate_beats is None:
                duration = float(score.tempo_map.beat_to_seconds(event.end_beats) - onset_seconds)
            else:
                gate_end = event.onset_beats + Fraction(str(gate_beats))
                duration = float(score.tempo_map.beat_to_seconds(gate_end) - onset_seconds)
            records.append({
                **base,
                "lane": event.voice_id,
                "kind": f"{score.metadata.get('synth_palette', 'subtractive')}_synth_note",
                "duration": duration,
                "frequency": event.frequency_hz,
                "midi_note": event.pitch,
                "source_x": parameters.get("source_x"),
                "source_y": parameters.get("source_y"),
                "motif_id": parameters.get("motif_id"),
                "motif_transform": parameters.get("motif_transform"),
                "phrase_index": parameters.get("phrase_index"),
                "section_name": parameters.get("section_name"),
                "phrase_function": parameters.get("phrase_function"),
                "synthesis_profile": parameters.get("synthesis_profile"),
            })
            continue

        records.append({
            **base,
            "lane": event.voice_id,
            "kind": str(parameters.get("source_kind", event.kind)),
            "pattern_style": parameters.get("pattern_style"),
            "motif_id": parameters.get("motif_id"),
            "motif_relation": parameters.get("motif_relation"),
            "section_name": parameters.get("section_name"),
            "phrase_function": parameters.get("phrase_function"),
            "sound_profile": parameters.get("sound_profile"),
        })

    records.sort(key=lambda item: (
        float(item.get("time", 0.0)), str(item.get("lane", "")),
        str(item.get("score_event_id", "")),
    ))
    return records
