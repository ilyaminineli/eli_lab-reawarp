"""Optional Pyo-backed offline effects rack and portable FX-chain format.

The NumPy renderer remains the deterministic reference engine. Pyo is loaded
only when an FX render is requested, so importing Reawarp never requires Pyo.
"""

from __future__ import annotations

import json
import math
import logging
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping, Sequence

import numpy as np

FX_CHAIN_SCHEMA_VERSION = 1

logger = logging.getLogger(__name__)
_PYO_RENDER_LOCK = threading.RLock()
FX_MAX_STAGES = 12

FX_STAGE_DEFAULTS: dict[str, dict[str, float]] = {
    "highpass": {"cutoff_hz": 40.0, "mix": 1.0},
    "lowpass": {"cutoff_hz": 12_000.0, "mix": 1.0},
    "bandpass": {"center_hz": 1_000.0, "q": 2.0, "mix": 1.0},
    "saturation": {"drive": 0.3, "slope": 0.7, "mix": 1.0},
    "delay": {"delay_seconds": 0.25, "feedback": 0.2, "mix": 1.0},
    "reverb": {"size": 0.35, "damping": 0.6, "mix": 1.0},
    "frequency_shift": {"shift_hz": 10.0, "mix": 1.0},
}

# (minimum, maximum, step, decimals, suffix)
FX_STAGE_PARAMETERS: dict[str, dict[str, tuple[float, float, float, int, str]]] = {
    "highpass": {
        "cutoff_hz": (20.0, 21_600.0, 10.0, 1, " Hz"),
        "mix": (0.0, 1.0, 0.05, 2, ""),
    },
    "lowpass": {
        "cutoff_hz": (40.0, 21_600.0, 100.0, 1, " Hz"),
        "mix": (0.0, 1.0, 0.05, 2, ""),
    },
    "bandpass": {
        "center_hz": (40.0, 21_600.0, 25.0, 1, " Hz"),
        "q": (0.5, 24.0, 0.25, 2, ""),
        "mix": (0.0, 1.0, 0.05, 2, ""),
    },
    "saturation": {
        "drive": (0.0, 0.98, 0.02, 2, ""),
        "slope": (0.0, 1.0, 0.05, 2, ""),
        "mix": (0.0, 1.0, 0.05, 2, ""),
    },
    "delay": {
        "delay_seconds": (0.01, 2.0, 0.01, 3, " s"),
        "feedback": (0.0, 0.82, 0.02, 2, ""),
        "mix": (0.0, 1.0, 0.05, 2, ""),
    },
    "reverb": {
        "size": (0.0, 1.0, 0.05, 2, ""),
        "damping": (0.0, 1.0, 0.05, 2, ""),
        "mix": (0.0, 1.0, 0.05, 2, ""),
    },
    "frequency_shift": {
        "shift_hz": (-500.0, 500.0, 1.0, 1, " Hz"),
        "mix": (0.0, 1.0, 0.05, 2, ""),
    },
}

FX_STAGE_DESCRIPTIONS = {
    "highpass": "Remove low-frequency energy before it reaches later stages.",
    "lowpass": "Restrict bandwidth and soften the upper spectrum.",
    "bandpass": "Focus a resonant frequency region with adjustable Q.",
    "saturation": "Add controlled nonlinear harmonics.",
    "delay": "Create repeats with bounded feedback.",
    "reverb": "Add a diffuse resonant tail.",
    "frequency_shift": "Displace partials by a fixed frequency offset.",
}

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


def default_fx_stage(kind: str) -> dict[str, float | str]:
    """Return a fresh copy of the default settings for one effect type."""
    if kind not in FX_STAGE_DEFAULTS:
        raise ValueError(f"Unknown FX stage {kind!r}")
    return {"type": kind, **FX_STAGE_DEFAULTS[kind].copy()}


