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


def tapped_player_class():
    """AudioPlayer that also hands every block it plays to the echo gate (listen.Listener.gate)."""
    from mlx_audio.tts.audio_player import AudioPlayer

    class TappedPlayer(AudioPlayer):
        tap = None

        def callback(self, outdata, frames, time_info, status):
            try:
                super().callback(outdata, frames, time_info, status)
            finally:  # also when the last block ends the stream (CallbackStop)
                if self.tap is not None:
                    self.tap(outdata[:, 0])
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
                player.flush()
                player.stop_stream()
            except Exception as e:
                logger.warning(f"Closing the audio stream failed: {e}")

    def say(self, text):
        self.stop()
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
            with self.lock:
                if token != self.token:
                    self._close(player)
                    return
                self.player = player
            started = time.time()
            first = None
            try:
                for result in self._generate(text):
                    if token != self.token:
                        break
                    if first is None:
                        first = time.time() - started
                    player.queue_audio(result.audio)
                if token == self.token:
                    player.wait_for_drain()
                    time.sleep(0.15)  # the last callback is still returning; closing now races its CoreAudio stop (deadlock)
                    done = "Spoke" if token == self.token else "Interrupted"
                    logger.info(f"{done} {len(text)} chars (first audio queued after {first or 0:.2f}s)")
            except Exception as e:
                logger.error(f"Error while speaking: {e}")
            finally:
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


def main():
    INBOX.mkdir(parents=True, exist_ok=True)
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
                speaker.stop()
                logger.info("Push-to-talk key down: stopped speaking")
            was_held = held
            drain_inbox(speaker, quiet=held)
        except Exception as e:
            logger.error(f"Error in the main loop: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
