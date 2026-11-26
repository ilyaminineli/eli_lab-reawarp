#!/usr/bin/env python3
"""Create a matched-level M24.6 resonant feedback-network listening set."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from reawarp.dsp.feedback_network import feedback_delay_network


def _match_rms(audio: np.ndarray, reference: np.ndarray, ceiling: float = 0.95):
    source = np.asarray(audio, dtype=np.float64)
    target = np.asarray(reference, dtype=np.float64)
    source_rms = float(np.sqrt(np.mean(source * source))) if source.size else 0.0
    target_rms = float(np.sqrt(np.mean(target * target))) if target.size else 0.0
    gain = target_rms / max(source_rms, 1e-12)
    peak = float(np.max(np.abs(source))) if source.size else 0.0
    if peak * gain > ceiling:
        gain = ceiling / max(peak, 1e-12)
    return np.asarray(audio * np.float32(gain), dtype=np.float32), gain


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("output/m24-6-feedback-network"))
    parser.add_argument("--sample-rate", type=int, default=48_000)
    args = parser.parse_args()
    rate = args.sample_rate
    if not 8_000 <= rate <= 192_000:
        parser.error("sample rate must be between 8000 and 192000 Hz")

    duration = 3.2
    frames = int(round(duration * rate))
    source = np.zeros((frames, 2), dtype=np.float32)
    pulse_samples = np.asarray([1.0, -0.44, 0.18, -0.06], dtype=np.float32)
    spacing = int(0.31 * rate)
    for onset in range(0, frames, spacing):
        end = min(frames, onset + len(pulse_samples))
        source[onset:end, 0] += pulse_samples[:end - onset] * 0.24
        source[onset:end, 1] += pulse_samples[:end - onset] * 0.19
    time_axis = np.arange(frames, dtype=np.float64) / rate
    source[:, 0] += (0.012 * np.sin(2 * np.pi * 147.0 * time_axis)).astype(np.float32)
    source[:, 1] += (0.010 * np.sin(2 * np.pi * 151.7 * time_axis)).astype(np.float32)

    result = feedback_delay_network(
        source,
        rate,
        delay_times_ms=(29.7, 37.1, 41.1, 43.7),
        feedback_gain=0.74,
        input_gain=0.58,
        dry=0.78,
        wet=0.42,
        max_tail_seconds=5.0,
        tail_threshold_db=80.0,
        output_ceiling=0.95,
    )
    dry = np.pad(source, ((0, len(result.audio) - len(source)), (0, 0)))
    matched, match_gain = _match_rms(result.audio, dry)
    args.output.mkdir(parents=True, exist_ok=True)
    sf.write(args.output / "01-dry-machine-pulses.wav", dry, rate, subtype="FLOAT")
    sf.write(args.output / "02-feedback-network-level-matched.wav", matched, rate, subtype="FLOAT")
    sf.write(args.output / "03-feedback-network-unmatched.wav", result.audio, rate, subtype="FLOAT")
    report = {
        "module": "m24.6.feedback_network",
        "sample_rate": rate,
        "matched_audition_gain": match_gain,
        "diagnostics": result.diagnostics,
        "listening_questions": [
            "Do the four unequal delay paths form a coherent but non-repeating resonant tail?",
            "Does cross-coupling create useful stereo movement without weakening mono playback?",
            "Does the tail support the source gesture, or does it obscure the next phrase?",
            "Does the decay remain controlled at low monitoring level and near the tail cap?",
        ],
    }
    (args.output / "render.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote M24.6 matched-level listening set to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
