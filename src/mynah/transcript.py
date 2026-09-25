"""Finds and reads the most recent assistant message across all Claude Code
session transcripts on this machine.

Transcripts live at ~/.claude/projects/<escaped-cwd>/<session-id>.jsonl, one
line of JSON per event. "Latest" is defined globally (the most recently
modified .jsonl file anywhere under projects/, not just the current one) —
mynah is meant to answer "what did Claude just say", regardless of which
project/terminal that was in.
"""

import json
import re
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"


def _latest_transcript_path() -> Path | None:
    candidates = PROJECTS_DIR.glob("*/*.jsonl")
    latest = None
    latest_mtime = -1.0
    for path in candidates:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime > latest_mtime:
            latest_mtime = mtime
            latest = path
    return latest


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
