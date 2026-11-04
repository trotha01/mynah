"""Publish J's mouth events with the time each one reaches the speaker.

speakd queues each Kokoro chunk's audio and its viseme timeline (viseme.py). The audio callback only records an anchor:
which sample of the stream is about to go to the output and at what unix time that block reaches the speaker (PortAudio's
outputBufferDacTime, about 48 ms ahead on the laptop speakers). A writer thread, never the callback (file I/O there once
deadlocked CoreAudio), turns that into the events of the next 0.7 s with absolute unix times and replaces
~/.local/state/mynah/voice-visemes atomically, about every 20 ms. The companion page schedules the mouth from those
timestamps, so polling delay and block size no longer matter: events arrive ~0.6 s before they are due.
"""
import json
import os
import threading
import time
from pathlib import Path

VISEME_FILE = Path(os.getenv("MYNAH_VISEME_FILE", str(Path.home() / ".local/state/mynah/voice-visemes")))
AHEAD_S = 0.7     # events published ahead of the sound
BEHIND_S = 0.15   # and a little behind, so a late reader still sees the one in progress


class LipSync:
    def __init__(self, sample_rate):
        self.sr = float(sample_rate)
        self.lock = threading.Lock()
        self.chunks = []        # (start sample in the stream, [(t0, t1, shape, open)] in seconds from the chunk start)
        self.queued = 0         # samples queued so far
        self.played = 0         # samples handed to the output so far
        self.anchor = None      # (sample index of the block's first sample, unix time it reaches the speaker, monotonic)

    def add_chunk(self, n_samples, events):
        """Call before queueing the chunk's audio; events may be None (no timeline: the mouth falls back to loudness)."""
        with self.lock:
            if events:
                self.chunks.append((self.queued, events))
            self.queued += int(n_samples)

    def on_block(self, frames, time_info):
        """From the audio callback: only remembers where the stream is. Never raises."""
        try:
            try:
                lead = float(time_info.outputBufferDacTime - time_info.currentTime)
                if not (0.0 <= lead <= 1.0):
                    lead = 0.05
            except Exception:
                lead = 0.05
            self.anchor = (self.played, time.time() + lead, time.monotonic())
            self.played += int(frames)
        except Exception:
            pass

    def stop(self):
        """The audio was cut (barge-in, end of speech): stop publishing events at once."""
        self.anchor = None

    def snapshot(self, now=None):
        """{"w": now, "ev": [[t0, t1, shape, open], ...]} with unix times, or None when nothing is playing."""
        a = self.anchor
        if a is None or time.monotonic() - a[2] > 0.25:
            return None
        now = time.time() if now is None else now
        s0, u0, _ = a
        out = []
        with self.lock:
            chunks = list(self.chunks)
        for start, events in chunks:
            for t0, t1, shape, op in events:
                u_a = u0 + (start + t0 * self.sr - s0) / self.sr
                u_b = u0 + (start + t1 * self.sr - s0) / self.sr
                if u_b > now - BEHIND_S and u_a < now + AHEAD_S:
                    out.append([round(u_a, 3), round(u_b, 3), shape, op])
        return {"w": round(now, 3), "ev": out}


_current = None
_thread = None


def publish(stream):
    """Make `stream` (a LipSync, or None) the one the writer thread publishes."""
    global _current, _thread
    _current = stream
    if stream is not None and _thread is None:
        _thread = threading.Thread(target=_run, daemon=True, name="lipsync-writer")
        _thread.start()


def _run():
    tmp = VISEME_FILE.with_name(VISEME_FILE.name + ".tmp")
    while True:
        time.sleep(0.02)
        ls = _current
        if ls is None:
            continue
        try:
            snap = ls.snapshot()
            if snap is None:
                continue
            VISEME_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(snap, separators=(",", ":")) + "\n")
            os.replace(tmp, VISEME_FILE)
        except Exception:
            pass
