"""Echo cancellation for voice-conversation mode: removes the speaker's own reply from the microphone signal.

This is WebRTC's AEC3 (the canceller in Chrome, Meet and LiveKit), used through LiveKit's
`AudioProcessingModule` (https://github.com/livekit/python-sdks); nothing here is a home-made filter. It needs
two feeds, both in 10 ms frames at 16 kHz:
  - the far end (the reverse stream): everything mynah plays - the speaker's audio callback hands each block to
    `tap` as it goes to the device;
  - the near end: the microphone, through `process`, which returns the echo-cancelled signal.
AEC3 estimates the delay between the two itself; `set_delay_ms` only gives it a starting point (output plus
input latency). What comes out is the room and whoever talks over the reply, which Silero VAD and Parakeet can
use as if the reply were not playing. Measured on a synthetic room with spoken audio: the echo falls 43 dB within
a second while a voice over it loses ~2 dB.

The two streams run in different threads, so one lock covers the module.
"""
import queue
import threading

import numpy as np
from scipy.signal import resample_poly

RATE = 16000
CHUNK = 160     # 10 ms, the only frame size the module takes


class EchoCanceller:
    def __init__(self, source_rate=24000, delay_ms=120):
        self.source_rate = source_rate
        g = int(np.gcd(RATE, source_rate))
        self.up, self.down = RATE // g, source_rate // g
        self.delay_ms = delay_ms
        self.lock = threading.Lock()
        self.apm = None
        self.far_queue = queue.Queue()   # the audio callback only enqueues; a worker feeds the canceller
        self.forget()
        threading.Thread(target=self._far_worker, daemon=True, name="aec-far").start()

    def forget(self):
        """Start over with a fresh canceller (new output device or room)."""
        from livekit import rtc
        with self.lock:
            self.apm = rtc.AudioProcessingModule(echo_cancellation=True, high_pass_filter=True)
            self.apm.set_stream_delay_ms(self.delay_ms)
            self._far = np.zeros(0, dtype=np.int16)
            self._near = np.zeros(0, dtype=np.int16)
            self._out = np.zeros(0, dtype=np.int16)

    def reset_reference(self):
        """A new reply starts. AEC3 keeps what it learned about the room; drop any half-chunk of the last reply."""
        with self.lock:
            self._far = np.zeros(0, dtype=np.int16)

    def set_delay_ms(self, delay_ms):
        with self.lock:
            self.delay_ms = int(delay_ms)
            self.apm.set_stream_delay_ms(self.delay_ms)

    @staticmethod
    def _frame(samples):
        from livekit import rtc
        return rtc.AudioFrame(samples.tobytes(), RATE, 1, CHUNK)

    # ---- speaker side (audio output callback thread: must not block, so it only enqueues)
    def tap(self, block, t=None):
        self.far_queue.put(np.array(block, dtype=np.float32))

    def flush(self):
        """Wait until everything handed to `tap` has reached the canceller (tests)."""
        self.far_queue.join()

    def _far_worker(self):
        while True:
            x = self.far_queue.get()
            try:
                if self.up != self.down:
                    x = resample_poly(x, self.up, self.down)
                x = (np.clip(x, -1, 1) * 32767).astype(np.int16)
                with self.lock:
                    self._far = np.concatenate([self._far, x])
                    while len(self._far) >= CHUNK:
                        self.apm.process_reverse_stream(self._frame(self._far[:CHUNK]))
                        self._far = self._far[CHUNK:]
            except Exception as e:  # echo cancelling is best effort; never take the speaker down
                import logging
                logging.getLogger("mynah.aec").warning(f"Far-end feed failed: {e}")
            finally:
                self.far_queue.task_done()

    # ---- microphone side
    def process(self, t, frame):
        """Echo-cancelled mic audio. Takes any number of float32 samples; returns the same count as 10 ms chunks
        become available (after the first call, always the full count), or None while the first chunk is filling."""
        x = (np.clip(np.asarray(frame, dtype=np.float32), -1, 1) * 32767).astype(np.int16)
        n = len(x)
        with self.lock:
            self._near = np.concatenate([self._near, x])
            while len(self._near) >= CHUNK:
                f = self._frame(self._near[:CHUNK])
                self.apm.process_stream(f)
                self._out = np.concatenate([self._out, np.frombuffer(bytes(f.data), dtype=np.int16)])
                self._near = self._near[CHUNK:]
            if len(self._out) < n:
                return None
            out, self._out = self._out[:n], self._out[n:]
        return out.astype(np.float32) / 32767