def normalise_fx_stages(
    stages: Sequence[Mapping[str, Any]],
    *,
    sample_rate: int | None = None,
) -> tuple[dict[str, float | str], ...]:
    """Validate and normalise an ordered chain to bounded numeric parameters."""
    if not isinstance(stages, Sequence) or isinstance(stages, (str, bytes)):
        raise ValueError("FX stages must be a sequence of stage objects")
    if not 1 <= len(stages) <= FX_MAX_STAGES:
        raise ValueError(f"FX chain must contain between 1 and {FX_MAX_STAGES} stages")

    nyquist_limit = 21_600.0
    if sample_rate is not None:
        if int(sample_rate) <= 0:
            raise ValueError("sample_rate must be positive")
        nyquist_limit = min(nyquist_limit, float(sample_rate) * 0.45)

    result: list[dict[str, float | str]] = []
    for index, raw in enumerate(stages, start=1):
        if not isinstance(raw, Mapping):
            raise ValueError(f"FX stage {index} must be an object")
        kind = raw.get("type")
        if not isinstance(kind, str) or kind not in FX_STAGE_DEFAULTS:
            raise ValueError(f"FX stage {index} has an unknown type: {kind!r}")
        defaults = FX_STAGE_DEFAULTS[kind]
        unknown = set(raw) - {"type", *defaults.keys()}
        if unknown:
            raise ValueError(
                f"FX stage {index} ({kind}) has unknown parameter(s): "
                + ", ".join(sorted(str(item) for item in unknown))
            )

        stage: dict[str, float | str] = {"type": kind}
        for field, default in defaults.items():
            try:
                value = float(raw.get(field, default))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"FX stage {index} parameter {field} must be numeric"
                ) from exc
            if not math.isfinite(value):
                raise ValueError(f"FX stage {index} parameter {field} must be finite")
            low, high, *_ = FX_STAGE_PARAMETERS[kind][field]
            if field in {"cutoff_hz", "center_hz"}:
                high = nyquist_limit
                # Clamp a high cutoff to the source's safe Nyquist region rather than
                # rejecting an otherwise valid low-sample-rate file.
                value = min(value, high)
            if not low <= value <= high:
                raise ValueError(
                    f"FX stage {index} parameter {field} must be between {low:g} and {high:g}"
                )
            stage[field] = value
        result.append(stage)
    return tuple(result)


def load_fx_chain(
    path: str | Path, *, sample_rate: int | None = None
) -> dict[str, Any]:
    """Load and validate a portable version-1 FX chain JSON file."""
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("FX chain file must contain a JSON object")
    if payload.get("schema_version") != FX_CHAIN_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported FX chain schema version: {payload.get('schema_version')!r}"
        )
    name = str(payload.get("name", "Custom chain")).strip() or "Custom chain"
    wet = float(payload.get("wet", 0.75))
    tail_seconds = float(payload.get("tail_seconds", 1.5))
    if not math.isfinite(wet) or not 0.0 <= wet <= 1.0:
        raise ValueError("chain wet must be between 0 and 1")
    if not math.isfinite(tail_seconds) or not 0.0 <= tail_seconds <= 12.0:
        raise ValueError("chain tail_seconds must be between 0 and 12")
    stages = normalise_fx_stages(payload.get("stages", []), sample_rate=sample_rate)
    return {
        "schema_version": FX_CHAIN_SCHEMA_VERSION,
        "name": name,
        "wet": wet,
        "tail_seconds": tail_seconds,
        "stages": stages,
    }


