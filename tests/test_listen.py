"""Tests for the voice-conversation listener that need no microphone, speaker or model.
Run: ~/.local/share/uv/tools/mynah/bin/python -m unittest discover -s tests -v   (from the repo root)"""
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

_tmp = tempfile.mkdtemp(prefix="mynah-test.")
os.environ["MYNAH_VOICE_MODE_FILE"] = str(Path(_tmp) / "voice-conversation")
os.environ["MYNAH_VOICE_STATE_FILE"] = str(Path(_tmp) / "voice-state")

from mynah import listen  # noqa: E402

FRAME = np.zeros(listen.FRAME, dtype=np.float32)


def run(ep, probs, speaking=False):
    events = []
    for p in probs:
        events += ep.push(FRAME + 0.01, p, speaking)
    return events


class EndpointerTest(unittest.TestCase):
    def test_utterance_then_silence_ends_it(self):
        ep = listen.Endpointer(silence_seconds=0.5)
        events = run(ep, [0.0] * 5 + [0.9] * 30 + [0.0] * 40)
        self.assertEqual([e[0] for e in events], ["start", "end"])
        audio = events[1][1]
        self.assertGreater(len(audio), 30 * listen.FRAME)       # speech plus pre-roll
        self.assertLess(len(audio), 45 * listen.FRAME)          # not the whole silence

    def test_short_in_the_middle_pause_does_not_end_it(self):
        ep = listen.Endpointer(silence_seconds=0.9)
        events = run(ep, [0.9] * 10 + [0.0] * 15 + [0.9] * 10 + [0.0] * 40)
        self.assertEqual([e[0] for e in events], ["start", "end"])

    def test_blip_is_dropped(self):
        ep = listen.Endpointer(silence_seconds=0.3)
        events = run(ep, [0.9] * 4 + [0.0] * 30)
        self.assertEqual([e[0] for e in events], ["start", "drop"])

    def test_nothing_without_speech(self):
        self.assertEqual(run(listen.Endpointer(), [0.1] * 200), [])

    def test_barge_in_needs_strong_sustained_speech(self):
        ep = listen.Endpointer()
        self.assertEqual(run(ep, [0.7] * 50, speaking=True), [])            # echo-like: not strong enough
        ep.reset()
        self.assertEqual(run(ep, [0.9] * 5 + [0.0] + [0.9] * 5, speaking=True), [])  # not sustained
        ep.reset()
        events = run(ep, [0.95] * 12, speaking=True)
        self.assertEqual(events, [("start", True)])

    def test_normal_start_is_not_barge(self):
        self.assertEqual(run(listen.Endpointer(), [0.9] * 5, speaking=False), [("start", False)])

    def test_max_length_forces_an_end(self):
        ep = listen.Endpointer()
        events = run(ep, [0.9] * (ep.max_frames + 5))
        self.assertEqual([e[0] for e in events][:2], ["start", "end"])  # continued speech opens the next one


class TextTest(unittest.TestCase):
    def test_fillers_are_not_submitted(self):
        for t in ["", "  ", "Mm.", "Uh-huh.", "Um, uh", "hmm"]:
            self.assertIsNone(listen.usable_transcript(t), t)
        self.assertEqual(listen.usable_transcript(" Yes. "), "Yes.")
        self.assertEqual(listen.usable_transcript("List the todos"), "List the todos")

    def test_stop_command_matches_the_whole_utterance_only(self):
        self.assertTrue(listen.is_stop_command("Stop listening."))
        self.assertTrue(listen.is_stop_command("Voice mode off"))
        self.assertFalse(listen.is_stop_command("Please stop listening to the radio and read my todo list"))


class DeviceTest(unittest.TestCase):
    def test_headphones_vs_speakers(self):
        for name in ["External Headphones", "Trevor's AirPods Pro", "Beats Studio Buds", "USB Headset"]:
            self.assertTrue(listen.is_headphones(name), name)
        for name in ["MacBook Air Speakers", "Studio Display Speakers", "JBL Flip 6", "", None]:
            self.assertFalse(listen.is_headphones(name), name)


class FakeSpeaker:
    speaking = False
    player = None

    def __init__(self):
        self.said = []

    def say(self, t):
        self.said.append(t)

    def stop(self):
        pass


class DeliverTest(unittest.TestCase):
    def setUp(self):
        listen.MODE_FILE.unlink(missing_ok=True)
        self.sent = []
        self.speaker = FakeSpeaker()
        self.l = listen.Listener(self.speaker, submit=self.sent.append, vad=object(), stt=object())
        listen.CUES = False

    def test_mode_off_never_acts_on_speech(self):
        self.l.deliver("delete everything")
        self.l.deliver("stop listening")
        self.assertEqual(self.sent, [])

    def test_mode_on_submits(self):
        listen.MODE_FILE.touch()
        self.l.deliver("list the open todos")
        self.assertEqual(self.sent, ["list the open todos"])
        self.assertEqual(self.l.state, "waiting")

    def test_mode_switched_off_while_transcribing_discards(self):
        listen.MODE_FILE.touch()
        self.l.transcribe = lambda audio: (listen.MODE_FILE.unlink(), "do the thing")[1]  # off during the STT
        self.l.handle_utterance(np.zeros(16000, dtype=np.float32))
        self.assertEqual(self.sent, [])

    def test_spoken_stop_turns_the_mode_off_and_submits_nothing(self):
        listen.MODE_FILE.touch()
        self.l.deliver("Stop listening.")
        self.assertFalse(listen.mode_on())
        self.assertEqual(self.sent, [])

    def test_failed_submit_is_reported_aloud(self):
        listen.MODE_FILE.touch()
        def boom(_): raise RuntimeError("no tmux")
        self.l.submit = boom
        self.l.deliver("hello there")
        self.assertEqual(self.speaker.said, ["I could not send that."])

    def test_filler_is_not_submitted(self):
        listen.MODE_FILE.touch()
        self.l.deliver("Mm.")
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
