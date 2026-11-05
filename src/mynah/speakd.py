#!/usr/bin/env python3
"""Resident Kokoro speaker: reads Claude Code replies aloud as they arrive.

mynah (main.py) speaks on a hotkey and follows the iTerm2 tab. This is the hands-free half: a process
that keeps Kokoro loaded and warm (the first generation after a cold start takes ~8 s, a warm one is
well under a second to first audio) and speaks whatever a Claude Code hook drops in its inbox, so
no menu-bar app, hotkey or terminal-specific lookup is involved.

Inbox protocol (hooks/claude-speak writes it; a file appears atomically via rename):
    <time>.<pid>.say    text to speak; cuts off whatever is speaking
    <time>.<pid>.stop   stop speaking
Only the newest pending file counts: a newer one replaces older ones, and files older than
STALE_SECONDS are discarded unread (so a restart never replays old replies).
"""
import faulthandler
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import audiowatch, lipsync, viseme
from .listen import Listener, mode_on
from .transcript import strip_markdown_for_speech

MODEL_ID = os.getenv("MYNAH_MODEL", "mlx-community/Kokoro-82M-bf16")
VOICE = os.getenv("MYNAH_VOICE", "af_heart")
SPEED = float(os.getenv("MYNAH_SPEED", "1.0"))
# A long reply read in full is minutes of audio: speak the opening, point at the screen for the rest.
MAX_CHARS = int(os.getenv("MYNAH_MAX_CHARS", "700"))
INBOX = Path(os.getenv("MYNAH_INBOX", str(Path.home() / ".local/state/mynah/inbox")))
PIDFILE = INBOX.parent / "speakd.pid"  # hooks/claude-speak checks it to start this process on demand
SLEEP_AFTER_SECONDS = int(os.getenv("MYNAH_SLEEP_AFTER", "300"))  # voice mode off and nothing to say for this long: unload the models (see sleep_main)
STALE_SECONDS = 120
POLL_SECONDS = 0.1
# Hold-to-talk: Parakeet Dictation's push-to-talk key (its saved setting) stops the speech.
PARAKEET_SETTINGS = Path.home() / "Library/Application Support/parakeet-dictation/settings.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("mynah.speakd")

_URL_RE = re.compile(r"https?://\S+")
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")


def clean_for_speech(text: str) -> str:
    """strip_markdown_for_speech, then drop what is miserable to hear (URLs) and cap the length."""
    text = _URL_RE.sub("a link", strip_markdown_for_speech(text))
    if len(text) <= MAX_CHARS:
        return text
    head = text[:MAX_CHARS]
    ends = [m.end() for m in _SENTENCE_END_RE.finditer(head)]
    cut = ends[-1] if ends and ends[-1] > MAX_CHARS // 3 else len(head)
    return head[:cut].rstrip() + " The rest is on screen."


def refresh_audio_devices():
    """PortAudio snapshots the device list once and misses Bluetooth reconnects (see main.py)."""
    import sounddevice as sd
    try:
        with audiowatch.audio_lock("refresh_audio_devices"):   # never under another thread's stream stop / mic open
            sd._terminate()
            sd._initialize()
    except Exception as e:
        logger.warning(f"Could not refresh audio device list: {e}")


LEVEL_FILE = Path(os.getenv("MYNAH_LEVEL_FILE", str(Path.home() / ".local/state/mynah/voice-level")))
_level_at = 0.0


def write_level(block):
    """Publish the RMS of the block being played (for the Jmacs companion's mouth; companion/companion.lisp
    reads it). Called from the audio callback, which must stay light (file I/O there starves the mic thread and
    once deadlocked CoreAudio), so only the number is stored here; a thread writes the file. Never raises."""
    global _level_at, _level_rms
    now = time.monotonic()
    if now - _level_at < 0.03:
        return
    _level_at = now
    try:
        _level_rms = float((block.astype("float32") ** 2).mean() ** 0.5)
        _start_level_writer()
    except Exception:
        pass


