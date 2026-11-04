"""Noise gate: pause (not stop) a reply when the room is loud, resume when quiet. Synthetic frames, no models, no audio.
Run: ~/.local/share/uv/tools/mynah/bin/python -m pytest tests/test_noisepause.py  (or unittest)"""
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

_tmp = tempfile.mkdtemp(prefix="mynah-np.")
os.environ["MYNAH_VOICE_MODE_FILE"] = str(Path(_tmp) / "voice-conversation")
os.environ["MYNAH_VOICE_STATE_FILE"] = str(Path(_tmp) / "voice-state")
os.environ["MYNAH_VOICE_SETTINGS_FILE"] = str(Path(_tmp) / "voice-settings")

from mynah import listen, noisepause as npz  # noqa: E402

F, DT = npz.FRAME, npz.FRAME_S
rng = np.random.default_rng(1)


def noise(db_):
    return (rng.normal(0, 1, F) * 10 ** (db_ / 20)).astype(np.float32)


def run(gate, plan, t0=0.0):
    """plan: list of (seconds, level_dbfs, voice_prob). Returns [(t, action)]."""
    out, t = [], t0
    for secs, lv, p in plan:
        for _ in range(round(secs / DT)):
            a = gate.push(t, noise(lv), p)
            if a:
                out.append((round(t, 2), a))
            t += DT
    return out


QUIET = (-60, 0.02)


class GateTest(unittest.TestCase):
    def test_loud_noise_pauses_then_resumes_after_quiet(self):
        g = npz.NoiseGate()
        ev = run(g, [(1, *QUIET), (3, -15, 0.1), (3, *QUIET)])
        self.assertEqual([a for _, a in ev], ["pause", "resume"])
        self.assertLess(ev[0][0] - 1.0, 0.35)                      # pause within ~0.3 s of the noise start
        self.assertAlmostEqual(ev[1][0] - 4.0, npz.NOISE_QUIET, delta=0.25)

    def test_cough_or_clap_pauses_nothing(self):
        g = npz.NoiseGate()
        self.assertEqual(run(g, [(1, *QUIET), (0.1, -10, 0.3), (2, *QUIET)]), [])

    def test_short_burst_just_over_trigger_pauses_briefly(self):
        g = npz.NoiseGate()
        ev = run(g, [(0.5, *QUIET), (0.3, -10, 0.3), (3, *QUIET)])
        self.assertEqual([a for _, a in ev], ["pause", "resume"])
        self.assertGreaterEqual(ev[1][0] - ev[0][0], npz.NOISE_MIN_PAUSE)

    def test_flapping_noise_is_one_pause(self):
        g = npz.NoiseGate()
        plan = [(0.5, *QUIET)] + [(0.4, -15, 0.2), (0.6, *QUIET)] * 8 + [(3, *QUIET)]
        self.assertEqual([a for _, a in run(g, plan)], ["pause", "resume"])

    def test_voice_without_profile_that_is_long_is_not_a_command(self):
        g = npz.NoiseGate()      # no classifier: unknown speaker
        ev = run(g, [(0.5, *QUIET), (12, -25, 0.95), (3, *QUIET)])   # a TV talking for 12 s
        self.assertEqual([a for _, a in ev], ["pause", "resume"])

    def test_short_loud_speech_without_profile_is_a_command(self):
        g = npz.NoiseGate()
        ev = run(g, [(0.5, *QUIET), (2, -25, 0.95), (3, *QUIET)])
        self.assertEqual([a for _, a in ev], ["pause", "barge"])

    def test_trevor_voice_is_a_barge_in_within_about_a_second(self):
        g = npz.NoiseGate(classify=lambda a: True)
        ev = run(g, [(0.5, *QUIET), (4, -25, 0.95)])
        self.assertEqual([a for _, a in ev], ["pause", "barge"])
        self.assertLess(ev[1][0] - 0.5, 1.5)

    def test_someone_else_speaking_waits_until_they_finish(self):
        g = npz.NoiseGate(classify=lambda a: False)
        ev = run(g, [(0.5, *QUIET), (5, -25, 0.95), (3, *QUIET)])
        self.assertEqual([a for _, a in ev], ["pause", "resume"])

    def test_note_after_three_minutes_once(self):
        g = npz.NoiseGate(classify=lambda a: False)
        notes, t = 0, 0.0
        for _ in range(round(200 / DT)):
            g.push(t, noise(-15), 0.1)
            notes += g.note
            t += DT
        self.assertTrue(g.paused)                  # no timeout while it stays noisy
        self.assertEqual(notes, 1)

    def test_quiet_room_never_triggers(self):
        self.assertEqual(run(npz.NoiseGate(), [(30, -50, 0.3)]), [])


class FakeSpeaker:
    speaking, player, paused, auto_paused = True, object(), False, False
    stopped = 0

    def set_paused(self, p, auto=False):
        if p == self.paused:
            return False
        self.paused, self.auto_paused = p, p and auto
        return True

    def stop(self):
        self.stopped += 1
        self.speaking = self.paused = self.auto_paused = False

    def say(self, t):
        pass


class ListenerGlue(unittest.TestCase):
    def make(self, classify=None):
        sp = FakeSpeaker()
        l = listen.Listener(sp)
        l.mode, l.half_duplex = "echo", False
        l.gate = npz.NoiseGate(classify=classify)
        return l, sp

    def feed(self, l, plan, t0=0.0):
        t = t0
        for secs, lv, p in plan:
            for _ in range(round(secs / DT)):
                if not l.speaker.speaking:
                    return t       # the real loop only feeds the gate while a reply plays
                l.noise_step(t, noise(lv), p)
                t += DT
        return t

    def test_pause_keeps_microphone_wanted_and_state(self):
        l, sp = self.make()
        self.feed(l, [(0.2, *QUIET), (1, -15, 0.1)])
        self.assertTrue(sp.paused and sp.auto_paused and sp.stopped == 0)
        self.assertEqual(l.state, "paused-noise")
        self.assertTrue(l.mic_wanted(True))                 # microphone open during an automatic pause
        sp.auto_paused = False                              # manual pause: microphone shut as before
        self.assertFalse(l.mic_wanted(True))

    def test_resume_unpauses(self):
        l, sp = self.make()
        self.feed(l, [(0.2, *QUIET), (1, -15, 0.1), (3, *QUIET)])
        self.assertFalse(sp.paused)
        self.assertEqual(sp.stopped, 0)

    def test_trevor_stops_reply_and_opens_utterance(self):
        l, sp = self.make(classify=lambda a: True)
        self.feed(l, [(0.2, *QUIET), (3, -25, 0.95)])
        self.assertEqual(sp.stopped, 1)
        self.assertTrue(l.endpointer.in_speech)
        self.assertEqual(l.state, "hearing")

    def test_manual_pause_is_untouched(self):
        l, sp = self.make()
        sp.paused = True                                    # Right Command
        self.assertTrue(l.gate_active())                    # gate itself is only fed when the mic is open
        self.assertFalse(l.mic_wanted(True))                # ... which it is not during a manual pause
        self.assertFalse(sp.auto_paused)

    def test_gate_resets_when_a_key_tap_resumes(self):
        l, sp = self.make()
        self.feed(l, [(0.2, *QUIET), (1, -15, 0.1)])
        sp.paused = sp.auto_paused = False
        l.gate.reset() if not sp.auto_paused else None
        self.assertFalse(l.gate.paused)


if __name__ == "__main__":
    unittest.main()
