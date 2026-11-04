import numpy as np
from mynah import viseme

VOCAB = set("həlˈOtɹɛvəɹ,ðɪsɪzɐɡbpmfwjnkdʃWAIQYɑæɔuiʊ .?!ˌ")
SHAPES = set("MAEIOU")


def tl(ps, frames_each=3, pad=(4, 4), audio=None):
    chars = [c for c in ps if c in VOCAB]
    dur = [pad[0]] + [frames_each] * len(chars) + [pad[1]]
    return viseme.timeline(ps, dur, VOCAB, audio)


def test_events_are_contiguous_and_cover_the_chunk():
    ev = tl("həlˈO tɹˈɛvəɹ, ðɪs ɪz ɐ tˈɛst.")
    assert ev[0][0] == 0
    for a, b in zip(ev, ev[1:]):
        assert abs(a[1] - b[0]) < 1e-3
    total = (4 + 3 * len([c for c in "həlˈO tɹˈɛvəɹ, ðɪs ɪz ɐ tˈɛst." if c in VOCAB]) + 4) * viseme.FRAME_S
    assert abs(ev[-1][1] - total) < 0.01
    assert all(e[2] in SHAPES and 0 <= e[3] <= 1 for e in ev)


def test_starts_and_ends_closed():
    ev = tl("ɑ")
    assert ev[0][2] == "M" and ev[-1][2] == "M"


def test_lip_closure_for_m_b_p():
    ev = tl("ɑmɑ", frames_each=4)
    assert [e[2] for e in ev if e[2] != "M" or e[3] == 0][1:-1].count("M") >= 1
    assert any(e[2] == "M" and 0.1 < e[0] < 0.6 for e in ev)


def test_vowel_shapes():
    for ch, shape in [("ɑ", "A"), ("ɛ", "E"), ("i", "I"), ("ɔ", "O"), ("u", "U")]:
        ev = tl(ch, frames_each=6)
        assert shape in [e[2] for e in ev], (ch, ev)


def test_diphthong_glides_between_two_shapes():
    ev = tl("I", frames_each=8)   # aɪ: A then I
    shapes = [e[2] for e in ev if e[2] != "M"]
    assert shapes[:2] == ["A", "I"], ev


def test_no_flicker_tiny_events_are_absorbed():
    ev = tl("həlˈO tɹˈɛvəɹ ðɪs ɪz ɐ tˈɛst", frames_each=1)   # 25 ms per phoneme
    assert all(e[1] - e[0] >= viseme.MIN_EVENT_S - 1e-3 or e[2] == "M" for e in ev), ev


def test_louder_audio_opens_wider():
    n = int(24000 * (4 + 6 + 4) * viseme.FRAME_S)
    quiet = np.full(n, 0.02, dtype="float32"); quiet[: n // 2] *= 0.1
    loud = quiet * 5
    a = [e for e in tl("ɑ", frames_each=6, audio=quiet) if e[2] == "A"][0][3]
    b = [e for e in tl("ɑ", frames_each=6, audio=loud) if e[2] == "A"][0][3]
    assert a <= 1 and b <= 1 and a > 0


def test_word_timeline_glues_punctuation_and_fits_the_audio():
    from types import SimpleNamespace as N
    toks = [N(text="Hi", whitespace="", start_ts=0.1, end_ts=0.3), N(text=",", whitespace=" ", start_ts=None, end_ts=None),
            N(text="you", whitespace="", start_ts=0.4, end_ts=0.8), N(text=".", whitespace="", start_ts=None, end_ts=None)]
    w = viseme.word_timeline(toks, [1] * 40, audio_s=2.0)    # 40 frames = 1.0 s predicted, 2.0 s real: stretched x2
    assert [x[2] for x in w] == ["Hi, ", "you."]
    assert abs(w[0][0] - 0.2) < 1e-6 and abs(w[1][1] - 1.6) < 1e-6
    assert viseme.word_timeline(None, [1], 1.0) is None


def test_word_timeline_glues_timed_punctuation_too():
    from types import SimpleNamespace as N
    toks = [N(text="Hi", whitespace="", start_ts=0.0, end_ts=0.3), N(text=",", whitespace=" ", start_ts=0.3, end_ts=0.4),
            N(text="you", whitespace="", start_ts=0.4, end_ts=0.8)]
    w = viseme.word_timeline(toks, [1] * 32, audio_s=0.8)
    assert [x[2] for x in w] == ["Hi, ", "you"] and abs(w[0][1] - 0.4) < 1e-6
