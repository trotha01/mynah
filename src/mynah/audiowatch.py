"""Guards for speakd's audio output: timed stream stop, one lock for every PortAudio/CoreAudio call, a watchdog.

Why this exists (2026-11-04 pid 42270, 2026-11-05 pid 83437): speakd wedged inside CoreAudio. The sample of the first
shows one thread in stop_stream (AudioOutputUnitStop > HALB_Mutex::Lock) and the IO thread in the audio callback
(startStopCallback > AudioUnitGetProperty > recursive_mutex::lock): a lock cycle inside CoreAudio that Python cannot
break. The process then sat for hours with 11.8 GB of swapped footprint and spoke nothing. Python code cannot unwedge
CoreAudio, so the answers are: (1) never wait for it unbounded, (2) keep the evidence, (3) restart the process.

Everything here is plain Python with no macOS or MLX import, so the decisions are unit-tested on Linux
(tests/test_audiowatch.py). speakd.py only wires it in (see "audiowatch" there).
"""
import contextlib
import faulthandler
import logging
import os
import shlex
import subprocess
import threading
import time
from pathlib import Path

logger = logging.getLogger("mynah.audiowatch")

STOP_TIMEOUT = float(os.getenv("MYNAH_STOP_TIMEOUT", "3"))            # flush + stop_stream may take this long
LOCK_TIMEOUT = float(os.getenv("MYNAH_AUDIO_LOCK_TIMEOUT", "8"))      # waiting for the audio lock this long means a holder is wedged
SAY_STALE_SECONDS = float(os.getenv("MYNAH_WATCHDOG_SAY", "10"))      # an unconsumed .say this old: the main loop is stuck
MAX_UTTERANCE_SECONDS = float(os.getenv("MYNAH_MAX_UTTERANCE", "150"))  # 700 chars is about a minute of speech
CAP_GRACE_SECONDS = 10.0                                              # after the soft stop, this long before the restart
MAX_RESTARTS, RESTART_WINDOW = 5, 600.0                               # no more than this many restarts per window
RESTART_ENV = "MYNAH_WEDGE_RESTARTS"                                  # restart times, carried through exec
KILL_FALLBACK_SECONDS = 6.0
STATE_DIR = Path(os.getenv("MYNAH_STATE_DIR", str(Path.home() / ".local/state/mynah")))


# ---- bounded calls ---------------------------------------------------------------------------------------------

def run_timed(fn, timeout, name="audio-call"):
    """Run fn() on a daemon thread and wait at most `timeout` s. Returns (finished, error). A call that does not
    finish is abandoned (its thread stays stuck, which is the point: the caller can go on to recover)."""
    box = {}

    def target():
        try:
            box["result"] = fn()
        except BaseException as e:  # noqa: BLE001 - handed to the caller
            box["error"] = e

    th = threading.Thread(target=target, daemon=True, name=name)
    th.start()
    th.join(timeout)
    if th.is_alive():
        return False, None
    return True, box.get("error")


def timed_stop(player, timeout=None):
    """player.flush() and player.stop_stream() on a helper thread, bounded. True when the stream stopped. A timeout
    means CoreAudio is wedged: WEDGE.trigger() keeps the evidence and restarts the process. An error that
    stop_stream itself raised is re-raised for the caller to log."""
    def stop():
        player.flush()
        player.stop_stream()
    finished, err = run_timed(stop, STOP_TIMEOUT if timeout is None else timeout, "audio-stop")
    if not finished:
        WEDGE.trigger(f"stop_stream did not return within {STOP_TIMEOUT if timeout is None else timeout:.1f}s")
        return False
    if err is not None:
        raise err
    return True


# ---- one lock for everything that touches PortAudio ------------------------------------------------------------

AUDIO_LOCK = threading.RLock()   # re-entrant: release_mic() inside a locked section of the same thread is fine


class AudioLockTimeout(RuntimeError):
    pass


@contextlib.contextmanager
def audio_lock(what="audio", timeout=None):
    """Serialises stream stop/close, microphone open/close and PortAudio re-initialisation, so no two threads touch
    PortAudio at once (sd._terminate under another thread's stop_stream is what the old comments call a crash).
    Waiting longer than LOCK_TIMEOUT means the holder is wedged: that is treated like a stop timeout."""
    wait = LOCK_TIMEOUT if timeout is None else timeout
    if not AUDIO_LOCK.acquire(timeout=wait):
        WEDGE.trigger(f"audio lock still held after {wait:.0f}s (wanted for {what})")
        raise AudioLockTimeout(what)
    try:
        yield
    finally:
        AUDIO_LOCK.release()


def locked_call(what, fn):
    with audio_lock(what):
        return fn()


def serialized(fn, what):
    """fn wrapped so it runs under the audio lock (used for Listener.open_mic / release_mic, which live in listen.py)."""
    def wrapper(*a, **kw):
        try:
            with audio_lock(what):
                return fn(*a, **kw)
        except AudioLockTimeout:
            # the wedge is already triggered; raising would kill the listener thread (its except clause calls
            # release_mic, which would raise too), fatal when restarts are capped
            logger.error(f"{what} skipped: audio lock wedged")
            return None
    wrapper.__name__ = getattr(fn, "__name__", what)
    return wrapper