def save_fx_chain(
    path: str | Path,
    *,
    name: str,
    stages: Sequence[Mapping[str, Any]],
    wet: float = 0.75,
    tail_seconds: float = 1.5,
) -> Path:
    """Save a validated, versioned FX chain JSON file."""
    destination = Path(path).expanduser()
    if not name.strip():
        raise ValueError("FX chain name cannot be empty")
    wet = float(wet)
    tail_seconds = float(tail_seconds)
    if not math.isfinite(wet) or not 0.0 <= wet <= 1.0:
        raise ValueError("wet must be between 0 and 1")
    if not math.isfinite(tail_seconds) or not 0.0 <= tail_seconds <= 12.0:
        raise ValueError("tail_seconds must be between 0 and 12")
    chain = {
        "schema_version": FX_CHAIN_SCHEMA_VERSION,
        "name": name.strip(),
        "wet": wet,
        "tail_seconds": tail_seconds,
        "stages": normalise_fx_stages(stages),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(chain, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination


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


def _make_stage(
    pyo: Any, source: Any, stage: dict[str, float | str], sample_rate: int
) -> Any:
    kind = str(stage["type"])
    mix = float(stage.get("mix", 1.0))
    nyquist_guard = float(sample_rate) * 0.45
    if kind == "highpass":
        processed = pyo.ButHP(
            source, freq=min(float(stage["cutoff_hz"]), nyquist_guard)
        )
    elif kind == "lowpass":
        processed = pyo.ButLP(
            source, freq=min(float(stage["cutoff_hz"]), nyquist_guard)
        )
    elif kind == "bandpass":
        center = min(float(stage["center_hz"]), nyquist_guard)
        processed = pyo.ButBP(source, freq=center, q=float(stage["q"]))
    elif kind == "saturation":
        processed = pyo.Disto(
            source, drive=float(stage["drive"]), slope=float(stage["slope"])
        )
    elif kind == "delay":
        delay_seconds = float(stage["delay_seconds"])
        processed = pyo.Delay(
            source,
            delay=delay_seconds,
            feedback=float(stage["feedback"]),
            maxdelay=max(0.5, delay_seconds * 2.5),
        )
    elif kind == "reverb":
        processed = pyo.Freeverb(
            source,
            size=float(stage["size"]),
            damp=float(stage["damping"]),
            bal=1.0,
        )
    elif kind == "frequency_shift":
        processed = pyo.FreqShift(source, shift=float(stage["shift_hz"]))
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
    preset: str | None = "restrained_space",
    stages: Sequence[Mapping[str, Any]] | None = None,
    wet: float = 0.75,
    tail_seconds: float = 1.5,
) -> np.ndarray:
    """Render an ordered Pyo chain with isolated files and a serialised server.

    Pyo's offline server is process-global in some builds. A process-wide lock
    prevents concurrent server lifecycles, while the unique TemporaryDirectory
    gives each render independent source and result paths. Explicitly release
    the player/graph before deleting its input WAV (important on Windows).
    """
    if stages is None:
        if preset is None or preset not in FX_PRESETS:
            raise ValueError(
                f"Unknown FX preset {preset!r}; choose from {', '.join(FX_PRESETS)}"
            )
        chain = normalise_fx_stages(FX_PRESETS[preset], sample_rate=sample_rate)
    else:
        chain = normalise_fx_stages(stages, sample_rate=sample_rate)
    if not 0.0 <= float(wet) <= 1.0:
        raise ValueError("wet must be between 0 and 1")
    if not 0.0 <= float(tail_seconds) <= 12.0:
        raise ValueError("tail_seconds must be between 0 and 12 seconds")

    samples = _validate_audio(audio, sample_rate)
    try:
        import soundfile as sf
    except ImportError as exc:
        raise RuntimeError(
            "SoundFile is required for the FX Lab. Install it with: "
            'python -m pip install -e ".[pyo]"'
        ) from exc
    try:
        import pyo
    except Exception as exc:
        raise RuntimeError(
            "Pyo is required for the FX Lab. Install it with: "
            'python -m pip install -e ".[pyo]"'
        ) from exc

    duration = len(samples) / float(sample_rate)
    render_duration = duration + float(tail_seconds)
    with _PYO_RENDER_LOCK:
        with TemporaryDirectory(prefix="reawarp-fx-") as temporary:
            source_path = Path(temporary) / "source.wav"
            rendered_path = Path(temporary) / "processed.wav"
            logger.debug(
                "Pyo FX start: rate=%s frames=%s channels=%s stages=%s source=%s",
                sample_rate,
                len(samples),
                samples.shape[1],
                [str(stage["type"]) for stage in chain],
                source_path,
            )
            sf.write(str(source_path), samples, int(sample_rate), subtype="FLOAT")
            server = pyo.Server(
                sr=int(sample_rate),
                nchnls=int(samples.shape[1]),
                buffersize=512,
                duplex=0,
                audio="offline",
                verbosity=0,
            )
            source = processed = output = None
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
                for stage in chain:
                    processed = _make_stage(
                        pyo, processed, dict(stage), int(sample_rate)
                    )
                output = source * (1.0 - float(wet)) + processed * float(wet)
                output.out()
                server.start()
            finally:
                # Stop the file player explicitly, then release the graph before
                # temporary-file cleanup. Deleting the graph is significant on
                # Windows, where an open SfPlayer handle prevents unlinking.
                if source is not None:
                    try:
                        source.stop()
                    except Exception:
                        logger.debug(
                            "Pyo SfPlayer stop raised during cleanup", exc_info=True
                        )
                try:
                    server.stop()
                except Exception:
                    logger.debug("Pyo server stop raised during cleanup", exc_info=True)
                try:
                    server.shutdown()
                except Exception:
                    logger.debug(
                        "Pyo server shutdown raised during cleanup", exc_info=True
                    )
                del output, processed, source
                import gc

                gc.collect()

            if not rendered_path.is_file():
                raise RuntimeError(
                    "Pyo offline render finished without producing an output file "
                    f"(expected {rendered_path})"
                )
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
    logger.debug("Pyo FX complete: %s frames", len(rendered))
    return np.ascontiguousarray(rendered, dtype=np.float32)
