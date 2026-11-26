"""Adapters between existing rendered projects and the symbolic score model."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from reawarp.score.events import MusicalEvent
from reawarp.score.model import Score
from reawarp.score.render import ScoreRenderer
from reawarp.score.time import MeterMap, TempoMap


def project_to_score(project, *, title: str | None = None) -> Score:
    """Convert current seconds-based generator records into exact-beat score events."""
    bpm = float(project.config.bpm)
    tempo_map = TempoMap.constant(bpm)
    seed_streams = project.metadata.get("seed_streams", {})
    lane_stream = {
        "kick": "kick_pattern",
        "snare": "snare_pattern",
        "hats": "hat_pattern",
        "synthetic_break": "break_pattern",
        "melody": "melody_pattern",
        "noise_texture": "texture_synthesis",
        "ambience": "ambience_synthesis",
        "break": "break_pattern",
    }
    events: list[MusicalEvent] = []
    for index, source in enumerate(project.events):
        seconds = float(source.get("time", 0.0))
        onset = Fraction(str(seconds * bpm / 60.0)).limit_denominator(15_360)
        voice = str(source.get("lane", "unknown"))
        source_kind = str(source.get("kind", "hit"))
        is_note = source.get("midi_note") is not None or source.get("frequency") is not None
        kind = "note" if is_note else (
            "trigger" if source_kind == "sample_trigger" else
            "grain" if source_kind in {"coloured_noise", "harmonic_ambient_bed"} else "hit"
        )
        duration_seconds = float(source.get("duration", 0.0))
        duration = (
            Fraction(str(duration_seconds * bpm / 60.0)).limit_denominator(15_360)
            if duration_seconds > 0 else Fraction(1, 16)
        )
        excluded = {
            "lane", "step", "time", "duration", "midi_note", "frequency",
            "frequency_hz", "velocity", "pan", "source_x", "source_y",
        }
        parameters: dict[str, Any] = {
            key: value for key, value in source.items() if key not in excluded | {"kind"}
        }
        parameters["source_kind"] = source_kind
        parameters["source_step"] = source.get("step")
        stream_name = lane_stream.get(voice)
        seed = seed_streams.get(stream_name) if stream_name else None
        tags = (voice, source_kind)
        frequency = source.get("frequency_hz", source.get("frequency"))
        events.append(MusicalEvent(
            event_id=f"reawarp-event-{index:06d}",
            voice_id=voice,
            onset_beats=onset,
            duration_beats=duration,
            kind=kind,
            pitch=(
                float(source["midi_note"])
                if source.get("midi_note") is not None else None
            ),
            frequency_hz=float(frequency) if frequency is not None else None,
            velocity=float(source.get("velocity", 0.8)),
            articulation="default",
            parameters=parameters,
            tags=tags,
            source_id=source.get("source_id", source.get("source_lane")),
            seed=int(seed) if seed is not None else None,
            tuning_id="12tet",
        ))

    metadata = {
        "source_application": "eli_lab-reawarp",
        "source_algorithm_version": project.metadata.get("algorithm_version"),
        "sample_rate": int(project.sample_rate),
        "frame_count": int(project.frame_count),
        "duration_seconds": float(project.duration),
        "renderer_version": f"reawarp-score-renderer/{ScoreRenderer.VERSION}",
        "render_provenance": {
            "score_renderer_version": ScoreRenderer.VERSION,
            "engine_algorithm_version": project.metadata.get("algorithm_version"),
            "event_source": "ReawarpProject.events",
            "event_timebase": "seconds converted to rational beats at the project BPM",
            "root_seed": project.config.seed,
            "sample_rate": int(project.sample_rate),
            "frame_count": int(project.frame_count),
            "duration_seconds": float(project.duration),
            "seed_streams": project.metadata.get("seed_streams", {}),
            "generator_families": project.metadata.get("generator_families", {}),
        },
        "root_seed": project.config.seed,
        "generator_families": project.metadata.get("generator_families", {}),
        "render_stems": list(project.stems),
    }
    return Score(
        title=title or f"Reawarp {project.config.seed}",
        ppq=960,
        tempo_map=tempo_map,
        meter_map=MeterMap(),
        events=tuple(events),
        metadata=metadata,
    )
