"""Finds and reads the most recent assistant message across Claude Code
session transcripts on this machine.

Transcripts live at ~/.claude/projects/<escaped-cwd>/<session-id>.jsonl, one
line of JSON per event, where <escaped-cwd> is the session's working
directory with every "/" turned into "-" (e.g. /Users/trevor/Downloads ->
-Users-trevor-Downloads).

"Latest" follows iTerm2's current tab, resolved as precisely as possible:

1. Exact match — ask iTerm2 for the current tab's tty, find the `claude`
   process attached to that tty, and read ITS sessionId straight out of
   Claude Code's own ~/.claude/sessions/<pid>.json state file. This is the
   only reliable way to tell two Claude Code sessions apart when they
   happen to share a cwd (e.g. one tab resumed via `claude -r` from the
   same directory another tab is already sitting in) — matching by
   directory alone can't distinguish them, and picking "whichever file in
   that directory was modified most recently" just favors whichever
   session happens to be more chatty at the moment, not whichever tab
   you're actually looking at.
2. Falls back to the most recently modified transcript under that tab's
   own cwd, if step 1 didn't resolve (no claude process on that tty, or its
   session state file is missing/stale).
3. Falls back to the most recently modified transcript anywhere under
   projects/, if iTerm2's tab itself can't be determined at all (not
   running, Automation permission not granted yet).
"""

import json
import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger("mynah")

PROJECTS_DIR = Path.home() / ".claude" / "projects"
SESSIONS_DIR = Path.home() / ".claude" / "sessions"


def _run_osascript(script: str) -> str | None:
    try:
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.info(f"osascript query failed to run: {e}")
        return None
    if result.returncode != 0:
        logger.info(f"osascript query returned an error: {result.stderr.strip()}")
        return None
    return result.stdout.strip() or None


def _current_iterm_cwd() -> str | None:
    return _run_osascript(
        'tell application "iTerm2" to tell current session of current window '
        'to return variable named "session.path"'
    )


def _current_iterm_tty() -> str | None:
    return _run_osascript(
        'tell application "iTerm2" to tell current session of current window to return tty'
    )


def _claude_pid_for_tty(tty: str) -> int | None:
    """The PID of the `claude` CLI process attached to this tty, if any — a
    tty can have other processes too (the shell, tool subprocesses), so
    only a process whose own command is exactly "claude" or "claude <args>"
    counts."""
    tty_name = tty.removeprefix("/dev/")
    try:
        result = subprocess.run(
            ["ps", "-t", tty_name, "-o", "pid=,command="],
            capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        pid_str, _, command = line.partition(" ")
        if command == "claude" or command.startswith("claude "):
            try:
                return int(pid_str)
            except ValueError:
                continue
    return None


def _transcript_for_pid(pid: int) -> Path | None:
    state_path = SESSIONS_DIR / f"{pid}.json"
    try:
        data = json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    session_id, cwd = data.get("sessionId"), data.get("cwd")
    if not session_id or not cwd:
        return None
    path = PROJECTS_DIR / cwd.replace("/", "-") / f"{session_id}.jsonl"
    return path if path.exists() else None


def _latest_in(paths) -> Path | None:
    latest = None
    latest_mtime = -1.0
    for path in paths:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > latest_mtime:
            latest_mtime = mtime
            latest = path
    return latest


def _latest_transcript_path() -> Path | None:
    tty = _current_iterm_tty()
    cwd = _current_iterm_cwd()
    logger.info(f"iTerm current tab: tty={tty} cwd={cwd}")

    if tty:
        pid = _claude_pid_for_tty(tty)
        if pid is not None:
            exact = _transcript_for_pid(pid)
            if exact is not None:
                logger.info(f"Using exact transcript for claude pid {pid} on this tab: {exact}")
                return exact
            logger.info(f"No usable session state for claude pid {pid} on this tab")
        else:
            logger.info(f"No claude process found on tty {tty}")

    if cwd:
        project_dir = PROJECTS_DIR / cwd.replace("/", "-")
        scoped = _latest_in(project_dir.glob("*.jsonl"))
        if scoped is not None:
            logger.info(f"Using transcript scoped to current tab's cwd: {scoped}")
            return scoped
        logger.info(f"No transcript found under {project_dir}")

    path = _latest_in(PROJECTS_DIR.glob("*/*.jsonl"))
    logger.info(f"Falling back to globally latest transcript: {path}")
    return path


def _extract_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = [block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"]
    return "".join(parts).strip()


def latest_assistant_text() -> str | None:
    """The most recent assistant reply's text, or None if nothing readable was found.

    Skips sidechain entries (subagent-internal output, not a reply to the
    user) and assistant turns that carry no text block (pure tool-use turns)
    — those aren't "the latest message" in any meaningful sense.
    """
    path = _latest_transcript_path()
    if path is None:
        return None

    last_text = None
    try:
        with path.open(encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue  # last line of a session still being written can be a partial write
                if obj.get("type") != "assistant" or obj.get("isSidechain"):
                    continue
                text = _extract_text(obj.get("message", {}))
                if text:
                    last_text = text
    except OSError:
        return None

    return last_text


_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_ITALIC_RE = re.compile(r"(\*\*\*|\*\*|\*|___|__|_)(.+?)\1")
_HEADER_RE = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+", re.MULTILINE)
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def strip_markdown_for_speech(text: str) -> str:
    """Rough markdown -> plain-speech cleanup so Kokoro doesn't read out
    literal asterisks, hashes, and link brackets. Not a full markdown
    parser — good enough for how Claude actually formats replies."""
    text = _FENCED_CODE_RE.sub(" (code block) ", text)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _BOLD_ITALIC_RE.sub(r"\2", text)
    text = _HEADER_RE.sub("", text)
    text = _LINK_RE.sub(r"\1", text)
    text = _LIST_MARKER_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()
