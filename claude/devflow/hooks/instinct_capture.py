#!/usr/bin/env python3.13
"""
Stop hook — automatically captures qualitative learnings from each session.

Reads session JSONL, extracts assistant messages, calls Haiku to distill
1-3 atomic learnings, and appends them to InstinctStore.

Always exits 0 — non-blocking.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import get_session_id, read_hook_stdin

sys.path.insert(0, str(Path(__file__).parent.parent))
from analysis.instinct_store import Instinct, InstinctStore

PROJECTS_DIR = Path.home() / ".claude" / "projects"
_DEFAULT_N_MESSAGES = 5
_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_MIN_TOOL_USES = 3

_EXTRACT_PROMPT = """\
You are reviewing a coding session transcript.
Extract 1-3 atomic learnings that should be remembered
for future sessions in this project.
Each learning must be:
- Specific and actionable (not generic advice)
- Grounded in what actually happened in this session
- 1-3 sentences maximum

For each learning, respond with JSON array:
[{
  "content": "...",
  "confidence": 0.3-0.9,
  "category": "pattern|preference|convention|pitfall"
}]

Respond ONLY with the JSON array. No preamble."""


def _cwd_to_slug(cwd: str) -> str:
    return cwd.replace("/", "-")


def _find_session_jsonl(session_id: str, cwd: str) -> Path | None:
    slug = _cwd_to_slug(cwd)
    candidate = PROJECTS_DIR / slug / f"{session_id}.jsonl"
    return candidate if candidate.exists() else None


_JSONL_LINE_LIMIT = 2000  # max lines to parse — avoids O(n) on huge sessions


def _tail_file_lines(path: Path, n: int) -> list[str]:
    """Read last N lines without loading the entire file into memory."""
    chunk = 16384
    lines: list[str] = []
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            remaining = f.tell()
            buf = b""
            while remaining > 0 and len(lines) < n:
                read_size = min(chunk, remaining)
                remaining -= read_size
                f.seek(remaining)
                buf = f.read(read_size) + buf
                lines = buf.decode("utf-8", errors="ignore").splitlines()
        return lines[-n:]
    except Exception:
        return []


def _parse_transcript(jsonl_path: Path, n_messages: int) -> tuple[int, list[str]]:
    """
    Parse session JSONL — reads only the last _JSONL_LINE_LIMIT lines.
    Returns (tool_use_count, last_n_assistant_text_messages).
    """
    tool_use_count = 0
    assistant_texts: list[str] = []

    for line in _tail_file_lines(jsonl_path, _JSONL_LINE_LIMIT):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if entry.get("type") != "assistant":
            continue

        content = entry.get("message", {}).get("content", [])
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "tool_use":
                tool_use_count += 1
            elif item.get("type") == "text":
                text = item.get("text", "").strip()
                if text:
                    assistant_texts.append(text)

    return tool_use_count, assistant_texts[-n_messages:]


_HAIKU_TIMEOUT = 30
_HAIKU_MAX_RETRIES = 2
_HAIKU_RETRY_DELAY = 5  # seconds between retries


def _call_haiku(transcript_text: str) -> list[dict]:
    """
    Calls `claude -p` with Haiku model. Retries once with backoff on timeout.

    Without retry, a transient 30s timeout causes instinct_capture to silently
    drop all learning from a session. Two attempts cover 95%+ of cold-start cases.
    """
    prompt = f"{_EXTRACT_PROMPT}\n\nSession transcript:\n{transcript_text}"
    cmd = ["claude", "-p", prompt, "--model", _HAIKU_MODEL]
    last_exc: Exception = subprocess.SubprocessError("no attempts made")

    for attempt in range(_HAIKU_MAX_RETRIES):
        if attempt > 0:
            time.sleep(_HAIKU_RETRY_DELAY)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=_HAIKU_TIMEOUT,
                env={**os.environ, "DEVFLOW_JUDGE_SUBPROCESS": "1"},
            )
        except subprocess.TimeoutExpired as exc:
            last_exc = subprocess.SubprocessError(f"timeout after {_HAIKU_TIMEOUT}s (attempt {attempt + 1})")
            continue
        if result.returncode != 0:
            raise subprocess.SubprocessError(
                f"claude exit {result.returncode}: {result.stderr[:200]}"
            )
        raw = result.stdout.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:])
            if raw.endswith("```"):
                raw = raw[:-3].strip()
        return json.loads(raw)

    raise last_exc


def main() -> int:
    # Skip condition 0: running inside a judge/instinct subprocess — prevents re-entrant loops
    if os.environ.get("DEVFLOW_JUDGE_SUBPROCESS") == "1":
        print("[devflow:instinct] skipped (subprocess guard)", file=sys.stderr)
        return 0

    # Skip condition 1: env var override
    if os.environ.get("DEVFLOW_INSTINCT_SKIP", "").strip() == "1":
        return 0

    hook_data = read_hook_stdin()
    session_id = hook_data.get("session_id") or get_session_id()
    cwd = hook_data.get("cwd") or os.getcwd()
    project = Path(cwd).name or cwd

    # Skip condition 2: meta-capture
    if project == "devflow":
        return 0

    if not session_id or session_id == "default":
        print("[devflow:instinct] skip: no session_id", file=sys.stderr)
        return 0

    n_messages = int(os.environ.get("DEVFLOW_INSTINCT_MESSAGES", _DEFAULT_N_MESSAGES))

    jsonl_path = _find_session_jsonl(session_id, cwd)
    if not jsonl_path:
        print("[devflow:instinct] skip: session JSONL not found", file=sys.stderr)
        return 0

    try:
        tool_use_count, assistant_texts = _parse_transcript(jsonl_path, n_messages)
    except OSError as e:
        print(f"[devflow:instinct] skip: {e}", file=sys.stderr)
        return 0

    # Skip condition 3: session too short
    if tool_use_count < _MIN_TOOL_USES:
        print(
            f"[devflow:instinct] skip: too few tool uses ({tool_use_count})",
            file=sys.stderr,
        )
        return 0

    if not assistant_texts:
        print("[devflow:instinct] skip: no assistant text found", file=sys.stderr)
        return 0

    transcript_text = "\n\n---\n\n".join(assistant_texts)

    try:
        raw_instincts = _call_haiku(transcript_text)
    except Exception as e:
        print(f"[devflow:instinct] skip: LLM error: {e}", file=sys.stderr)
        return 0

    if not isinstance(raw_instincts, list):
        print("[devflow:instinct] skip: unexpected LLM response format", file=sys.stderr)
        return 0

    store = InstinctStore()
    now = datetime.now(tz=timezone.utc).isoformat()
    captured = 0

    for item in raw_instincts:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        category = str(item.get("category", "pattern"))

        instinct = Instinct(
            id=uuid.uuid4().hex[:8],
            project=project,
            captured_at=now,
            session_id=session_id,
            content=content,
            confidence=max(0.3, min(0.9, confidence)),
            category=category,
            status="pending",
            promoted_to=None,
        )
        try:
            store.append(instinct)
            captured += 1
        except OSError as e:
            print(f"[devflow:instinct] warning: append failed: {e}", file=sys.stderr)

    if captured > 0:
        print(f"[devflow:instinct] captured {captured} instinct(s) for {project}", file=sys.stderr)
        # Record in TelemetryStore (best-effort)
        try:
            from telemetry.store import TelemetryStore
            TelemetryStore().record({
                "task_id": session_id,
                "instincts_captured_count": captured,
            })
        except Exception as exc:
            print(f"[devflow:instinct] warning: telemetry write failed: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
