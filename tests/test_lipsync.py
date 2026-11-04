import time
from types import SimpleNamespace

from mynah import lipsync


def ti(lead=0.048):
    return SimpleNamespace(currentTime=10.0, outputBufferDacTime=10.0 + lead)


def test_event_times_are_anchored_to_when_the_block_reaches_the_speaker():
    ls = lipsync.LipSync(24000)
    ls.add_chunk(48000, [(0.0, 0.5, "M", 0.0), (0.5, 1.0, "A", 0.8)])
    t_cb = time.time()
    ls.on_block(2048, ti(0.048))          # stream sample 0 reaches the speaker 48 ms after the callback
    snap = ls.snapshot(now=t_cb)
    a = [e for e in snap["ev"] if e[2] == "A"][0]
    assert abs(a[0] - (t_cb + 0.048 + 0.5)) < 0.01     # the A starts 0.5 s into the audio
    assert a[3] == 0.8


def test_second_chunk_continues_the_stream():
    ls = lipsync.LipSync(24000)
    ls.add_chunk(12000, [(0.0, 0.5, "M", 0.0)])     # 0.5 s
    ls.add_chunk(24000, [(0.0, 1.0, "O", 0.6)])     # starts 0.5 s into the stream
    ls.on_block(2048, ti())
    o = [e for e in ls.snapshot(now=time.time())["ev"] if e[2] == "O"]
    assert o and abs(o[0][0] - (time.time() + 0.048 + 0.5)) < 0.05


def test_later_blocks_re_anchor_without_drift():
    ls = lipsync.LipSync(24000)
    ls.add_chunk(48000, [(0.0, 0.5, "M", 0.0), (0.5, 1.0, "A", 0.8)])
    ls.on_block(2048, ti())
    first = [e for e in ls.snapshot()["ev"] if e[2] == "A"][0][0]
    ls.on_block(2048, ti())               # the next block, played == 2048 now, but the clock moved a bit later in real life
    assert ls.played == 4096


def test_stop_cuts_the_mouth_at_once():
    ls = lipsync.LipSync(24000)
    ls.add_chunk(24000, [(0.0, 1.0, "A", 0.8)])
    ls.on_block(2048, ti())
    assert ls.snapshot() is not None
    ls.stop()
    assert ls.snapshot() is None


def test_old_anchor_means_nothing_is_playing():
    ls = lipsync.LipSync(24000)
    ls.add_chunk(24000, [(0.0, 1.0, "A", 0.8)])
    ls.on_block(2048, ti())
    ls.anchor = (ls.anchor[0], ls.anchor[1], time.monotonic() - 1.0)
    assert ls.snapshot() is None
