"""Phoneme -> viseme timeline for J's mouth.

Kokoro (misaki, US English) turns each chunk of text into a phoneme string and predicts a duration, in frames of
600 samples (25 ms at 24 kHz), for every phoneme character plus a leading and trailing pad. This turns those into a short
list of mouth events, anime-simple: six shapes.

  M  lips closed (m b p), also used for pauses and silence (rest)
  A  wide open     E  half open, spread     I  narrow slit, teeth     O  rounded     U  pursed

The grouping follows the sound groups of Rhubarb Lip Sync's mouth shapes (A closed lips for M/B/P, B teeth for s/d/t/k/i,
C open for e, D wide for a, E rounded for o, F pucker for u/w, G for f/v) and the usual Oculus/Preston Blair viseme
families, folded into six shapes; diphthongs glide between two shapes (aɪ = A then I). A shape has an aperture (how far
the mouth opens), scaled by how loud that stretch of the audio really is, so stressed syllables open wider.
"""
import numpy as np

FRAME_S = 600 / 24000   # one Kokoro duration frame
MIN_EVENT_S = 0.06     # shorter stretches are absorbed by a neighbour (no flicker)

# misaki monophthongs: shape and aperture (0..1)
VOWELS = {
    "ɑ": ("A", 1.0), "æ": ("A", .9), "ʌ": ("A", .8), "ɐ": ("A", .65), "a": ("A", 1.0),
    "ɛ": ("E", .7), "e": ("E", .65), "ə": ("E", .5), "ᵊ": ("E", .35), "ɪ": ("E", .45), "ᵻ": ("E", .45), "ɜ": ("E", .55), "ɚ": ("E", .5),
    "i": ("I", .4),
    "ɔ": ("O", .85), "o": ("O", .8), "ɒ": ("O", .85),
    "u": ("U", .5), "ʊ": ("U", .5),
}
# misaki diphthongs: first shape/aperture, then second (the glide takes the last 45 % of the sound)
DIPHTHONGS = {
    "A": (("E", .7), ("I", .4)),    # eɪ  day
    "I": (("A", 1.0), ("I", .4)),   # aɪ  my
    "O": (("O", .8), ("U", .5)),    # oʊ  go
    "Q": (("E", .5), ("U", .5)),    # əʊ
    "W": (("A", 1.0), ("U", .5)),   # aʊ  now
    "Y": (("O", .85), ("I", .4)),   # ɔɪ  boy
}
# consonants that have a mouth shape of their own
CONSONANTS = {
    "p": ("M", 0.0), "b": ("M", 0.0), "m": ("M", 0.0),
    "f": ("I", .25), "v": ("I", .25),
    "w": ("U", .4), "ɹ": ("U", .3), "r": ("U", .3),
    "s": ("I", .25), "z": ("I", .25), "ʃ": ("I", .3), "ʒ": ("I", .3), "ʧ": ("I", .3), "ʤ": ("I", .3),
    "j": ("I", .3), "θ": ("I", .3), "ð": ("I", .3),
}
# consonants whose shape is whatever vowel is next to them, only less open (tongue sounds, k/g, h)
NEUTRAL = set("tdnlkgŋhTʔɫ")
STRESS = set("ˈˌːˑ")
PAUSE = set(",.!?;:—…-–()\"'“”‘’")


def _classify(ch):
    """('shape', aperture) | ('N',) neutral consonant | ('diph', a, b) | ('skip',) | ('rest',) | ('space',)."""
    if ch in VOWELS: return ("v",) + VOWELS[ch]
    if ch in DIPHTHONGS: return ("diph",) + DIPHTHONGS[ch]
    if ch in CONSONANTS: return ("c",) + CONSONANTS[ch]
    if ch in NEUTRAL: return ("N",)
    if ch in STRESS: return ("skip",)
    if ch == " ": return ("space",)
    if ch in PAUSE: return ("rest",)
    return ("N",) if ch.isalpha() else ("skip",)


