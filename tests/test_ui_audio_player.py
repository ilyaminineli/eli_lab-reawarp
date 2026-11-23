"""Transport tests use a fake PortAudio stream; no audio hardware is required."""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

pytest.importorskip("PySide6")

from reawarp.ui.audio_player import AudioPlayer


class FakeCallbackStop(Exception):
    pass


class FakeOutputStream:
    def __init__(self, **kwargs):
        self.callback = kwargs["callback"]
        self.finished_callback = kwargs["finished_callback"]
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True

    def render(self, frames: int) -> np.ndarray:
        outdata = np.empty((frames, 2), dtype=np.float32)
        try:
            self.callback(outdata, frames, None, None)
        except FakeCallbackStop:
            self.finished_callback()
        return outdata


@pytest.fixture
def fake_sounddevice(monkeypatch):
    module = types.ModuleType("sounddevice")
    module.CallbackStop = FakeCallbackStop
    module.OutputStream = FakeOutputStream
    module.query_devices = lambda: []
    monkeypatch.setitem(sys.modules, "sounddevice", module)
    return module


def test_audio_player_copies_buffers_pause_resume_and_finishes(fake_sounddevice):
    player = AudioPlayer()
    source = np.column_stack((
        np.arange(8, dtype=np.float32),
        np.arange(8, dtype=np.float32) + 10,
    ))
    player.start(source, 48_000)
    stream = player._stream

    first = stream.render(3)
    assert np.array_equal(first, source[:3])
    assert player.position_frames == 3

    player.pause()
    paused = stream.render(2)
    assert np.array_equal(paused, np.zeros((2, 2), dtype=np.float32))
    assert player.position_frames == 3

    player.resume()
    last = stream.render(5)
    assert np.array_equal(last, source[3:])
    assert player.position_frames == len(source)
    assert not player.is_playing
    assert player.duration_frames == len(source)
    player.stop()


def test_audio_player_replaces_playback_buffer_at_next_block(fake_sounddevice):
    player = AudioPlayer()
    original = np.ones((10, 2), dtype=np.float32)
    updated = np.full((10, 2), 0.25, dtype=np.float32)
    player.start(original, 48_000)
    stream = player._stream

    assert np.array_equal(stream.render(4), original[:4])
    assert player.replace_audio(updated)
    next_block = stream.render(3)
    assert np.array_equal(next_block, updated[4:7])
    assert player.position_frames == 7

    player.stop()
    assert not player.replace_audio(updated)


def test_audio_player_rejects_invalid_buffers(fake_sounddevice):
    player = AudioPlayer()
    with pytest.raises(ValueError, match="mono or stereo"):
        player.start(np.zeros((10, 3), dtype=np.float32), 48_000)
    with pytest.raises(ValueError, match="positive"):
        player.start(np.zeros((10, 2), dtype=np.float32), 0)
    player.stop()
