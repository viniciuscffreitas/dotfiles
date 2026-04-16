"""Error-loop: N+ consecutive tool failures without recovery.

Tool failures reset on any success. A run of ≥3 failures flags the signal —
either the agent isn't adapting, or the infra is broken. Either is worth seeing.
"""
from __future__ import annotations

from dataclasses import dataclass

ERROR_LOOP_THRESHOLD = 3          # flag at 3 consecutive failures
ERROR_LOOP_CRITICAL = 5           # upgrade severity at 5+


@dataclass(frozen=True)
class ErrorLoopHit:
    session_id: str
    tool_name: str                # tool that was failing when the streak broke (or ended)
    consecutive_failures: int
    severity: str                 # "high" | "critical"


def _is_error_result(block: dict) -> bool:
    """A tool_result is an error if `is_error=True` OR its text contains <tool_use_error>."""
    if block.get("is_error") is True:
        return True
    content = block.get("content")
    if isinstance(content, str):
        return "<tool_use_error>" in content
    if isinstance(content, list):
        for inner in content:
            if isinstance(inner, dict) and "<tool_use_error>" in (inner.get("text") or ""):
                return True
    return False


def detect_error_loops(session_id: str, events: list[dict]) -> list[ErrorLoopHit]:
    """Walk events in order, tracking consecutive tool failures per streak."""
    hits: list[ErrorLoopHit] = []
    current_tool: str | None = None
    streak = 0

    def flush() -> None:
        nonlocal streak
        if streak >= ERROR_LOOP_THRESHOLD and current_tool:
            hits.append(
                ErrorLoopHit(
                    session_id=session_id,
                    tool_name=current_tool,
                    consecutive_failures=streak,
                    severity="critical" if streak >= ERROR_LOOP_CRITICAL else "high",
                )
            )
        streak = 0

    for event in events:
        etype = event.get("type")
        if etype == "assistant":
            content = (event.get("message") or {}).get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        current_tool = block.get("name")
        elif etype == "user":
            content = (event.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not (isinstance(block, dict) and block.get("type") == "tool_result"):
                    continue
                if _is_error_result(block):
                    streak += 1
                else:
                    flush()

    flush()  # final streak at EOF also counts
    return hits