class HoldClock:
    """A Lock that remembers since when it is held (monotonic), so the watchdog can read how long an utterance has
    held the stream without taking any lock itself. Drop-in for threading.Lock as a context manager."""

    def __init__(self):
        self._lock = threading.Lock()
        self.held_since = None

    def acquire(self, blocking=True, timeout=-1):
        ok = self._lock.acquire(blocking, timeout)
        if ok:
            self.held_since = time.monotonic()
        return ok

    def release(self):
        self.held_since = None
        self._lock.release()

    __enter__ = acquire

    def __exit__(self, *exc):
        self.release()


# ---- evidence + restart ------------------------------------------------------------------------------------------

def restart_allowed(history, now, max_restarts=MAX_RESTARTS, window=RESTART_WINDOW):
    """history: wall-clock times of earlier restarts. False when a restart loop is under way (each restart reloads
    the models, so an endless loop would swap the machine to death too)."""
    return sum(1 for t in history if now - t < window) < max_restarts


def parse_history(text):
    out = []
    for part in (text or "").split(","):
        try:
            out.append(float(part))
        except ValueError:
            pass
    return out


def dump_diagnostics(reason, state_dir=None, pid=None, now=None, native=True):
    """Write every Python thread's stack to <state_dir>/speakd-wedge-<pid>-<timestamp>.txt (the next incident's
    evidence, like the 2026-11-04 `sample`). With native=True on macOS also runs `sample` (native stacks: the CoreAudio
    side, which faulthandler cannot see) and `footprint` for at most a few seconds. Returns the path, or None."""
    state_dir = Path(state_dir or STATE_DIR)
    pid = pid or os.getpid()
    now = time.time() if now is None else now
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    path = state_dir / f"speakd-wedge-{pid}-{stamp}.txt"
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            f.write(f"speakd wedge {time.strftime('%F %T', time.localtime(now))} pid {pid}\nreason: {reason}\n\n"
                    f"--- Python threads (faulthandler) ---\n")
            f.flush()
            faulthandler.dump_traceback(file=f, all_threads=True)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Could not write the wedge dump: {e}")
        return None
    if native:
        _native_evidence(pid, path.with_suffix(".sample.txt"), path.with_suffix(".footprint.txt"))
    return path


def _native_evidence(pid, sample_out, footprint_out, deadline=8.0):
    jobs = []
    for tool, args, out in (("/usr/bin/sample", [str(pid), "1", "-file", str(sample_out)], None),
                            ("/usr/bin/footprint", [str(pid)], footprint_out)):
        if not os.path.exists(tool):
            continue
        try:
            fh = open(out, "w") if out else subprocess.DEVNULL
            jobs.append((subprocess.Popen([tool, *args], stdout=fh, stderr=subprocess.STDOUT), fh))
        except OSError:
            pass
    end = time.monotonic() + deadline
    for proc, fh in jobs:
        try:
            proc.wait(max(0.1, end - time.monotonic()))
        except subprocess.TimeoutExpired:
            proc.kill()
        if fh is not subprocess.DEVNULL:
            fh.close()


def fallback_command(pid, speaker_app, python, delay=KILL_FALLBACK_SECONDS):
    """Shell line for the last resort when exec itself hangs: kill this pid, then start the speaker the way
    hooks/claude-speak Start does (the app when it is installed, else the python directly)."""
    if speaker_app and os.path.isdir(speaker_app):
        start = f"open -g {shlex.quote(str(speaker_app))}"
    else:
        start = f"cd /tmp && nohup {shlex.quote(str(python))} -m mynah.speakd >/dev/null 2>&1 </dev/null &"
    return f"sleep {delay:g}; kill -9 {int(pid)}; sleep 1; {start}"


class WedgeHandler:
    """Called when the audio device is judged wedged. Acts once per process: log, dump evidence, restart."""

    def __init__(self):
        self.restart = None          # callable(reason): replaces this process; set by speakd.main()
        self.state_dir = STATE_DIR
        self.tripped = None          # the reason of the first trigger
        self._lock = threading.Lock()
        self.dump_path = None
        self.native = True
        self.exit = os._exit         # replaced in tests

    def configure(self, restart, state_dir=None, native=True):
        self.restart, self.native = restart, native
        if state_dir is not None:
            self.state_dir = Path(state_dir)

    def trigger(self, reason):
        with self._lock:
            if self.tripped is not None:
                return False
            self.tripped = reason
        logger.error(f"AUDIO WEDGED at {time.strftime('%F %T')}: {reason}")
        # on its own thread: the caller may be the main loop, or hold locks the restart must not wait for
        threading.Thread(target=self._recover, args=(reason,), daemon=True, name="wedge-recover").start()
        return True

    def _recover(self, reason):
        self.dump_path = dump_diagnostics(reason, self.state_dir, native=self.native)
        if self.dump_path:
            logger.error(f"Wedge evidence saved to {self.dump_path} (and .sample.txt / .footprint.txt next to it)")
        history = parse_history(os.environ.get(RESTART_ENV))
        now = time.time()
        if self.restart is None:
            logger.error("No restart configured; the speaker stays wedged")
            return
        if not restart_allowed(history, now):
            # the abandoned audio-stop thread keeps PortAudio state, so staying up would only time out forever.
            # os._exit skips atexit and Pa_Terminate; hooks/claude-speak starts speakd on the next reply (no pid file).
            logger.error("Too many wedge restarts: exiting; the next reply's hook starts speakd again")
            try:
                (Path(self.state_dir) / "speakd.pid").unlink(missing_ok=True)
            except OSError:
                pass
            self.exit(1)
            return
        os.environ[RESTART_ENV] = ",".join(f"{t:.0f}" for t in [*history, now] if now - t < RESTART_WINDOW)
        logger.error("Restarting speakd")
        self.restart(reason)