_level_rms = 0.0
_level_thread = None


def _start_level_writer():
    global _level_thread
    if _level_thread is not None:
        return
    def run():
        while True:
            time.sleep(0.03)
            if time.monotonic() - _level_at > 0.1:
                continue   # nothing playing: leave the file old, which the companion reads as silence
            try:
                LEVEL_FILE.parent.mkdir(parents=True, exist_ok=True)
                LEVEL_FILE.write_text(f"{_level_rms:.4f} {time.time():.3f}\n")
            except Exception:
                pass
    _level_thread = threading.Thread(target=run, daemon=True, name="level-writer")
    _level_thread.start()


SAY_KIND_FILE = Path(os.getenv("MYNAH_SAY_KIND_FILE", str(Path.home() / ".local/state/mynah/voice-say-kind")))


def write_say_kind(text):
    """Tell the Jmacs companion whether the reply being spoken ends in a question ("question" or "statement"),
    so J can raise its brows. Only that one word is written, never the text. Never raises."""
    try:
        SAY_KIND_FILE.parent.mkdir(parents=True, exist_ok=True)
        SAY_KIND_FILE.write_text("question\n" if text.rstrip().rstrip("\"')*_ ").endswith("?") else "statement\n")
    except Exception:
        pass


def tapped_player_class():
    """AudioPlayer that also hands every block it plays to the echo gate (listen.Listener.gate)."""
    from mlx_audio.tts.audio_player import AudioPlayer

    class TappedPlayer(AudioPlayer):
        tap = None

        lipsync = None
        paused = False

        def callback(self, outdata, frames, time_info, status):
            if self.paused:
                # Paused: play silence and leave the queue alone, so resuming continues from the same sample. The mouth
                # anchor is not refreshed (the mouth closes and the sample counter holds still).
                outdata.fill(0)
                if self.tap is not None:
                    self.tap(outdata[:, 0])
                write_level(outdata[:, 0])
                return
            if self.lipsync is not None:
                self.lipsync.on_block(frames, time_info)   # only records where the stream is (the mouth timeline)
            import sounddevice as sd
            try:
                super().callback(outdata, frames, time_info, status)
                self._silent = 0
            except sd.CallbackStop:
                # AudioPlayer raises CallbackStop on an empty buffer, which makes PortAudio stop the audio unit from
                # the IO thread (startStopCallback) while _close stops it from Python: the lock cycle in
                # speakd-hang.sample. Swallow it: the stream keeps running on silence and only _close stops it.
                # mlx-audio sets drain_event from the stream's finished_callback, which now never fires, so set it
                # here, one silent block after the last real one (so the tail is not clipped by _close's abort).
                self._silent = getattr(self, "_silent", 0) + 1
                if self._silent >= 2:
                    self.drain_event.set()
            finally:  # also when the last block ends the stream (CallbackStop)
                if self.tap is not None:
                    self.tap(outdata[:, 0])
                write_level(outdata[:, 0])
    return TappedPlayer


