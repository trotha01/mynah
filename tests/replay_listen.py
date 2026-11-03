"""Replay test with the real Silero VAD and Parakeet models and spoken (macOS `say`) audio fed in place of the
microphone: checks the whole listen -> endpoint -> transcribe -> submit path, and that mode off acts on nothing.
Run: HF_HUB_OFFLINE=1 ~/.local/share/uv/tools/mynah/bin/python tests/replay_listen.py"""
import os
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np

tmp = Path(tempfile.mkdtemp(prefix="mynah-replay."))
os.environ["MYNAH_VOICE_MODE_FILE"] = str(tmp / "voice-conversation")
os.environ["MYNAH_VOICE_STATE_FILE"] = str(tmp / "voice-state")
os.environ["MYNAH_CUES"] = "0"
from mynah import listen  # noqa: E402


def speech(text):
    aiff, wav = tmp / "s.aiff", tmp / "s.wav"
    subprocess.run(["say", "-o", str(aiff), text], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(aiff), "-ar", "16000", "-ac", "1",
                    "-c:a", "pcm_s16le", str(wav)], check=True)
    w = wave.open(str(wav))
    return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def silence(seconds):
    return np.random.default_rng(0).normal(0, 0.001, int(seconds * 16000)).astype(np.float32)


class Speaker:
    speaking = False
    player = None
    said = []
    def say(self, t): self.said.append(t)
    def stop(self): pass


class ReplayListener(listen.Listener):
    """open_mic feeds the prepared audio at real-time pace (x8) instead of opening a device."""
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.audio = np.zeros(0, dtype=np.float32)

    def open_mic(self):
        if self.stream is not None:
            return
        self.vad_state = self.vad.initial_state(sample_rate=listen.SAMPLE_RATE)
        self.stream = object()
        audio = self.audio
        def feed():
            for i in range(0, len(audio) - listen.FRAME, listen.FRAME):
                if self.stream is None:
                    return
                self.frames.put(audio[i:i + listen.FRAME].copy())
                time.sleep(listen.FRAME_SECONDS / 8)
        threading.Thread(target=feed, daemon=True).start()

    def release_mic(self):
        self.stream = None


def scenario(name, audio, mode, expect):
    sent = []
    listen.MODE_FILE.unlink(missing_ok=True)
    if mode:
        listen.MODE_FILE.touch()
    l = ReplayListener(Speaker(), submit=sent.append, vad=VAD, stt=STT)
    l.audio = audio
    l.idle_state = "listening"
    deadline = time.time() + len(audio) / 16000 / 8 + 6
    def loop():
        while time.time() < deadline:
            if mode:
                l.step()
            else:
                time.sleep(0.05)   # mode off: the real run() never calls step(), i.e. never opens the mic
    loop()
    ok = [s.lower().strip(" .?!") for s in sent] == [e.lower() for e in expect]
    print(("PASS" if ok else "FAIL"), name, sent)
    return ok


from mlx_audio.vad.utils import load_model as load_vad  # noqa: E402
from mlx_audio.stt.utils import load_model as load_stt  # noqa: E402
VAD = load_vad(listen.VAD_MODEL)
STT = load_stt(listen.STT_MODEL)
helper = ReplayListener(Speaker(), vad=VAD, stt=STT)
helper.transcribe(np.zeros(16000, dtype=np.float32))

a = speech("Please list the open todo items and tell me which one is blocked.")
b = speech("Yes, go ahead and merge it.")
results = [
    scenario("one utterance", np.concatenate([silence(1), a, silence(2)]), True,
             ["please list the open to do items and tell me which one is blocked"]),
    scenario("two utterances", np.concatenate([silence(1), b, silence(1.6), b, silence(2)]), True,
             ["yes, go ahead and merge it".strip(), "yes, go ahead and merge it"]),
    scenario("only silence/noise", silence(5), True, []),
    scenario("mode off ignores speech", np.concatenate([silence(1), a, silence(2)]), False, []),
]
sys.exit(0 if all(results) else 1)
