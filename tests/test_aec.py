"""WebRTC AEC3 wrapper on a synthetic room with spoken audio (macOS `say`): echo is removed, a voice over it is not."""
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from mynah.aec import EchoCanceller

TEXT = ("The quick brown fox jumps over the lazy dog. She sells sea shells by the sea shore. A long reply from the "
        "orchestrator goes on for a while so that there is time to interrupt it, and the build finished without errors.")


def db(a):
    return 20 * np.log10(np.sqrt(np.mean(np.square(a, dtype=np.float64))) + 1e-9)


class EchoCancellerTest(unittest.TestCase):
    def run_room(self, voice):
        d = Path(tempfile.mkdtemp())
        subprocess.run(["say", "-v", "Samantha", "-o", str(d / "r.aiff"), TEXT], check=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(d / "r.aiff"), "-ar", "16000", "-ac", "1",
                        "-c:a", "pcm_s16le", str(d / "r.wav")], check=True)
        w = wave.open(str(d / "r.wav"))
        ref = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64) / 32768
        n = len(ref) // 512 * 512
        ref = ref[:n]
        rir = np.zeros(1200); rir[[0, 50, 200, 600]] = [.25, .12, -.07, .04]
        echo = np.convolve(np.concatenate([np.zeros(1920), ref]), rir)[:n]            # 120 ms late
        u0 = int(n * .75)
        user = np.zeros(n)
        if voice:
            t = np.arange(n - u0)
            user[u0:] = 0.05 * np.sin(2 * np.pi * 200 * t / 16000) * (1 + np.sin(t / 700))
        mic = (echo + user + np.random.default_rng(0).normal(0, 3e-4, n)).astype(np.float32)
        aec = EchoCanceller(source_rate=16000)
        out = []
        for k in range(0, n, 512):
            aec.tap(ref[k:k + 512].astype(np.float32))
            aec.flush()
            r = aec.process(0.0, mic[k:k + 512])
            out.append(r if r is not None else np.zeros(512, dtype=np.float32))
        return mic, np.concatenate(out), user, u0, n

    def test_echo_is_removed(self):
        mic, out, _, _, n = self.run_room(voice=False)
        late = slice(int(n * .4), int(n * .7))
        self.assertGreater(db(mic[late]) - db(out[late]), 25)

    def test_voice_over_the_echo_is_kept(self):
        mic, out, user, u0, n = self.run_room(voice=True)
        seg = slice(u0 + 8000, n - 3000)
        self.assertGreater(db(out[seg]), db(user[seg]) - 6)


if __name__ == "__main__":
    unittest.main()
