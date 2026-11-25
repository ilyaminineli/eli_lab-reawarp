"""Measure M21 voice-family and hybrid render time/memory without enabling defaults."""
from __future__ import annotations

import argparse
import json
import time
import tracemalloc
from pathlib import Path

import numpy as np

from reawarp.synthesis.sound_object import (
    EnvelopeSpec,
    HybridVoiceRenderer,
    SoundObjectLayer,
    SoundObjectPatch,
    SoundObjectSource,
    render_additive_partial_voice,
    render_modal_resonator_bank,
)


def _measure(label, callback, sample_rate: int):
    tracemalloc.start()
    started = time.perf_counter()
    audio = callback()
    elapsed = time.perf_counter() - started
    _current, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    arrays = (
        audio.audio if hasattr(audio, "audio") else audio
    )
    diagnostics = getattr(audio, "diagnostics", {})
    return {
        "family": label,
        "elapsed_seconds": elapsed,
        "real_time_factor": elapsed / (len(arrays) / sample_rate) if len(arrays) else None,
        "frames": int(len(arrays)),
        "output_bytes": int(np.asarray(arrays).nbytes),
        "tracemalloc_peak_bytes": int(traced_peak),
        "peak": float(np.max(np.abs(arrays))) if len(arrays) else 0.0,
        "diagnostics": diagnostics,
    }


def _hybrid_patch(sample_rate: int, frames: int, seed: int) -> SoundObjectPatch:
    transient_end = max(1, min(frames, int(sample_rate * 0.08)))
    tail_start = max(0, min(frames - 1, frames // 2))
    return SoundObjectPatch(
        patch_id="benchmark-hybrid",
        name="Benchmark transient body tail",
        sample_rate=sample_rate,
        seed=seed,
        source_identity_id="benchmark:source",
        processing_identity_id="benchmark:hybrid-v1",
        sources=(
            SoundObjectSource(
                "transient", source_kind="procedural",
                sample_rate=sample_rate, source_model="noise-impulse",
            ),
            SoundObjectSource(
                "body", source_kind="procedural",
                sample_rate=sample_rate, source_model="modal-bank",
            ),
            SoundObjectSource(
                "tail", source_kind="procedural",
                sample_rate=sample_rate, source_model="decaying-additive-cloud",
            ),
        ),
        layers=(
            SoundObjectLayer(
                "transient", "transient", "transient", 0, transient_end,
                gain=0.5, envelope=EnvelopeSpec(
                    attack_seconds=0.001, decay_seconds=0.04,
                    sustain_level=0.0, release_seconds=0.04,
                ),
            ),
            SoundObjectLayer(
                "body", "body", "body", 0, frames,
                gain=0.35, envelope=EnvelopeSpec(
                    attack_seconds=0.004, decay_seconds=0.3,
                    sustain_level=0.2, release_seconds=0.25,
                ),
            ),
            SoundObjectLayer(
                "tail", "tail", "tail", tail_start, frames,
                gain=0.2, envelope=EnvelopeSpec(
                    attack_seconds=0.03, decay_seconds=1.2,
                    sustain_level=0.05, release_seconds=0.8,
                ),
            ),
        ),
        pitch_model={"kind": "resonant", "frequency_hz": 110.0},
        spectrum={"partials": [
            {"ratio": 1.0, "gain": 1.0, "decay_seconds": 0.6},
            {"ratio": 1.414, "gain": 0.4, "decay_seconds": 0.3},
        ]},
    )


def benchmark(sample_rate: int, duration: float, seed: int) -> list[dict]:
    frames = int(round(sample_rate * duration))
    if frames < 1:
        raise ValueError("duration is too short for the selected sample rate")
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, 0.04, frames).astype(np.float32)
    modal_frequencies = np.asarray(
        [110, 165, 220, 277, 330, 415, 523, 659, 831, 1_047, 1_319, 1_661, 2_093, 2_637, 3_323, 4_187],
        dtype=np.float64,
    )
    modal_gains = np.geomspace(1.0, 0.05, len(modal_frequencies))
    partials = [
        {"ratio": float(index + 1), "gain": 1.0 / (index + 1),
         "decay_seconds": 0.6 / (1.0 + index * 0.12)}
        for index in range(16)
    ]

    def measured(label, callback):
        return _measure(label, callback, sample_rate)

    modal = measured("modal_resonator_bank", lambda: render_modal_resonator_bank(
        modal_frequencies, modal_gains, frames=frames, sample_rate=sample_rate,
        decay_seconds=0.7, seed=seed,
    ))
    additive = measured("additive_partial_voice", lambda: render_additive_partial_voice(
        110.0, partials, frames=frames, sample_rate=sample_rate, seed=seed,
    ))
    patch = _hybrid_patch(sample_rate, frames, seed)
    body = render_modal_resonator_bank(
        modal_frequencies, modal_gains, frames=frames, sample_rate=sample_rate,
        decay_seconds=0.7, seed=seed,
    )
    tail = render_additive_partial_voice(
        110.0, partials, frames=frames, sample_rate=sample_rate, seed=seed,
    )
    hybrid_sources = {
        "transient": noise,
        "body": body,
        "tail": tail,
    }
    hybrid = measured("hybrid_transient_body_tail", lambda: HybridVoiceRenderer().render(
        patch, hybrid_sources
    ))
    for result in (modal, additive, hybrid):
        result["sample_rate"] = sample_rate
        result["requested_duration_seconds"] = duration
    return [modal, additive, hybrid]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--durations", nargs="+", type=float, default=(1.0, 5.0, 30.0))
    parser.add_argument("--sample-rates", nargs="+", type=int, default=(22_050, 48_000))
    parser.add_argument("--seed", type=int, default=20261125)
    parser.add_argument("--output", type=Path, default=Path("benchmark-m21-sound-objects.json"))
    args = parser.parse_args()
    if any(value <= 0 for value in args.durations) or any(value <= 0 for value in args.sample_rates):
        parser.error("durations and sample rates must be positive")
    results = []
    for rate in args.sample_rates:
        for duration in args.durations:
            results.extend(benchmark(rate, duration, args.seed))
    payload = {
        "schema_version": 1,
        "seed": args.seed,
        "new_voice_defaults_enabled": False,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    print(f"Wrote {len(results)} benchmark cases to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
