"""TappedPlayer against fakes that mimic mlx-audio 0.5.6 and 0.6.4 AudioPlayer semantics (the real one needs macOS audio).
The fakes copy the logic of mlx_audio/tts/audio_player.py in each wheel; line numbers in comments are from those files.
Run: PYTHONPATH=src python3 -m pytest tests/test_tapped_player.py -q"""
import sys
import threading
import time
import types
from collections import deque

import numpy as np
import pytest

SR, BLOCK = 8000, 400   # 50 ms blocks: fast tests, same shape as the real 24 kHz / 2048


class CallbackStop(Exception):
    pass


class FakeStream:
    """sounddevice.OutputStream: a thread calls callback every block; CallbackStop ends it and fires finished_callback."""
    registry = []

    def __init__(self, samplerate, channels, callback, blocksize, finished_callback=None):
        self.callback, self.blocksize, self.finished = callback, blocksize, finished_callback
        self.stopping = threading.Event()
        self.thread = None
        self.closed = False
        self.consumed = 0   # real (non-silent) samples this stream pulled
        FakeStream.registry.append(self)

    @property
    def active(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self.stopping.is_set():
            out = np.zeros((self.blocksize, 1), dtype=np.float32)
            try:
                self.callback(out, self.blocksize, types.SimpleNamespace(), None)
            except CallbackStop:
                break
            self.consumed += int(np.count_nonzero(out))
            time.sleep(self.blocksize / SR)
        if self.finished:
            self.finished()

    def stop(self):
        self.stopping.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(2)

    abort = stop

    def close(self):
        self.closed = True


class _Base:
    """Shared with both versions: buffer, callback body (0.5.6 :28-47, 0.6.4 :29-47), queue_audio (:73-112 / :97-136)."""
    min_buffer_seconds = 0.3

    def __init__(self, sample_rate=SR, buffer_size=BLOCK):
        self.sample_rate, self.buffer_size = sample_rate, buffer_size
        self.audio_buffer = deque()
        self.buffer_lock = threading.Lock()
        self.stream = None
        self.playing = False
        self.drain_event = threading.Event()
        self.arrival_rate = sample_rate

    def _fill(self, outdata, frames):
        filled = 0
        with self.buffer_lock:
            while filled < frames and self.audio_buffer:
                buf = self.audio_buffer[0]
                n = min(frames - filled, len(buf))
                outdata[filled:filled + n, 0] = buf[:n]
                filled += n
                if n == len(buf):
                    self.audio_buffer.popleft()
                else:
                    self.audio_buffer[0] = buf[n:]
            return not self.audio_buffer and filled < frames

    def buffered_samples(self):
        return sum(map(len, self.audio_buffer))

    def queue_audio(self, samples):
        samples = np.asarray(samples, dtype=np.float32)
        with self.buffer_lock:
            self.audio_buffer.append(samples)
        if not self.playing and self.buffered_samples() >= int(self.arrival_rate * self.min_buffer_seconds):
            self.start_stream()

    def flush(self):   # 0.5.6 :133-142
        if not self.playing:
            return
        with self.buffer_lock:
            self.audio_buffer.clear()
        self.stop_stream()
        self.playing = False
        self.drain_event.set()


class Player056(_Base):
    def callback(self, outdata, frames, time_, status):
        outdata.fill(0)
        if self._fill(outdata, frames):
            self.drain_event.set()      # :45
            self.playing = False        # :46
            raise CallbackStop()

    def start_stream(self):             # :49-59: overwrites self.stream, never stops the old one
        self.stream = FakeStream(self.sample_rate, 1, self.callback, self.buffer_size)
        self.stream.start()
        self.playing = True
        self.drain_event.clear()

    def stop_stream(self):              # :61-68
        try:
            if self.stream:
                self.stream.stop()
                self.stream.close()
        finally:
            self.stream = None
            self.playing = False

    def wait_for_drain(self):           # :114-123
        if not self.playing:
            if self.buffered_samples() > 0:
                self.start_stream()
            else:
                return
        return self.drain_event.wait(10)


class Player064(_Base):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.drain_event.set()          # :23

    def callback(self, outdata, frames, time_, status):
        outdata.fill(0)
        if self._fill(outdata, frames):
            self.playing = False        # :46 (drain_event is NOT set here)
            raise CallbackStop()

    def _on_stream_finished(self):      # :49-53
        self.playing = False
        self.drain_event.set()

    def start_stream(self):             # :55-76: stops the old stream first
        if self.stream is not None:
            self.stop_stream()
        self.stream = FakeStream(self.sample_rate, 1, self.callback, self.buffer_size, self._on_stream_finished)
        self.drain_event.clear()
        self.playing = True
        self.stream.start()

    def stop_stream(self, *, abort=False):   # :78-91
        try:
            if self.stream is not None:
                try:
                    self.stream.stop()
                finally:
                    self.stream.close()
        finally:
            self.stream = None
            self.playing = False
            self.drain_event.set()

    def wait_for_drain(self):           # :138-146
        if not self.playing and self.buffered_samples() > 0:
            self.start_stream()
        if self.stream is not None:
            return self.drain_event.wait(10)


@pytest.fixture(params=[Player056, Player064], ids=["mlx-audio-0.5.6", "mlx-audio-0.6.4"])
def tapped(request, monkeypatch):
    try:
        import mynah.listen  # noqa: F401
    except ImportError:   # no scipy / macOS bits here (Linux CI): the player does not use listen, speakd only imports it
        m = types.ModuleType("mynah.listen")
        m.Listener, m.mode_on = object, lambda: False
        monkeypatch.setitem(sys.modules, "mynah.listen", m)
    sd = types.ModuleType("sounddevice")
    sd.CallbackStop = CallbackStop
    pkg = {"mlx_audio": types.ModuleType("mlx_audio"), "mlx_audio.tts": types.ModuleType("mlx_audio.tts"),
           "mlx_audio.tts.audio_player": types.ModuleType("mlx_audio.tts.audio_player")}
    pkg["mlx_audio.tts.audio_player"].AudioPlayer = request.param
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    for k, v in pkg.items():
        monkeypatch.setitem(sys.modules, k, v)
    from mynah import audiowatch, speakd
    h = audiowatch.WedgeHandler()
    h.native = False
    h.exit = lambda code: None
    h.restart = lambda reason: None
    monkeypatch.setattr(audiowatch, "WEDGE", h)
    monkeypatch.setattr(speakd, "write_level", lambda block: None)
    FakeStream.registry = []
    cls = speakd.tapped_player_class()
    p = cls(sample_rate=SR, buffer_size=BLOCK)
    p.min_buffer_seconds = 0.3
    yield p, speakd, h
    for s in FakeStream.registry:
        s.stopping.set()


def tone(seconds):
    return np.full(int(SR * seconds), 0.5, dtype=np.float32)


def open_streams():
    return [s for s in FakeStream.registry if not s.closed]


def running_streams():
    return [s for s in FakeStream.registry if s.active]


def test_normal_path_one_stream_drains_in_audio_time(tapped):
    p, speakd, _ = tapped
    t0 = time.time()
    p.queue_audio(tone(0.6))
    p.wait_for_drain()
    took = time.time() - t0
    assert 0.5 < took < 0.95, took
    time.sleep(0.15)
    assert len(FakeStream.registry) == 1
    speakd.Speaker._close(types.SimpleNamespace(), p)   # same call shape as Speaker._close(self, player)
    assert open_streams() == [] and running_streams() == []


def test_mid_reply_underrun_leaves_exactly_one_stream(tapped):
    p, speakd, _ = tapped
    p.queue_audio(tone(0.4))        # starts the stream
    time.sleep(0.4 + 0.3)           # buffer runs empty, the stream sits on silence
    t0 = time.time()
    p.queue_audio(tone(0.6))        # more audio after the underrun: start_stream again
    p.wait_for_drain()
    took = time.time() - t0
    assert len(running_streams()) == 1, "exactly one stream pulling from the buffer"
    assert len(open_streams()) == 1, "the old stream was closed, not leaked"
    assert 0.5 < took < 0.95, f"{took:.2f}s for 0.6 s of audio (a leaked second stream would halve it)"
    total = sum(s.consumed for s in FakeStream.registry)
    assert total == int(SR * 0.4) + int(SR * 0.6), "every sample played exactly once"
    time.sleep(0.15)
    speakd.Speaker._close(types.SimpleNamespace(), p)
    assert open_streams() == [] and running_streams() == []


def test_start_stream_after_close_starts_nothing_and_does_not_hang(tapped):
    p, speakd, _ = tapped
    p.queue_audio(tone(0.4))
    speakd.Speaker._close(types.SimpleNamespace(), p)
    n = len(FakeStream.registry)
    p.queue_audio(tone(0.5))        # a late chunk from the speak thread
    p.wait_for_drain()
    assert len(FakeStream.registry) == n and open_streams() == []


def test_old_stream_errors_are_logged_not_raised(tapped, caplog):
    p, _, _ = tapped
    p.queue_audio(tone(0.2))
    p.queue_audio(tone(0.2))        # started by the second chunk (0.4 s >= 0.3 s)
    old = p.stream
    assert old is not None

    def boom():
        raise OSError("device gone")
    old.stop = boom
    time.sleep(0.5)                 # underrun
    p.queue_audio(tone(0.4))
    assert old.closed, "close() still ran after stop() raised"
    assert any("previous stream failed" in r.message for r in caplog.records)
    assert p.stream is not old and p.stream is not None


def test_hung_old_stream_stop_triggers_wedge_handling_and_does_not_block_forever(tapped, monkeypatch):
    p, speakd, wedge = tapped
    from mynah import audiowatch
    monkeypatch.setattr(audiowatch, "STOP_TIMEOUT", 0.3)
    triggered = []
    wedge.trigger = lambda reason: triggered.append(reason)
    p.queue_audio(tone(0.4))
    release = threading.Event()
    p.stream.stop = lambda: release.wait(5)
    time.sleep(0.7)
    t0 = time.time()
    p.queue_audio(tone(0.3))
    assert time.time() - t0 < 1.5
    assert triggered and "previous stream" in triggered[0]
    release.set()


def test_start_stream_is_safe_under_a_lock_the_caller_holds(tapped):
    p, _, _ = tapped
    from mynah import audiowatch
    p.queue_audio(tone(0.4))
    time.sleep(0.7)
    with audiowatch.AUDIO_LOCK:     # e.g. start_stream reached from inside a locked section: RLock, no deadlock
        p.queue_audio(tone(0.3))
    assert len(running_streams()) == 1
