# Jmacs voice: memory and speed

Untested on a Mac by the author (written in a Linux cloud session). Every change below is off by default; Trevor measures first.

## What the code already does (found by reading)

- **It is already one process.** `speakd.py` runs Kokoro (TTS) and `listen.Listener` (Silero VAD, Parakeet STT, speaker-id, AEC) in the same Python process. "Mynah Speaker.app" is only a launcher that starts speakd in the desktop session and exits. The companion is a separate `sbcl` page (small). The only real duplicate is `mynah` (`main.py`, the old hotkey menu-bar app): it loads its own Kokoro, so do not run it next to speakd. Merging processes would save nothing; `tools/voice-measure.lisp` lists every process so this can be checked.
- **Voice mode off:** `speakd --sleep` (after 300 s idle) re-execs into a process holding no models (~75 MB). Waking re-execs again: full import + Kokoro load + ~8 s warm-up.
- **Voice mode off but speakd awake (the first 300 s):** the STT/VAD models stay loaded until the idle exit. That is the cheapest thing to drop sooner (`unload_on_off`).
- **Parakeet size:** the `mlx-community/parakeet-tdt-0.6b-v3` repo is a single 2508 MB fp32 `model.safetensors`; mlx_audio's loader casts to bf16 (`from_pretrained(..., dtype=mx.bfloat16)`), so about half of that (~1.2 GB) should be resident. Measure; do not trust this.
- **Wired memory:** `wire_model_memory()` sets `mx.set_wired_limit(4 GB)` by default (to stop page-out). That is a cap on pinned memory, which the system cannot reclaim: it is the opposite of "low memory". `MYNAH_WIRED_GB=0` is the lever to try (whether 0 disables wiring is an MLX behaviour I could not test).

## Knobs (defaults = old behaviour)

Settings-file lines go in `~/.config/jmacs/voice-settings` (re-read each time voice mode is turned on; `sleep_after` every 5 s). The env var is the fallback.

| Setting line | Env var | Default | Effect |
|---|---|---|---|
| `sleep_after=60` | `MYNAH_SLEEP_AFTER` | 300 | Seconds idle (mode off, nothing to say) before speakd unloads everything. Floor 10. |
| `unload_on_off=1` | `MYNAH_UNLOAD_ON_OFF=1` | off | Voice mode off drops STT, VAD and voiceprint models at once and clears the MLX cache. Kokoro stays (small, keeps replies fast). Turning the mode on reloads from the disk cache; the log says `Voice models ready in X.Xs`. |
| `clear_cache=1` | `MYNAH_CLEAR_CACHE=1` | off | Returns MLX's buffer cache to the system after each utterance. |
| `stt_model=<id>` | `MYNAH_STT_MODEL` | `mlx-community/parakeet-tdt-0.6b-v3` | STT model; takes effect the next time voice mode is turned on. |
| (env only) | `MYNAH_MLX_CACHE_MB` | unset | `mx.set_cache_limit`. Try 64–256. |
| (env only) | `MYNAH_MLX_MEMORY_GB` | unset | `mx.set_memory_limit` (hard cap; too low = errors). |
| (env only) | `MYNAH_WIRED_GB` | 4 | existing; lower or 0 trades page-out protection for memory. |
| (env only) | `MYNAH_WARM_SECONDS` | 3.0 | Keep-warm ping interval while voice mode is on. Longer = less work, more page-out risk. |

The env vars must reach speakd: it is started by "Mynah Speaker.app", whose shell does not read your profile, so prefer the settings-file lines where one exists, or edit `hooks/speaker.applescript`.

## STT candidates (sizes and licenses from the Hugging Face API, 2026-11-05)

Size = sum of `.safetensors` in the repo (disk); resident is roughly half for fp32 repos loaded as bf16, about equal for 4-bit. All are in mlx_audio's STT list (https://github.com/Blaizzy/mlx-audio README) unless noted.

