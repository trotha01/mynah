"""Voice-conversation mode: listen for Trevor, notice when he stops talking, transcribe, submit.

Runs inside speakd (same process as Kokoro, so it knows exactly when a reply is being spoken). The mode is
switched by one file, ~/.config/jmacs/voice-conversation (hooks/voice-mode on|off). While it does not exist
the microphone is not open at all and nothing here can act on speech. While it exists:

    listening -> (speech starts) hearing -> (about SILENCE_SECONDS of silence) transcribing
              -> `jmacs ask "<text>"` -> waiting -> (the Stop hook drops the reply) speaking -> listening

Pieces, all local: Silero VAD (mlx-audio) frame by frame, Parakeet TDT 0.6B v3 (mlx-audio) on the finished
utterance, sounddevice for the microphone.

Barge-in. The microphone stays open while a reply is spoken and sustained speech on top of it (a stricter
threshold) stops the reply and becomes the next utterance. With headphones (output device named headphones,
AirPods, ...) the microphone signal is used as is. On speakers (the laptop's, or any unknown output) it first goes
through WebRTC's AEC3 echo canceller (aec.py) fed with everything mynah plays; without that Kokoro barges in on
its own reply within a second (measured). `barge_in=voice|echo|key` in the mode file overrides the choice; `key`
shuts the microphone during replies and leaves the push-to-talk key (hold right Option) as the only interruption.
"""
import logging
import os
import queue
import re
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

from .aec import EchoCanceller

logger = logging.getLogger("mynah.listen")

SAMPLE_RATE = 16000
FRAME = 512                                  # Silero's window: 32 ms at 16 kHz
FRAME_SECONDS = FRAME / SAMPLE_RATE

SETTINGS_FILE = Path(os.getenv("MYNAH_VOICE_SETTINGS_FILE", str(Path.home() / ".config/jmacs/voice-settings")))
MODE_FILE = Path(os.getenv("MYNAH_VOICE_MODE_FILE", str(Path.home() / ".config/jmacs/voice-conversation")))
STATE_FILE = Path(os.getenv("MYNAH_VOICE_STATE_FILE", str(Path.home() / ".local/state/mynah/voice-state")))
JMACS = os.getenv("MYNAH_JMACS", str(Path.home() / ".local/bin/jmacs"))
VAD_MODEL = os.getenv("MYNAH_VAD_MODEL", "mlx-community/silero-vad")
STT_MODEL = os.getenv("MYNAH_STT_MODEL", "mlx-community/parakeet-tdt-0.6b-v3")
SILENCE_SECONDS = float(os.getenv("MYNAH_SILENCE", "0.9"))      # quiet this long = he is done
THRESHOLD = float(os.getenv("MYNAH_VAD_THRESHOLD", "0.5"))      # speech probability that counts as speech
WARM_SECONDS = float(os.getenv("MYNAH_WARM_SECONDS", "3.0"))   # idle time between model warm-ups
# Memory knobs (all default to the old behaviour). Settings file lines of the same name win over the env var.
#   unload_on_off=1   (MYNAH_UNLOAD_ON_OFF) drop STT / VAD / voiceprint models the moment voice mode is turned off,
#                     instead of holding them until speakd's idle exit. Kokoro stays; turning the mode on reloads (logged).
#   stt_model=<id>    (MYNAH_STT_MODEL) the speech-to-text model; see docs/voice-memory.md for candidates.
#   clear_cache=1     (MYNAH_CLEAR_CACHE) hand MLX's buffer cache back to the system after each utterance.
UNLOAD_ON_OFF = os.getenv("MYNAH_UNLOAD_ON_OFF", "0") == "1"
CLEAR_CACHE = os.getenv("MYNAH_CLEAR_CACHE", "0") == "1"
BARGE_THRESHOLD = float(os.getenv("MYNAH_BARGE_THRESHOLD", "0.85"))  # stricter while a reply is playing
MIN_SPEECH_SECONDS = 0.25                    # shorter blips (clicks, a cough) are dropped
BARGE_SPEECH_SECONDS = 0.25                  # sustained speech over a reply before it is cut off
START_SECONDS = 0.1                          # sustained speech that opens an utterance
PREROLL_SECONDS = 0.35                       # audio kept from before the VAD noticed the speech
MAX_UTTERANCE_SECONDS = 90.0
SPEAKER_TAIL_SECONDS = 0.5                   # half-duplex: keep the mic shut while the room still rings
SPEAKER_THRESHOLD = 0.5   # cosine similarity to Trevor's voiceprint (speaker_id.py)
CUES = os.getenv("MYNAH_CUES", "1") != "0"
# Utterances quieter than this (dBFS, RMS of the speech) are far-away voices, a TV, the next room: ignored.
MIN_LEVEL_DB = float(os.getenv("MYNAH_MIN_LEVEL_DB", "-40"))

