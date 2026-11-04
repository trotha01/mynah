from mynah import speakd


class FakeKey(speakd.PauseKey):
    def __init__(self):                      # no Quartz: flags and the last key-down time are set by the test
        self.mask, self.down_at, self.chord = 0x10, None, False
        self.flags, self.since_key = 0, 99.0
        self._flags = lambda: self.flags
        self._since_key = lambda: self.since_key


def tap(k, hold=0.1, others=0, since=99.0, now=[1000.0]):
    t = speakd.time.time
    try:
        speakd.time.time = lambda: now[0]
        k.flags, k.since_key = 0x10 | others, since
        r1 = k.poll()
        now[0] += hold
        k.flags = 0
        return r1, k.poll()
    finally:
        speakd.time.time = t


def test_a_short_clean_tap_counts_once_on_release():
    assert tap(FakeKey()) == (False, True)


def test_a_long_press_is_not_a_tap():
    assert tap(FakeKey(), hold=0.9) == (False, False)


def test_command_with_another_modifier_is_a_chord():
    assert tap(FakeKey(), others=0x8)[1] is False        # left Command held too


def test_command_used_for_a_shortcut_is_ignored():
    assert tap(FakeKey(), hold=0.2, since=0.1)[1] is False   # a key went down while it was held
    assert tap(FakeKey(), hold=0.2, since=5.0)[1] is True    # typed long before: still a tap


def test_a_player_that_is_paused_plays_silence_and_keeps_its_queue():
    import numpy as np
    from types import SimpleNamespace
    P = speakd.tapped_player_class()
    p = P.__new__(P)
    p.paused, p.tap, p.lipsync = True, None, None
    out = np.ones((8, 1), dtype=np.float32)
    p.callback(out, 8, SimpleNamespace(), None)
    assert not out.any()


def test_resume_makes_the_listener_deaf_for_a_moment():
    import threading, time
    from types import SimpleNamespace
    sp = speakd.Speaker.__new__(speakd.Speaker)
    sp.lock, sp.speaking, sp.paused = threading.Lock(), True, True
    sp.player = SimpleNamespace(paused=True)
    sp.listener = SimpleNamespace(deaf_until=0.0)
    assert sp.set_paused(False) and not sp.player.paused
    assert sp.listener.deaf_until > time.time() + 1.0