class Speaker:
    def __init__(self):
        from mlx_audio.tts.utils import load_model
        logger.info(f"Loading {MODEL_ID}...")
        self.model = load_model(MODEL_ID)
        self.lock = threading.Lock()      # guards token and player
        self.run_lock = audiowatch.HoldClock()  # one generation at a time (the watchdog reads how long it has been held)
        self.close_lock = audiowatch.AUDIO_LOCK  # AudioPlayer.stop_stream is not thread-safe (see _close); also guards refresh/mic
        self.token = 0                    # bumped by every say/stop; a stale _speak stops itself
        self.player = None
        self.speaking = False             # a reply is queued or playing (the listener reads it)
        self.listener = None              # listen.Listener: gives up the microphone before devices are refreshed
        self.paused = False               # the reply is held (Right Command tap); the audio queue is kept

    def _chunks(self, text):
        """Yield (audio, mouth events, timed words) per chunk. Drives Kokoro's pipeline directly, so the phonemes and the per-phoneme
        durations it already computes become the mouth timeline (viseme.py); falls back to plain generate() with no
        timeline (the mouth then follows loudness) if that is not possible."""
        import numpy as np
        started = False
        try:
            pipeline = self.model._get_pipeline("a")
            pipeline.voices = {}
            for r in pipeline(text, voice=VOICE, speed=SPEED, split_pattern=r"\n+"):
                audio = np.asarray(r.audio, dtype=np.float32).reshape(-1)
                if not len(audio):
                    continue
                events = None
                try:
                    events = viseme.timeline(r.phonemes, np.asarray(r.pred_dur), self.model.vocab, audio)
                except Exception as e:
                    logger.warning(f"No mouth timeline for this chunk: {e}")
                words = None
                try:
                    words = viseme.word_timeline(getattr(r, "tokens", None), np.asarray(r.pred_dur), len(audio) / self.model.sample_rate)
                except Exception as e:
                    logger.warning(f"No word timeline for this chunk: {e}")
                started = True
                yield audio, events, words
            return
        except Exception as e:
            if started:
                raise
            logger.warning(f"Kokoro pipeline unavailable ({e}); speaking without a mouth timeline")
        for result in self._generate(text):
            yield np.asarray(result.audio, dtype=np.float32).reshape(-1), None, None

    def warm_up(self):
        t = time.time()
        for _ in self._generate("Ready."):
            pass
        logger.info(f"Warm-up done in {time.time() - t:.1f}s")

    def _generate(self, text):
        return self.model.generate(text=text, voice=VOICE, speed=SPEED, lang_code="a", verbose=False)

    def set_paused(self, paused):
        """Hold or release the reply being spoken. Returns whether the state changed (False when nothing is playing)."""
        with self.lock:
            player = self.player
            if not self.speaking or player is None or paused == self.paused:
                return False
            self.paused = paused
            player.paused = paused
        logger.info("Paused: the reply is held and the microphone is shut" if paused else "Resumed the reply")
        if not paused and self.listener is not None:
            # The microphone reopens on resume and Trevor is usually still finishing what he said to the room: that must not
            # count as barge-in and cancel the reply he just resumed (seen 2026-11-04, 1 s after a resume).
            self.listener.deaf_until = max(self.listener.deaf_until, time.time() + RESUME_GRACE_SECONDS)
        return True

    def stop(self):
        with self.lock:
            self.token += 1
            self.speaking = False
            self.paused = False
            player = self.player
        if player is not None:
            self._close(player)  # cuts audio that is already playing

    def _close(self, player):
        """Drop what is buffered and close the stream. An interrupt and the end of the speech both do this
        from different threads, and racing in stop_stream (one sets stream to None between the other's stop
        and close) crashed the process."""
        try:
            with audiowatch.audio_lock("close"):
                if getattr(player, "_mynah_closed", False):
                    return   # the other of stop() / end of speech got here first: never stop a stream twice
                player._mynah_closed = True
                lip = getattr(player, "lipsync", None)
                if lip is not None:
                    lip.stop()   # the audio is cut: the mouth must stop with it
                audiowatch.timed_stop(player)   # flush + stop_stream, bounded: a CoreAudio wedge restarts speakd
                if lip is not None:
                    lip.stop()   # a last callback may have run in between
        except Exception as e:
            logger.warning(f"Closing the audio stream failed: {e}")

    def say(self, text):
        self.stop()
        write_say_kind(text)
        with self.lock:
            token = self.token
            self.speaking = True
        threading.Thread(target=self._speak, args=(text, token), daemon=True).start()

    def _speak(self, text, token):
        try:
            self._speak_locked(text, token)
        finally:
            with self.lock:
                if token == self.token:
                    self.speaking = False  # also when starting the audio failed

    def _speak_locked(self, text, token):
        with self.run_lock:
            if token != self.token:
                return
            from mlx_audio.tts.audio_player import AudioPlayer
            if self.listener is not None:
                self.listener.release_mic()  # PortAudio cannot be re-initialised under an open input stream
            refresh_audio_devices()
            player = audiowatch.locked_call("open", lambda: tapped_player_class()(sample_rate=self.model.sample_rate))
            if self.listener is not None:
                player.tap = self.listener.aec.tap
                self.listener.aec.reset_reference()
            player.paused = False
            player.lipsync = lipsync.LipSync(self.model.sample_rate)
            lipsync.publish(player.lipsync)
            with self.lock:
                if token != self.token:
                    self._close(player)
                    return
                self.player = player
            started = time.time()
            first = None
            try:
                for audio, events, words in self._chunks(text):
                    if token != self.token:
                        break
                    if first is None:
                        first = time.time() - started
                    player.lipsync.add_chunk(len(audio), events, words)
                    player.queue_audio(audio)
                if token == self.token:
                    player.wait_for_drain()
                    time.sleep(0.15)  # the last callback is still returning; closing now races its CoreAudio stop (deadlock)
                    done = "Spoke" if token == self.token else "Interrupted"
                    logger.info(f"{done} {len(text)} chars (first audio queued after {first or 0:.2f}s)")
            except Exception as e:
                logger.error(f"Error while speaking: {e}")
            finally:
                lipsync.publish(None)
                self._close(player)
                with self.lock:
                    if self.player is player:
                        self.player = None
                    if token == self.token:
                        self.speaking = False