_FILLER_RE = re.compile(r"^(m+h*m*|h+m+|u+h+|u+m+|a+h+|o+h+|e+h+|e+r+|h+u+h+|mhm+|uhhuh|mmhmm+|the|a)$")
_STOP_PHRASES = {"stop listening", "voice mode off", "turn off voice mode", "turn voice mode off",
                 "stop voice mode", "end voice mode", "stop the voice mode", "exit voice mode"}


def mode_on():
    return MODE_FILE.exists()


def mode_settings():
    """Optional `name=value` lines in ~/.config/jmacs/voice-settings (read each time the mode is switched on):
    min_level_db=-35, silence=1.2, barge_in=voice|echo|key, speaker=on, speaker_threshold=0.5,
    stt_model=<hf id>, unload_on_off=1, clear_cache=1, sleep_after=<seconds> (speakd's idle unload).
    A separate file, because switching the mode off deletes the mode file."""
    out = {}
    for path in (MODE_FILE, SETTINGS_FILE):   # the mode file's own lines still work (older setups)
        try:
            for line in path.read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    out[k.strip()] = v.strip()
        except OSError:
            pass
    return out


def clear_mlx_cache():
    """Give MLX's buffer cache (freed-but-kept GPU buffers) back to the system. Never raises; a no-op without MLX."""
    try:
        import gc
        import mlx.core as mx
        gc.collect()
        (getattr(mx, "clear_cache", None) or mx.metal.clear_cache)()
    except Exception as e:
        logger.warning(f"Could not clear the MLX cache: {e}")


def normalize(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]+", "", text.lower().replace("-", ""))).strip()


def usable_transcript(text):
    """The text to submit, or None when it is empty or only a filler the model made out of noise."""
    text = (text or "").strip()
    words = normalize(text).split()
    if not words or all(_FILLER_RE.match(w.replace("'", "")) for w in words):
        return None
    return text


_WAKE_PREFIX = {"hey", "hi", "ok", "okay", "oh", "um", "uh", "so"}


def addressed_to_alexa(text):
    """True when the transcript starts by calling an Alexa/Echo (Trevor talks to his speaker too, and Alexa
    commands must not reach the orchestrator). Fuzzy on the first word because Parakeet mishears the name
    ("Luxa", "Alexis", "Lexa", "A Lexa", "Alexa,"); an optional "hey"/"okay" before it is skipped."""
    from difflib import SequenceMatcher
    words = normalize(text).split()
    while words and words[0] in _WAKE_PREFIX:
        words = words[1:]
    if not words:
        return False
    candidates = [words[0]]
    if len(words) > 1 and len(words[0]) <= 2:
        candidates.append(words[0] + words[1])      # "a lexa"
    for w in candidates:
        if w in ("echo", "eko", "eco"):
            return True
        if 3 <= len(w) <= 7 and SequenceMatcher(None, w, "alexa").ratio() >= 0.66:
            return True
    return False


