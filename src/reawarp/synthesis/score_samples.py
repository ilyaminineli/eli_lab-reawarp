"""Frame-scheduled sample-bank and imported-break voices for score rendering.

The preparation pass turns existing percussion hits into explicit score trigger
events. Asset choice is resolved from score section/cycle metadata before audio
callbacks run, while playback, transient windows, break slicing, trimming and
fades are measured in the renderer's sample-frame domain.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from reawarp.config import GenerationConfig
from reawarp.core.random_streams import derive_seed
from reawarp.samples.io import read_sample
from reawarp.samples.selection import select_sample_variant
from reawarp.score.events import MusicalEvent
from reawarp.score.model import Score
from reawarp.score.render import ScheduledScoreEvent, ScoreVoiceRenderer
from reawarp.score.timeline import RenderTimeline
from reawarp.transforms.analysis import auto_slice
from reawarp.transforms.pipeline import apply_break_transforms


_BASELINE_SAMPLE_FUNCTIONS = {
    "introduction", "establishment", "return", "silence", "outro",
}
_AUTOMATIC_SWITCH_FUNCTIONS = {
    "development", "uplift", "arrival", "contrast", "transition", "false_return",
}
_AUTOMATIC_SAMPLE_FACTORS = {
    "introduction": 0.35, "establishment": 0.90, "continuation": 0.78,
    "development": 1.05, "uplift": 1.18, "arrival": 1.35, "drop": 0.32,
    "silence": 0.0, "contrast": 1.08, "return": 0.92, "false_return": 0.58,
    "transition": 0.72, "residue": 0.30, "outro": 0.24,
}


@dataclass(frozen=True, slots=True)
class PreparedScoreSamples:
    score: Score
    voice_renderers: dict[str, ScoreVoiceRenderer]
    sample_manifest: dict[str, Any]


def _bank_entries(config: GenerationConfig, role: str) -> list[dict[str, Any]]:
    entries = [dict(item) for item in config.sample_banks.get(role, ())]
    if not entries and config.sample_paths.get(role):
        entries = [{
            "path": config.sample_paths[role],
            "metadata": dict(config.sample_metadata.get(role, {})),
            "features": {},
        }]
    return entries


def _load_bank(config: GenerationConfig, role: str) -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = []
    for raw in _bank_entries(config, role):
        path = Path(str(raw.get("path", ""))).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"{role} sample-bank file does not exist: {path}")
        audio = read_sample(path, config.sample_rate)
        digest = str(raw.get("sha256") or hashlib.sha256(path.read_bytes()).hexdigest())
        metadata = dict(raw.get("metadata") or {})
        features = dict(raw.get("features") or {})
        loaded.append({
            "path": str(path.resolve()),
            "audio": audio,
            "sha256": digest,
            "asset_id": str(raw.get("asset_id") or metadata.get("asset_id") or digest[:16]),
            "label": str(raw.get("label") or path.name),
            "metadata": metadata,
            "features": features,
            "duration_seconds": len(audio) / float(config.sample_rate),
        })
    return loaded


def _section_context(
    score: Score,
    event,
    timeline: RenderTimeline,
    cycle_bars: int,
) -> dict[str, Any]:
    bar_number, _ = timeline.bar_and_beat(event.onset_beats)
    bar_index = max(0, int(bar_number) - 1)
    metadata = score.metadata
    plan = metadata.get("composition_plan", {})
    sections = (
        metadata.get("sample_section_schedule")
        or plan.get("sections", [])
        or metadata.get("sections", [])
    )
    chosen: dict[str, Any] = {}
    chosen_index = 0
    for index, candidate in enumerate(sections):
        if not isinstance(candidate, dict):
            continue
        if candidate.get("start_beat") is not None:
            start = Fraction(str(candidate.get("start_beat", 0)))
            end = Fraction(str(candidate.get("end_beat", 10**9)))
            match = start <= event.onset_beats < end
        else:
            start_bar = int(candidate.get("start_bar", 0))
            end_bar = int(candidate.get("end_bar", start_bar + 1))
            match = start_bar <= bar_index < end_bar
        if match:
            chosen = candidate
            chosen_index = int(candidate.get("index", index))
            break

    function = str(
        event.parameters.get("phrase_function")
        or chosen.get("phrase_function")
        or chosen.get("function")
        or "establishment"
    ).casefold()
    directives = metadata.get("phrase_directives", [])
    for directive in directives:
        if not isinstance(directive, dict):
            continue
        start_bar = int(directive.get("start_bar", 0))
        end_bar = int(directive.get("end_bar", start_bar + 1))
        if start_bar <= bar_index < end_bar:
            function = str(directive.get("function", function)).casefold()
            break
    if function == "intro":
        function = "introduction"
    start_bar = int(chosen.get("start_bar", 0))
    name = str(chosen.get("name", f"section-{chosen_index + 1}"))
    return {
        "index": chosen_index,
        "name": name,
        "start_bar": start_bar,
        "bar": int(bar_number),
        "cycle_index": max(
            0, (bar_index - start_bar) // max(1, int(cycle_bars))
        ),
        "function": function,
    }


def _source_levels(
    config: GenerationConfig,
    phrase_function: str,
) -> tuple[float, float]:
    mode = config.percussion_source_mode
    if mode == "synth":
        return 1.0, 0.0
    if mode == "sample":
        return 0.0, 1.0
    sample_mix = float(config.percussion_sample_mix)
    if mode == "automatic":
        sample_mix = float(np.clip(
            sample_mix * _AUTOMATIC_SAMPLE_FACTORS.get(phrase_function, 0.8),
            0.0, 0.90,
        ))
    if config.percussion_hybrid_architecture in {"transient_body", "feature_guided"}:
        return 1.0, sample_mix
    return 1.0 - sample_mix, sample_mix


def _sample_duration_beats(
    score: Score,
    onset: Fraction,
    duration_seconds: float,
) -> Fraction:
    start_seconds = score.tempo_map.beat_to_seconds(onset)
    end_beat = score.tempo_map.seconds_to_beat(start_seconds + float(duration_seconds))
    return max(Fraction(1, 64), end_beat - onset)


def _fade_edges(audio: np.ndarray, sample_rate: int, fade_ms: float = 2.0) -> np.ndarray:
    result = np.asarray(audio, dtype=np.float32).reshape(-1).copy()
    fade = min(max(1, int(round(sample_rate * fade_ms / 1000.0))), len(result) // 2)
    if fade:
        result[:fade] *= np.linspace(0.0, 1.0, fade, endpoint=False, dtype=np.float32)
        result[-fade:] *= np.linspace(1.0, 0.0, fade, endpoint=False, dtype=np.float32)
    return result


def _fit_frames(audio: np.ndarray, frames: int) -> np.ndarray:
    result = np.zeros(max(0, int(frames)), dtype=np.float32)
    source = np.asarray(audio, dtype=np.float32).reshape(-1)
    count = min(len(source), len(result))
    if count:
        result[:count] = source[:count]
    return result


def _select_bank_variants(
    score: Score,
    config: GenerationConfig,
    timeline: RenderTimeline,
    triggers: list[Any],
    banks: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, int], dict[str, list[dict[str, Any]]]]:
    selected_by_event: dict[str, int] = {}
    switch_history: dict[str, list[dict[str, Any]]] = {
        role: [] for role in banks
    }
    for role, bank in banks.items():
        current_index = 0
        selection_cache: dict[tuple[int, int], int] = {}
        role_events = sorted(
            (event for event in triggers if event.voice_id == role),
            key=lambda item: (item.onset_beats, item.event_id),
        )
        for event in role_events:
            section = _section_context(score, event, timeline, config.drum_part_cycle_bars)
            function = section["function"]
            cycle_index = section["cycle_index"]
            mode = config.drum_sample_automation
            if len(bank) == 1 or mode == "fixed":
                selected_index = 0
            else:
                key = (
                    section["index"],
                    -1 if mode == "section" else cycle_index,
                )
                if mode == "section":
                    should_switch = function not in _BASELINE_SAMPLE_FUNCTIONS
                elif mode == "cycle":
                    should_switch = function not in _BASELINE_SAMPLE_FUNCTIONS
                else:
                    should_switch = function in _AUTOMATIC_SWITCH_FUNCTIONS
                if function == "return":
                    selected_index = 0
                    selection_cache[key] = 0
                elif not should_switch:
                    selected_index = current_index
                elif key in selection_cache:
                    selected_index = selection_cache[key]
                else:
                    switch_seed = derive_seed(
                        config.seed,
                        f"sample-switch:{role}:{section['index']}:{cycle_index}:{function}",
                    )
                    selected_index = select_sample_variant(
                        bank,
                        role=role,
                        phrase_function=function,
                        seed=switch_seed,
                        anchor_index=0,
                        previous_index=current_index,
                        intensity=config.drum_change_intensity,
                    )
                    selection_cache[key] = selected_index
            previous_index = current_index
            current_index = int(selected_index)
            selected_by_event[event.event_id] = int(selected_index)
            if current_index != previous_index:
                asset = bank[current_index]
                switch_history[role].append({
                    "at_beat": str(event.onset_beats),
                    "bar": section["bar"],
                    "section": section["name"],
                    "function": function,
                    "from_index": previous_index,
                    "to_index": current_index,
                    "asset_id": asset["asset_id"],
                    "label": asset["label"],
                })
    return selected_by_event, switch_history


def _prepare_break(
    config: GenerationConfig,
) -> tuple[np.ndarray, list[tuple[int, int]], dict[str, Any]] | None:
    sample_path = config.sample_paths.get("break")
    if not sample_path:
        return None
    path = Path(sample_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"break sample does not exist: {path}")
    audio = read_sample(path, config.sample_rate)
    source_frames = len(audio)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    transforms = list(config.break_transforms)
    if transforms:
        audio = apply_break_transforms(
            audio,
            config.sample_rate,
            transforms,
            np.random.default_rng(derive_seed(config.seed, "score-break-processing")),
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
    detected = auto_slice(audio, config.sample_rate, max_slices=config.break_slice_count)
    ranges = [(int(item.start), int(item.end)) for item in detected]
    if len(ranges) < 2:
        requested = min(config.break_slice_count, max(2, len(audio) // 128))
        boundaries = np.linspace(0, len(audio), requested + 1).round().astype(int)
        ranges = [
            (int(left), int(right))
            for left, right in zip(boundaries[:-1], boundaries[1:])
            if right > left
        ]
    manifest = {
        "path": str(path.resolve()),
        "sha256": digest,
        "source": dict(config.sample_metadata.get("break", {})),
        "frames_before_processing": int(source_frames),
        "frames_after_processing": int(len(audio)),
        "duration_after_processing": len(audio) / float(config.sample_rate),
        "transforms": transforms,
        "slice_count": len(ranges),
        "trigger_mode": "score-frame-sliced",
    }
    return np.asarray(audio, dtype=np.float32), ranges, manifest



def _feature_synthesis_parameters(
    role: str,
    features: dict[str, Any],
) -> dict[str, Any]:
    """Retain the legacy feature-guided voice/pitch/velocity adaptation."""
    centroid = float(features.get("spectral_centroid_hz", 3_000.0))
    flatness = float(features.get("spectral_flatness", 0.35))
    onset_density = float(features.get("onset_density_per_second", 4.0))
    brightness = float(np.clip(
        np.log(max(100.0, centroid) / 100.0) / np.log(160.0), 0.0, 1.0
    ))
    transient_density = float(np.clip(onset_density / 12.0, 0.0, 1.0))
    pitch_ratio = float(2.0 ** ((brightness - 0.5) * 4.0 / 12.0))
    velocity_scale = float(np.clip(0.88 + 0.18 * transient_density, 0.84, 1.08))
    voice = {
        "kick": "dry_thump" if flatness >= 0.30 else "soft_kick",
        "snare": "muted_rim" if flatness < 0.28 else "paper_snare",
        "hat": "metal_tick" if centroid >= 5_500.0 else "noise_hat",
    }[role]
    return {
        "synthesis_voice": voice,
        "synthesis_pitch_ratio": pitch_ratio,
        "synthesis_velocity_scale": velocity_scale,
        "synthesis_guidance": {
            "spectral_centroid_hz": centroid,
            "spectral_flatness": float(np.clip(flatness, 0.0, 1.0)),
            "onset_density_per_second": onset_density,
            "brightness": brightness,
            "transient_density": transient_density,
            "pitch_ratio": pitch_ratio,
            "velocity_scale": velocity_scale,
        },
    }

def prepare_score_sample_renderers(
    score: Score,
    config: GenerationConfig,
) -> PreparedScoreSamples:
    """Load sample assets, annotate source gains and append frame-scheduled triggers."""
    percussion_roles = ("kick", "snare", "hat")
    source_mode = config.percussion_source_mode
    active_roles = [
        role for role in percussion_roles
        if source_mode != "synth"
        and any(event.voice_id == role and event.kind == "hit" for event in score.events)
        and _bank_entries(config, role)
    ]
    banks = {role: _load_bank(config, role) for role in active_roles}
    timeline = RenderTimeline(config.sample_rate, score.tempo_map, score.meter_map)
    percussion_events = [
        event for event in score.events
        if event.kind == "hit" and event.voice_id in active_roles
    ]
    selected, switch_history = _select_bank_variants(
        score, config, timeline, percussion_events, banks,
    ) if banks else ({}, {})

    prepared_events = []
    sample_triggers = []
    manifest: dict[str, Any] = {}
    variant_usage: dict[str, dict[str, int]] = {
        role: {} for role in banks
    }
    assets_by_id = {
        asset["asset_id"]: asset
        for bank in banks.values() for asset in bank
    }
    for role, bank in banks.items():
        anchor = bank[0]
        manifest[role] = {
            "path": anchor["path"],
            "sha256": anchor["sha256"],
            "source": anchor["metadata"],
            "bank_count": len(bank),
            "variants": [{
                "index": index,
                "asset_id": item["asset_id"],
                "path": item["path"],
                "sha256": item["sha256"],
                "label": item["label"],
                "metadata": item["metadata"],
                "features": item["features"],
                "duration_seconds": item["duration_seconds"],
            } for index, item in enumerate(bank)],
            "trigger_count": 0,
            "trigger_mode": "score-trigger",
            "selection_mode": config.drum_sample_automation,
            "hybrid_architecture": config.percussion_hybrid_architecture,
            "switch_points": switch_history[role],
        }

    for event in score.events:
        role = event.voice_id
        if event.kind != "hit" or role not in banks:
            prepared_events.append(event)
            continue
        section = _section_context(score, event, timeline, config.drum_part_cycle_bars)
        synth_gain, sample_gain = _source_levels(config, section["function"])
        if config.percussion_synthesis == "samples":
            synth_gain = 0.0
        variant_index = selected[event.event_id]
        asset = banks[role][variant_index]
        parameters = dict(event.parameters)
        parameters.update({
            "synth_gain": float(synth_gain),
            "sample_gain": float(sample_gain),
            "sample_source_mode": source_mode,
            "sample_architecture": config.percussion_hybrid_architecture,
            "sample_variant_index": int(variant_index),
            "sample_asset_id": asset["asset_id"],
            "sample_section_index": section["index"],
            "sample_section_name": section["name"],
            "phrase_function": section["function"],
            "sample_cycle_index": section["cycle_index"],
        })
        if (
            config.percussion_hybrid_architecture == "feature_guided"
            and source_mode != "sample"
        ):
            parameters.update(_feature_synthesis_parameters(role, asset["features"]))
        prepared_events.append(replace(event, parameters=parameters))
        if sample_gain <= 1e-8:
            continue
        transient_seconds = float(config.hybrid_transient_ms) / 1000.0
        if config.percussion_hybrid_architecture == "feature_guided" and source_mode != "sample":
            crest = float(asset["features"].get("crest_factor_db", 6.0))
            transient_seconds *= float(np.clip(0.72 + crest / 35.0, 0.65, 1.35))
        if (
            source_mode != "sample"
            and config.percussion_hybrid_architecture in {"transient_body", "feature_guided"}
        ):
            trigger_seconds = transient_seconds
        else:
            trigger_seconds = float(asset["duration_seconds"])
        trigger_duration = _sample_duration_beats(
            score, event.onset_beats, trigger_seconds
        )
        trigger_parameters = {
            **parameters,
            "sample_role": role,
            "sample_path": asset["path"],
            "sample_sha256": asset["sha256"],
            "sample_label": asset["label"],
            "sample_metadata": asset["metadata"],
            "sample_features": asset["features"],
            "sample_duration_seconds": asset["duration_seconds"],
            "sample_transient_seconds": transient_seconds,
        }
        sample_triggers.append(MusicalEvent(
            event_id=f"sample-trigger-{event.event_id}",
            voice_id=role,
            onset_beats=event.onset_beats,
            duration_beats=trigger_duration,
            kind="trigger",
            velocity=event.velocity,
            articulation="sample-trigger",
            parameters=trigger_parameters,
            tags=tuple(dict.fromkeys((*event.tags, "sample", "sample-trigger"))),
            source_id=asset["asset_id"],
            seed=event.seed,
            channel=event.channel,
            tuning_id=event.tuning_id,
        ))
        usage = variant_usage[role]
        usage[str(variant_index)] = usage.get(str(variant_index), 0) + 1
        manifest[role]["trigger_count"] += 1

    break_voice_renderer: ScoreVoiceRenderer | None = None
    break_events = sorted(
        (event for event in score.events if event.kind == "hit" and event.voice_id == "break"),
        key=lambda item: (item.onset_beats, item.event_id),
    )
    break_prepared = _prepare_break(config) if break_events else None
    if break_prepared is not None and break_events:
        break_audio, slice_ranges, break_manifest = break_prepared
        manifest["break"] = break_manifest
        break_triggers = []
        for index, event in enumerate(break_events):
            meter = score.meter_map.at(event.onset_beats)
            bar_beats = Fraction(int(meter.numerator) * 4, int(meter.denominator))
            _bar_number, beat_in_bar = timeline.bar_and_beat(event.onset_beats)
            bar_start_beat = event.onset_beats - beat_in_bar
            bar_start_frame, bar_end_frame = timeline.beat_span_to_frames(
                bar_start_beat, bar_beats,
            )
            bar_length_frames = max(1, bar_end_frame - bar_start_frame)
            source_bars = max(1, int(round(len(break_audio) / bar_length_frames)))
            step = int(event.parameters.get("step", round(float(event.onset_beats) * 4.0)))
            source_slot = ((step // 16) % source_bars) * 16 + (step % 16)
            slice_index = min(
                len(slice_ranges) - 1,
                int(source_slot * len(slice_ranges) / (source_bars * 16)),
            )
            frame_start, frame_end = slice_ranges[slice_index]
            remaining_bar_beats = max(Fraction(0), bar_beats - beat_in_bar)
            if index + 1 < len(break_events):
                next_onset = break_events[index + 1].onset_beats
                until_next = max(Fraction(0), next_onset - event.onset_beats)
                duration_beats = min(remaining_bar_beats, until_next)
            else:
                duration_beats = remaining_bar_beats
            duration_beats = max(Fraction(1, 64), duration_beats)
            parameters = {
                **event.parameters,
                "sample_role": "break",
                "sample_path": break_manifest["path"],
                "sample_sha256": break_manifest["sha256"],
                "sample_metadata": break_manifest["source"],
                "break_slice_index": int(slice_index),
                "break_source_frame_start": int(frame_start),
                "break_source_frame_end": int(frame_end),
                "break_max_length_beats": str(duration_beats),
                "break_transforms": break_manifest["transforms"],
            }
            break_triggers.append(MusicalEvent(
                event_id=f"sample-break-{event.event_id}",
                voice_id="sample_break",
                onset_beats=event.onset_beats,
                duration_beats=duration_beats,
                kind="trigger",
                velocity=event.velocity,
                articulation="break-slice",
                parameters=parameters,
                tags=tuple(dict.fromkeys((*event.tags, "sample", "break-slice"))),
                source_id=break_manifest["sha256"],
                seed=event.seed,
                channel=event.channel,
                tuning_id=event.tuning_id,
            ))

        def render_break(
            scheduled: ScheduledScoreEvent,
            sample_rate: int,
            controls,
        ) -> np.ndarray:
            del controls
            params = scheduled.event.parameters
            start = int(params["break_source_frame_start"])
            end = int(params["break_source_frame_end"])
            segment = break_audio[start:end]
            # The schedule span is the absolute next-trigger boundary. Never
            # let a slice run into the following event or past the track end.
            segment = segment[:scheduled.duration_frames]
            return _fit_frames(
                _fade_edges(segment, sample_rate),
                scheduled.duration_frames,
            )

        sample_triggers.extend(break_triggers)
        break_voice_renderer = render_break
        manifest["break"]["trigger_count"] = len(break_triggers)

    def make_sample_renderer(role: str) -> ScoreVoiceRenderer:
        def render(
            scheduled: ScheduledScoreEvent,
            sample_rate: int,
            controls,
        ) -> np.ndarray:
            del controls
            params = scheduled.event.parameters
            asset = assets_by_id.get(str(params.get("sample_asset_id", "")))
            if asset is None:
                raise LookupError(
                    f"score sample trigger {scheduled.event.event_id!r} "
                    "references an asset that was not loaded"
                )
            segment = asset["audio"]
            transient_seconds = float(params.get("sample_transient_seconds", 0.0))
            transient_mode = (
                params.get("sample_source_mode") != "sample"
                and params.get("sample_architecture") in {"transient_body", "feature_guided"}
            )
            if transient_mode and transient_seconds > 0.0:
                transient_frames = max(1, int(round(sample_rate * transient_seconds)))
                segment = segment[:transient_frames]
            segment = segment[:scheduled.duration_frames]
            segment = _fade_edges(segment, sample_rate)
            sample_gain = float(np.clip(params.get("sample_gain", 1.0), 0.0, 1.0))
            return _fit_frames(segment, scheduled.duration_frames) * np.float32(sample_gain)
        return render

    voice_renderers = {
        role: make_sample_renderer(role) for role in banks
    }
    if break_voice_renderer is not None:
        voice_renderers["sample_break"] = break_voice_renderer

    # Persist the variant decisions on score metadata as well as on each trigger.
    updated_metadata = dict(score.metadata)
    if manifest:
        updated_metadata["sample_schedule"] = {
            "timebase": "rational-score-beats",
            "selection_clock": "section-and-cycle-boundaries",
            "switch_summary": {
                role: {
                    "bank_count": len(banks[role]),
                    "switch_count": len(switch_history[role]),
                    "variant_usage": variant_usage[role],
                    "switch_points": switch_history[role],
                }
                for role in banks
            },
            "sources": manifest,
        }
    prepared_score = Score(
        title=score.title,
        ppq=score.ppq,
        tempo_map=score.tempo_map,
        meter_map=score.meter_map,
        events=tuple((*prepared_events, *sample_triggers)),
        automation=score.automation,
        tuning_id=score.tuning_id,
        tuning_reference_pitch=score.tuning_reference_pitch,
        tuning_reference_frequency_hz=score.tuning_reference_frequency_hz,
        tuning_divisions_per_period=score.tuning_divisions_per_period,
        metadata=updated_metadata,
        schema_version=score.schema_version,
    )
    return PreparedScoreSamples(
        score=prepared_score,
        voice_renderers=voice_renderers,
        sample_manifest=manifest,
    )
