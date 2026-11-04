# mynah

Reads Claude Code's latest reply out loud when you tap a hotkey. Named after
the mynah bird — famous for mimicking human speech clearly — as the
speaking-back sibling to [parakeet-dictation](https://github.com/trotha01/parakeet-dictation),
which listens.

## What it does

Tap **Right Shift + Right Command**, and mynah:

1. Finds the exact Claude Code session running in iTerm2's current tab —
   switch tabs and mynah follows. It resolves this precisely (which `claude`
   process is attached to that tab's tty, then that process's own session
   state), not just by matching directories, since two tabs can share a cwd
   (e.g. one resumed via `claude -r` from a directory another tab is
   already in) and directory-matching alone can't tell those apart. Falls
   back to the most recently modified transcript under that tab's directory,
   then to the most recently modified transcript anywhere, if iTerm2's tab
   can't be determined at all.
2. Pulls the last assistant reply out of it (skipping subagent/sidechain
   output and tool-only turns with no text).
3. Strips it down for speech (drops markdown formatting, collapses fenced
   code blocks to "(code block)").
4. Reads it out loud via [Kokoro](https://huggingface.co/mlx-community/Kokoro-82M-bf16),
   running locally through [mlx-audio](https://github.com/Blaizzy/mlx-audio) —
   no network calls at read time, no API cost.

Tap Right Shift + Right Command again while it's talking to stop immediately.

You can also trigger a read from the 🔊 menu-bar icon: **Read Latest
Message**.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/trotha01/mynah/main/install.sh | bash
```

Needs **Input Monitoring** permission (System Settings → Privacy &
Security) granted to whatever app you launch it from, so it can detect the
Right Shift + Right Command hotkey globally. The installer opens that settings pane for
you. Nothing else — mynah doesn't type at your cursor or read the
microphone, so it doesn't need Accessibility or Microphone access.

## Run

```bash
mynah
```

Look for 🔊 in your menu bar. First launch downloads the Kokoro model
(~350MB) from Hugging Face; after that it's instant.

## Configuration (env vars)

| Variable       | Default                          | What it does                         |
|----------------|-----------------------------------|---------------------------------------|
| `MYNAH_MODEL`  | `mlx-community/Kokoro-82M-bf16`   | Which MLX TTS model to load           |
| `MYNAH_VOICE`  | `af_heart`                        | Kokoro voice preset                   |
| `MYNAH_SPEED`  | `1.0`                             | Playback speed multiplier             |

## Why it follows your iTerm2 tab

You typically have several Claude Code sessions open across different
terminal tabs — sometimes even sharing the same working directory (a tab
resumed with `claude -r` from a directory another tab is already sitting
in). mynah answers "what did Claude just say **here**" by asking iTerm2 for
the current tab's tty, finding the specific `claude` process attached to
it, and reading that exact process's own session id from Claude Code's
`~/.claude/sessions/<pid>.json` state — so the message it reads changes as
you switch tabs, rather than always being whichever session happened to
type most recently. The first time it does this, macOS will prompt you to
grant Automation permission for controlling iTerm2 (System Settings →
Privacy & Security → Automation); without it, mynah falls back to the most
recently modified
transcript anywhere.

## Development

```bash
git clone https://github.com/trotha01/mynah.git
cd mynah
uv tool install --editable .
```

Edits to `src/mynah/` take effect on the next launch (editable install —
no reinstall needed).

## Hands-free replies for the Jmacs orchestrator (speakd + hooks/claude-speak)

The hotkey reader above follows the iTerm2 tab; this half speaks every reply of the Jmacs orchestrator
(the `claude` in tmux session `left`) the moment it finishes, with no hotkey and no terminal lookup.

- `src/mynah/speakd.py` keeps Kokoro loaded and warm (a cold first generation takes ~8 s, a warm one starts
  speaking in ~0.5 s) and watches `~/.local/state/mynah/inbox/`. A `.say` file is spoken (a newer one cuts the
  old one off); a `.stop` file stops speech. Long replies are cut at a sentence after ~700 characters
  (`MYNAH_MAX_CHARS`) with "The rest is on screen." It exits after 2 idle hours (`MYNAH_IDLE_EXIT`).
- `hooks/claude-speak` is the Claude Code hook: `Stop` writes the reply (`last_assistant_message`) to the inbox
  and starts speakd if it is not running; `UserPromptSubmit` writes a `.stop`, so a new prompt interrupts speech.
  Other sessions (workers, other tabs) stay silent.
- Registered in `~/.claude/settings.json` under `Stop` and `UserPromptSubmit`
  (`$HOME/src/mynah/hooks/claude-speak Stop` / `... UserPromptSubmit`). Claude Code reads hooks at startup, so a
  running session needs `/hooks` (review) or a restart to pick them up.
- Mute: `rm ~/.config/jmacs/voice-replies`; unmute: `touch ~/.config/jmacs/voice-replies`.
- Log: `~/Library/Logs/mynah-speakd.log`. Stop it now: `kill $(cat ~/.local/state/mynah/speakd.pid)`.
- Input side: parakeet-dictation (hold right Option, words type at the cursor).
- Hold-to-talk: while you hold parakeet-dictation's push-to-talk key (read from its saved setting, Right Option by
  default), speakd stops speaking and keeps new replies quiet until you let go, so the microphone does not hear
  Kokoro. It polls the modifier flags (`CGEventSourceFlagsState`, ~10 Hz) rather than listening with an event
  tap, which would need Accessibility/Input Monitoring (pynput reports "This process is not trusted"); the
  flags need no permission. Two things make that work, both found with the real key on macOS 26:
  - Only the flags change. `CGEventSourceKeyState` and `NSEvent.modifierFlags` stay false.
  - Only in the desktop (Aqua) session. The tmux server, and every hook it runs, is in the Background
    session (`launchctl managername`), where nothing changes. So `hooks/claude-speak` starts speakd through
    "Mynah Speaker.app" (`open -g`), a tiny applet that LaunchServices runs in the desktop session; build it
    once with `hooks/build-speaker-app` (source: `hooks/speaker.applescript`, installed in
    `~/.local/share/mynah/`). Without the app, replies still speak but hold-to-talk does not. The speakd log
    says which session it runs in.
  Only modifier hotkeys are watched. Talking over the speech by voice is voice-conversation mode's barge-in (below).
  `kill -USR1 $(cat ~/.local/state/mynah/speakd.pid)` writes every thread's stack to the log (hang diagnosis).

## Voice conversation with the orchestrator (src/mynah/listen.py + hooks/voice-mode)

A hands-free loop with the `claude` in tmux session `left`: it replies, the reply is spoken, mynah listens,
notices when you stop talking, transcribes locally and submits the text with `jmacs ask`. All local: Silero VAD
and Parakeet TDT 0.6B v3 (both via mlx-audio, run inside speakd next to Kokoro).

- **Toggle:** `hooks/voice-mode on|off|toggle|enroll|status`. **Off stays off:** only Trevor turns it on; nothing in
  this repo re-enables it (enroll and the tests leave it off), and from inside a Claude Code session `on` is refused
  unless given `--yes` (= Trevor asked for it just now). Every on/off/refusal is logged with its caller in
  `~/.local/state/mynah/voice-mode.log`. The mode is the file `~/.config/jmacs/voice-conversation`
  (present = on). It is announced aloud. **While it is off the microphone is not open at all** - speech is neither
  recorded nor acted on - and an utterance still being transcribed when you switch off is thrown away.
  Saying exactly "stop listening" / "voice mode off" also turns it off; nothing spoken can turn it on.
  The mode also makes the Stop hook speak replies (like `voice-replies`, which only speaks and never listens).
- **Loop:** `listening` -> `hearing` -> ~0.9 s of silence -> `transcribing` -> `jmacs ask` (a Tink sound) ->
  `waiting` -> reply `speaking` -> `listening`. `hooks/voice-mode status` shows the state.
- **Barge-in:** the mic stays open while a reply plays and ~0.25 s of strong speech cuts it off and becomes your
  next utterance. On speakers the mic signal first goes through **WebRTC AEC3** (the echo canceller in Chrome and
  LiveKit, via the `livekit` package; `src/mynah/aec.py`), fed with everything mynah plays, so Kokoro does not
  barge in on itself (without it it did, within a second) and the transcript of what you said over it is clean.
  Headphones skip the canceller. `barge_in=voice|echo|key` in the mode file overrides the choice; `key` shuts the
  mic during replies and leaves holding right Option as the only interruption.
- **Ignored:** blips, fillers ("mm-hmm", "uh"), and utterances quieter than -40 dBFS (people talking across the
  room measured -37 to -60 dBFS; speaking at the laptop measured -19 to -35). Everything heard and sent is in the log.
- **Only your voice (optional):** `hooks/voice-mode enroll` (about a minute: read six sentences after the tone;
  pauses the mode meanwhile) stores your voiceprint; add `speaker=on` to `~/.config/jmacs/voice-settings` and utterances that do not
  match it are logged ("Voice match 0.31: someone else, ignored") and never sent. Uses SpeechBrain's ECAPA-TDNN
  (`src/mynah/speaker_id.py`); `speaker_threshold=0.5` tunes it. With macOS voices the same voice scored
  0.67-0.88, other voices 0.01-0.44. Short utterances score noisier; a recording of you would pass; interrupting a
  reply is not voice-checked, only what is then sent.
- **Settings:** optional `name=value` lines in `~/.config/jmacs/voice-settings` (not the mode file: switching off deletes that), read each time it is switched on:
  `min_level_db=-35`, `silence=1.2`, `barge_in=voice|key`.
- **Permission:** macOS asks for microphone access for "Mynah Speaker" the first time the mode is switched on
  (`hooks/build-speaker-app` adds the usage text; rebuild it after pulling).
- **Caution:** it hears everyone in earshot. Switch it off before talking to someone else or taking a call.
- **Tests:** `~/.local/share/uv/tools/mynah/bin/python -m unittest discover -s tests` (no models; the echo test
  uses macOS `say`), and
  `tests/replay_listen.py` (real models, `say`-generated audio in place of the mic). Never test against `left`:
  use a throwaway tmux session with `JMACS_LEFT=jmtest` (`jmacs ask` honours it).

## J, the voice companion

`hooks/companion open` shows J (a little robot) in the Jmacs web view; `companion split` puts it in its own pane. It is a
read-only page served by `companion/companion.lisp` (port 8860): it follows `~/.local/state/mynah/voice-state`
(asleep only when the voice-mode flag file is absent, i.e. `voice-mode status` says off; listening, hearing, thinking, speaking) and moves its mouth to
`~/.local/state/mynah/voice-level`, the RMS of the audio speakd is playing (`write_level` in `speakd.py`). Speech cut off
by you (speaking, then hearing) makes it jump. J's eyes blink, glance around while thinking, squint and raise its brows on emphasis in the speech, and widen on a question (speakd writes `voice-say-kind`: just the word question or statement) or on barge-in; waiting and idle are a calm breathing. `?demo=speaking` previews a state without the voice loop.

J also announces worker sessions. `companion.lisp` polls todoview (`GET :8850/api/items`, the same todo.org tags the
`jmacs todo-status` hooks set) and, when a worker's tag changes to waiting, done, needs_you or blocked, shows a note
bubble and a matching expression, using the :SHORT: name ("Saint videos is waiting for you"). With voice mode on it
also speaks the line, by writing a `.say` file into the speaker inbox, only after the state has been `listening` for
2.5 s with no audio and nothing queued in the inbox, so it never talks over a reply or over you. Several pending
workers are grouped into one line, lines older than 90 s are dropped, the same worker and tag is ignored for 90 s,
the orchestrator (window `left`) is skipped, and nothing is queued for speech while voice mode is off. The first poll
after a start only records the current tags.

### Looks

`http://127.0.0.1:8860/looks` compares five alternative looks for J (Mochi, Sprout, Nimbus, Kit, Orbit), each animating through
the same states. `companion/engine.js` is the shared expression engine (states, blinks, glances, emphasis squint, brows,
mouth from the audio level, thinking dots, worker-news reactions); `companion/looks.js` holds one SVG + `apply()` per look.
Buttons pick a state, "Auto tour" cycles all of them, "Live" follows the real voice loop. `?state=speaking&cycle=0&warm=1`
renders one settled state (used for screenshots); `?look=kit` shows a single look. The main page (`/`) is still the robot.

### Expressions, timing and the looks

`companion/engine.js` is the shared expression engine. It holds one expression from a fixed set (neutral, listening, thinking,
happy, speaking, surprised, concerned, sleep). It never flickers: a state must last 300 ms before the face reacts (blips are
ignored), and a shown expression is held 0.4 to 1.4 s so it can be read before the face changes again; transitions themselves are
quick (~120 ms). Blinks come every 3 to 6.5 s (about 170 ms, sometimes a double blink, not in the middle of a loud word), glances
every 1.6 to 3.5 s, and the mouth shape (a/e/i/o/u) is picked once per syllable. A barge-in is speaking turning into hearing
and staying there.

Looks: `looks.js` (five early looks), `anime.js` (the robot, Hana, Mio, Yuki, and the robot x anime blends Hana-01, Hana-02, Hana-03).
`/looks` shows each with an expression sheet; `/` is the live panel and shows `DEFAULT_LOOK` (Hana-02, "half and half", chosen by Trevor as J), or `/?look=robot` etc. to
preview another.

### Lip sync (J's mouth)

The mouth follows the words, not just the loudness. `speakd` drives Kokoro's pipeline directly and takes the phoneme string and the
per-phoneme durations Kokoro already predicts (one frame = 25 ms) for each chunk; `src/mynah/viseme.py` turns them into mouth events
in six anime shapes (M closed for m/b/p and pauses, A, E, I, O, U), grouped like Rhubarb Lip Sync's mouth shapes, with diphthongs
gliding between two shapes, short stretches merged so the mouth changes about 5 times a second, and the opening scaled by how loud
that stretch of the audio really is. `src/mynah/lipsync.py` timestamps every event with the moment it reaches the speaker (the
audio callback only records PortAudio's output time; a thread writes `~/.local/state/mynah/voice-visemes` atomically every 20 ms
with the next 0.7 s of events). `companion.lisp` passes that file to the page in `/api/s` as `vis`, and `engine.js` shows whichever
event is current at the page's clock, so polling delay and block size no longer matter. With no schedule (pipeline unavailable)
the mouth falls back to loudness. `/?lag=40` delays the mouth by 40 ms (negative = earlier) if a Bluetooth speaker needs it.
Measured (laptop speakers): output latency 48 ms, audio blocks 85 ms, the mouth switches within about one frame (median 24 ms) of
each event, events reach the page ~0.6 s before they are due.
