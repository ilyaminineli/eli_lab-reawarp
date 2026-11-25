"""Portable, deterministic convolution and designed impulse-response instruments.

The module is independent of the M22 mixer, renders offline, uses NumPy only,
and never mutates the input signal or impulse response.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


IR_FORMAT = "reawarp_impulse_response"
IR_SCHEMA_VERSION = 1
_MIN_BLOCK_SIZE = 64
_MAX_BLOCK_SIZE = 8192
_MAX_IR_SECONDS = 60.0
_MAX_MODES = 256


def _finite_number(value: Any, name: str, low: float, high: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result) or result < low or result > high:
        raise ValueError(f"{name} must be finite and between {low} and {high}")
    return result


def _json_object(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(json.dumps(dict(value), ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("impulse-response design metadata must be finite JSON data") from exc


def _canonical_audio(audio: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(np.asarray(audio, dtype="<f4"))


def _audio_sha256(audio: np.ndarray) -> str:
    value = _canonical_audio(audio)
    digest = hashlib.sha256()
    digest.update(str(value.shape).encode("ascii"))
    digest.update(value.tobytes())
    return digest.hexdigest()


def _audio_channels(audio: Any, name: str) -> tuple[np.ndarray, bool]:
    value = np.asarray(audio)
    if value.dtype.kind not in {"f", "i", "u"}:
        raise ValueError(f"{name} must be a real numeric audio array")
    if value.ndim == 1:
        mono_vector = True
        value = value[:, None]
    elif value.ndim == 2 and value.shape[1] in {1, 2}:
        mono_vector = False
    else:
        raise ValueError(f"{name} must be mono or stereo (frames, channels)")
    value = np.asarray(value, dtype=np.float32)
    if not np.isfinite(value).all():
        raise ValueError(f"{name} must contain only finite samples")
    return np.ascontiguousarray(value), mono_vector


@dataclass(frozen=True, slots=True)
class ImpulseResponse:
    """Immutable, hash-addressed mono or dual-mono stereo impulse response."""

    samples: np.ndarray = field(repr=False, compare=False)
    sample_rate: int
    name: str = "Impulse response"
    impulse_id: str = "ir"
    source_identity_id: str = "source:impulse-response"
    processing_identity_id: str = "process:convolution"
    seed: int = 0
    design: dict[str, Any] = field(default_factory=dict)
    schema_version: int = IR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            isinstance(self.sample_rate, bool)
            or int(self.sample_rate) != self.sample_rate
            or int(self.sample_rate) <= 0
        ):
            raise ValueError("sample_rate must be a positive integer")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        if self.schema_version != IR_SCHEMA_VERSION:
            raise ValueError(f"unsupported impulse-response schema: {self.schema_version}")
        samples, _mono_vector = _audio_channels(self.samples, "impulse response")
        if len(samples) < 1:
            raise ValueError("impulse response cannot be empty")
        if len(samples) > int(self.sample_rate * _MAX_IR_SECONDS):
            raise ValueError(f"impulse response cannot exceed {_MAX_IR_SECONDS:g} seconds")
        frozen = samples.copy()
        frozen.setflags(write=False)
        object.__setattr__(self, "samples", frozen)
        object.__setattr__(self, "sample_rate", int(self.sample_rate))
        for name in ("name", "impulse_id", "source_identity_id", "processing_identity_id"):
            value = str(getattr(self, name)).strip()
            if not value:
                raise ValueError(f"{name} cannot be empty")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "design", _json_object(self.design))

    @property
    def frame_count(self) -> int:
        return int(len(self.samples))

    @property
    def channels(self) -> int:
        return int(self.samples.shape[1])

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / float(self.sample_rate)

    @property
    def sha256(self) -> str:
        return _audio_sha256(self.samples)

    def to_manifest(self) -> dict[str, Any]:
        return {
            "format": IR_FORMAT,
            "schema_version": self.schema_version,
            "impulse_id": self.impulse_id,
            "name": self.name,
            "source_identity_id": self.source_identity_id,
            "processing_identity_id": self.processing_identity_id,
            "sample_rate": self.sample_rate,
            "frame_count": self.frame_count,
            "channels": self.channels,
            "duration_seconds": self.duration_seconds,
            "seed": self.seed,
            "design": self.design,
            "sha256": self.sha256,
            "sample_encoding": "float32_little_endian",
        }

    def save(self, path: str | Path) -> Path:
        """Write a portable compressed NPZ with JSON manifest and float32 audio."""
        destination = Path(path).expanduser()
        if destination.suffix.casefold() != ".npz":
            raise ValueError("impulse responses must be saved as .npz files")
        destination.parent.mkdir(parents=True, exist_ok=True)
        manifest = json.dumps(
            self.to_manifest(), ensure_ascii=False, sort_keys=True, allow_nan=False
        )
        with destination.open("wb") as handle:
            np.savez_compressed(
                handle,
                manifest=np.asarray(manifest),
                samples=np.asarray(self.samples, dtype="<f4"),
            )
        return destination

    @classmethod
    def load(cls, path: str | Path) -> "ImpulseResponse":
        source = Path(path).expanduser()
        with np.load(source, allow_pickle=False) as archive:
            if set(archive.files) != {"manifest", "samples"}:
                raise ValueError("impulse-response archive has unexpected members")
            manifest = json.loads(str(archive["manifest"].item()))
            samples = np.asarray(archive["samples"], dtype=np.float32).copy()
        if manifest.get("format") != IR_FORMAT:
            raise ValueError("file is not a Reawarp impulse response")
        if int(manifest.get("schema_version", -1)) != IR_SCHEMA_VERSION:
            raise ValueError("unsupported impulse-response schema version")
        if int(manifest.get("frame_count", -1)) != len(samples):
            raise ValueError("impulse-response frame count does not match its manifest")
        channel_count = 1 if samples.ndim == 1 else samples.shape[1]
        if int(manifest.get("channels", -1)) != channel_count:
            raise ValueError("impulse-response channel count does not match its manifest")
        result = cls(
            samples=samples,
            sample_rate=int(manifest["sample_rate"]),
            name=str(manifest.get("name", "Impulse response")),
            impulse_id=str(manifest.get("impulse_id", "ir")),
            source_identity_id=str(manifest.get("source_identity_id", "source:impulse-response")),
            processing_identity_id=str(manifest.get("processing_identity_id", "process:convolution")),
            seed=int(manifest.get("seed", 0)),
            design=dict(manifest.get("design", {})),
            schema_version=int(manifest.get("schema_version", IR_SCHEMA_VERSION)),
        )
        if result.sha256 != str(manifest.get("sha256", "")):
            raise ValueError("impulse-response audio hash does not match its manifest")
        return result


@dataclass(frozen=True, slots=True)
class ConvolutionResult:
    audio: np.ndarray
    diagnostics: dict[str, Any]


def design_resonant_ir(
    sample_rate: int,
    duration_seconds: float,
    modes: Sequence[Mapping[str, Any]],
    *,
    seed: int = 0,
    diffuse_noise: float = 0.0,
    stereo_spread: float = 0.0,
    name: str = "Designed resonant response",
    impulse_id: str = "designed-resonator",
) -> ImpulseResponse:
    """Design an inharmonic modal response for metallic, glassy or machine-like tones.

    A mode contains frequency_hz, gain, decay_seconds and optional phase_radians.
    diffuse_noise adds a deterministic exponentially decaying noise component.
    stereo_spread creates a small per-channel frequency divergence (0..0.05).
    No peak normalisation is performed: response gain remains an authored choice.
    """
    if isinstance(sample_rate, bool) or int(sample_rate) < 1000:
        raise ValueError("sample_rate must be an integer >= 1000 Hz")
    rate = int(sample_rate)
    duration = _finite_number(duration_seconds, "duration_seconds", 1.0 / rate, _MAX_IR_SECONDS)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    if not modes or len(modes) > _MAX_MODES:
        raise ValueError(f"modes must contain between 1 and {_MAX_MODES} entries")
    noise_amount = _finite_number(diffuse_noise, "diffuse_noise", 0.0, 1.0)
    spread = _finite_number(stereo_spread, "stereo_spread", 0.0, 0.05)
    frames = max(1, int(round(rate * duration)))
    time_axis = np.arange(frames, dtype=np.float64) / rate
    channels = 2 if spread > 0 else 1
    output = np.zeros((frames, channels), dtype=np.float64)
    normalized_modes: list[dict[str, float]] = []
    rng = np.random.default_rng(seed)

    for index, item in enumerate(modes):
        if not isinstance(item, Mapping):
            raise ValueError(f"mode {index} must be an object")
        frequency = _finite_number(
            item.get("frequency_hz"), f"modes[{index}].frequency_hz",
            0.1, rate * 0.499 / (1.0 + spread)
        )
        gain = _finite_number(item.get("gain", 1.0), f"modes[{index}].gain", 0.0, 4.0)
        decay = _finite_number(
            item.get("decay_seconds", 0.5), f"modes[{index}].decay_seconds", 0.001, 120.0
        )
        phase = _finite_number(
            item.get("phase_radians", 0.0), f"modes[{index}].phase_radians",
            -math.tau * 1000.0, math.tau * 1000.0,
        )
        normalized_modes.append({
            "frequency_hz": frequency, "gain": gain,
            "decay_seconds": decay, "phase_radians": phase,
        })
        envelope = np.exp(-time_axis / decay)
        if channels == 1:
            output[:, 0] += gain * np.sin(math.tau * frequency * time_axis + phase) * envelope
        else:
            left_frequency = frequency * (1.0 - spread)
            right_frequency = frequency * (1.0 + spread)
            output[:, 0] += gain * np.sin(math.tau * left_frequency * time_axis + phase) * envelope
            output[:, 1] += gain * np.sin(math.tau * right_frequency * time_axis + phase) * envelope

    if noise_amount > 0.0:
        noise = rng.standard_normal((frames, channels), dtype=np.float64)
        noise_decay = max(duration * 0.32, 0.01)
        output += noise_amount * 0.08 * noise * np.exp(-time_axis[:, None] / noise_decay)

    return ImpulseResponse(
        samples=np.ascontiguousarray(output, dtype=np.float32),
        sample_rate=rate,
        name=name,
        impulse_id=impulse_id,
        source_identity_id=f"designed:{impulse_id}",
        processing_identity_id="process:modal-convolution-ir",
        seed=seed,
        design={
            "method": "deterministic_modal_resonator",
            "duration_seconds": duration,
            "modes": normalized_modes,
            "diffuse_noise": noise_amount,
            "stereo_spread": spread,
            "normalization": "none",
        },
    )


def convolve_partitioned(
    audio: np.ndarray,
    impulse_response: ImpulseResponse | np.ndarray | None,
    sample_rate: int,
    *,
    wet: float = 1.0,
    block_size: int = 1024,
    bypass: bool = False,
) -> ConvolutionResult:
    """Offline causal FIR convolution using uniform partitioned overlap-add.

    A full wet render returns N + M - 1 frames. Latency is zero in the offline
    file; this is not a streaming processor. Stereo processing is dual-mono.
    bypass=True or wet=0 returns a separate exact-length float32 dry copy.
    """
    source, source_was_vector = _audio_channels(audio, "input audio")
    amount = _finite_number(wet, "wet", 0.0, 1.0)
    if isinstance(block_size, bool) or not isinstance(block_size, int):
        raise ValueError("block_size must be an integer power of two")
    if block_size < _MIN_BLOCK_SIZE or block_size > _MAX_BLOCK_SIZE or block_size & (block_size - 1):
        raise ValueError(
            f"block_size must be a power of two between {_MIN_BLOCK_SIZE} and {_MAX_BLOCK_SIZE}"
        )
    if isinstance(sample_rate, bool) or int(sample_rate) != sample_rate or int(sample_rate) <= 0:
        raise ValueError("sample_rate must be a positive integer")
    rate = int(sample_rate)
    started = time.perf_counter()

    if bypass or amount == 0.0:
        dry = source.copy()
        result_audio = dry[:, 0] if source_was_vector else dry
        elapsed = time.perf_counter() - started
        return ConvolutionResult(
            audio=np.ascontiguousarray(result_audio, dtype=np.float32),
            diagnostics={
                "module": "m24.1.convolution", "algorithm": "bypass", "bypass": True,
                "sample_rate": rate, "input_frames": int(len(source)),
                "output_frames": int(len(source)), "tail_frames": 0, "tail_seconds": 0.0,
                "latency_frames": 0, "processing_seconds": elapsed, "wet": amount,
                "finite_output": True,
            },
        )

    if impulse_response is None:
        raise ValueError("an impulse response is required unless bypass is enabled")
    if isinstance(impulse_response, ImpulseResponse):
        response = impulse_response
        if response.sample_rate != rate:
            raise ValueError(
                f"impulse response sample rate {response.sample_rate} Hz does not match input {rate} Hz; "
                "resample the IR explicitly before convolution"
            )
        ir, _ir_vector = _audio_channels(response.samples, "impulse response")
        ir_sha, ir_id = response.sha256, response.impulse_id
    else:
        ir, _ir_vector = _audio_channels(impulse_response, "impulse response")
        ir_sha, ir_id = _audio_sha256(ir), "array-ir"
    if len(ir) == 0:
        raise ValueError("impulse response cannot be empty")

    input_channels, ir_channels = source.shape[1], ir.shape[1]
    if input_channels == 1 and ir_channels == 2:
        source_channels, filter_channels, output_channels = (
            np.repeat(source, 2, axis=1), ir, 2
        )
    elif input_channels == 2 and ir_channels == 1:
        source_channels, filter_channels, output_channels = (
            source, np.repeat(ir, 2, axis=1), 2
        )
    elif input_channels == ir_channels:
        source_channels, filter_channels, output_channels = source, ir, input_channels
    else:
        raise ValueError("input and impulse response channel layouts are incompatible")

    input_frames = int(len(source_channels))
    ir_frames = int(len(filter_channels))
    if input_frames == 0:
        empty = np.zeros((0, output_channels), dtype=np.float32)
        output = empty[:, 0] if source_was_vector and output_channels == 1 else empty
        return ConvolutionResult(
            audio=output,
            diagnostics={
                "module": "m24.1.convolution", "algorithm": "partitioned_overlap_add",
                "bypass": False, "sample_rate": rate, "input_frames": 0,
                "output_frames": 0, "tail_frames": 0, "tail_seconds": 0.0,
                "latency_frames": 0, "processing_seconds": 0.0, "wet": amount,
                "impulse_response_id": ir_id, "impulse_response_sha256": ir_sha,
                "finite_output": True,
            },
        )

    partitions = [
        filter_channels[offset:offset + block_size]
        for offset in range(0, ir_frames, block_size)
    ]
    fft_size, bins = block_size * 2, block_size + 1
    filter_spectra = np.empty(
        (len(partitions), bins, output_channels), dtype=np.complex128
    )
    for part_index, part in enumerate(partitions):
        padded = np.zeros((fft_size, output_channels), dtype=np.float64)
        padded[:len(part)] = part
        filter_spectra[part_index] = np.fft.rfft(padded, axis=0)

    partition_count = len(partitions)
    input_blocks = int(math.ceil(input_frames / block_size))
    output_frames = input_frames + ir_frames - 1
    output_blocks = int(math.ceil(output_frames / block_size))
    history = np.zeros(
        (partition_count, bins, output_channels), dtype=np.complex128
    )
    wet_accumulator = np.zeros((output_frames, output_channels), dtype=np.float64)

    # For output block k, sum X[k-p] * H[p], then overlap-add the 2B-1 result.
    for output_block in range(output_blocks):
        if output_block < input_blocks:
            offset = output_block * block_size
            chunk = source_channels[offset:offset + block_size]
            padded_input = np.zeros((fft_size, output_channels), dtype=np.float64)
            padded_input[:len(chunk)] = chunk
            history[output_block % partition_count] = np.fft.rfft(padded_input, axis=0)

        accumulated_spectrum = np.zeros(
            (bins, output_channels), dtype=np.complex128
        )
        max_partition = min(partition_count, output_block + 1)
        for partition_index in range(max_partition):
            input_index = output_block - partition_index
            if input_index >= input_blocks:
                continue
            accumulated_spectrum += (
                history[input_index % partition_count] * filter_spectra[partition_index]
            )

        convolved_block = np.fft.irfft(accumulated_spectrum, n=fft_size, axis=0)
        output_offset = output_block * block_size
        count = min(fft_size, output_frames - output_offset)
        if count > 0:
            wet_accumulator[output_offset:output_offset + count] += convolved_block[:count]

    wet_audio = np.asarray(wet_accumulator, dtype=np.float32)
    if amount < 1.0:
        dry_padded = np.zeros((output_frames, output_channels), dtype=np.float32)
        dry_padded[:input_frames] = source_channels
        mixed = dry_padded + (wet_audio - dry_padded) * np.float32(amount)
    else:
        mixed = wet_audio

    finite_output = bool(np.isfinite(mixed).all())
    if not finite_output:
        raise FloatingPointError("convolution produced non-finite output")
    peak = float(np.max(np.abs(mixed))) if mixed.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(mixed, dtype=np.float64)))) if mixed.size else 0.0
    elapsed = time.perf_counter() - started
    preserve_vector = source_was_vector and output_channels == 1
    output = np.ascontiguousarray(mixed[:, 0] if preserve_vector else mixed, dtype=np.float32)
    estimated_working_bytes = int(
        filter_spectra.nbytes + history.nbytes + wet_accumulator.nbytes
        + source_channels.nbytes + filter_channels.nbytes + mixed.nbytes
    )
    return ConvolutionResult(
        audio=output,
        diagnostics={
            "module": "m24.1.convolution",
            "algorithm": "uniform_partitioned_overlap_add",
            "bypass": False,
            "sample_rate": rate,
            "input_frames": input_frames,
            "output_frames": output_frames,
            "input_channels": input_channels,
            "impulse_response_channels": ir_channels,
            "output_channels": output_channels,
            "impulse_response_id": ir_id,
            "impulse_response_sha256": ir_sha,
            "impulse_response_frames": ir_frames,
            "partition_count": partition_count,
            "block_size_frames": block_size,
            "fft_size": fft_size,
            "wet": amount,
            "latency_frames": 0,
            "tail_frames": ir_frames - 1,
            "tail_seconds": (ir_frames - 1) / float(rate),
            "processing_seconds": elapsed,
            "real_time_factor": elapsed / (input_frames / float(rate)),
            "estimated_working_bytes": estimated_working_bytes,
            "output_bytes": int(output.nbytes),
            "peak": peak,
            "peak_dbfs": 20.0 * math.log10(max(peak, 1e-12)),
            "rms": rms,
            "headroom_db": 20.0 * math.log10(max(1e-12, 1.0 / max(peak, 1e-12))),
            "over_unity": bool(peak > 1.0),
            "finite_output": finite_output,
            "denormal_sample_count": int(np.count_nonzero(
                (np.abs(output) > 0.0) & (np.abs(output) < np.finfo(np.float32).tiny)
            )),
            "random_policy": "none_in_convolution",
            "reproducibility": "same-environment deterministic",
        },
    )


def spectral_imprint(
    audio: np.ndarray,
    impulse_response: ImpulseResponse,
    sample_rate: int,
    *,
    wet: float = 1.0,
    block_size: int = 1024,
    bypass: bool = False,
) -> ConvolutionResult:
    """Use a designed resonant response as a causal FIR spectral/timbral imprint.

    This is linear convolution, not STFT envelope transfer, phase-vocoder or
    time-varying spectral delay processing.
    """
    result = convolve_partitioned(
        audio, impulse_response, sample_rate,
        wet=wet, block_size=block_size, bypass=bypass,
    )
    diagnostics = dict(result.diagnostics)
    diagnostics["instrument"] = "spectral_imprint"
    diagnostics["spectral_imprint_semantics"] = "causal_fir_resonant_coloration"
    return ConvolutionResult(result.audio, diagnostics)


__all__ = [
    "IR_FORMAT", "IR_SCHEMA_VERSION", "ImpulseResponse", "ConvolutionResult",
    "design_resonant_ir", "convolve_partitioned", "spectral_imprint",
]
