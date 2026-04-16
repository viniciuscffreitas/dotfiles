"""JSONL transcript reader — enumerates Claude Code session files.

Claude Code writes one JSONL per session under `~/.claude/projects/<slug>/<session_id>.jsonl`.
Each line is an event (user, assistant, tool_use, tool_result, queue-operation, etc.).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator


CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"

# Edit tools that count toward thrashing. Case-insensitive substring match.
EDIT_TOOL_NAMES = ("edit", "write", "multiedit", "notebookedit")


def iter_transcript_events(path: Path) -> Iterator[dict]:
    """Yield one parsed dict per valid JSON line. Malformed lines are skipped."""
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return
    with handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def iter_project_transcripts(projects_dir: Path = CLAUDE_PROJECTS_DIR) -> Iterator[Path]:
    """Yield every `.jsonl` transcript under `~/.claude/projects/`."""
    if not projects_dir.is_dir():
        return
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        for transcript in project_dir.glob("*.jsonl"):
            yield transcript


def extract_tool_uses(events: list[dict]) -> list[dict]:
    """Return tool_use blocks (dicts with name/input) from assistant events."""
    uses: list[dict] = []
    for event in events:
        if event.get("type") != "assistant":
            continue
        content = (event.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                uses.append(block)
    return uses


def iter_tool_results(events: list[dict]) -> Iterator[dict]:
    """Yield tool_result blocks (may appear in user events as arrays)."""
    for event in events:
        if event.get("type") != "user":
            continue
        content = (event.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                yield block


def is_edit_tool(tool_name: str) -> bool:
    """True if tool name matches one of EDIT_TOOL_NAMES (case-insensitive)."""
    lower = tool_name.lower()
    return any(needle in lower for needle in EDIT_TOOL_NAMES)


def extract_file_path(tool_input: dict) -> str | None:
    """Claude Code edit tools use varied key names — check all of them."""
    for key in ("file_path", "path", "filePath", "target_file", "file"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return None
