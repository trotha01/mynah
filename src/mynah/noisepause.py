"""Automatic pause of a reply when the room is loud, instead of cancelling it (pure logic: no audio device, no model).

Fed one echo-cancelled microphone frame at a time while a reply plays (`NoiseGate.push`), it says what to do:

    None       nothing
    "pause"    hold the reply in place (the manual pause mechanism), keep the microphone open
    "resume"   the room has been quiet long enough: continue from the same word
    "barge"    what was heard is Trevor (or, without a voice profile, a clear spoken command): stop the reply

Rules (all times in seconds, each configurable through the environment or ~/.config/jmacs/voice-settings):
  trigger   at least 0.2 s (6 frames) of frames at or above noise_db (-28 dBFS after echo cancelling) within the last
            second, or voice probability >= 0.85 for 0.25 s (today's barge rule). One cough or clap is shorter than
            that and pauses nothing; clatter that adds up to 0.2 s does.
  classify  1.0 s after the pause (and again each time another 1.0 s of voice-like audio has come in, and once more
            when the quiet arrives) `classify(audio)` is asked whether it is Trevor. True -> "barge". The default
            classifier is speaker verification against the enrolment; without a profile it is None (unknown).
  resume    no noisy frame for `quiet` (1.2 s) and the pause is at least `min_pause` (0.8 s) old. Noise bursts closer
            than `quiet` are one pause (no flapping).
  unknown   without a profile nothing is ever Trevor during the noise. When the quiet arrives, speech-like audio of
            command length (0.5 s .. 8 s of voice frames, voice level >= -35 dBFS) counts as a spoken command: "barge".
            Longer speech (TV, a conversation), music and clatter are not commands: "resume".
"""
import os
from collections import deque

import numpy as np

RATE = 16000
FRAME = 512
FRAME_S = FRAME / RATE


def _f(name, default):
    return float(os.getenv(name, default))


NOISE_DB = _f("MYNAH_NOISE_DB", "-28")
NOISE_QUIET = _f("MYNAH_NOISE_QUIET", "1.2")
NOISE_MIN_PAUSE = _f("MYNAH_NOISE_MIN_PAUSE", "0.8")
NOISE_CLASSIFY = _f("MYNAH_NOISE_CLASSIFY", "1.0")
NOISE_NOTE_AFTER = _f("MYNAH_NOISE_NOTE_AFTER", "180")
NOISE_PAUSE = os.getenv("MYNAH_NOISE_PAUSE", "1") != "0"      # 0 = old behaviour (barge-in stops at once)
TRIGGER_S = 0.2
VOICE_P = 0.85          # barge-in voice probability while a reply plays
VOICE_NOISY_P = 0.5     # a frame at least this voice-like keeps the pause going
COMMAND_MIN_S, COMMAND_MAX_S, COMMAND_DB = 0.5, 8.0, -35.0


def db(a):
    return 20 * np.log10(max(float(np.sqrt(np.mean(np.square(a, dtype=np.float64)))), 1e-6)) if len(a) else -120.0