def level_db(audio):
    """RMS level of the loudest half-second-ish part of the utterance, in dBFS (so pauses do not dilute it)."""
    if audio.size == 0:
        return -120.0
    win = SAMPLE_RATE // 2
    chunks = [audio[i:i + win] for i in range(0, max(1, audio.size - win // 2), win)]
    rms = max(float(np.sqrt(np.mean(c.astype(np.float64) ** 2))) for c in chunks)
    return 20 * np.log10(max(rms, 1e-6))


def is_stop_command(text):
    return normalize(text) in _STOP_PHRASES


class Endpointer:
    """Frame-by-frame utterance boundaries from VAD probabilities (pure: no model, no audio device).

    push(frame, prob, speaking) returns a list of events:
        ("start", barge)   speech opened an utterance; barge is True when it began over a spoken reply
        ("end", audio)     the utterance is over; audio is float32 16 kHz (pre-roll included)
        ("drop", None)     it was too short to be speech
    While `speaking` (a reply is playing) the stricter BARGE_THRESHOLD and BARGE_SPEECH_SECONDS apply to
    opening an utterance; once open, the normal threshold (with hysteresis) decides when it ends."""

    def __init__(self, silence_seconds=SILENCE_SECONDS, threshold=THRESHOLD, barge_threshold=BARGE_THRESHOLD):
        self.threshold = threshold
        self.barge_threshold = barge_threshold
        self.neg_threshold = max(threshold - 0.15, 0.1)
        self.silence_frames = max(1, round(silence_seconds / FRAME_SECONDS))
        self.start_frames = max(1, round(START_SECONDS / FRAME_SECONDS))
        self.barge_frames = max(1, round(BARGE_SPEECH_SECONDS / FRAME_SECONDS))
        self.min_speech_frames = max(1, round(MIN_SPEECH_SECONDS / FRAME_SECONDS))
        self.max_frames = round(MAX_UTTERANCE_SECONDS / FRAME_SECONDS)
        self.preroll = deque(maxlen=round(PREROLL_SECONDS / FRAME_SECONDS))
        self.reset()

    def reset(self):
        self.preroll.clear()
        self.in_speech = False
        self.run = 0            # consecutive speech frames while idle
        self.frames = []        # the open utterance
        self.silence = 0
        self.speech_frames = 0

    def push(self, frame, prob, speaking=False):
        events = []
        if not self.in_speech:
            threshold = self.barge_threshold if speaking else self.threshold
            need = self.barge_frames if speaking else self.start_frames
            self.run = self.run + 1 if prob >= threshold else 0
            self.preroll.append(frame)
            if self.run >= need:
                self.in_speech = True
                self.frames = list(self.preroll)   # echo-cancelled already, so the pre-roll is clean
                self.speech_frames = self.run
                self.silence = 0
                events.append(("start", speaking))
            return events
        self.frames.append(frame)
        if prob >= self.neg_threshold:
            self.silence = 0
            self.speech_frames += 1
        else:
            self.silence += 1
        if self.silence >= self.silence_frames or len(self.frames) >= self.max_frames:
            keep = self.frames[: len(self.frames) - max(0, self.silence - 2)]  # drop most of the trailing quiet
            speech = self.speech_frames
            self.reset()
            if speech < self.min_speech_frames:
                events.append(("drop", None))
            else:
                events.append(("end", np.concatenate(keep)))
        return events


_HEADPHONES_RE = re.compile(r"headphone|airpods|earpods|earbuds|buds|headset|beats|powerbeats|earphone|in-ear", re.I)


def is_headphones(device_name):
    """True for outputs that cannot feed back into the microphone. Anything unknown (the laptop's speakers,
    an external or Bluetooth speaker, a display) counts as speakers, the safe side: Kokoro would barge in on itself."""
    return bool(_HEADPHONES_RE.search(device_name or ""))


def current_output_name():
    import sounddevice as sd
    try:
        return sd.query_devices(sd.default.device[1])["name"]
    except Exception:
        return None


def output_is_headphones():
    import sounddevice as sd
    try:
        name = sd.query_devices(sd.default.device[1])["name"]
    except Exception as e:
        logger.warning(f"Cannot tell the output device ({e}); assuming speakers")
        return False
    logger.info(f"Output device: {name}")
    return is_headphones(name)


def submit_text(text):
    env = dict(os.environ)
    env.setdefault("PATH", "/usr/bin:/bin:/opt/homebrew/bin")
    r = subprocess.run([JMACS, "ask", text], capture_output=True, text=True, timeout=15, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"jmacs ask failed ({r.returncode}): {(r.stdout + r.stderr).strip()}")


def play_cue(name):
    if CUES:
        subprocess.Popen(["afplay", f"/System/Library/Sounds/{name}.aiff"], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class Listener(threading.Thread):
    """The hands-free loop. `speaker` needs: .speaking (bool), .say(text), .stop(). `suspended()` is True while
    the push-to-talk key is held (Dictation owns the microphone then)."""

    def __init__(self, speaker, suspended=lambda: False, submit=submit_text, vad=None, stt=None):
        super().__init__(daemon=True, name="listener")
        self.speaker = speaker
        self.suspended = suspended
        self.submit = submit
        self.vad = vad
        self.stt = stt
        self.stt_model = STT_MODEL    # the id to load; apply_settings may change it
        self.stt_loaded = None        # the id self.stt was loaded from (None: injected or not loaded)
        self.unload_on_off = UNLOAD_ON_OFF
        self.clear_cache = CLEAR_CACHE
        self.stream = None
        self.stream_lock = threading.Lock()
        self.frames = queue.Queue(maxsize=400)
        self.endpointer = Endpointer()
        self.min_level_db = MIN_LEVEL_DB
        self.speaker_check = False
        self.speaker_threshold = SPEAKER_THRESHOLD
        self.verifier = None
        self.barge_in = os.getenv("MYNAH_BARGE_IN")
        self.vad_state = None
        self.state = "off"
        self.half_duplex = None       # key barge-in: mic shut while a reply plays. Decided per reply
        self.mode = None              # key | voice (headphones) | echo (speakers, echo-cancelled)
        self.aec = EchoCanceller()
        self.output_name = None
        self.gate_mode = None
        self.gate_until = 0.0
        self.idle_state = "listening"
        self.was_speaking = False
        self.deaf_until = 0.0
        self.mic_not_before = 0.0     # half-duplex: the mic stays shut a moment after a reply ends
        self.active = time.time()     # last moment the mode was on; speakd uses it to stay alive

    # ---- state shown by `hooks/voice-mode status`
    def set_state(self, state):
        if self.muted and state not in ("off", "loading"):
            # the companion shows "muted" even while a reply speaks: "muted" alone, or "<state>-muted"
            state = "muted" if state in ("listening", "hearing", "muted") else state + "-muted"
        if state != self.state:
            self.state = state
            try:
                STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
                STATE_FILE.write_text(state + "\n")
            except OSError:
                pass

    # ---- microphone
    def _callback(self, indata, frames, time_info, status):
        try:
            self.frames.put_nowait((time.perf_counter(), indata[:, 0].copy()))
        except queue.Full:
            pass

    def open_mic(self):
        with self.stream_lock:
            if self.stream is not None:
                return
            import sounddevice as sd
            self.drain_frames()
            self.endpointer.reset()
            self.vad_state = self.vad.initial_state(sample_rate=SAMPLE_RATE)
            self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=FRAME,
                                         callback=self._callback)
            self.stream.start()
            logger.info(f"Microphone open ({sd.query_devices(sd.default.device[0])['name']})")

    def release_mic(self):
        """Close the microphone. Speaker calls this before it refreshes PortAudio's device list.
        PortAudio's stop() can hang for good inside CoreAudio (seen 2026-11-04 16:18: every reply thread queued
        behind it, the state stuck at 'speaking', the process dead). So it runs on a helper thread that is given
        2 s; a stream that will not stop is abandoned (its callback goes quiet) instead of freezing everything."""
        with self.stream_lock:
            stream, self.stream = self.stream, None
        if stream is not None:
            def close():
                try:
                    stream.stop()
                    stream.close()
                except Exception as e:
                    logger.warning(f"Closing the microphone failed: {e}")
            th = threading.Thread(target=close, daemon=True, name="mic-close")
            th.start()
            th.join(2.0)
            if th.is_alive():
                logger.error("Closing the microphone hung (CoreAudio); abandoning that stream")
            else:
                logger.info("Microphone closed")
        self.drain_frames()
        self.endpointer.reset()

    def drain_frames(self):
        try:
            while True:
                self.frames.get_nowait()
        except queue.Empty:
            pass

    # ---- models
    def unload_models(self):
        """Drop the STT, VAD and voiceprint models and return their memory (voice mode is off, so nothing needs them).
        Kokoro belongs to the speaker and stays. The next load_models reads the weights back from the disk cache."""
        had = self.stt is not None or self.vad is not None or self.verifier is not None
        self.stt = self.vad = self.verifier = None
        self.stt_loaded = None
        self.vad_state = None
        if had:
            clear_mlx_cache()
            logger.info("Voice models unloaded (STT, VAD, voiceprint)")

    def load_models(self):
        t0 = time.time()
        if self.stt is not None and self.stt_loaded not in (None, self.stt_model):
            logger.info(f"STT model changed to {self.stt_model}: reloading")
            self.stt = None
        if self.vad is None:
            from mlx_audio.vad.utils import load_model as load_vad
            self.vad = load_vad(VAD_MODEL)
        if self.stt is None:
            from mlx_audio.stt.utils import load_model as load_stt
            self.stt = load_stt(self.stt_model)
            self.stt_loaded = self.stt_model
            self.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32))  # warm up
        if self.speaker_check and self.verifier is None:
            from .speaker_id import SpeakerVerifier
            self.verifier = SpeakerVerifier()
            if self.verifier.enrolled:
                self.verifier._load()
                self.verifier.embed(np.zeros(SAMPLE_RATE, dtype=np.float32))  # warm up
        logger.info(f"Voice models ready in {time.time() - t0:.1f}s (STT {self.stt_model})")

    def speech_probability(self, frame):
        import mlx.core as mx
        prob, self.vad_state = self.vad.feed(frame, self.vad_state, sample_rate=SAMPLE_RATE)
        mx.eval(prob)
        return float(np.array(prob).reshape(-1)[0])

    def transcribe(self, audio):
        import mlx.core as mx
        return self.stt.generate(mx.array(audio.astype(np.float32))).text

    # ---- one utterance
    def handle_utterance(self, audio):
        self.set_state("transcribing")
        t = time.time()
        level = level_db(audio)
        if level < self.min_level_db:
            logger.info(f"Heard {len(audio) / SAMPLE_RATE:.1f}s at {level:.0f} dBFS: too quiet (below {self.min_level_db:.0f}), ignored")
            return
        if self.speaker_check and not self.is_trevor(audio):
            return
        text = self.transcribe(audio)
        if self.clear_cache:
            clear_mlx_cache()
        logger.info(f"Heard {len(audio) / SAMPLE_RATE:.1f}s at {level:.0f} dBFS, transcribed in {time.time() - t:.2f}s: {text!r}")
        self.deliver(text)

    def is_trevor(self, audio):
        """With speaker=on: does this sound like the enrolled voice? Fails open (with a log line) when no one is enrolled."""
        if self.verifier is None:
            from .speaker_id import SpeakerVerifier
            self.verifier = SpeakerVerifier()
        if not self.verifier.enrolled:
            logger.warning("speaker=on but no voice profile: run hooks/voice-mode enroll. Not filtering by voice.")
            return True
        score = self.verifier.score(audio)
        ok = score >= self.speaker_threshold
        logger.info(f"Voice match {score:.2f} (threshold {self.speaker_threshold:.2f}): "
                    + ("Trevor" if ok else "someone else, ignored"))
        if not ok:
            self.keep_rejected(audio, score)
        return ok

    def keep_rejected(self, audio, score):
        """Diagnostics: log what a rejected utterance said and keep the last 10 as wav, so the threshold can be tuned."""
        try:
            import wave
            d = Path.home() / ".local/state/mynah/rejected"
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"{time.strftime('%H%M%S')}-{score:.2f}.wav"
            with wave.open(str(p), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE)
                w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
            for old in sorted(d.glob("*.wav"))[:-10]:
                old.unlink()
            logger.info(f"  rejected said {self.transcribe(audio)!r} at {level_db(audio):.0f} dBFS (kept {p.name})")
        except Exception as e:
            logger.warning(f"keep_rejected failed: {e}")

    def deliver(self, text):
        """Act on a transcript - only if the mode is still on (it may have been switched off meanwhile)."""
        if not mode_on():
            logger.info("Voice mode is off: speech discarded")
            return
        if self.muted:
            logger.info("Muted: speech discarded")
            return
        if is_stop_command(text):
            logger.info("Spoken stop command: voice mode off")
            MODE_FILE.unlink(missing_ok=True)
            return
        if addressed_to_alexa(text):
            logger.info(f"ignored: addressed to Alexa ({text!r})")
            return
        text = usable_transcript(text)
        if text is None:
            logger.info("Nothing usable in that (noise or filler)")
            return
        try:
            self.submit(text)
        except Exception as e:
            logger.error(f"Submitting failed: {e}")
            self.speaker.say("I could not send that.")
            return
        logger.info(f"Sent to the orchestrator: {text!r}")
        self.idle_state = "waiting"
        self.set_state("waiting")

    # ---- loop
    def run(self):
        was_on = False
        while True:
            try:
                on = mode_on()
                if on:
                    self.active = time.time()
                if on and not was_on:
                    self.turn_on()
                elif was_on and not on:
                    self.turn_off()
                was_on = on
                if not on:
                    time.sleep(0.1)
                    continue
                self.step()
            except Exception as e:  # never let the loop die: the mode would silently stop working
                logger.error(f"Listener error: {e}", exc_info=True)
                self.release_mic()
                time.sleep(1)

    def apply_settings(self):
        cfg = mode_settings()
        self.speaker_check = cfg.get("speaker", "off").lower() in ("on", "true", "1", "yes")
        self.speaker_threshold = float(cfg.get("speaker_threshold", SPEAKER_THRESHOLD))
        try:
            self.min_level_db = float(cfg.get("min_level_db", MIN_LEVEL_DB))
            self.endpointer = Endpointer(silence_seconds=float(cfg.get("silence", SILENCE_SECONDS)))
        except ValueError as e:
            logger.warning(f"Bad setting in {MODE_FILE}: {e}; using defaults")
            self.min_level_db, self.endpointer = MIN_LEVEL_DB, Endpointer()
        self.barge_in = cfg.get("barge_in") or os.getenv("MYNAH_BARGE_IN")
        self.stt_model = cfg.get("stt_model") or STT_MODEL
        self.unload_on_off = cfg.get("unload_on_off", "1" if UNLOAD_ON_OFF else "0") in ("1", "on", "true", "yes")
        self.clear_cache = cfg.get("clear_cache", "1" if CLEAR_CACHE else "0") in ("1", "on", "true", "yes")
        logger.info(f"Settings: min level {self.min_level_db:.0f} dBFS, silence {self.endpointer.silence_frames * FRAME_SECONDS:.2f}s, "
                    f"barge-in {self.barge_in or 'auto'}")

    def turn_on(self):
        self.apply_settings()
        logger.info("Voice mode on")
        self.set_state("loading")
        self.load_models()
        self.speaker.say("Voice mode on.")
        self.deaf_until = time.time() + 3.0   # its own announcement: the canceller has not learned the room yet
        self.idle_state = "listening"
        self.set_state("listening")

    def turn_off(self):
        logger.info("Voice mode off")
        self.muted = False
        self.release_mic()
        self.set_state("off")
        self.speaker.say("Voice mode off.")
        if self.unload_on_off:
            self.unload_models()

    muted = False

    def set_muted(self, muted):
        """Tap of the push-to-talk key: stop listening (mic closed, nothing heard) or listen again. Voice mode
        stays on and replies are still spoken. Always cleared when the mode is switched off."""
        if muted == self.muted:
            return
        self.muted = muted
        logger.info("Muted: the microphone is ignored until the key is tapped again" if muted else "Unmuted: listening")
        play_cue("Basso" if muted else "Pop")
        if muted:
            self.release_mic()
        self.set_state("speaking" if self.speaker.speaking else self.idle_state)

    def mic_wanted(self, speaking):
        if self.muted or getattr(self.speaker, "paused", False):   # paused: Trevor is talking to the room
            return False
        if self.suspended():
            return False
        if speaking and (self.half_duplex is not False):   # undecided counts as shut
            return False
        return time.time() >= self.mic_not_before

    def decide_duplex(self):
        if self.barge_in in ("key", "voice", "echo"):
            self.mode = self.barge_in
        else:
            self.mode = "voice" if output_is_headphones() else "echo"
        name = current_output_name()
        if name != self.output_name:
            self.aec.forget()      # other speakers or room path: relearn the echo
            self.output_name = name
        self.half_duplex = self.mode == "key"
        self.gate_mode = self.mode   # outlives the reply: its tail is still gated
        logger.info("Reply speaking; " + {
            "key": "microphone shut (hold right Option to interrupt)",
            "voice": "microphone open for barge-in (headphones)",
            "echo": "microphone open for barge-in, echo cancelled"}[self.mode])

    diag = {"n": 0, "vad_ms": 0.0, "lag_ms": 0.0, "prob": 0.0, "level": -99.0}

    last_warm = 0.0

    def keep_models_warm(self):
        """With little free memory macOS pages an idle process's weights out; the next transcription then took
        20-30 s (measured 2026-11-04: 0.6 s normally) reading ~1 GB back. A tiny transcription and voiceprint
        every few seconds while idle keep the weights resident, for ~0.1 s of work."""
        self.last_warm = time.time()
        try:
            t = time.perf_counter()
            noise = (np.random.randn(SAMPLE_RATE) * 0.01).astype(np.float32)
            self.transcribe(noise)
            if self.speaker_check and self.verifier is not None and self.verifier.enrolled:
                self.verifier.embed(noise)
            took = (time.perf_counter() - t) * 1000
            if took > 1500:
                logger.info(f"Model warm-up took {took:.0f} ms (weights had been paged out)")
        except Exception as e:
            logger.warning(f"warm-up failed: {e}")

    def log_reply_diag(self):
        """After each reply: why did (or didn't) speech over it barge in? Peak voice probability after echo
        cancellation vs the barge threshold, how far behind real time the listener ran, the slowest VAD frame."""
        d, self.diag = self.diag, {"n": 0, "vad_ms": 0.0, "lag_ms": 0.0, "prob": 0.0, "level": -99.0}
        if d["n"]:
            logger.info(f"Barge diag: {d['n']} frames over the reply, peak voice prob {d['prob']:.2f} "
                        f"(barge needs {BARGE_THRESHOLD}), peak level {d['level']:.0f} dBFS, "
                        f"slowest VAD {d['vad_ms']:.0f} ms, max lag behind the mic {d['lag_ms']:.0f} ms")

    def step(self):
        speaking = bool(self.speaker.speaking)
        if speaking and self.half_duplex is None and getattr(self.speaker, "player", None) is not None:
            self.decide_duplex()   # only once the speaker has refreshed the device list and opened its output
        if not speaking:
            if self.was_speaking:
                self.log_reply_diag()
                self.gate_until = time.time() + 0.5   # the room still rings: keep ignoring the reply's tail
                self.mic_not_before = time.time() + (SPEAKER_TAIL_SECONDS if self.half_duplex else 0)
                self.idle_state = "listening"
            self.half_duplex = self.mode = None
        self.was_speaking = speaking
        if not self.mic_wanted(speaking):
            self.release_mic()
            self.set_state("paused" if getattr(self.speaker, "paused", False) else "speaking" if speaking else self.idle_state)
            time.sleep(0.05)
            return
        if self.stream is None:
            if speaking and getattr(self.speaker, "player", None) is None:
                time.sleep(0.02)   # the speaker is still refreshing the device list; do not race it
                return
            self.open_mic()
        try:
            item = self.frames.get(timeout=0.1)
        except queue.Empty:
            return
        t, frame = item if isinstance(item, tuple) else (time.perf_counter(), item)
        if time.time() < self.deaf_until:
            return
        if self.gate_mode == "echo" and (speaking or time.time() < self.gate_until):
            frame = self.aec.process(t, frame)   # the reply's own echo removed
            if frame is None:
                return
        t0 = time.perf_counter()
        if not speaking and not self.endpointer.in_speech and time.time() - self.last_warm > WARM_SECONDS:
            self.keep_models_warm()
        prob = self.speech_probability(frame)
        if speaking:
            d = self.diag
            d["n"] += 1
            d["vad_ms"] = max(d["vad_ms"], (time.perf_counter() - t0) * 1000)
            d["lag_ms"] = max(d["lag_ms"], (time.perf_counter() - t) * 1000)
            d["prob"] = max(d["prob"], prob)
            d["level"] = max(d["level"], level_db(frame))
        for kind, payload in self.endpointer.push(frame, prob, speaking):
            if kind == "start":
                if payload:
                    logger.info("Barge-in: speech over the reply, stopping it")
                    self.speaker.stop()
                self.set_state("hearing")
            elif kind == "drop":
                self.set_state("speaking" if self.speaker.speaking else self.idle_state)
            elif kind == "end":
                self.handle_utterance(payload)
                if self.state == "transcribing":
                    self.set_state(self.idle_state)
                self.drain_frames()
                self.endpointer.reset()
                self.vad_state = self.vad.initial_state(sample_rate=SAMPLE_RATE)
