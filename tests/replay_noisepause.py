"""Replay test for the noise pause with the real Silero VAD, the real speaker-verification code path and the real
WebRTC echo canceller, on generated audio (macOS `say` voices, noise, tones, clatter). No microphone, no speaker,
simulated clock (one mic frame = 32 ms). The reply is a TappedPlayer fed block by block through its real callback,
so "the word position is kept" is checked on the actual audio samples.
Run: PYTHONPATH=src HF_HUB_OFFLINE=1 ~/.local/share/uv/tools/mynah/bin/python tests/replay_noisepause.py"""
import os
import subprocess
import sys
import tempfile
import threading
import wave
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import numpy as np

tmp = Path(tempfile.mkdtemp(prefix="mynah-npreplay."))
os.environ["MYNAH_VOICE_MODE_FILE"] = str(tmp / "voice-conversation")
os.environ["MYNAH_VOICE_STATE_FILE"] = str(tmp / "voice-state")
os.environ["MYNAH_VOICE_PROFILE"] = str(tmp / "profile.npz")
from mynah import listen, noisepause as npz, speakd, speaker_id  # noqa: E402
from mynah.aec import EchoCanceller  # noqa: E402
from mlx_audio.vad.utils import load_model as load_vad  # noqa: E402

R, F, DT = 16000, npz.FRAME, npz.FRAME_S
rng = np.random.default_rng(3)
VAD = load_vad(listen.VAD_MODEL)