# Device-dependent modifier bits (IOKit NX_DEVICE*KEYMASK) in CGEventSourceFlagsState, for the names Parakeet
# Dictation saves a hotkey under. "alt" is the LEFT Option key, as in pynput; the right one is "alt_r".
_MODIFIER_FLAGS = {"ctrl": 0x1, "shift": 0x2, "shift_r": 0x4, "cmd": 0x8, "cmd_r": 0x10,
                   "alt": 0x20, "alt_r": 0x40, "ctrl_r": 0x2000}


def parakeet_flag_masks():
    """Flag bits of Parakeet Dictation's push-to-talk modifiers: its saved hotkey, Right Option by default."""
    try:
        hotkey = json.loads(PARAKEET_SETTINGS.read_text())["hotkey"]
        names = list(hotkey["modifiers"])
        if hotkey.get("key"):
            logger.warning(f"Push-to-talk key {hotkey['key']!r} is not watched, only the modifiers {names}")
    except (OSError, ValueError, KeyError, TypeError):
        names = ["alt_r"]
    return [_MODIFIER_FLAGS[n] for n in names if n in _MODIFIER_FLAGS]


class HoldToTalk:
    """Whether Trevor is holding the push-to-talk key. While he is, the speech stops and replies stay quiet:
    his microphone would hear Kokoro otherwise. It asks macOS for the keyboard's current modifier flags instead
    of listening for key events, which needs no Accessibility or Input Monitoring permission (an event tap
    does). It only works in the user's desktop (Aqua) session: under the tmux server, which runs in the
    Background session, the flags never change, so hooks/claude-speak starts this process through an app.
    CGEventSourceKeyState sees nothing even there; only the flags do (checked with the real key, macOS 26)."""

    def __init__(self):
        from Quartz import CGEventSourceFlagsState, kCGEventSourceStateHIDSystemState
        self._flags = lambda: CGEventSourceFlagsState(kCGEventSourceStateHIDSystemState)
        self.masks = parakeet_flag_masks()
        domain = subprocess.run(["launchctl", "managername"], capture_output=True, text=True).stdout.strip()
        logger.info(f"Push-to-talk flag bits {[hex(m) for m in self.masks]} stop the speech (launchd session: {domain})")
        if domain != "Aqua":
            logger.warning("Not in the desktop (Aqua) session: the push-to-talk key cannot be seen from here")

    def held(self):
        flags = self._flags()
        return bool(self.masks) and all(flags & mask for mask in self.masks)


