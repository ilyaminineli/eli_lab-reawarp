"""Offline-first Reawarp synthesis coordinator."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import numpy as np

from reawarp.config import GenerationConfig
from reawarp.core.project import ReawarpProject
from reawarp.core.random_streams import RandomStreams, derive_seed
from reawarp.generators.melody import build_melody_events
from reawarp.generators.percussion import build_percussion_events
from reawarp.samples.io import read_sample
from reawarp.synthesis.instruments import (
    render_fm_note,
    render_hat,
    render_kick,
    render_noise_texture,
    render_snare,
)


class ReawarpEngine:
    """Generate deterministic musical material and render synchronized stereo stems."""

    VERSION = "0.1.0"

    def generate_variant(
        self,
        config: GenerationConfig,
        stem: str,
        variation: int = 1,
    ) -> ReawarpProject:
        """Regenerate one stem while retaining all unrelated stems bit-identically."""
        return self.generate(config, regenerate=stem, variation=variation)

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
        stream_groups = {
            "kick": ("kick_pattern", "kick_synthesis"),
            "snare": ("snare_pattern", "snare_synthesis"),
            "hats": ("hat_pattern", "hat_synthesis"),
            "synthetic_break": ("break_pattern", "break_synthesis"),
            "melody": ("melody_pattern", "melody_synthesis"),
            "noise_texture": ("texture_synthesis",),
        }
        if regenerate is not None and regenerate not in stream_groups:
            raise ValueError(f"unknown stem for regeneration: {regenerate}")
        seed_overrides = {}
        if regenerate is not None:
            for stream_name in stream_groups[regenerate]:
                seed_overrides[stream_name] = derive_seed(
                    config.seed, f"variation:{regenerate}:{variation}:{stream_name}"
                )

        frame_count = config.frame_count
        sample_rate = config.sample_rate
        streams = RandomStreams(config.seed, seed_overrides=seed_overrides)
        stems: dict[str, np.ndarray] = {}
        event_records: list[dict[str, Any]] = []

        def new_stem(name: str) -> np.ndarray:
            audio = np.zeros((frame_count, 2), dtype=np.float32)
            stems[name] = audio
            return audio

        def place_mono(target: np.ndarray, signal: np.ndarray, start_seconds: float, pan: float = 0.0) -> None:
            start = max(0, int(round(start_seconds * sample_rate)))
            if start >= frame_count or signal.size == 0:
                return
            count = min(int(signal.size), frame_count - start)
            angle = (float(np.clip(pan, -1.0, 1.0)) + 1.0) * (math.pi / 4.0)
            left_gain, right_gain = math.cos(angle), math.sin(angle)
            target[start : start + count, 0] += signal[:count] * left_gain
            target[start : start + count, 1] += signal[:count] * right_gain

        def place_sample(target: np.ndarray, sample: np.ndarray, start_seconds: float, velocity: float, pan: float) -> None:
            shaped = sample * float(np.clip(velocity, 0.0, 1.0)) * 0.72
            place_mono(target, shaped, start_seconds, pan)

        percussion_rngs = {
            "kick": streams.get("kick_pattern"),
            "snare": streams.get("snare_pattern"),
            "hat": streams.get("hat_pattern"),
            "break": streams.get("break_pattern"),
        }
        percussion = build_percussion_events(config, percussion_rngs)
        melody_events = build_melody_events(config, streams.get("melody_pattern"))

        kick_stem = new_stem("kick")
        snare_stem = new_stem("snare")
        hat_stem = new_stem("hats")
        break_stem = new_stem("synthetic_break")

        for event in percussion["kick"]:
            signal = render_kick(sample_rate, streams.get("kick_synthesis"), event.velocity)
            place_mono(kick_stem, signal, event.time, event.pan)
            event_records.append(event.to_dict())

        for event in percussion["snare"]:
            signal = render_snare(sample_rate, streams.get("snare_synthesis"), event.velocity)
            place_mono(snare_stem, signal, event.time, event.pan)
            event_records.append(event.to_dict())

        for event in percussion["hat"]:
            signal = render_hat(sample_rate, streams.get("hat_synthesis"), event.velocity)
            place_mono(hat_stem, signal, event.time, event.pan)
            event_records.append(event.to_dict())

        for event in percussion["break"]:
            break_rng = streams.get("break_synthesis")
            if event.kind == "kick":
                signal = render_kick(
                    sample_rate, break_rng, event.velocity * 0.82, duration=0.31, amp_decay=0.16
                )
            elif event.kind == "snare":
                signal = render_snare(sample_rate, break_rng, event.velocity * 0.78, duration=0.22)
            else:
                signal = render_hat(sample_rate, break_rng, event.velocity * 0.9, duration=0.075)
            place_mono(break_stem, signal, event.time, event.pan)
            event_records.append(event.to_dict())

        if config.include_melody:
            melody_stem = new_stem("melody")
            for event in melody_events:
                signal = render_fm_note(
                    event.frequency,
                    sample_rate,
                    streams.get("melody_synthesis"),
                    duration=event.duration,
                    velocity=event.velocity,
                    modulation_index=1.8 + config.complexity * 3.7,
                )
                place_mono(melody_stem, signal, event.time, event.pan)
                record = event.to_dict()
                record.update({"lane": "melody", "kind": "fm_note"})
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
            texture_stem[:, 0] += texture * 0.72
            texture_stem[:, 1] += delayed * 0.72
            event_records.append({
                "lane": "noise_texture",
                "time": 0.0,
                "duration": config.duration,
                "kind": "coloured_noise",
            })

        sample_manifest: dict[str, dict[str, Any]] = {}
        for role, sample_path in config.sample_paths.items():
            path = Path(sample_path).expanduser()
            sample = read_sample(path, sample_rate)
            sample_digest = hashlib.sha256(path.read_bytes()).hexdigest()
            sample_stem = new_stem(f"sample_{role}")
            triggers = percussion[role]
            for event in triggers:
                place_sample(sample_stem, sample, event.time, event.velocity, event.pan)
                event_records.append({
                    "lane": f"sample_{role}",
                    "source_lane": role,
                    "time": event.time,
                    "step": event.step,
                    "velocity": event.velocity,
                    "pan": event.pan,
                    "kind": "sample_trigger",
                })
            sample_manifest[role] = {
                "path": str(path.resolve()),
                "sha256": sample_digest,
                "frames_after_resampling": int(len(sample)),
                "trigger_count": len(triggers),
            }

        # Apply peak attenuation per stem. A shared gain would make regenerating one
        # lane alter all other stems, violating the stem-regeneration contract.
        peak_ceiling = 10.0 ** (-1.0 / 20.0)
        stem_headroom_gains: dict[str, float] = {}
        for stem_name, stem_audio in stems.items():
            stem_peak = float(np.max(np.abs(stem_audio))) if stem_audio.size else 0.0
            stem_gain = min(1.0, peak_ceiling / stem_peak) if stem_peak > 0.0 else 1.0
            if stem_gain < 1.0:
                stem_audio *= stem_gain
            stem_headroom_gains[stem_name] = stem_gain

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
                    "melody_pattern", "melody_synthesis", "texture_synthesis",
                )
            },
            "generator_families": {
                "percussion": "euclidean + prime-indexed mutation + logistic control",
                "synthetic_break": "stochastic event grammar with kick/snare/hat resynthesis",
                "melody": "3:5 Lissajous curve + logistic-map contour + FM synthesis",
                "texture": "coloured noise with low-frequency amplitude modulation",
            },
            "sample_sources": sample_manifest,
            "event_count": len(event_records),
            "stem_headroom_gains": stem_headroom_gains,
        }
        return ReawarpProject(
            config=config,
            sample_rate=sample_rate,
            stems=stems,
            events=event_records,
            metadata=metadata,
        )
