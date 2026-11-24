"""Optional Pyo-backed offline effects rack for Reawarp.

The NumPy renderer remains the deterministic reference engine. Pyo is loaded only
when an FX render is requested, so importing Reawarp never requires a Pyo runtime.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import numpy as np

FX_PRESETS: dict[str, tuple[dict[str, float | str], ...]] = {
    "restrained_space": (
        {"type": "highpass", "cutoff_hz": 28.0, "mix": 1.0},
        {"type": "lowpass", "cutoff_hz": 15_500.0, "mix": 0.86},
        {"type": "reverb", "size": 0.24, "damping": 0.72, "mix": 0.22},
    ),
    "tape_echo": (
        {"type": "highpass", "cutoff_hz": 52.0, "mix": 1.0},
        {"type": "lowpass", "cutoff_hz": 9_200.0, "mix": 0.82},
        {
            "type": "delay",
            "delay_seconds": 0.375,
            "feedback": 0.25,
            "mix": 0.27,
        },
    ),
    "metallic_machine": (
        {"type": "bandpass", "center_hz": 1_850.0, "q": 2.7, "mix": 0.60},
        {"type": "frequency_shift", "shift_hz": 13.0, "mix": 0.18},
        {"type": "reverb", "size": 0.46, "damping": 0.38, "mix": 0.28},
    ),
    "digital_fracture": (
        {"type": "saturation", "drive": 0.38, "slope": 0.76, "mix": 0.42},
        {"type": "lowpass", "cutoff_hz": 10_500.0, "mix": 0.82},
        {
            "type": "delay",
            "delay_seconds": 0.047,
            "feedback": 0.14,
            "mix": 0.20,
        },
    ),
}

FX_PRESET_DESCRIPTIONS = {
    "restrained_space": "Low-end control and a short, dark room; keeps the source in front.",
    "tape_echo": "Filtered quarter-note echo with restrained feedback and no tempo guess.",
    "metallic_machine": "Narrow resonant focus, a small frequency displacement, and a diffuse tail.",
    "digital_fracture": "Moderate nonlinear drive, bandwidth reduction, and a short fractured repeat.",
}


def _validate_audio(audio: np.ndarray, sample_rate: int) -> np.ndarray:
    samples = np.asarray(audio, dtype=np.float32)
    if samples.ndim == 1:
        samples = samples[:, None]
    if samples.ndim != 2 or samples.shape[1] not in (1, 2):
        raise ValueError("audio must be mono or stereo, with shape (frames, channels)")
    if samples.shape[0] == 0:
        raise ValueError("audio is empty")
    if not 8_000 <= int(sample_rate) <= 192_000:
        raise ValueError("sample_rate must be between 8000 and 192000 Hz")
    if not np.all(np.isfinite(samples)):
        samples = np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
    return np.ascontiguousarray(samples, dtype=np.float32)


def _make_stage(pyo: Any, source: Any, stage: dict[str, float | str], sample_rate: int) -> Any:
    kind = str(stage["type"])
    mix = float(stage.get("mix", 1.0))
    if not 0.0 <= mix <= 1.0:
        raise ValueError(f"FX stage mix must be between 0 and 1: {kind}")

    nyquist_guard = float(sample_rate) * 0.45
    if kind == "highpass":
        processed = pyo.ButHP(
            source, freq=min(max(20.0, float(stage.get("cutoff_hz", 40.0))), nyquist_guard)
        )
    elif kind == "lowpass":
        processed = pyo.ButLP(
            source,
            freq=min(max(40.0, float(stage.get("cutoff_hz", 12_000.0))), nyquist_guard),
        )
    elif kind == "bandpass":
        center = min(
            max(40.0, float(stage.get("center_hz", 1_000.0))), nyquist_guard
        )
        q = min(max(0.5, float(stage.get("q", 2.0))), 24.0)
        processed = pyo.ButBP(source, freq=center, q=q)
    elif kind == "saturation":
        drive = min(max(0.0, float(stage.get("drive", 0.3))), 0.98)
        slope = min(max(0.0, float(stage.get("slope", 0.7))), 1.0)
        processed = pyo.Disto(source, drive=drive, slope=slope)
    elif kind == "delay":
        delay_seconds = min(max(0.01, float(stage.get("delay_seconds", 0.25))), 2.0)
        feedback = min(max(0.0, float(stage.get("feedback", 0.2))), 0.82)
        processed = pyo.Delay(
            source,
            delay=delay_seconds,
            feedback=feedback,
            maxdelay=max(0.5, delay_seconds * 2.5),
        )
    elif kind == "reverb":
        size = min(max(0.0, float(stage.get("size", 0.35))), 1.0)
        damping = min(max(0.0, float(stage.get("damping", 0.6))), 1.0)
        processed = pyo.Freeverb(source, size=size, damp=damping, bal=1.0)
    elif kind == "frequency_shift":
        shift = min(max(-500.0, float(stage.get("shift_hz", 10.0))), 500.0)
        processed = pyo.FreqShift(source, shift=shift)
    else:
        raise ValueError(f"Unsupported Pyo FX stage: {kind}")

    if mix >= 1.0:
        return processed
    if mix <= 0.0:
        return source
    return source * (1.0 - mix) + processed * mix


def render_pyo_fx(
    audio: np.ndarray,
    sample_rate: int,
    *,
    preset: str = "restrained_space",
    wet: float = 0.75,
    tail_seconds: float = 1.5,
) -> np.ndarray:
    """Render a preset to a new float32 buffer without changing the input.

    This is an offline render: it does not open an audio device. Pyo and
    SoundFile are imported lazily so the rest of Reawarp remains usable without
    either optional package.
    """
    if preset not in FX_PRESETS:
        raise ValueError(f"Unknown FX preset {preset!r}; choose from {', '.join(FX_PRESETS)}")
    if not 0.0 <= float(wet) <= 1.0:
        raise ValueError("wet must be between 0 and 1")
    if not 0.0 <= float(tail_seconds) <= 12.0:
        raise ValueError("tail_seconds must be between 0 and 12 seconds")

    samples = _validate_audio(audio, sample_rate)
    try:
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError(
            'SoundFile is required for the FX Lab. Install it with: '
            'python -m pip install -e ".[pyo]"'
        ) from exc
    try:
        import pyo
    except Exception as exc:
        raise RuntimeError(
            'Pyo is required for the FX Lab. Install it with: '
            'python -m pip install -e ".[pyo]"'
        ) from exc

    duration = len(samples) / float(sample_rate)
    render_duration = duration + float(tail_seconds)
    with TemporaryDirectory(prefix="reawarp-fx-") as temporary:
        source_path = Path(temporary) / "source.wav"
        rendered_path = Path(temporary) / "processed.wav"
        sf.write(str(source_path), samples, int(sample_rate), subtype="FLOAT")

        server = pyo.Server(
            sr=int(sample_rate),
            nchnls=int(samples.shape[1]),
            buffersize=512,
            duplex=0,
            audio="offline",
            verbosity=0,
        )
        try:
            server.boot()
            server.recordOptions(
                dur=render_duration,
                filename=str(rendered_path),
                fileformat=0,
                sampletype=3,
            )
            source = pyo.SfPlayer(str(source_path), loop=False, interp=4)
            processed = source
            for stage in FX_PRESETS[preset]:
                processed = _make_stage(pyo, processed, dict(stage), int(sample_rate))

            output = source * (1.0 - float(wet)) + processed * float(wet)
            output.out()
            server.start()
        finally:
            try:
                server.stop()
            except Exception:
                pass
            server.shutdown()

        if not rendered_path.is_file():
            raise RuntimeError("Pyo offline render finished without producing an output file")
        rendered, rendered_rate = sf.read(
            str(rendered_path), dtype="float32", always_2d=True
        )
        if int(rendered_rate) != int(sample_rate):
            raise RuntimeError(
                f"Pyo changed the sample rate unexpectedly: {rendered_rate} != {sample_rate}"
            )

    rendered = np.nan_to_num(rendered, nan=0.0, posinf=0.0, neginf=0.0)
    peak = float(np.max(np.abs(rendered))) if rendered.size else 0.0
    if peak > 0.98:
        rendered *= 0.98 / peak
    return np.ascontiguousarray(rendered, dtype=np.float32)
