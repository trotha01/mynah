"""Pure-logic tests for src/mynah/audiowatch.py: fake streams that hang, threads and events. No audio, no macOS.
Run: PYTHONPATH=src python3 -m pytest tests/test_audiowatch.py -q"""
import os
import threading
import time

import pytest

from mynah import audiowatch as aw


class FakePlayer:
    def __init__(self, hang=False, error=None):
        self.hang, self.error = hang, error
        self.release = threading.Event()   # the test frees a hung stop at the end
        self.calls = []

    def flush(self):
        self.calls.append("flush")

    def stop_stream(self):
        self.calls.append("stop_stream")
        if self.error:
            raise self.error
        if self.hang:
            self.release.wait(30)          # CoreAudio's lock cycle: never returns on its own


@pytest.fixture(autouse=True)
def fresh_wedge(tmp_path):
    h = aw.WedgeHandler()
    h.state_dir = tmp_path
    h.native = False
    old = aw.WEDGE
    aw.WEDGE = h
    yield h
    aw.WEDGE = old


def wait_for(cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


# ---- timed stop
def test_run_timed_returns_result_and_error():
    assert aw.run_timed(lambda: 1, 1) == (True, None)
    ok, err = aw.run_timed(lambda: 1 / 0, 1)
    assert ok and isinstance(err, ZeroDivisionError)


def test_normal_stop_does_not_trip(fresh_wedge):
    p = FakePlayer()
    assert aw.timed_stop(p, 1.0) is True
    assert p.calls == ["flush", "stop_stream"] and fresh_wedge.tripped is None


def test_stop_stream_error_is_raised_to_the_caller(fresh_wedge):
    with pytest.raises(ValueError):
        aw.timed_stop(FakePlayer(error=ValueError("boom")), 1.0)
    assert fresh_wedge.tripped is None


def test_hung_stop_returns_at_the_timeout_and_recovers(fresh_wedge, tmp_path):
    restarted = threading.Event()
    reasons = []
    fresh_wedge.configure(lambda r: (reasons.append(r), restarted.set()), tmp_path, native=False)
    p = FakePlayer(hang=True)
    t0 = time.time()
    assert aw.timed_stop(p, 0.2) is False
    assert time.time() - t0 < 2                       # the caller was not held hostage
    assert restarted.wait(3)
    assert "stop_stream" in reasons[0]
    dumps = list(tmp_path.glob("speakd-wedge-*.txt"))
    assert len(dumps) == 1 and str(os.getpid()) in dumps[0].name
    text = dumps[0].read_text()
    assert "reason:" in text and "in stop_stream" in text   # the stuck thread's stack is in the dump
    p.release.set()


def test_wedge_acts_once(fresh_wedge, tmp_path):
    n = []
    fresh_wedge.configure(lambda r: n.append(r), tmp_path, native=False)
    assert fresh_wedge.trigger("a") is True
    assert fresh_wedge.trigger("b") is False
    assert wait_for(lambda: len(n) == 1)
    time.sleep(0.1)
    assert len(n) == 1


def test_restart_loop_is_capped(fresh_wedge, tmp_path, monkeypatch):
    now = time.time()
    monkeypatch.setenv(aw.RESTART_ENV, ",".join(str(now - i) for i in range(aw.MAX_RESTARTS)))
    n = []
    fresh_wedge.configure(lambda r: n.append(r), tmp_path, native=False)
    fresh_wedge.trigger("again")
    assert wait_for(lambda: fresh_wedge.dump_path is not None)
    time.sleep(0.2)
    assert n == []
    assert aw.restart_allowed([now - 700] * 10, now)   # old restarts do not count


def test_restart_history_is_carried_in_the_environment(fresh_wedge, tmp_path, monkeypatch):
    monkeypatch.delenv(aw.RESTART_ENV, raising=False)
    done = threading.Event()
    fresh_wedge.configure(lambda r: done.set(), tmp_path, native=False)
    fresh_wedge.trigger("x")
    assert done.wait(3)
    assert len(aw.parse_history(os.environ[aw.RESTART_ENV])) == 1


# ---- audio lock
def test_audio_lock_is_reentrant_and_serialises():
    order = []
    started = threading.Event()

    def other():
        started.set()
        with aw.audio_lock("other"):
            order.append("other")
    with aw.audio_lock("a"):
        with aw.audio_lock("nested"):
            pass
        th = threading.Thread(target=other)
        th.start()
        started.wait()
        time.sleep(0.1)
        order.append("first")
    th.join(2)
    assert order == ["first", "other"]


def test_audio_lock_held_by_a_wedged_thread_trips_the_wedge(fresh_wedge, tmp_path):
    fresh_wedge.configure(lambda r: None, tmp_path, native=False)
    held, free = threading.Event(), threading.Event()

    def holder():
        with aw.audio_lock("holder"):
            held.set()
            free.wait(10)
    th = threading.Thread(target=holder, daemon=True)
    th.start()
    held.wait()
    with pytest.raises(aw.AudioLockTimeout):
        with aw.audio_lock("close", timeout=0.2):
            pass
    assert "audio lock" in fresh_wedge.tripped
    free.set()
    th.join(2)


def test_stop_and_end_of_speech_never_overlap_in_the_stream():
    """Two threads close the same player: the stream's stop runs strictly one at a time."""
    inside, overlap = [0], []

    class P(FakePlayer):
        def stop_stream(self):
            inside[0] += 1
            overlap.append(inside[0])
            time.sleep(0.05)
            inside[0] -= 1

    p = P()

    def close():
        with aw.audio_lock("close"):
            aw.timed_stop(p, 2)
    ths = [threading.Thread(target=close) for _ in range(4)]
    [t.start() for t in ths]
    [t.join(3) for t in ths]
    assert max(overlap) == 1


def test_holdclock_tracks_when_it_is_held():
    c = aw.HoldClock()
    assert c.held_since is None
    with c:
        assert c.held_since is not None
    assert c.held_since is None


# ---- watchdog decisions
def test_decision_idle_and_fresh_say_are_fine():
    assert aw.watchdog_decision(None, False, None) is None
    assert aw.watchdog_decision(2.0, False, None) is None
    assert aw.watchdog_decision(None, False, 30.0) is None


def test_decision_stale_say_restarts_idle_or_speaking():
    assert aw.watchdog_decision(11.0, False, None)[0] == "restart"
    assert aw.watchdog_decision(11.0, False, 5.0)[0] == "restart"


def test_decision_paused_reply_keeps_say_waiting_by_design():
    assert aw.watchdog_decision(60.0, True, 5.0) is None


def test_decision_utterance_cap_stops_then_restarts():
    cap = aw.MAX_UTTERANCE_SECONDS
    assert aw.watchdog_decision(None, False, cap + 1) == "stop"
    assert aw.watchdog_decision(None, False, cap + aw.CAP_GRACE_SECONDS + 1)[0] == "restart"


class FakeSpeaker:
    def __init__(self):
        self.run_lock = aw.HoldClock()
        self.paused = False


def make_watchdog(tmp_path, clock):
    sp, stops, wedges = FakeSpeaker(), [], []
    w = aw.Watchdog(sp, tmp_path, stop_speech=lambda: stops.append(1), wedge=wedges.append, clock=clock, started=clock())
    return sp, w, stops, wedges


def test_watchdog_restarts_on_a_stale_say_file(tmp_path):
    t = [time.time()]
    sp, w, stops, wedges = make_watchdog(tmp_path, lambda: t[0])
    f = tmp_path / "1.1.say"
    f.write_text("hi")
    os.utime(f, (t[0] - 30, t[0] - 30))
    t[0] += 20                      # past the startup grace: the file really has waited
    assert w.tick()[0] == "restart" and len(wedges) == 1


def test_watchdog_ignores_files_that_waited_only_while_it_was_loading(tmp_path):
    t = [time.time()]
    sp, w, stops, wedges = make_watchdog(tmp_path, lambda: t[0])
    f = tmp_path / "1.1.say"
    f.write_text("hi")
    os.utime(f, (t[0] - 60, t[0] - 60))
    assert w.tick() is None         # the watchdog itself has run for 0 s


def test_watchdog_ignores_dot_files_and_stop_files(tmp_path):
    t = [time.time() + 100]
    sp, w, stops, wedges = make_watchdog(tmp_path, lambda: t[0])
    w.started = t[0] - 100
    for n in (".x.tmp", "1.1.stop"):
        (tmp_path / n).write_text("")
        os.utime(tmp_path / n, (0, 0))
    assert w.tick() is None


def test_watchdog_utterance_cap_excludes_paused_time(tmp_path):
    t = [1000.0]
    sp, w, stops, wedges = make_watchdog(tmp_path, lambda: t[0])
    sp.run_lock.acquire()
    w.tick()
    sp.paused = True
    for _ in range(10):
        t[0] += 100                 # 1000 s paused
        assert w.tick() is None
    sp.paused = False
    t[0] += aw.MAX_UTTERANCE_SECONDS - 10
    w.tick()
    t[0] += 5
    assert w.tick() is None         # 145 s of real speech: under the cap
    t[0] += 10
    assert w.tick() == "stop"
    assert wait_for(lambda: stops == [1])
    t[0] += 1
    w.tick()
    time.sleep(0.05)
    assert stops == [1]             # the soft stop is sent once per utterance
    t[0] += aw.CAP_GRACE_SECONDS
    assert w.tick()[0] == "restart" and wedges


def test_watchdog_new_utterance_resets_the_clock(tmp_path):
    t = [1000.0]
    sp, w, stops, wedges = make_watchdog(tmp_path, lambda: t[0])
    sp.run_lock.acquire()
    w.tick()
    t[0] += 100
    w.tick()
    sp.run_lock.release()
    w.tick()
    t[0] += 1
    sp.run_lock.acquire()
    w.tick()
    t[0] += 100
    assert w.tick() is None


def test_fallback_command_kills_then_starts():
    c = aw.fallback_command(123, "/nonexistent/App.app", "/x/python")
    assert "kill -9 123" in c and "-m mynah.speakd" in c
    c2 = aw.fallback_command(123, os.getcwd(), "/x/python")
    assert "open -g" in c2
