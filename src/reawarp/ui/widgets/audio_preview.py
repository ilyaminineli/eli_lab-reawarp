"""Waveform and spectrogram preview widgets for the Reawarp desktop UI."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt
from PySide6.QtWidgets import QLabel, QStackedWidget, QTabWidget, QVBoxLayout, QWidget


class AudioPreview(QWidget):
    """Efficient waveform and short-time spectrum views for rendered buffers."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        pg.setConfigOptions(antialias=False, imageAxisOrder="col-major")
        self.tabs = QTabWidget(self)
        self.waveform = pg.PlotWidget()
        self.waveform.setBackground("#11151b")
        self.waveform.showGrid(x=True, y=True, alpha=0.18)
        self.waveform.setLabel("bottom", "Time", units="s")
        self.waveform.setLabel("left", "Amplitude")
        self.waveform.setYRange(-1.05, 1.05, padding=0)
        self.waveform_min = self.waveform.plot(pen=pg.mkPen("#5b8fe8", width=1))
        self.waveform_max = self.waveform.plot(pen=pg.mkPen("#83b9ff", width=1))
        self.marker_items: list[pg.InfiniteLine] = []

        self.waveform_stack = QStackedWidget()
        self.waveform_empty = self._empty_state(
            "NO WAVEFORM",
            "Generate, load or select audio to inspect its amplitude over time.",
        )
        self.waveform_stack.addWidget(self.waveform)
        self.waveform_stack.addWidget(self.waveform_empty)
        self.waveform_stack.setCurrentWidget(self.waveform_empty)
        self.tabs.addTab(self.waveform_stack, "WAVEFORM")

        self.spectrum = pg.PlotWidget()
        self.spectrum.setBackground("#11151b")
        self.spectrum.showGrid(x=True, y=True, alpha=0.18)
        self.spectrum.setLabel("bottom", "Time", units="s")
        self.spectrum.setLabel("left", "Frequency", units="Hz")
        self.spectrum_item = pg.ImageItem()
        self.spectrum.addItem(self.spectrum_item)
        self.spectrum_stack = QStackedWidget()
        self.spectrum_empty = self._empty_state(
            "NO SPECTRUM",
            "A spectrogram will appear after audio is available.",
        )
        self.spectrum_stack.addWidget(self.spectrum)
        self.spectrum_stack.addWidget(self.spectrum_empty)
        self.spectrum_stack.setCurrentWidget(self.spectrum_empty)
        self.tabs.addTab(self.spectrum_stack, "SPECTROGRAM")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)
        self._duration = 0.0

    @staticmethod
    def _empty_state(title: str, description: str) -> QWidget:
        panel = QWidget()
        panel.setObjectName("previewEmptyState")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.addStretch(1)
        heading = QLabel(title)
        heading.setObjectName("previewEmptyTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(heading)
        caption = QLabel(description)
        caption.setObjectName("muted")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption.setWordWrap(True)
        layout.addWidget(caption)
        layout.addStretch(1)
        return panel

    def set_audio(
        self,
        audio: np.ndarray | None,
        sample_rate: int = 48_000,
        markers: list[int] | None = None,
    ) -> None:
        self.waveform_min.setData([], [])
        self.waveform_max.setData([], [])
        for marker in self.marker_items:
            self.waveform.removeItem(marker)
        self.marker_items.clear()
        self.spectrum_item.clear()
        if audio is None:
            self._duration = 0.0
            self.waveform_stack.setCurrentWidget(self.waveform_empty)
            self.spectrum_stack.setCurrentWidget(self.spectrum_empty)
            return
        samples = np.asarray(audio, dtype=np.float32)
        if samples.ndim == 2:
            mono = samples.mean(axis=1, dtype=np.float32)
        elif samples.ndim == 1:
            mono = samples
        else:
            raise ValueError("preview audio must be mono or frame-major multichannel")
        if sample_rate <= 0 or mono.size == 0:
            self._duration = 0.0
            self.waveform_stack.setCurrentWidget(self.waveform_empty)
            self.spectrum_stack.setCurrentWidget(self.spectrum_empty)
            return
        mono = np.nan_to_num(mono, nan=0.0, posinf=0.0, neginf=0.0)
        self._duration = len(mono) / float(sample_rate)

        stride = max(1, int(np.ceil(len(mono) / 12_000)))
        offsets = np.arange(0, len(mono), stride, dtype=np.int64)
        self.waveform_min.setData(
            offsets / sample_rate, np.minimum.reduceat(mono, offsets)
        )
        self.waveform_max.setData(
            offsets / sample_rate, np.maximum.reduceat(mono, offsets)
        )
        self.waveform.setXRange(0.0, max(self._duration, 0.01), padding=0)
        for frame in markers or []:
            if 0 < frame < len(mono):
                line = pg.InfiniteLine(
                    pos=frame / float(sample_rate),
                    angle=90,
                    movable=False,
                    pen=pg.mkPen("#d89b55", width=1, style=Qt.PenStyle.DashLine),
                )
                self.waveform.addItem(line)
                self.marker_items.append(line)
        self._set_spectrogram(mono, sample_rate)
        self.waveform_stack.setCurrentWidget(self.waveform)
        self.spectrum_stack.setCurrentWidget(self.spectrum)

    def _set_spectrogram(self, mono: np.ndarray, sample_rate: int) -> None:
        fft_size, hop = 1024, 256
        signal = np.pad(mono, (0, max(0, fft_size - len(mono))))
        frames = np.lib.stride_tricks.sliding_window_view(signal, fft_size)[::hop]
        window = np.hanning(fft_size).astype(np.float32)
        magnitude = np.abs(np.fft.rfft(frames * window[None, :], axis=1)).astype(
            np.float32
        )
        decibels = 20.0 * np.log10(np.maximum(magnitude, 1e-7))
        maximum = float(np.max(decibels))
        decibels = np.clip(decibels, maximum - 80.0, maximum)
        self.spectrum_item.setImage(
            decibels, autoLevels=False, levels=(maximum - 80.0, maximum)
        )
        self.spectrum_item.setRect(
            QRectF(0.0, 0.0, self._duration, float(sample_rate) / 2.0)
        )
        self.spectrum.setXRange(0.0, max(self._duration, 0.01), padding=0)
        self.spectrum.setYRange(0.0, sample_rate / 2.0, padding=0)
