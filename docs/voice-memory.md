# Voice memory and the speakd wedge

(If another branch also adds `docs/voice-memory.md`, keep both: this section is self-contained, append it.)

## The speakd audio wedge (2026-11-04, 2026-11-05)

**Symptom.** Jmacs stops speaking; speakd (`python -m mynah.speakd`) is alive but silent for hours. Seen twice
(pid 42270, pid 83437). pid 83437 was 20 h old with a physical footprint of 11.8 GB (peak 12.1 GB), 11.2 GB of it
swapped, and system swap at 8.8 of 9.2 GB; killing it dropped swap to 5.1 GB. Every other app on the 16 GB MacBook
Air paid for it.

**Cause (confirmed for 42270, same class assumed for 83437).** A lock cycle inside CoreAudio, not in Python.
`~/.local/state/mynah/speakd-hang.sample`: the thread closing the stream is in
`cdata_call > FinishStoppingStream (libportaudio) > AudioOutputUnitStop > AudioDeviceStop_mac_imp >
HALC_ProxyIOContext::StopIOProc > HALB_Mutex::Lock > __psynch_mutexwait`, while the IO thread sits in
`startStopCallback (libportaudio) > AudioUnitGetProperty > std::recursive_mutex::lock`. Each waits for the other.
Python's `close_lock` is not involved, so no Python-level fix can release it; the process has to be restarted.

**What speakd does now** (`src/mynah/audiowatch.py`, wired into `speakd.py`):

- `flush()` + `stop_stream()` run on a helper thread with a 3 s timeout (`MYNAH_STOP_TIMEOUT`). On timeout the
  device is judged wedged.
- One re-entrant lock (`audiowatch.AUDIO_LOCK`) covers stream stop/close, `refresh_audio_devices()` (the PortAudio
  terminate/initialize), player creation and the listener's `open_mic` / `release_mic`, so `stop()`, the end of
  speech, mic release and device refresh never touch PortAudio from two threads at once. A stream is stopped at most
  once. Waiting more than 8 s for this lock is also treated as a wedge.
- On a wedge: log `AUDIO WEDGED at <time>: <reason>`, write `~/.local/state/mynah/speakd-wedge-<pid>-<time>.txt`
  (every Python thread's stack), plus `.sample.txt` (macOS `sample`: the native CoreAudio stacks, like the 11-04
  file) and `.footprint.txt`, then restart speakd by `exec` (same pid, same desktop session; the pid file is
  removed first so the new image does not see itself as "Already running"). `exec` keeps the pid, so whatever
  parent speakd has (the applet and its `sh`/bash, still alive in the 2026-11-05 sample) stays its parent. If `exec` itself hangs, a detached
  shell kills the pid after about 6 s and starts the speaker the way `hooks/claude-speak Start` does. At most 5
  wedge restarts per 10 minutes; after that speakd logs that it will not restart again.
- A watchdog thread (reads only plain attributes, takes no speakd lock) restarts on the same path when a `.say` in
  the inbox has gone unconsumed for 10 s (`MYNAH_WATCHDOG_SAY`; not while a reply is paused, which holds the inbox by
  design), or when one utterance has held the stream longer than 150 s of unpaused time (`MYNAH_MAX_UTTERANCE`):
  it first tries a normal `stop()`, and restarts 10 s later if the utterance still holds the stream.
- The reply that was playing when the restart happened is lost (not replayed, so a reply that wedges the device
  cannot loop).

**Audio callback.** Left as it is. `tap` only enqueues onto an unbounded queue that a worker drains, `lipsync.on_block`
only stores a tuple, and `write_level` only stores a number (a thread writes the file). None takes a lock the
other threads hold for long, so moving them to another thread would add a hand-off and timing error (the mouth
and echo-canceller depend on the callback's own `time_info`) for no blocking removed. The remaining calls in the callback are
inside mlx_audio's `AudioPlayer.callback`, which this repo does not own.

## Reading a footprint (RSS lies)

`ps -o rss` showed 6.6 MB for the wedged process whose footprint was 11.8 GB: swapped-out pages are not resident,
and MLX reserves address space. Use the macOS physical footprint:

    pid=$(cat ~/.local/state/mynah/speakd.pid)
    footprint $pid                      # one line: total footprint
    vmmap -summary $pid | grep -E 'Physical footprint|^(TOTAL|MALLOC|IOKit|IOAccelerator)'
    sysctl vm.swapusage                 # system-wide swap used / total

`Physical footprint:` is the number to compare (resident plus swapped plus compressed); `Physical footprint (peak)`
is its high-water mark. `vmmap` lists swapped per region in the `SWAPPED` column. A healthy speakd with voice mode on
showed a footprint of 11.9 GB with RSS 2.9 GB (probably MLX address space, not a leak). That is a different thing from
the wedge: the wedge is footprint that grows or stays high while nothing is spoken and replies pile up in
`~/.local/state/mynah/inbox`.

- `TappedPlayer.callback` swallows mlx-audio's `sd.CallbackStop` (empty buffer), so PortAudio never stops the audio
  unit from the IO thread; the stream runs on silence and only `_close` (under `AUDIO_LOCK`) stops it.
- `TappedPlayer.start_stream` stops and closes the previous stream first (under `AUDIO_LOCK`, bounded by `STOP_TIMEOUT`,
  errors logged) and starts nothing after `_close`. Needed after a mid-reply underrun: mlx-audio 0.5.6 would otherwise
  overwrite `self.stream`, leaving the old one running on the shared buffer.
- mlx-audio versions: `pyproject.toml` says `mlx-audio>=0.5.6` (not pinned). Tested: 0.5.6 (the live tool; its callback sets
  `playing=False` and `drain_event` itself) and 0.6.4 (callback sets `playing=False` only; `drain_event` comes from the
  stream's `finished_callback`, which never fires with `CallbackStop` swallowed, so the callback sets it from the second
  silent block; its `start_stream` stops the old stream itself). Unit tests: `tests/test_tapped_player.py`, fakes of both.
- Running the tests: `uv tool install --force mynah --with pytest` (or `uvx --with-editable . pytest`), then
  `PYTHONPATH=src ~/.local/share/uv/tools/mynah/bin/python -m pytest tests/test_audiowatch.py -q`. On Linux:
  `pip install pytest && PYTHONPATH=src python3 -m pytest tests/test_audiowatch.py -q`.