| Model id | Repo size | License (HF card) | Notes |
|---|---|---|---|
| `mlx-community/parakeet-tdt-0.6b-v3` (now) | 2508 MB | CC-BY-4.0 (base `nvidia/parakeet-tdt-0.6b-v3`) | 25 European languages |
| `mlx-community/parakeet-tdt-0.6b-v2` | 2472 MB | CC-BY-4.0 | English only; same size |
| `mlx-community/parakeet-tdt_ctc-110m` | 459 MB | CC-BY-4.0 (`nvidia/parakeet-tdt_ctc-110m`) | English, 110M params, closest quality to now at ~1/5 the size. mlx_audio has a `ParakeetTDTCTC` class; I did not verify this checkpoint loads with the TDT decode path `generate` uses. Try first. |
| `mlx-community/whisper-large-v3-turbo-4bit` | 463 MB | card says Apache-2.0; `openai/whisper-large-v3-turbo` says MIT | 4-bit, large-quality; slower than Parakeet |
| `mlx-community/whisper-small-asr-4bit` (or `whisper-small.en-asr-4bit`) | 139 MB | Apache-2.0 (`openai/whisper-small` is Apache-2.0) | the "Whisper-small" option; `-asr-` is the naming the mlx_audio README uses (`whisper-large-v3-turbo-asr-fp16`) |
| `mlx-community/whisper-base.en-asr-4bit` | 42 MB | Apache-2.0 | |
| `mlx-community/whisper-tiny.en-asr-4bit` | 22 MB | Apache-2.0 | likely too inaccurate |

There is **no 4-bit Parakeet** in the `mlx-community` namespace (searched: only `parakeet-{tdt,ctc,rnnt}-*` full-size checkpoints plus `tdt_ctc-110m`). Other mlx_audio STT families (Moonshine, Phonon, Nemotron streaming) exist; not evaluated.
Whisper caveats: it hallucinates words on near-silence (`usable_transcript` filters only fillers) and Whisper checkpoints may want a different `generate` call path in mlx_audio (`.text` exists on both). Check word accuracy on real speech before keeping one, with the speaker filter and Alexa filter still working.

## Measure (Trevor)

Voice mode stays OFF for steps 1–3; nothing here turns it on.

```sh
cd ~/code/mynah   # wherever the repo is
sbcl --script tools/voice-measure.lisp            # RSS per voice process + timings from ~/Library/Logs/mynah-speakd.log
```

1. **Baseline, asleep** (`pkill -f mynah.speakd; ` then wait for nothing to run): expect no speakd line; then `hooks/claude-speak Start`, wait ~10 s, run it: speakd ~ several hundred MB (Kokoro) with mode off. Expected: the `Kokoro warm-up after (re)start` line is ~8 s.
2. **Time to first audio, mode off:** in the Jmacs left tmux pane let a reply be spoken (or `echo hello > ~/.local/state/mynah/inbox/.x && mv ~/.local/state/mynah/inbox/.x ~/.local/state/mynah/inbox/$(date +%s).1.say` with `voice-replies` flag present), re-run the script: `time to first audio` n≥1. Expected ≈ 0.3–1 s warm.
3. **After:** set `sleep_after=60` in the settings file, speak a reply, wait 70 s, run the script: the speakd line must say `[ASLEEP: models unloaded]` and RSS ≈ 75 MB. Then drop a reply in the inbox and note the `Warm-up done in` (that is the reload cost the shorter timeout adds to the next reply).
4. **Voice mode ON (Trevor turns it on himself, I did not):** run the script at idle for the full-load RSS; say a sentence and read `transcription` (expected ~0.6 s); turn the mode off with `unload_on_off=1` in the settings file and rerun: RSS should fall by the STT/VAD size, and the next `voice-mode on` logs `Voice models ready in X.Xs`. Switch `stt_model=` between candidates in the table the same way and compare RSS, `transcription` and the `page-out stalls logged` count after leaving the machine under memory pressure for an hour.
5. `footprint -p $(cat ~/.local/state/mynah/speakd.pid)` (also printed by the script) is the better memory number than RSS, since macOS compresses and swaps.

Tests that need no Mac: `PYTHONPATH=src python3 -m pytest tests/test_listen.py` (new `MemoryKnobsTest`), `sbcl --script tools/voice-measure.lisp /some/log`.