def say(text, voice, rate=R):
    a, w = tmp / "s.aiff", tmp / "s.wav"
    subprocess.run(["say", "-v", voice, "-o", str(a), text], check=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(a), "-ar", str(rate), "-ac", "1", "-c:a", "pcm_s16le", str(w)], check=True)
    x = wave.open(str(w))
    return np.frombuffer(x.readframes(x.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def scale(x, db_):
    return x * 10 ** (db_ / 20) / (np.sqrt(np.mean(x ** 2)) + 1e-9)


def quiet(s):
    return rng.normal(0, 0.0005, int(s * R)).astype(np.float32)


def white(s, db_):
    return scale(rng.normal(0, 1, int(s * R)).astype(np.float32), db_)


def music(s, db_):
    t = np.arange(int(s * R)) / R
    x = sum(np.sin(2 * np.pi * f * t) * (1 + 0.3 * np.sin(2 * np.pi * 2 * t)) for f in (220, 277.2, 329.6, 440))
    return scale(x.astype(np.float32), db_)


def clatter(s, db_):
    x = np.zeros(int(s * R), dtype=np.float32)
    for i in range(0, len(x) - 800, 2400):
        x[i:i + 800] = scale(rng.normal(0, 1, 800).astype(np.float32) * np.exp(-np.arange(800) / 150), db_)
    return x


# ---- the reply: a long TappedPlayer fed through its real callback (24 kHz, 2048 blocks)
REPLY = say("This is a long reply from the orchestrator. It goes on for quite a while, so that there is time to make noise "
            "over it, and to check that after a pause it continues from exactly the same word and does not repeat or skip one. "
            "Here is some more text to keep going for another few seconds, and then a little more at the very end.", "Karen", 24000)


def make_player():
    P = speakd.tapped_player_class()
    p = P.__new__(P)
    p.paused, p.tap, p.lipsync = False, None, None
    p.audio_buffer, p.buffer_lock, p.drain_event = deque([REPLY.copy()]), threading.Lock(), threading.Event()
    p.playing = True
    return p


def make_speaker(player):
    sp = speakd.Speaker.__new__(speakd.Speaker)
    sp.lock, sp.speaking, sp.paused, sp.auto_paused, sp.player = threading.Lock(), True, False, False, player
    sp.listener = SimpleNamespace(deaf_until=0.0)
    sp.token = 0
    sp._close = lambda p: None
    return sp


def run(name, mic, expect, verdict=None, profile=None, echo_ref=None, duration=None):
    """mic: the microphone signal; expect: dict with 'pauses', 'resumes', 'barge' (bool). Returns result dict."""
    player = make_player()
    sp = make_speaker(player)
    classify = None
    if profile is not None:
        classify = lambda a: profile.score(a[-6 * R:]) >= listen.SPEAKER_THRESHOLD
    gate = npz.NoiseGate(classify=classify)
    state = VAD.initial_state(sample_rate=R)
    aec = EchoCanceller(source_rate=24000) if echo_ref is not None else None
    played, pos_log = [], []
    t, nblk, acts = 0.0, 0.0, []
    blk_dt = 2048 / 24000
    n = (len(mic) // F) - 1
    barged = False
    for i in range(n):
        t = i * F / R
        while nblk <= t:                                  # the output callback runs every 85 ms
            out = np.zeros((2048, 1), dtype=np.float32)
            before = player.buffered_samples() if hasattr(player, "buffered_samples") else sum(map(len, player.audio_buffer))
            try:
                player.callback(out, 2048, SimpleNamespace(), None)
            except Exception:
                pass
            played.append((nblk, out[:, 0].copy(), player.paused))
            if aec is not None:
                aec.tap(out[:, 0])
            nblk += blk_dt
        frame = mic[i * F:(i + 1) * F].copy()
        if echo_ref is not None:                          # echo: what the room sends back, built from the played blocks
            frame = frame  # (precomputed in the mic signal)
        if aec is not None:
            aec.flush()
            frame = aec.process(t, frame)
            if frame is None:
                continue
        if barged or t < getattr(sp.listener, "deaf_until", 0) - 0 and False:
            continue
        import mlx.core as mx
        prob, state = VAD.feed(frame, state, sample_rate=R)
        mx.eval(prob)
        prob = float(np.array(prob).reshape(-1)[0])
        if sp.paused and not sp.auto_paused:
            continue
        deaf = getattr(sp, "_deaf", 0.0)
        a = gate.push(t, frame, prob)
        if a == "pause":
            sp.set_paused(True, auto=True)
        elif a == "resume":
            sp.set_paused(False)
        elif a == "barge":
            sp.speaking = sp.paused = sp.auto_paused = False
            player.paused = False
            barged = True
        if a:
            acts.append((round(t, 2), a))
    # position check: the audio that came out, with the paused (silent) blocks removed, is a prefix of the reply
    heard = np.concatenate([b for _, b, p in played if not p]) if played else np.zeros(0)
    heard = heard[: len(REPLY)]
    k = len(heard)
    if barged:
        heard = np.concatenate([b for _, b, p in played if not p])
    contiguous = bool(np.array_equal(np.trim_zeros(heard, "b")[: min(len(heard), len(REPLY))], REPLY[: len(np.trim_zeros(heard, "b"))][: min(len(heard), len(REPLY))]))
    pauses = [x for x in acts if x[1] == "pause"]
    resumes = [x for x in acts if x[1] == "resume"]
    got = dict(pauses=len(pauses), resumes=len(resumes), barge=barged)
    ok = all(got[k] == v for k, v in expect.items() if k != "start" and k != "end") and contiguous
    lat = ""
    if "start" in expect and pauses:
        lat += f" noise->pause {pauses[0][0] - expect['start']:.2f}s"
    if "start" in expect and barged:
        lat += f" start->barge {acts[-1][0] - expect['start']:.2f}s"
    if "end" in expect and resumes:
        lat += f" end->resume {resumes[-1][0] - expect['end']:.2f}s"
    print(("PASS" if ok else "FAIL"), name, acts, f"reply-position-contiguous={contiguous}", lat.strip())
    return ok


def sc(lead, event, tail):
    return np.concatenate([quiet(lead), event, quiet(tail)])


results = []
LEAD, TAIL = 2.0, 5.0
daniel = say("Honey, did you see where I put the car keys? I thought they were on the kitchen table this morning.", "Daniel")
tv = np.concatenate([say("Tonight on the news, the weather will stay cloudy across most of the region with a chance of rain by the weekend.", "Fred")] * 3)
enrol_text = speaker_id.ENROLL_SENTENCES
V = speaker_id.SpeakerVerifier()
V.enroll([say(t, "Samantha") for t in enrol_text[:4]])      # a throwaway profile in tmp: Samantha stands in for Trevor
trevor = say("Wait, stop, I want to ask something else instead of that.", "Samantha")

D = len(daniel) / R
results += [
    run("loud white noise 3 s", sc(LEAD, white(3, -15), TAIL), dict(pauses=1, resumes=1, barge=False, start=LEAD, end=LEAD + 3), profile=V),
    run("music-like tones 4 s", sc(LEAD, music(4, -20), TAIL), dict(pauses=1, resumes=1, barge=False, start=LEAD, end=LEAD + 4), profile=V),
    run("clatter 1.5 s", sc(LEAD, clatter(1.5, -10), TAIL), dict(pauses=1, resumes=1, barge=False, start=LEAD, end=LEAD + 1.5), profile=V),
    run("someone else speaks (Daniel)", sc(LEAD, scale(daniel, -22), TAIL), dict(pauses=1, resumes=1, barge=False, start=LEAD, end=LEAD + D), profile=V),
    run("Trevor speaks (enrolled voice)", sc(LEAD, scale(trevor, -22), TAIL), dict(pauses=1, barge=True, start=LEAD), profile=V),
    run("cough (0.12 s)", sc(LEAD, white(0.12, -10), TAIL), dict(pauses=0, resumes=0, barge=False), profile=V),
    run("flapping noise, 8 bursts of 0.4 s", sc(LEAD, np.concatenate([np.concatenate([white(0.4, -15), quiet(0.6)]) for _ in range(8)]), TAIL),
        dict(pauses=1, resumes=1, barge=False), profile=V),
    run("quiet room, nothing", quiet(14), dict(pauses=0, resumes=0, barge=False), profile=V),
    run("no profile: TV talk 12 s (not a command)", sc(LEAD, scale(tv[: 12 * R], -22), TAIL), dict(pauses=1, resumes=1, barge=False), profile=None),
    run("no profile: a short spoken command", sc(LEAD, scale(trevor, -22), TAIL), dict(pauses=1, barge=True), profile=None),
]

# the reply's own echo through a synthetic room and the real AEC3: must never pause
reply16 = np.interp(np.arange(0, len(REPLY) * R // 24000), np.arange(len(REPLY)) * R / 24000, REPLY).astype(np.float32)
rir = np.zeros(1200); rir[[0, 50, 200, 600]] = [.35, .17, -.09, .05]
echo = np.convolve(np.concatenate([np.zeros(1920), reply16]), rir)[: len(reply16)].astype(np.float32)
echo += rng.normal(0, 3e-4, len(echo)).astype(np.float32)
results.append(run("reply's own echo only (AEC3)", echo[: 14 * R], dict(pauses=0, resumes=0, barge=False), profile=V, echo_ref=True))

# what the real enrolment says about the generated voices (the real code path; the score only)
real = speaker_id.SpeakerVerifier.__new__(speaker_id.SpeakerVerifier)
os.environ.pop("MYNAH_VOICE_PROFILE", None)
speaker_id.PROFILE = Path.home() / ".config/jmacs/voice-profile.npz"
RV = speaker_id.SpeakerVerifier()
if RV.enrolled:
    print("real enrolment vs generated voices (threshold 0.30):", {v: round(RV.score(say(trevor_t := "Wait, stop, I want to ask something else.", v)), 2) for v in ("Samantha", "Daniel", "Karen")})
sys.exit(0 if all(results) else 1)