class PauseKey:
    """Tap of the pause key (Right Command by default, MYNAH_PAUSE_KEY=cmd_r|shift_r|ctrl_r) pauses the reply being spoken, and
    the next tap resumes it. Like HoldToTalk it only sees modifier flags. A Command press used in a shortcut (any key went
    down while it was held) is not a tap: CGEventSourceSecondsSinceLastEventType tells when the last key went down."""

    def __init__(self):
        from Quartz import (CGEventSourceFlagsState, CGEventSourceSecondsSinceLastEventType,
                            kCGEventSourceStateHIDSystemState, kCGEventKeyDown)
        name = os.getenv("MYNAH_PAUSE_KEY", "cmd_r")
        self.mask = _MODIFIER_FLAGS.get(name, 0x10)
        self._flags = lambda: CGEventSourceFlagsState(kCGEventSourceStateHIDSystemState)
        self._since_key = lambda: CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateHIDSystemState, kCGEventKeyDown)
        self.down_at = None
        logger.info(f"Pause key: {name} (flag {hex(self.mask)}), tap pauses / resumes the reply")

    def poll(self):
        """True once, when a clean tap of the key has just ended."""
        flags = self._flags()
        down = bool(flags & self.mask)
        others = flags & 0xFF & ~self.mask & 0x7F                  # another modifier held with it: a chord, not a tap
        now = time.time()
        if down and self.down_at is None:
            self.down_at = now
            self.chord = bool(others)
        elif down:
            self.chord = self.chord or bool(others)
        elif self.down_at is not None:
            held, self.down_at = now - self.down_at, None
            try:
                key_during = self._since_key() < held + 0.05   # a real key went down while it was held
            except Exception:
                key_during = False
            return held < TAP_SECONDS and not self.chord and not key_during
        return False

    chord = False


def drain_inbox(speaker, quiet=False):
    """Apply the newest pending inbox file: a say, or a stop. Everything older is dropped.
    quiet: take the files but do not speak (Trevor is talking)."""
    now = time.time()
    action = None
    for path in sorted(INBOX.glob("*")):
        if path.name.startswith(".") or path.suffix not in (".say", ".stop"):
            continue
        try:
            fresh = now - path.stat().st_mtime < STALE_SECONDS
            text = path.read_text(errors="replace") if fresh and path.suffix == ".say" else ""
            path.unlink(missing_ok=True)
        except OSError:
            continue
        if fresh:
            action = ("stop", "") if path.suffix == ".stop" else ("say", text)
    if action is None:
        return
    if action[0] == "stop":
        speaker.stop()
        logger.info("Stopped")
        return
    spoken = clean_for_speech(action[1])
    if quiet:
        logger.info("Push-to-talk key held: reply not spoken")
    elif spoken:
        logger.info(f"Speaking {len(spoken)} chars: {spoken[:60]!r}")
        speaker.say(spoken)


RESUME_GRACE_SECONDS = float(os.getenv("MYNAH_RESUME_GRACE", "2.5"))   # after a resume the mic hears nothing for this long
def toggle_voice_mode(listener):
    """Tap of the push-to-talk key (Right Option): switch voice mode off if it is on, on if it is off. The mode is the file
    listen.MODE_FILE (hooks/voice-mode does the same with `on` / `off`); the listener running in this process sees the file
    change, announces it and opens or closes the microphone. Trevor pressed the key, so this is the one place besides
    `voice-mode on --yes` where the mode is turned on; the log line says which key did it."""
    from .listen import MODE_FILE
    on = mode_on()
    try:
        log = Path(os.getenv("MYNAH_VOICE_MODE_LOG", str(Path.home() / ".local/state/mynah/voice-mode.log")))
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as f:
            f.write(f"{time.strftime('%F %T')} {'off' if on else 'on'} source=right-option-tap\n")
        if on:
            MODE_FILE.unlink(missing_ok=True)
        else:
            listener.muted = False          # an old mute must not survive into the new session
            MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
            MODE_FILE.touch()
        logger.info(f"Key tap: voice mode {'off' if on else 'on'}")
    except OSError as e:
        logger.error(f"Key tap could not switch voice mode: {e}")


