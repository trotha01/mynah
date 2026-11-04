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

from . import lipsync, viseme
from .listen import Listener, mode_on
from .transcript import strip_markdown_for_speech

MODEL_ID = os.getenv("MYNAH_MODEL", "mlx-community/Kokoro-82M-bf16")
VOICE = os.getenv("MYNAH_VOICE", "af_heart")
SPEED = float(os.getenv("MYNAH_SPEED", "1.0"))
# A long reply read in full is minutes of audio: speak the opening, point at the screen for the rest.
MAX_CHARS = int(os.getenv("MYNAH_MAX_CHARS", "700"))
INBOX = Path(os.getenv("MYNAH_INBOX", str(Path.home() / ".local/state/mynah/inbox")))
PIDFILE = INBOX.parent / "speakd.pid"  # hooks/claude-speak checks it to start this process on demand
IDLE_EXIT_SECONDS = int(os.getenv("MYNAH_IDLE_EXIT", "7200"))  # frees the model's memory when unused
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

        def callback(self, outdata, frames, time_info, status):
            if self.lipsync is not None:
                self.lipsync.on_block(frames, time_info)   # only records where the stream is (the mouth timeline)
            try:
                super().callback(outdata, frames, time_info, status)
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
        self.run_lock = threading.Lock()  # one generation at a time
        self.close_lock = threading.Lock()  # AudioPlayer.stop_stream is not thread-safe (see _close)
        self.token = 0                    # bumped by every say/stop; a stale _speak stops itself
        self.player = None
        self.speaking = False             # a reply is queued or playing (the listener reads it)
        self.listener = None              # listen.Listener: gives up the microphone before devices are refreshed

    def _chunks(self, text):
        """Yield (audio, mouth events) per chunk. Drives Kokoro's pipeline directly, so the phonemes and the per-phoneme
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
                started = True
                yield audio, events
            return
        except Exception as e:
            if started:
                raise
            logger.warning(f"Kokoro pipeline unavailable ({e}); speaking without a mouth timeline")
        for result in self._generate(text):
            yield np.asarray(result.audio, dtype=np.float32).reshape(-1), None

    def warm_up(self):
        t = time.time()
        for _ in self._generate("Ready."):
            pass
        logger.info(f"Warm-up done in {time.time() - t:.1f}s")

    def _generate(self, text):
        return self.model.generate(text=text, voice=VOICE, speed=SPEED, lang_code="a", verbose=False)

    def stop(self):
        with self.lock:
            self.token += 1
            self.speaking = False
            player = self.player
        if player is not None:
            self._close(player)  # cuts audio that is already playing

    def _close(self, player):
        """Drop what is buffered and close the stream. An interrupt and the end of the speech both do this
        from different threads, and racing in stop_stream (one sets stream to None between the other's stop
        and close) crashed the process."""
        with self.close_lock:
            try:
                lip = getattr(player, "lipsync", None)
                if lip is not None:
                    lip.stop()   # the audio is cut: the mouth must stop with it
                player.flush()
                player.stop_stream()
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
            player = tapped_player_class()(sample_rate=self.model.sample_rate)
            if self.listener is not None:
                player.tap = self.listener.aec.tap
                self.listener.aec.reset_reference()
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
                for audio, events in self._chunks(text):
                    if token != self.token:
                        break
                    if first is None:
                        first = time.time() - started
                    player.lipsync.add_chunk(len(audio), events)
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


def main():
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
    speaker = Speaker()
    speaker.warm_up()
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    faulthandler.register(signal.SIGUSR1, all_threads=True)  # kill -USR1 <pid>: every thread's stack goes to the log
    try:
        hold = HoldToTalk()
    except Exception as e:  # speaking must work without it
        logger.warning(f"Push-to-talk interrupt unavailable: {e}")
        hold = None
    listener = Listener(speaker, suspended=(hold.held if hold is not None else (lambda: False)))
    speaker.listener = listener
    listener.start()  # idle (no microphone, no models) until ~/.config/jmacs/voice-conversation exists
    logger.info(f"Ready; watching {INBOX}")
    last_activity = time.time()
    was_held = False
    spoke, press_at = False, 0.0
    while True:
        if mode_on() or any(p.suffix in (".say", ".stop") for p in INBOX.glob("*")):
            last_activity = time.time()
        elif time.time() - last_activity > IDLE_EXIT_SECONDS:
            logger.info("Idle; exiting (the next reply starts it again)")
            PIDFILE.unlink(missing_ok=True)
            return
        try:  # one bad iteration must not end the process: the hook only restarts it at the next reply
            held = hold is not None and hold.held()
            if held and not was_held:
                press_at = time.time()
                spoke = bool(speaker.speaking)
                speaker.stop()
                logger.info("Push-to-talk key down: stopped speaking")
            if was_held and not held and not spoke and time.time() - press_at < TAP_SECONDS and mode_on():
                listener.set_muted(not listener.muted)   # a short tap with nothing playing: mute / unmute
            was_held = held
            drain_inbox(speaker, quiet=held)
        except Exception as e:
            logger.error(f"Error in the main loop: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