def timeline(phonemes, pred_dur, vocab, audio=None, frame_s=FRAME_S):
    """Mouth events for one Kokoro chunk: [(t0, t1, shape, open)], seconds from the start of the chunk's audio.

    phonemes: the chunk's phoneme string; pred_dur: Kokoro's per-token frame counts (pad, one per phoneme character that
    is in the vocab, pad); vocab: the model's phoneme->id dict (characters outside it have no duration); audio: optional
    float samples of the chunk, used to scale apertures by loudness."""
    dur = [int(x) for x in pred_dur]
    segs = []   # [seconds, kind, shape, aperture]
    if dur:
        segs.append([dur[0] * frame_s, "rest", "M", 0.0])
    idx = 1
    for ch in phonemes:
        if ch not in vocab:
            continue
        if idx >= len(dur) - 1:
            break
        d = dur[idx] * frame_s
        idx += 1
        c = _classify(ch)
        k = c[0]
        if k == "diph":
            segs.append([d * .55, "v", c[1][0], c[1][1]]); segs.append([d * .45, "v", c[2][0], c[2][1]])
        elif k in ("v", "c"):
            segs.append([d, k, c[1], c[2]])
        elif k == "N":
            segs.append([d, "N", None, .3])
        elif k == "rest":
            segs.append([d, "rest", "M", 0.0])
        elif k == "space":
            segs.append([d, "space", None, 0.0])
        else:   # stress marks: no mouth of their own, give their time to the previous sound
            if segs: segs[-1][0] += d
    if dur:
        segs.append([dur[-1] * frame_s, "rest", "M", 0.0])
    # spaces: a long one is a pause (rest), a short one just continues the previous sound
    for s in segs:
        if s[1] == "space":
            if s[0] >= .12: s[1:] = ["rest", "M", 0.0]
    out = []
    for s in segs:
        if s[1] == "space":
            if out: out[-1][0] += s[0]
            else: out.append(s)
        else:
            out.append(s)
    segs = out
    # neutral consonants take the shape of the next vowel (anticipation), else the previous one, at low aperture
    for i, s in enumerate(segs):
        if s[1] != "N": continue
        nxt = next((t for t in segs[i + 1:] if t[1] in ("v", "c") and t[2]), None)
        stop = next((j for j, t in enumerate(segs[i + 1:]) if t[1] == "rest"), None)
        if nxt is not None and (stop is None or segs[i + 1:].index(nxt) < stop):
            s[2], s[3] = nxt[2], min(.3, nxt[3] * .5 + .1)
        else:
            prev = next((t for t in reversed(segs[:i]) if t[2] and t[1] != "rest"), None)
            s[2], s[3] = (prev[2], min(.3, prev[3] * .5 + .1)) if prev else ("E", .25)
    # merge stretches too short to read into a neighbour. The more important sound wins when two merge: a lip closure
    # (m b p) over a vowel over a consonant shape over a neutral consonant; silence stays silence.
    def prio(t):
        if t[1] == "rest": return -1
        if t[2] == "M": return 3
        return {"v": 2, "c": 1}.get(t[1], 0)
    while len(segs) > 1:
        def too_short(i):
            t = segs[i]
            if t[1] == "rest": return t[0] < .03
            floor = .04 if t[2] == "M" else MIN_EVENT_S
            return t[0] < floor
        cand = [i for i in range(len(segs)) if too_short(i)]
        if not cand: break
        i = min(cand, key=lambda k: segs[k][0]); t = segs[i]
        nb = [j for j in (i - 1, i + 1) if 0 <= j < len(segs) and segs[j][1] != "rest"] or [j for j in (i - 1, i + 1) if 0 <= j < len(segs)]
        j = max(nb, key=lambda k: (prio(segs[k]), segs[k][0]))
        if prio(t) > prio(segs[j]): segs[j][1:] = t[1:]
        segs[j][0] += t[0]
        del segs[i]
    # join neighbours that look the same
    merged = []
    for s in segs:
        if merged and merged[-1][2] == s[2]:
            merged[-1][3] = max(merged[-1][3], s[3]); merged[-1][0] += s[0]
        else:
            merged.append(list(s))
    # times, and aperture scaled by loudness of that stretch of audio
    env = None
    if audio is not None and len(audio):
        sr = int(round(1 / (frame_s / 600)))
        hop = int(sr * .02)
        n = len(audio) // hop
        if n:
            env = np.sqrt((np.asarray(audio[: n * hop], dtype="float32").reshape(n, hop) ** 2).mean(axis=1))
            ref = max(float(np.percentile(env, 90)), 1e-4)
    events, t = [], 0.0
    for dur_s, kind, shape, ap in merged:
        t1 = t + dur_s
        if env is not None and shape != "M":
            a, b = int(t / .02), max(int(t / .02) + 1, int(t1 / .02))
            loud = float(env[a:b].mean()) / ref if a < len(env) else 0.0
            ap = ap * float(np.clip(.55 + .6 * loud, .45, 1.15))
        events.append((round(t, 4), round(t1, 4), shape, round(min(1.0, ap), 3)))
        t = t1
    return events


def word_timeline(tokens, pred_dur, audio_s, frame_s=FRAME_S):
    """[(t0, t1, text)] in seconds from the chunk start: one entry per spoken word, for the on-screen karaoke text.

    tokens: misaki tokens from Kokoro's pipeline (text, whitespace, start_ts, end_ts; punctuation has no timestamps and is
    glued to the word before it, or to the next word at the start); pred_dur: Kokoro's per-token frame counts; audio_s: the
    chunk's real length, used to stretch the predicted times onto the audio (the same way the mouth timeline is fitted).
    Returns None when there are no usable tokens."""
    if not tokens:
        return None
    total = float(sum(int(x) for x in pred_dur)) * frame_s
    k = (audio_s / total) if total > 0 and audio_s > 0 else 1.0
    out, lead = [], ""
    for t in tokens:
        text = (getattr(t, "text", "") or "") + (getattr(t, "whitespace", "") or "")
        a, b = getattr(t, "start_ts", None), getattr(t, "end_ts", None)
        if a is None or b is None or (out and not any(c.isalnum() for c in text)):
            if out:
                out[-1][2] += text
                if b is not None:
                    out[-1][1] = max(out[-1][1], b * k)    # the highlight stays on the word through its comma or full stop
            else:
                lead += text
            continue
        out.append([max(0.0, a * k), max(a * k, b * k), lead + text])
        lead = ""
    return [tuple(w) for w in out] or None
