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


def test_right_option_tap_toggles_the_voice_mode_file(tmp_path, monkeypatch=None):
    import os
    from types import SimpleNamespace
    from mynah import listen
    old, oldlog = listen.MODE_FILE, os.environ.get("MYNAH_VOICE_MODE_LOG")
    listen.MODE_FILE = tmp_path / "cfg" / "voice-conversation"
    os.environ["MYNAH_VOICE_MODE_LOG"] = str(tmp_path / "mode.log")
    try:
        lis = SimpleNamespace(muted=True)
        speakd.toggle_voice_mode(lis)
        assert listen.MODE_FILE.exists() and lis.muted is False       # off -> on, old mute cleared
        speakd.toggle_voice_mode(lis)
        assert not listen.MODE_FILE.exists()                          # on -> off
        assert (tmp_path / "mode.log").read_text().count("source=right-option-tap") == 2
    finally:
        listen.MODE_FILE = old
        if oldlog is None:
            os.environ.pop("MYNAH_VOICE_MODE_LOG", None)
        else:
            os.environ["MYNAH_VOICE_MODE_LOG"] = oldlog


def test_sleeping_speaker_wakes_on_a_key_tap_a_reply_or_the_mode_file(tmp_path):
    import os
    from mynah import listen
    class Woke(BaseException):
        pass
    saved = (speakd.INBOX, speakd.PIDFILE, speakd._reexec, speakd.HoldToTalk, listen.MODE_FILE, listen.STATE_FILE, speakd.POLL_SECONDS)
    os.environ["MYNAH_VOICE_MODE_LOG"] = str(tmp_path / "mode.log")
    try:
        speakd.INBOX, speakd.PIDFILE = tmp_path / "inbox", tmp_path / "speakd.pid"
        listen.MODE_FILE, listen.STATE_FILE = tmp_path / "mode", tmp_path / "state"
        speakd.POLL_SECONDS = 0.001
        def boom(*a):
            raise Woke(a)
        speakd._reexec = boom
        # 1. a reply in the inbox wakes it without touching the mode
        speakd.INBOX.mkdir()
        (speakd.INBOX / "1.say").write_text("hi")
        try:
            speakd.sleep_main(); assert False
        except Woke as w:
            assert w.args[0] == () and not listen.MODE_FILE.exists()
        assert listen.STATE_FILE.read_text().strip() == "loading"          # J shows "waking up"
        (speakd.INBOX / "1.say").unlink()
        # 2. a clean tap of the key turns voice mode on and wakes
        seq = iter([False, True, True, False] + [False] * 50)
        class Key:
            def held(self): return next(seq)
        speakd.HoldToTalk = Key
        try:
            speakd.sleep_main(); assert False
        except Woke:
            pass
        assert listen.MODE_FILE.exists()
        assert "right-option-tap (wake)" in (tmp_path / "mode.log").read_text()
    finally:
        speakd.INBOX, speakd.PIDFILE, speakd._reexec, speakd.HoldToTalk, listen.MODE_FILE, listen.STATE_FILE, speakd.POLL_SECONDS = saved
        os.environ.pop("MYNAH_VOICE_MODE_LOG", None)
