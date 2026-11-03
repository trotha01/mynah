# Voice conversation with the Jmacs orchestrator: plan

Goal: hands-free loop with the Claude in tmux session `left`. It replies, the reply is spoken, mynah listens,
notices when Trevor stops talking, transcribes locally and submits the text with `jmacs ask`.
Barge-in: Trevor speaking cuts the reply off. Nothing happens unless voice-conversation mode is on.

## What exists (kb finding:90)
- Output: Stop hook `hooks/claude-speak` -> inbox -> resident `speakd.py` (Kokoro). UserPromptSubmit cuts speech off.
- Input: Parakeet Dictation.app, hold right Option (push-to-talk, types at the cursor).
- Gate for replies: `~/.config/jmacs/voice-replies` (deleted today on Trevor's request; stays deleted until he turns the mode on).

## What is missing
1. Nothing opens the microphone: no continuous listening, no end-of-speech detection.
2. Nothing sends text to the orchestrator except Parakeet typing at the cursor; need `jmacs ask "<text>"`.
3. Barge-in only exists for the push-to-talk key, not for speech.
4. No explicit conversation mode: `voice-replies` is a mute switch, not a "we are talking" switch.
5. Echo: the mic hears Kokoro through the speakers.

## Chosen pieces (all local, all already installed in the mynah venv except one model file)
- Where it runs: extend `speakd.py` (same process as the speaker, so it knows exactly when Kokoro is speaking).
  Python, because it must live next to Kokoro/mlx-audio; a Lisp rewrite would mean a second process plus IPC for
  the same models. (Trevor's Lisp rule: this needs his OK; asking in the note.)
- VAD / end of speech: Silero VAD (mlx-audio `vad/silero_vad`, 32 ms frames) with mlx-audio's `TurnDetector`
  (threshold 0.5, end of turn after ~900 ms of silence, 300 ms pre-roll). Needs one ~2 MB weight download
  (mlx-community silero-vad) - the only network step.
- STT: Parakeet TDT 0.6B v3 via mlx-audio (`mlx-community/parakeet-tdt-0.6b-v3`, already in the HF cache, the same
  model family as Dictation.app). Transcribe the finished utterance in one shot (~0.3 s warm for a few seconds).
- Mic: `sounddevice` InputStream 16 kHz mono (already a dependency).
- Submit: `jmacs ask "<text>"` (types into session `left` and sends). Tests use a throwaway tmux session
  (`JMACS_LEFT=jmtest`), never `left`.

## The toggle
- State file `~/.config/jmacs/voice-conversation` (present = on). It also implies replies are spoken
  (claude-speak treats it like `voice-replies`); `voice-replies` alone keeps working as before and never opens the mic.
- CLI: `hooks/voice-mode on|off|toggle|status`. Off removes the file immediately: the mic stream is closed within
  ~100 ms, an in-flight utterance is thrown away, speech stops.
- On/off is announced aloud ("Voice mode on / off"), plus a macOS notification.
- Spoken "stop listening" turns it off (the safe direction only); there is no spoken way to turn it on.
- Mode off = no mic stream open at all (the orange mic dot goes out), so nothing can be heard, let alone acted on.

## Loop
`off` -> (toggle on) -> `listening` -> speech start -> `hearing` -> 900 ms silence -> `transcribing` -> `jmacs ask`
-> `waiting` (orchestrator busy; mic still open for barge-in/next utterance) -> Stop hook drops the reply ->
`speaking` -> reply done -> `listening`.
- Barge-in: while speaking, ~250 ms of sustained speech above a stricter threshold stops Kokoro and starts capturing
  that utterance (the words that triggered it are kept).
- Filters: drop transcripts shorter than 2 words or Parakeet noise artifacts; ignore audio while the push-to-talk
  key is held (Dictation owns the mic then).
- Echo: with speakers the mic hears Kokoro. Plan: while speaking, the stricter threshold + a 1.5x-over-playback-level
  gate; best fix is headphones, or macOS voice-processing AEC (AVAudioEngine) as a second step if it still false-triggers.

## Permissions / risks
- Microphone permission (TCC) for `Mynah Speaker.app` (the app that launches speakd in the Aqua session). First run
  shows a prompt Trevor must click; I cannot do that for him.
- Mis-transcription goes straight to the orchestrator as a prompt. Mitigation: a short log of every submitted text
  at `~/Library/Logs/mynah-speakd.log`, and "scratch that" within the confirm window is not planned for v1.

## Tests (no live orchestrator)
- Unit: TurnDetector/endpointing with synthetic probabilities; mode-off never calls submit.
- Replay: recorded/`say`-generated wav fed through the same pipeline -> transcript.
- End to end: throwaway tmux session with `cat` as the "orchestrator", `JMACS_LEFT` pointing at it.

## Questions for Trevor
1. OK to extend the Python speakd (instead of a new Lisp tool)?
2. Headphones or laptop speakers while talking?
3. Silence length before I submit (default 0.9 s)?

## Outcome (built 2026-11-03; Trevor: Python is fine, both speakers and headphones)
- Built as planned: `src/mynah/listen.py` (Listener, Endpointer), wired into `speakd.py`; `hooks/voice-mode`;
  `hooks/claude-speak` gained `Start` and honours either flag file. Details in README.
- Changed from the plan: speakers = half-duplex (mic shut while a reply plays; key barge-in), headphones = voice
  barge-in, decided per reply from the output device name; added a -40 dBFS level gate and settings in the mode file.
- Measured: on laptop speakers Kokoro triggers its own barge-in within ~1 s, so voice barge-in there is not usable.
- Not verified: the microphone prompt through "Mynah Speaker.app" (needs Trevor's click), real headphones.

## Update: echo cancellation (2026-11-03)
- Trevor asked for voice barge-in on laptop speakers. A home-made level gate and NLMS filter were tried first and
  dropped (echo level varied 5x between replies); then existing work was used instead: WebRTC AEC3 via
  LiveKit's `AudioProcessingModule` (PyPI `livekit`, prebuilt arm64 wheel). Synthetic room: echo -43 dB in 1 s, a
  voice over it -2 dB. Real speakers: a 17 s reply played untouched, an interjection cut in and was transcribed.
- Found on the way: stopping an output stream while its last callback returns deadlocks CoreAudio (the reply
  never finished, later replies queued forever). Fixed by waiting 0.15 s after the drain and by keeping the audio
  callback light (the far-end feed runs on a worker thread).
