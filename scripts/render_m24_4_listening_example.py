#!/usr/bin/env python3
"""Create matched-input native/oversampled nonlinear audition renders."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from reawarp.dsp.nonlinear import oversampled_waveshaper


def _rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(audio, dtype=np.float64) ** 2)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("output/m24-4-oversampled-nonlinear"))
    parser.add_argument("--sample-rate", type=int, default=48_000)
    args = parser.parse_args()
    rate = args.sample_rate
    if rate < 8000:
        parser.error("sample rate must be at least 8000 Hz for this example")
    duration = 3.0
    t = np.arange(int(rate * duration), dtype=np.float64) / rate
    source = (0.38 * np.sin(2 * np.pi * 997 * t) + 0.18 * np.sin(2 * np.pi * 5100 * t) +
              0.08 * np.sin(2 * np.pi * 0.19 * rate * t)).astype(np.float32)
    args.output.mkdir(parents=True, exist_ok=True)
    sf.write(args.output / "01-dry.wav", source, rate, subtype="FLOAT")
    report = {
        "module": "m24.4.oversampled_nonlinear", "sample_rate": rate,
        "input_rms": _rms(source), "oversampling": {},
    }
    for factor in (1, 2, 4, 8):
        result = oversampled_waveshaper(
            source, rate, shape="tanh", drive=4.0, oversample=factor,
        )
        filename = f"{factor + 1:02d}-{factor}x.wav"
        sf.write(args.output / filename, result.audio, rate, subtype="FLOAT")
        report["oversampling"][str(factor)] = {
            "file": filename, "rms": _rms(result.audio), "diagnostics": result.diagnostics,
        }
    report["listening_questions"] = [
        "At matched monitoring level, where do 2x/4x/8x reduce alias products?",
        "Does the added CPU cost buy a useful improvement for this source?",
        "Does the transfer curve add harmonics without flattening the transient?",
        "Would intentional 1x aliasing better serve a particular sound-design role?",
    ]
    (args.output / "render.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote M24.4 listening set to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
