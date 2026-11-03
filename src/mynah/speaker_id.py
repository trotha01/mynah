"""Speaker verification for voice-conversation mode: act only on Trevor's voice, not on whoever else is in the room.

Uses SpeechBrain's ECAPA-TDNN trained on VoxCeleb (https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb, Apache-2.0):
a 192-number "voiceprint" per clip; two clips are compared by cosine similarity. Enrolling (`voice-mode enroll`)
records a few sentences and stores their mean voiceprint in ~/.config/jmacs/voice-profile.npz. Turned on with
`speaker=on` in ~/.config/jmacs/voice-conversation; `speaker_threshold=0.5` tunes it. Measured with macOS voices:
the same voice scored 0.67-0.88 against its profile, other voices 0.01-0.44 (the nearest, a similar female voice,
0.44). Real speech varies more, so every score is logged.

Limits: short clips ("yes") give noisier scores; a recording of Trevor's voice passes; two people talking at once
give a mixed score. Interrupting a reply (barge-in) is not checked - only what is then sent.
"""
import logging
import os
import sys
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger("mynah.speaker_id")

PROFILE = Path(os.getenv("MYNAH_VOICE_PROFILE", str(Path.home() / ".config/jmacs/voice-profile.npz")))
MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"
MODEL_DIR = Path(os.getenv("MYNAH_ECAPA_DIR", str(Path.home() / ".local/share/mynah/ecapa")))
DEFAULT_THRESHOLD = 0.5
RATE = 16000

ENROLL_SENTENCES = [
    "Please list the open todo items and tell me which one is blocked.",
    "What is the status of the deployment, and when will it finish?",
    "Open the notes from yesterday and read me the summary.",
    "Yes, go ahead and merge it, then run the tests again.",
    "Stop, wait, I changed my mind about that.",
    "Send a message to the team that the build is ready for review.",
]


def cosine(a, b):
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


class SpeakerVerifier:
    def __init__(self, profile=None, encoder=None):
        self.encoder = encoder
        self.profile = profile
        if profile is None and PROFILE.exists():
            self.profile = np.load(PROFILE)["profile"]

    @property
    def enrolled(self):
        return self.profile is not None

    def _load(self):
        if self.encoder is None:
            import warnings
            warnings.filterwarnings("ignore")
            from speechbrain.inference.speaker import EncoderClassifier
            MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
            self.encoder = EncoderClassifier.from_hparams(source=MODEL_SOURCE, savedir=str(MODEL_DIR),
                                                          run_opts={"device": "cpu"})
        return self.encoder

    def embed(self, audio):
        import torch
        e = self._load().encode_batch(torch.from_numpy(np.asarray(audio, dtype=np.float32))[None])
        e = e.squeeze().cpu().numpy()
        return e / (np.linalg.norm(e) + 1e-9)

    def score(self, audio):
        """Cosine similarity of this clip to the enrolled voice (-1..1; same speaker is typically above 0.5)."""
        return cosine(self.embed(audio), self.profile)

    def enroll(self, clips):
        embs = [self.embed(c) for c in clips]
        profile = np.mean(embs, axis=0)
        profile /= np.linalg.norm(profile)
        PROFILE.parent.mkdir(parents=True, exist_ok=True)
        np.savez(PROFILE, profile=profile, embeddings=np.array(embs), enrolled=time.time())
        self.profile = profile
        return [cosine(e, profile) for e in embs]


def level_dbfs(a):
    return 20 * np.log10(max(float(np.sqrt(np.mean(np.square(a, dtype=np.float64)))), 1e-6))


def record(seconds):
    import sounddevice as sd
    rec = sd.rec(int(seconds * RATE), samplerate=RATE, channels=1, dtype="float32")
    sd.wait()
    return rec[:, 0]


def enroll_main():
    """`python -m mynah.speaker_id enroll`: read the sentences aloud, one after another (no keyboard needed)."""
    v = SpeakerVerifier()
    print("Loading the voice model (first time: ~90 MB download)...", flush=True)
    v._load()
    clips = []
    print("\nRead each sentence aloud at your normal speaking volume, as you will talk to the orchestrator.\n")
    for i, s in enumerate(ENROLL_SENTENCES, 1):
        print(f"[{i}/{len(ENROLL_SENTENCES)}] Read this after the tone:\n    \"{s}\"", flush=True)
        time.sleep(2.5)
        os.system("afplay /System/Library/Sounds/Tink.aiff")
        a = record(6.0)
        lvl = level_dbfs(a)
        print(f"    recorded, level {lvl:.0f} dBFS" + ("  (too quiet, skipped)" if lvl < -50 else ""))
        if lvl >= -50:
            clips.append(a)
    if len(clips) < 4:
        print("Fewer than 4 usable recordings: nothing saved. Is the microphone working?")
        return 1
    scores = v.enroll(clips)
    print(f"\nSaved {PROFILE}. Each recording's similarity to your profile: {[round(x, 2) for x in scores]}")
    print("(consistent recordings score above ~0.7; add `speaker=on` to ~/.config/jmacs/voice-conversation to use it)")
    return 0


if __name__ == "__main__":
    sys.exit(enroll_main() if sys.argv[1:2] == ["enroll"] else 2)
