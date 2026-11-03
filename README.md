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
  Only modifier hotkeys are watched. Talking over the speech by voice is voice-conversation mode's barge-in
  (below), which only works with headphones: on laptop speakers the microphone hears Kokoro itself.

## Voice conversation with the orchestrator (src/mynah/listen.py + hooks/voice-mode)

A hands-free loop with the `claude` in tmux session `left`: it replies, the reply is spoken, mynah listens,
notices when you stop talking, transcribes locally and submits the text with `jmacs ask`. All local: Silero VAD
and Parakeet TDT 0.6B v3 (both via mlx-audio, run inside speakd next to Kokoro).

- **Toggle:** `hooks/voice-mode on|off|toggle|status`. The mode is the file `~/.config/jmacs/voice-conversation`
  (present = on). It is announced aloud. **While it is off the microphone is not open at all** - speech is neither
  recorded nor acted on - and an utterance still being transcribed when you switch off is thrown away.
  Saying exactly "stop listening" / "voice mode off" also turns it off; nothing spoken can turn it on.
  The mode also makes the Stop hook speak replies (like `voice-replies`, which only speaks and never listens).
- **Loop:** `listening` -> `hearing` -> ~0.9 s of silence -> `transcribing` -> `jmacs ask` (a Tink sound) ->
  `waiting` -> reply `speaking` -> `listening`. `hooks/voice-mode status` shows the state.
- **Barge-in:** with headphones (output named headphones/AirPods/buds/headset...) the mic stays open during a reply
  and ~0.25 s of strong speech cuts it off and becomes your next utterance. On speakers the mic is shut while a
  reply plays (measured: Kokoro barges in on itself within a second otherwise) and the barge-in is holding right
  Option, as before. The choice is made per reply from the output device.
- **Ignored:** blips, fillers ("mm-hmm", "uh"), and utterances quieter than -40 dBFS (people talking across the
  room measured -37 to -60 dBFS; speaking at the laptop measured -19 to -35). Everything heard and sent is in the log.
- **Settings:** optional `name=value` lines in the mode file, read each time it is switched on:
  `min_level_db=-35`, `silence=1.2`, `barge_in=voice|key`.
- **Permission:** macOS asks for microphone access for "Mynah Speaker" the first time the mode is switched on
  (`hooks/build-speaker-app` adds the usage text; rebuild it after pulling).
- **Caution:** it hears everyone in earshot. Switch it off before talking to someone else or taking a call.
- **Tests:** `~/.local/share/uv/tools/mynah/bin/python -m unittest discover -s tests` (no models needed), and
  `tests/replay_listen.py` (real models, `say`-generated audio in place of the mic). Never test against `left`:
  use a throwaway tmux session with `JMACS_LEFT=jmtest` (`jmacs ask` honours it).
