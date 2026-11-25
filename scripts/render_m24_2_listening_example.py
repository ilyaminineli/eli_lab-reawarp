#!/usr/bin/env python3
"""Create a matched-level M24.2 transient-to-spectral-tail listening set."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from reawarp.dsp.spectral_delay import spectral_delay


def _match_rms(audio: np.ndarray, reference: np.ndarray, ceiling: float = 0.95) -> tuple[np.ndarray, float]:
    ref_rms = float(np.sqrt(np.mean(np.asarray(reference, dtype=np.float64) ** 2)))
    src_rms = float(np.sqrt(np.mean(np.asarray(audio, dtype=np.float64) ** 2)))
    scale = ref_rms / max(src_rms, 1e-12)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak * scale > ceiling:
        scale = ceiling / max(peak, 1e-12)
    return np.asarray(audio * scale, dtype=np.float32), scale


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("output/m24-2-spectral-delay"))
    parser.add_argument("--sample-rate", type=int, default=48_000)
    args = parser.parse_args()
    rate = args.sample_rate
    if rate < 8000:
        parser.error("sample rate must be at least 8000 Hz for this example")
    duration = 2.5
    frames = int(rate * duration)
    source = np.zeros(frames, dtype=np.float32)
    for beat in range(8):
        at = int(beat * 0.28 * rate)
        if at < frames:
            source[at:at + 3] += np.asarray([0.8, -0.25, 0.08], dtype=np.float32)
    t = np.arange(frames, dtype=np.float64) / rate
    source += (0.018 * np.sin(2 * np.pi * 311 * t)).astype(np.float32)
    result = spectral_delay(
        source, rate, frame_size=1024, hop_size=256, transient_preserve=0.65,
        max_tail_seconds=6.0,
        frequency_bands=[
            {"low_hz": 0, "high_hz": 700, "delay_ms": 120, "feedback": 0.48, "gain": 0.9},
            {"low_hz": 700, "high_hz": 3200, "delay_ms": 210, "feedback": 0.58, "gain": 0.88},
            {"low_hz": 3200, "high_hz": rate / 2, "delay_ms": 330, "feedback": 0.68, "gain": 0.82},
        ],
    )
    dry = np.pad(source, (0, len(result.audio) - len(source)))
    matched, scale = _match_rms(result.audio, dry)
    args.output.mkdir(parents=True, exist_ok=True)
    sf.write(args.output / "01-dry-click-phrase.wav", dry, rate, subtype="FLOAT")
    sf.write(args.output / "02-spectral-delay-level-matched.wav", matched, rate, subtype="FLOAT")
    sf.write(args.output / "03-spectral-delay-unmatched.wav", result.audio, rate, subtype="FLOAT")
    report = {
        "module": "m24.2.spectral_delay", "sample_rate": rate,
        "matched_audition_scale_only": scale, "diagnostics": result.diagnostics,
        "listening_questions": [
            "Do low, mid and high bands form distinct rhythmic trails?",
            "Does the transient remain legible at low monitoring level?",
            "Does the tail remain controlled when summed to mono?",
        ],
    }
    (args.output / "render.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote M24.2 listening set to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
