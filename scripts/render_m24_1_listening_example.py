"""Render a matched-level M24.1 impulse/resonator listening set."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from reawarp.dsp.convolution import convolve_partitioned, design_resonant_ir
from reawarp.export.wav import write_wav
from reawarp.fx_routing import match_audition_level


def build_excitation(sample_rate: int, duration: float) -> np.ndarray:
    frames = int(round(sample_rate * duration))
    audio = np.zeros(frames, dtype=np.float32)
    # Short, differently weighted excitations at 0.5 s intervals let the
    # designed resonances reveal themselves as a repeating musical object.
    for hit, gain in ((0.5, 0.8), (1.5, 0.56), (2.5, 0.68), (3.5, 0.42)):
        frame = int(round(hit * sample_rate))
        if frame + 48 < frames:
            audio[frame:frame + 48] += (
                np.exp(-np.arange(48, dtype=np.float32) / 7.0) * np.float32(gain)
            )
    return audio


def render(output: Path, sample_rate: int = 48_000, seed: int = 2401) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    excitation = build_excitation(sample_rate, 5.0)
    ir = design_resonant_ir(
        sample_rate,
        1.6,
        [
            {"frequency_hz": 293.7, "gain": 0.42, "decay_seconds": 0.72},
            {"frequency_hz": 440.0, "gain": 0.30, "decay_seconds": 1.05},
            {"frequency_hz": 611.4, "gain": 0.24, "decay_seconds": 1.28},
            {"frequency_hz": 887.0, "gain": 0.14, "decay_seconds": 0.88},
            {"frequency_hz": 1_447.2, "gain": 0.08, "decay_seconds": 0.65},
        ],
        seed=seed,
        diffuse_noise=0.018,
        stereo_spread=0.0015,
        name="Inharmonic glass-machine resonator",
        impulse_id="m24-1-glass-machine",
    )
    convolved = convolve_partitioned(excitation, ir, sample_rate, block_size=1024)
    dry_padded = np.zeros_like(convolved.audio)
    dry_padded[:len(excitation), :] = excitation[:, None]
    blended = dry_padded + (convolved.audio - dry_padded) * np.float32(0.28)

    dry_matched, dry_report = match_audition_level(dry_padded)
    wet_matched, wet_report = match_audition_level(convolved.audio)
    blend_matched, blend_report = match_audition_level(blended)

    ir.save(output / "glass-machine-ir.npz")
    write_wav(output / "01-excitation-matched.wav", dry_matched, sample_rate)
    write_wav(output / "02-convolution-matched.wav", wet_matched, sample_rate)
    write_wav(output / "03-role-blend-matched.wav", blend_matched, sample_rate)
    report = {
        "module": "m24.1.convolution",
        "example": "short rhythmic excitation into an inharmonic glass-machine resonator",
        "seed": seed,
        "sample_rate": sample_rate,
        "files": [
            "01-excitation-matched.wav",
            "02-convolution-matched.wav",
            "03-role-blend-matched.wav",
            "glass-machine-ir.npz",
        ],
        "level_match": {
            "target_rms_dbfs": -18.0,
            "peak_ceiling": 0.95,
            "dry": dry_report,
            "convolved": wet_report,
            "role_blend": blend_report,
        },
        "convolution": convolved.diagnostics,
        "listening_questions": [
            "Does the resonant response create a distinct object identity rather than generic room depth?",
            "Does the 28 percent blend preserve the excitation's rhythmic placement?",
            "Does the tail occupy useful negative space without masking the next hit?",
            "Does the dual-mono/spread design remain coherent in mono?",
        ],
        "artistic_evaluation": "human_listener_required",
    }
    (output / "render.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("m24-1-listening-example"))
    parser.add_argument("--sample-rate", type=int, default=48_000)
    parser.add_argument("--seed", type=int, default=2401)
    args = parser.parse_args()
    if args.sample_rate < 8_000:
        parser.error("sample-rate must be at least 8000 Hz")
    report = render(args.output, args.sample_rate, args.seed)
    print(
        f"Rendered M24.1 listening set · {args.sample_rate} Hz · "
        f"tail {report['convolution']['tail_seconds']:.3f} s · {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