WEDGE = WedgeHandler()


# ---- watchdog ----------------------------------------------------------------------------------------------------

def oldest_say_age(inbox, now):
    """Age in seconds of the oldest unconsumed .say file in the inbox, or None."""
    oldest = None
    try:
        for p in Path(inbox).glob("*.say"):
            if p.name.startswith("."):
                continue
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            oldest = m if oldest is None else min(oldest, m)
    except OSError:
        return None
    return None if oldest is None else max(0.0, now - oldest)


def watchdog_decision(say_age, paused, utterance_seconds, say_stale=SAY_STALE_SECONDS,
                      max_utterance=MAX_UTTERANCE_SECONDS, grace=CAP_GRACE_SECONDS):
    """Pure decision. Returns None (fine), "stop" (an utterance ran past its cap: cut it off), or ("restart", why).
    say_age: oldest unconsumed .say (s) or None. paused: the reply is deliberately held (a held reply also keeps new
    ones waiting in the inbox, by design). utterance_seconds: time the current utterance has held the stream,
    not counting time paused; None when nothing is speaking."""
    if utterance_seconds is not None and utterance_seconds > max_utterance + grace:
        return ("restart", f"one utterance held the audio stream for {utterance_seconds:.0f}s "
                           f"(cap {max_utterance:.0f}s and {grace:.0f}s to stop)")
    if not paused and say_age is not None and say_age > say_stale:
        return ("restart", f"a .say file has waited {say_age:.0f}s in the inbox unconsumed (limit {say_stale:.0f}s)")
    if utterance_seconds is not None and utterance_seconds > max_utterance:
        return "stop"
    return None


class Watchdog(threading.Thread):
    """Polls a speaker object (duck typed: .run_lock.held_since, .paused) and the inbox; never takes a speakd lock,
    so it still runs when everything else is stuck. `stop_speech` is called (on its own thread, bounded) for the
    soft cap; `wedge` for a restart."""

    def __init__(self, speaker, inbox, stop_speech, wedge=None, interval=1.0, started=None, clock=time.time):
        super().__init__(daemon=True, name="audio-watchdog")
        self.speaker, self.inbox, self.stop_speech = speaker, Path(inbox), stop_speech
        self.wedge = wedge or WEDGE.trigger
        self.interval, self.clock = interval, clock
        self.started = clock() if started is None else started
        self._held_key = None
        self._active = 0.0        # seconds the current utterance has held the stream, pause excluded
        self._last = None
        self._stop_sent_for = None
        self._stale_ticks = 0     # consecutive ticks that asked for a restart on a stale .say

    def tick(self):
        now = self.clock()
        held = getattr(getattr(self.speaker, "run_lock", None), "held_since", None)
        if held is None:
            self._held_key = self._last = None
            self._active, active = 0.0, None
        else:
            if held != self._held_key:
                self._held_key, self._active, self._stop_sent_for = held, 0.0, None
            if self._last is not None and not self.speaker.paused:
                self._active += max(0.0, now - self._last)
            self._last = now
            active = self._active
        age = oldest_say_age(self.inbox, now)
        if age is not None:
            age = min(age, now - self.started)   # a restart must not count the time the models were loading
        decision = watchdog_decision(age, self.speaker.paused, active)
        if decision and decision != "stop" and "unconsumed" in decision[1]:
            # a .say dropped just before system sleep ages across it: wait one more tick for the main loop to drain it
            self._stale_ticks += 1
            if self._stale_ticks < 2:
                return None
        else:
            self._stale_ticks = 0
        if decision == "stop":
            if self._stop_sent_for != self._held_key:
                self._stop_sent_for = self._held_key
                logger.error(f"Utterance past {MAX_UTTERANCE_SECONDS:.0f}s: cutting it off")
                threading.Thread(target=self.stop_speech, daemon=True, name="watchdog-stop").start()
        elif decision:
            self.wedge(decision[1])
        return decision

    def run(self):
        while True:
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Watchdog tick failed: {e}")
            time.sleep(self.interval)