class NoiseGate:
    def __init__(self, classify=None, noise_db=NOISE_DB, quiet=NOISE_QUIET, min_pause=NOISE_MIN_PAUSE,
                 classify_after=NOISE_CLASSIFY, note_after=NOISE_NOTE_AFTER, has_profile=False):
        self.classify = classify            # audio -> True (Trevor) / False (someone else) / None (cannot tell)
        self.has_profile = has_profile
        self.noise_db, self.quiet, self.min_pause = noise_db, quiet, min_pause
        self.classify_after, self.note_after = classify_after, note_after
        self.n_trigger = max(1, round(TRIGGER_S / FRAME_S))
        self.n_voice = max(1, round(0.25 / FRAME_S))
        self.recent = deque(maxlen=round(1.0 / FRAME_S))     # 1 = this frame was loud, over the last second
        self.preroll = deque(maxlen=round(0.35 / FRAME_S))
        self.voice_run = 0
        self.reset()

    def reset(self):
        self.paused = False
        self.done = False          # a barge-in was decided; silent until reset() (the listener reads audio() first)
        self.t_pause = self.t_noisy = self.t_check = 0.0
        self.buf = []              # audio since the noise began (pre-roll included)
        self.voice_frames = 0      # voice-like frames in buf
        self.voice_since_check = 0
        self.noisy_frames = 0
        self.note_sent = False
        self.last_verdict = None
        self.events = []           # (name, t) log of what happened, for tests and diagnostics
        self.recent.clear()
        self.voice_run = 0

    # ---- helpers
    def _noisy(self, frame, prob):
        loud = db(frame) >= (self.noise_db - (6 if self.paused else 0))
        return loud or prob >= (VOICE_NOISY_P if self.paused else 1.1)

    def audio(self):
        return np.concatenate(self.buf) if self.buf else np.zeros(0, dtype=np.float32)

    def check(self, t):
        """Ask the classifier about the audio so far. True -> Trevor."""
        self.t_check, self.voice_since_check = t, 0
        if self.classify is None or self.voice_frames * FRAME_S < 0.4:
            return False
        verdict = self.classify(self.audio())
        self.last_verdict = verdict
        return verdict is True

    # ---- per frame
    def push(self, t, frame, prob):
        """t: seconds (monotonic, any origin). Returns None, "pause", "resume" or "barge"; `note` is set when the
        3-minute corner note is due (read and clear it)."""
        self.note = False
        if self.done:
            return None
        if not self.paused:
            self.recent.append(1 if db(frame) >= self.noise_db else 0)
            self.preroll.append(frame)
            self.voice_run = self.voice_run + 1 if prob >= VOICE_P else 0
            loud = sum(self.recent) >= self.n_trigger
            if loud or self.voice_run >= self.n_voice:
                self.paused, self.t_pause, self.t_noisy, self.t_check = True, t, t, t
                self.buf = list(self.preroll)
                self.voice_frames = self.voice_run
                self.voice_since_check = self.voice_run
                self.noisy_frames = 1
                self.events.append(("pause", t))
                return "pause"
            return None
        self.buf.append(frame)
        if self._noisy(frame, prob):
            self.t_noisy = t
            self.noisy_frames += 1
        if prob >= VOICE_NOISY_P:
            self.voice_frames += 1
            self.voice_since_check += 1
        if not self.note_sent and t - self.t_pause >= self.note_after:
            self.note_sent, self.note = True, True
        # Trevor? first look after classify_after of noise, then after each further classify_after of voice
        if t - self.t_pause >= self.classify_after and t - self.t_check >= self.classify_after \
                and self.voice_since_check * FRAME_S >= 0.4 and self.check(t):
            self.events.append(("barge", t))
            self.done = True
            return "barge"
        quiet_for = t - self.t_noisy
        if quiet_for >= self.quiet and t - self.t_pause >= self.min_pause:
            return self._end(t)
        return None

    def _end(self, t):
        """The quiet has come: Trevor, a spoken command (no profile), or just noise to wait out."""
        if self.check(t):
            self.events.append(("barge", t))
            self.done = True
            return "barge"
        if self.classify is None and self.is_command():
            self.events.append(("command", t))
            self.done = True
            return "barge"
        self.events.append(("resume", t))
        self.paused = False
        self.buf = []
        self.recent.clear()
        self.voice_run = 0
        return "resume"

    def is_command(self):
        a = self.audio()
        voiced = self.voice_frames * FRAME_S
        win = RATE // 2    # loudest half second, so the quiet tail does not dilute it
        loudest = max((db(a[i:i + win]) for i in range(0, max(1, len(a) - win // 2), win)), default=-120.0)
        return COMMAND_MIN_S <= voiced <= COMMAND_MAX_S and loudest >= COMMAND_DB
