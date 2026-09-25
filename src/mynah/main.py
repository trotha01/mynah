#!/usr/bin/env python3
import logging
import os
import signal
import threading

import rumps
from pynput import keyboard

from .transcript import latest_assistant_text, strip_markdown_for_speech

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("mynah")

MODEL_ID = os.getenv("MYNAH_MODEL", "mlx-community/Kokoro-82M-bf16")
VOICE = os.getenv("MYNAH_VOICE", "af_heart")
SPEED = float(os.getenv("MYNAH_SPEED", "1.0"))
HOTKEY_DISPLAY = "Right Command + Right Control"
# Right Option is parakeet-dictation's hotkey — even as part of a chord,
# holding it also fires parakeet's own listener (they're independent
# CGEventTaps, both watching every key), which fought with mynah's own
# recording. Avoid Right Option entirely rather than just requiring it
# alongside another key.
REQUIRED_KEYS = {keyboard.Key.cmd_r, keyboard.Key.ctrl_r}

exit_flag = False


def _signal_handler(signum, frame):
    global exit_flag
    logger.info("Shutdown signal received, exiting...")
    exit_flag = True
    threading.Timer(2.0, lambda: os._exit(0)).start()


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


class MynahApp(rumps.App):
    def __init__(self):
        super().__init__("🔊", quit_button=rumps.MenuItem("Quit"))

        self.status_item = rumps.MenuItem("Status: Loading model...")
        self.read_item = rumps.MenuItem("Read Latest Message", callback=self.read_latest_clicked)
        self.menu = [self.read_item, None, self.status_item]

        self.model = None
        self.speaking = False
        self.player = None
        self._speak_lock = threading.Lock()

        threading.Thread(target=self._load_model, daemon=True).start()
        threading.Thread(target=self._run_hotkey_listener, daemon=True).start()

        self.watchdog = threading.Thread(target=self._check_exit_flag, daemon=True)
        self.watchdog.start()

    def _check_exit_flag(self):
        import time
        while True:
            if exit_flag:
                rumps.quit_application()
                os._exit(0)
            time.sleep(0.2)

    def _load_model(self):
        from mlx_audio.tts.utils import load_model
        logger.info(f"Loading {MODEL_ID}...")
        self.model = load_model(MODEL_ID)
        self.status_item.title = f"Status: Ready — tap {HOTKEY_DISPLAY} to read"
        logger.info(f"Model loaded. Press {HOTKEY_DISPLAY} to read Claude's latest message.")

    # ---------------------------
    # Hotkey: a chord (both required keys held together) toggles read/stop,
    # and never blocks the tap callback (see parakeet-dictation's freeze
    # postmortem — pynput callbacks run synchronously inside a macOS
    # CGEventTap; blocking there can wedge system-wide keyboard input).
    # `triggered` guards against firing again on OS key-repeat, or on the
    # second key's own on_press, while both keys stay held — it only resets
    # once one of them is released, requiring a fresh press to fire again.
    # ---------------------------
    def _run_hotkey_listener(self):
        held = set()
        triggered = False

        def on_press(key):
            nonlocal triggered
            if key in REQUIRED_KEYS:
                held.add(key)
                if held == REQUIRED_KEYS and not triggered:
                    triggered = True
                    threading.Thread(target=self.toggle_speak, daemon=True).start()

        def on_release(key):
            nonlocal triggered
            if key in REQUIRED_KEYS:
                held.discard(key)
                triggered = False

        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            listener.join()

    def read_latest_clicked(self, sender):
        threading.Thread(target=self.toggle_speak, daemon=True).start()

    def toggle_speak(self):
        if self.speaking:
            self.stop_speaking()
        else:
            self.speak_latest()

    def stop_speaking(self):
        self.speaking = False  # makes speak_latest's generation loop break on its next check
        player = self.player
        if player is not None:
            player.flush()  # cuts audio that's already playing immediately
        self.status_item.title = "Status: Stopped"

    def speak_latest(self):
        if self.model is None:
            self.status_item.title = "Status: Still loading the model..."
            return
        if not self._speak_lock.acquire(blocking=False):
            return  # a previous speak_latest call is still winding down
        try:
            text = latest_assistant_text()
            if not text:
                self.status_item.title = "Status: No Claude message found"
                logger.warning("No assistant message found in any transcript")
                return

            spoken = strip_markdown_for_speech(text)
            preview = spoken[:60].replace("\n", " ")
            self.status_item.title = f"Status: Reading: {preview}..."
            self.title = "🔊 (Speaking)"
            logger.info(f"Reading {len(spoken)} chars: {preview}...")

            from mlx_audio.tts.audio_player import AudioPlayer
            self.player = AudioPlayer(sample_rate=self.model.sample_rate)
            self.speaking = True
            try:
                results = self.model.generate(
                    text=spoken, voice=VOICE, speed=SPEED, lang_code="a", verbose=False
                )
                for result in results:
                    if not self.speaking:
                        break  # stop_speaking() was called mid-generation
                    self.player.queue_audio(result.audio)
                if self.speaking:
                    self.player.wait_for_drain()
            finally:
                self.player.stop_stream()
                self.speaking = False
                self.player = None
                self.title = "🔊"
                self.status_item.title = f"Status: Ready — tap {HOTKEY_DISPLAY} to read"
        except Exception as e:
            logger.error(f"Error while speaking: {e}")
            self.status_item.title = f"Status: Error — {e}"
            self.speaking = False
            self.player = None
            self.title = "🔊"
        finally:
            self._speak_lock.release()


def main():
    MynahApp().run()


if __name__ == "__main__":
    main()
