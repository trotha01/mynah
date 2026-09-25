"""Finds and reads the most recent assistant message across Claude Code
session transcripts on this machine.

Transcripts live at ~/.claude/projects/<escaped-cwd>/<session-id>.jsonl, one
line of JSON per event, where <escaped-cwd> is the session's working
directory with every "/" turned into "-" (e.g. /Users/trevor/Downloads ->
-Users-trevor-Downloads) — the same transform Claude Code itself uses, so
recomputing it from a directory reliably lands on the matching folder.

"Latest" prefers whatever's running in iTerm2's current tab: switching tabs
switches what mynah reads, by asking iTerm2 for that tab's cwd and looking
only at transcripts under that project directory. If iTerm2's cwd can't be
determined (not running, not frontmost, Automation permission not granted
yet) or that directory has no transcripts, it falls back to the most
recently modified .jsonl anywhere under projects/.
"""

import json
import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger("mynah")

PROJECTS_DIR = Path.home() / ".claude" / "projects"

_ITERM_CWD_SCRIPT = (
    'tell application "iTerm2" to tell current session of current window '
    'to return variable named "session.path"'
)


def _current_iterm_cwd() -> str | None:
    try:
        result = subprocess.run(
            ["osascript", "-e", _ITERM_CWD_SCRIPT],
            capture_output=True, text=True, timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.info(f"iTerm cwd query failed to run: {e}")
        return None
    if result.returncode != 0:
        logger.info(f"iTerm cwd query returned an error: {result.stderr.strip()}")
        return None
    cwd = result.stdout.strip() or None
    logger.info(f"iTerm current tab cwd: {cwd}")
    return cwd


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
    cwd = _current_iterm_cwd()
    if cwd:
        project_dir = PROJECTS_DIR / cwd.replace("/", "-")
        scoped = _latest_in(project_dir.glob("*.jsonl"))
        if scoped is not None:
            logger.info(f"Using transcript scoped to current tab: {scoped}")
            return scoped
        logger.info(f"No transcript found under {project_dir} — falling back to global latest")
    path = _latest_in(PROJECTS_DIR.glob("*/*.jsonl"))
    logger.info(f"Using globally latest transcript: {path}")
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
