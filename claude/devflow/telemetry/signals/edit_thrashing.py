"""Edit-thrashing: same file edited N+ times in one session.

Strong spiral indicator — when a file is rewritten repeatedly, the agent is
usually guessing instead of understanding. Live hooks (file_checker) see one
edit at a time; this detector surfaces the pattern *across* the session.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from telemetry.signals._transcripts import (
    extract_file_path,
    extract_tool_uses,
    is_edit_tool,
)

THRASHING_THRESHOLD = 5        # flag when a file is edited ≥5 times
THRASHING_CRITICAL = 10        # upgrade severity at 10+ edits


@dataclass(frozen=True)
class ThrashingHit:
    session_id: str
    file_path: str
    edit_count: int
    severity: str              # "high" | "critical"


def detect_edit_thrashing(session_id: str, events: list[dict]) -> list[ThrashingHit]:
    """Return one ThrashingHit per file that crossed the threshold in this session."""
    counts: Counter[str] = Counter()
    for tool_use in extract_tool_uses(events):
        name = tool_use.get("name", "")
        if not is_edit_tool(name):
            continue
        tool_input = tool_use.get("input") or {}
        file_path = extract_file_path(tool_input)
        if not file_path:
            continue
        counts[file_path] += 1

    return [
        ThrashingHit(
            session_id=session_id,
            file_path=path,
            edit_count=count,
            severity="critical" if count >= THRASHING_CRITICAL else "high",
        )
        for path, count in counts.most_common()
        if count >= THRASHING_THRESHOLD
    ]
