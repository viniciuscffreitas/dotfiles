"""
Stop hook — scans session JSONL and records per-phase token telemetry.

Detects active-spec.json writes (via Write tool or Bash command) and correlates
them with cumulative token usage to measure tokens spent per spec phase:

  PENDING → IMPLEMENTING : understand/plan phase
  IMPLEMENTING → COMPLETED: build/verify phase

Output: ~/.claude/devflow/telemetry/sessions.jsonl
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from _util import get_session_id, read_hook_stdin

TELEMETRY_DIR = Path.home() / ".claude" / "devflow" / "telemetry"
PROJECTS_DIR = Path.home() / ".claude" / "projects"


def _cwd_to_slug(cwd: str) -> str:
    return cwd.replace("/", "-")


def _project_name(cwd: str) -> str:
    return Path(cwd).name or cwd


def _tokens_for(usage: dict) -> int:
    return (
        usage.get("input_tokens", 0)
        + usage.get("cache_creation_input_tokens", 0)
        + usage.get("cache_read_input_tokens", 0)
        + usage.get("output_tokens", 0)
    )


def _parse_phase_from_write(inp: dict) -> tuple[Optional[str], Optional[str]]:
    """Extract (phase, task_id) from a Write tool_use input targeting active-spec.json."""
    if Path(inp.get("file_path", "")).name != "active-spec.json":
        return None, None
    try:
        spec = json.loads(inp.get("content", "{}"))
        return spec.get("status"), spec.get("plan_path") or spec.get("task_id")
    except (json.JSONDecodeError, TypeError):
        return None, None


def _parse_phase_from_bash(inp: dict) -> Optional[str]:
    """Extract phase from a Bash command that writes active-spec.json."""
    cmd = inp.get("command", "")
    if "active-spec.json" not in cmd:
        return None
    for status in ("PENDING", "IMPLEMENTING", "COMPLETED", "PAUSED"):
        if status in cmd:
            return status
    return None


def parse_session(jsonl_path: Path) -> dict:
    """
    Parse session JSONL and return phase markers with cumulative tokens.

    Returns:
        phases: list of {ts, phase, task_id, tokens_cumulative}
        total_tokens: int
    """
    phase_events: list[tuple[str, str, Optional[str], int]] = []
    running = 0

    with open(jsonl_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            if entry.get("type") != "assistant":
                continue

            ts = entry.get("timestamp", "")
            usage = entry.get("message", {}).get("usage", {})
            if usage:
                running += _tokens_for(usage)

            for item in entry.get("message", {}).get("content", []):
                if not isinstance(item, dict) or item.get("type") != "tool_use":
                    continue
                name = item.get("name", "")
                inp = item.get("input", {})

                if name == "Write":
                    phase, task_id = _parse_phase_from_write(inp)
                    if phase:
                        phase_events.append((ts, phase, task_id, running))
                elif name == "Bash":
                    phase = _parse_phase_from_bash(inp)
                    if phase:
                        phase_events.append((ts, phase, None, running))

    return {
        "phases": [
            {"ts": ts, "phase": phase, "task_id": task_id, "tokens_cumulative": cum}
            for ts, phase, task_id, cum in phase_events
        ],
        "total_tokens": running,
    }


def _find_session_jsonl(session_id: str, cwd: str) -> Optional[Path]:
    slug = _cwd_to_slug(cwd)
    candidate = PROJECTS_DIR / slug / f"{session_id}.jsonl"
    return candidate if candidate.exists() else None


def main() -> int:
    hook_data = read_hook_stdin()
    session_id = hook_data.get("session_id") or get_session_id()
    cwd = hook_data.get("cwd") or os.getcwd()

    if not session_id or session_id == "default":
        print("[devflow:telemetry] skip: no session_id (hook not invoked by Claude Code)", file=sys.stderr)
        return 0

    jsonl_path = _find_session_jsonl(session_id, cwd)
    if not jsonl_path:
        slug = _cwd_to_slug(cwd)
        print(f"[devflow:telemetry] skip: JSONL not found — {PROJECTS_DIR / slug / f'{session_id}.jsonl'}", file=sys.stderr)
        return 0

    try:
        result = parse_session(jsonl_path)
    except OSError:
        return 0

    if not result["phases"]:
        print(f"[devflow:telemetry] skip: no active-spec.json writes in {jsonl_path.name}", file=sys.stderr)
        print("[devflow:telemetry] hint: skill must write active-spec.json at PENDING/IMPLEMENTING/COMPLETED", file=sys.stderr)
        return 0

    record = {
        "session_id": session_id,
        "project": _project_name(cwd),
        "cwd": cwd,
        "ts_end": int(time.time()),
        "phases": result["phases"],
        "total_tokens": result["total_tokens"],
    }

    TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)
    log_path = TELEMETRY_DIR / "sessions.jsonl"
    if log_path.exists():
        try:
            lines = log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        existing_ids: set = set()
        corrupt = 0
        for line in lines:
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    existing_ids.add(parsed.get("session_id"))
                else:
                    corrupt += 1
            except json.JSONDecodeError:
                corrupt += 1
        if corrupt:
            print(f"[devflow:telemetry] warning: {corrupt} corrupt line(s) in {log_path.name}", file=sys.stderr)
        if session_id in existing_ids:
            return 0
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