TAP_SECONDS = 0.5   # a press shorter than this is a tap (mute toggle); longer is hold-to-talk


def wire_model_memory():
    """Keep the models' GPU buffers resident. With ~16 GB shared by many Claude sessions and browsers macOS swapped
    the idle weights out and the next transcription took 15-30 s to read them back (measured 2026-11-04); a
    keep-warm loop alone was not enough. MLX can wire its buffers (residency set) up to a limit; MYNAH_WIRED_GB."""
    try:
        import mlx.core as mx
        gb = float(os.getenv("MYNAH_WIRED_GB", "4"))
        old = mx.set_wired_limit(int(gb * 2**30))
        logger.info(f"MLX wired memory limit {gb:.1f} GB (was {old / 2**30:.1f} GB)")
    except Exception as e:
        logger.warning(f"Could not set the MLX wired limit: {e}")


def _restart_after_wedge(reason):
    """audiowatch.WEDGE.restart: replace this process with a fresh speakd. exec keeps the pid, so the applet and the
    shell that started it (still alive in the 2026-11-05 sample: bash [42269]; the earlier recovery had to kill the applet
    and its sh) stay its parent and nothing new is orphaned. The pid file holds our own pid, which the new image would read as "Already running": drop it.
    If exec itself hangs, a detached shell kills this pid and starts the speaker the way `claude-speak Start` does."""
    PIDFILE.unlink(missing_ok=True)
    write_state("loading")
    app = os.getenv("MYNAH_SPEAKER_APP", str(Path.home() / ".local/share/mynah/Mynah Speaker.app"))
    python = Path.home() / ".local/share/uv/tools/mynah/bin/python"
    cmd = audiowatch.fallback_command(os.getpid(), app, os.getenv("MYNAH_PYTHON", str(python)))
    def last_resort():
        logger.error("exec did not replace the process: killing it from a detached shell and starting it again")
        subprocess.Popen(["/bin/sh", "-c", cmd], start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    timer = threading.Timer(audiowatch.KILL_FALLBACK_SECONDS - 1, last_resort)
    timer.daemon = True
    timer.start()
    _reexec()


def _reexec(*args):
    """Replace this process with a fresh `python -m mynah.speakd` (same pid, same desktop session, so the key watcher keeps
    working). This is how the models are unloaded (sleep) and loaded again (wake): a new process image frees all of the old one."""
    logging.shutdown()
    os.execv(sys.executable, [sys.executable, "-m", "mynah.speakd", *args])


def write_state(state):
    from .listen import STATE_FILE
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(state + "\n")
    except OSError:
        pass


def sleep_main():
    """Voice mode is off and has been for a while: hold no models (about 3.6 GB went back to the system) and only watch the
    push-to-talk key and the inbox. A tap of the key turns voice mode on and loads everything again (J shows "waking up"
    while it does); so does a reply arriving for the speaker, or `voice-mode on`."""
    INBOX.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()))
    write_state("off")
    try:
        hold = HoldToTalk()
    except Exception as e:
        logger.warning(f"Push-to-talk key unavailable while asleep: {e}")
        hold = None
    logger.info(f"Asleep: no models loaded; a tap of the push-to-talk key, a reply or `voice-mode on` wakes it ({os.getpid()})")
    was_held, press_at = False, 0.0
    while True:
        try:
            held = hold is not None and hold.held()
            if held and not was_held:
                press_at = time.time()
            if was_held and not held and time.time() - press_at < TAP_SECONDS:
                wake(key=True)
            was_held = held
            if mode_on() or any(p.suffix in (".say", ".stop") for p in INBOX.glob("*")):
                wake()
        except Exception as e:
            logger.error(f"Error while asleep: {e}")
        time.sleep(POLL_SECONDS)


