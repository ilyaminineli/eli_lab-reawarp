"""Optional SoundDevice transport for auditioning rendered Reawarp audio."""

from __future__ import annotations

from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Signal


class AudioPlayer(QObject):
    """Callback-driven output transport for completed float32 audio buffers."""

    finished = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._stream: Any | None = None
        self._audio: np.ndarray | None = None
        self._position = 0
        self._paused = False
        self._playing = False
        self._callback_stop: Any | None = None

    @staticmethod
    def devices() -> list[tuple[int, str]]:
        try:
            import sounddevice as sd
            return [
                (index, str(device.get("name", f"Output {index}")))
                for index, device in enumerate(sd.query_devices())
                if int(device.get("max_output_channels", 0)) > 0
            ]
        except Exception:
            return []

    @property
    def available(self) -> bool:
        try:
            import sounddevice  # noqa: F401
            return True
        except ImportError:
            return False

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def position_frames(self) -> int:
        return self._position

    @property
    def duration_frames(self) -> int:
        return 0 if self._audio is None else len(self._audio)

    def start(self, audio: np.ndarray, sample_rate: int, device: int | None = None) -> None:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError(
                'SoundDevice is missing. Install it with: python -m pip install -e ".[m4]"'
            ) from exc
        self.stop()
        samples = np.asarray(audio, dtype=np.float32)
        if samples.ndim == 1:
            samples = np.column_stack((samples, samples))
        if samples.ndim != 2 or samples.shape[1] != 2:
            raise ValueError("playback audio must be mono or stereo")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if samples.shape[0] == 0:
            raise ValueError("there is no audio to play")

        self._audio = np.ascontiguousarray(
            np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
        )
        self._position = 0
        self._paused = False
        self._playing = True
        self._callback_stop = sd.CallbackStop
        try:
            self._stream = sd.OutputStream(
                samplerate=int(sample_rate),
                channels=2,
                dtype="float32",
                device=device,
                callback=self._callback,
                finished_callback=self._on_finished,
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            self._audio = None
            self._playing = False
            self._callback_stop = None
            raise RuntimeError(f"Could not open audio output: {exc}") from exc

    def _callback(self, outdata: np.ndarray, frames: int, _time: Any, _status: Any) -> None:
        audio = self._audio
        if audio is None or not self._playing:
            outdata.fill(0.0)
            if self._callback_stop is not None:
                raise self._callback_stop
            return
        if self._paused:
            outdata.fill(0.0)
            return
        start = self._position
        end = min(start + frames, len(audio))
        count = max(0, end - start)
        if count:
            outdata[:count] = audio[start:end]
        if count < frames:
            outdata[count:].fill(0.0)
        self._position = end
        if end >= len(audio):
            self._playing = False
            if self._callback_stop is not None:
                raise self._callback_stop

    def _on_finished(self) -> None:
        self._playing = False
        self.finished.emit()

    def pause(self) -> None:
        if self._stream is not None and self._playing:
            self._paused = True

    def resume(self) -> None:
        if self._stream is not None and self._playing:
            self._paused = False

    def stop(self) -> None:
        stream = self._stream
        self._stream = None
        self._playing = False
        self._paused = False
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        self._audio = None
        self._position = 0
        self._callback_stop = None
