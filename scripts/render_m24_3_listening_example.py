#!/usr/bin/env python3
"""Create the independent M24.3 ring, shift, envelope and vocoder audition set."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from reawarp.dsp.cross_synthesis import (
    frequency_shift, ring_modulate, spectral_envelope_transfer, vocoder,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("output/m24-3-cross-synthesis"))
    parser.add_argument("--sample-rate", type=int, default=48_000)
    args = parser.parse_args()
    rate = args.sample_rate
    if rate < 8000:
        parser.error("sample rate must be at least 8000 Hz for this example")
    duration = 3.0
    t = np.arange(int(rate * duration), dtype=np.float64) / rate
    gate = (0.5 + 0.5 * np.sin(2 * np.pi * 0.7 * t)) ** 2
    carrier = (gate * (0.18 * np.sin(2 * np.pi * 110 * t) +
                       0.09 * np.sin(2 * np.pi * 220 * t) +
                       0.045 * np.sin(2 * np.pi * 440 * t))).astype(np.float32)
    modulator = (0.2 * np.sin(2 * np.pi * (180 + 260 * (0.5 + 0.5 * np.sin(2 * np.pi * 0.35 * t))) * t) +
                 0.07 * np.sin(2 * np.pi * 730 * t)).astype(np.float32)
    results = {
        "ring_modulation": ring_modulate(carrier, modulator, rate),
        "frequency_shift_plus_43_hz": frequency_shift(carrier, rate, 43.0),
        "spectral_envelope_transfer": spectral_envelope_transfer(carrier, modulator, rate),
        "vocoder": vocoder(carrier, modulator, rate, bands=24),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    sf.write(args.output / "01-carrier.wav", carrier, rate, subtype="FLOAT")
    sf.write(args.output / "02-modulator.wav", modulator, rate, subtype="FLOAT")
    report = {"module": "m24.3.cross_synthesis", "sample_rate": rate, "operations": {}}
    for index, (name, result) in enumerate(results.items(), start=3):
        filename = f"{index:02d}-{name.replace('_', '-')}.wav"
        sf.write(args.output / filename, result.audio, rate, subtype="FLOAT")
        report["operations"][name] = {"file": filename, "diagnostics": result.diagnostics}
    report["listening_questions"] = [
        "Which transformation keeps the source recognisable and which makes it raw material?",
        "Does frequency shifting create inharmonic motion rather than a transposed pitch?",
        "Does the vocoder preserve carrier identity while articulating the modulator?",
        "Are spectral changes useful in the full arrangement and in mono?",
    ]
    (args.output / "render.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote M24.3 listening set to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