def wake(key=False):
    from .listen import MODE_FILE
    write_state("loading")           # J shows "waking up..." from this moment until the listener is ready
    if key:
        try:
            log = Path(os.getenv("MYNAH_VOICE_MODE_LOG", str(Path.home() / ".local/state/mynah/voice-mode.log")))
            with log.open("a") as f:
                f.write(f"{time.strftime('%F %T')} on source=right-option-tap (wake)\n")
            MODE_FILE.parent.mkdir(parents=True, exist_ok=True)
            MODE_FILE.touch()
        except OSError as e:
            logger.error(f"Key tap could not switch voice mode on: {e}")
    logger.info("Waking up: loading the models" + (" (voice mode on by key tap)" if key else ""))
    _reexec()


def main():
    if "--sleep" in sys.argv:
        return sleep_main()
    INBOX.mkdir(parents=True, exist_ok=True)
    wire_model_memory()
    # The hook starts this process when it is not running and drops the reply that triggered the start in
    # the inbox, so files that are still fresh must survive the warm-up; stale ones are dropped unread.
    try:  # two hooks firing together may both start one: the later one backs off
        os.kill(int(PIDFILE.read_text()), 0)
        logger.info("Already running")
        return
    except (OSError, ValueError):
        pass
    PIDFILE.write_text(str(os.getpid()))
    if mode_on():
        write_state("loading")       # J: "waking up..." while the models load
    speaker = Speaker()
    speaker.warm_up()
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    faulthandler.register(signal.SIGUSR1, all_threads=True)  # kill -USR1 <pid>: every thread's stack goes to the log
    try:
        hold = HoldToTalk()
    except Exception as e:  # speaking must work without it
        logger.warning(f"Push-to-talk interrupt unavailable: {e}")
        hold = None
    try:
        pause_key = PauseKey()
    except Exception as e:
        logger.warning(f"Pause key unavailable: {e}")
        pause_key = None
    listener = Listener(speaker, suspended=(hold.held if hold is not None else (lambda: False)))
    speaker.listener = listener
    # Wedge recovery (src/mynah/audiowatch.py): timed stream stop, one lock for PortAudio, a watchdog on the inbox.
    audiowatch.WEDGE.configure(restart=_restart_after_wedge, state_dir=INBOX.parent)
    listener.open_mic = audiowatch.serialized(listener.open_mic, "open_mic")
    listener.release_mic = audiowatch.serialized(listener.release_mic, "release_mic")
    listener.start()  # idle (no microphone, no models) until ~/.config/jmacs/voice-conversation exists
    audiowatch.Watchdog(speaker, INBOX, stop_speech=speaker.stop).start()
    logger.info(f"Ready; watching {INBOX}")
    last_activity = time.time()
    was_held = False
    spoke, press_at = False, 0.0
    while True:
        if mode_on() or any(p.suffix in (".say", ".stop") for p in INBOX.glob("*")):
            last_activity = time.time()
        elif time.time() - last_activity > SLEEP_AFTER_SECONDS:
            logger.info("Idle with voice mode off: unloading the models (a key tap, a reply or `voice-mode on` loads them again)")
            speaker.stop()
            listener.release_mic()
            _reexec("--sleep")
        try:  # one bad iteration must not end the process: the hook only restarts it at the next reply
            held = hold is not None and hold.held()
            if held and not was_held:
                press_at = time.time()
                spoke = bool(speaker.speaking)
                speaker.stop()
                logger.info("Push-to-talk key down: stopped speaking")
            if was_held and not held and not spoke and time.time() - press_at < TAP_SECONDS:
                toggle_voice_mode(listener)   # a short tap with nothing playing: voice mode off / on
            was_held = held
            if pause_key is not None and pause_key.poll() and not held:
                if speaker.paused:
                    speaker.set_paused(False)
                elif speaker.speaking:
                    speaker.set_paused(True)
            if not speaker.paused:   # a paused reply keeps new replies waiting in the inbox until it is resumed
                drain_inbox(speaker, quiet=held)
        except Exception as e:
            logger.error(f"Error in the main loop: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
