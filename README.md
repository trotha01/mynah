# mynah

Reads Claude Code's latest reply out loud when you tap a hotkey. Named after
the mynah bird — famous for mimicking human speech clearly — as the
speaking-back sibling to [parakeet-dictation](https://github.com/trotha01/parakeet-dictation),
which listens.

## What it does

Tap **Right Option + Right Command**, and mynah:

1. Finds Claude Code's session transcript for whatever directory iTerm2's
   current tab is sitting in — switch tabs and mynah follows, reading
   whatever project you're now looking at. Falls back to the most recently
   modified transcript anywhere if iTerm2's tab can't be queried (not
   running, Automation permission not granted yet) or that directory has no
   transcript of its own.
2. Pulls the last assistant reply out of it (skipping subagent/sidechain
   output and tool-only turns with no text).
3. Strips it down for speech (drops markdown formatting, collapses fenced
   code blocks to "(code block)").
4. Reads it out loud via [Kokoro](https://huggingface.co/mlx-community/Kokoro-82M-bf16),
   running locally through [mlx-audio](https://github.com/Blaizzy/mlx-audio) —
   no network calls at read time, no API cost.

Tap Right Option + Right Command again while it's talking to stop immediately.

You can also trigger a read from the 🔊 menu-bar icon: **Read Latest
Message**.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/trotha01/mynah/main/install.sh | bash
```

Needs **Input Monitoring** permission (System Settings → Privacy &
Security) granted to whatever app you launch it from, so it can detect the
Right Option + Right Command hotkey globally. The installer opens that settings pane for
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
terminal tabs. mynah answers "what did Claude just say **here**" by asking
iTerm2 for the current tab's working directory and reading that project's
transcript — so the message it reads changes as you switch tabs, rather
than always being whichever session happened to type most recently. The
first time it does this, macOS will prompt you to grant Automation
permission for controlling iTerm2 (System Settings → Privacy & Security →
Automation); without it, mynah falls back to the most recently modified
transcript anywhere.

## Development

```bash
git clone https://github.com/trotha01/mynah.git
cd mynah
uv tool install --editable .
```

Edits to `src/mynah/` take effect on the next launch (editable install —
no reinstall needed).
