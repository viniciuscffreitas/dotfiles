"""Tests for error-loop detector."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from telemetry.signals.error_loop import (
    ERROR_LOOP_CRITICAL,
    ERROR_LOOP_THRESHOLD,
    detect_error_loops,
)


def _tool_use(tool_name: str) -> dict:
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": tool_name, "input": {}},
    ]}}


def _tool_result(is_error: bool = False, marker: bool = False) -> dict:
    content = "<tool_use_error>boom</tool_use_error>" if marker else "ok"
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "is_error": is_error, "content": content},
    ]}}


def _streak(tool: str, n: int) -> list[dict]:
    out: list[dict] = []
    for _ in range(n):
        out.append(_tool_use(tool))
        out.append(_tool_result(is_error=True))
    return out


def test_under_threshold_no_hit():
    events = _streak("Edit", ERROR_LOOP_THRESHOLD - 1)
    assert detect_error_loops("s1", events) == []


def test_at_threshold_flags_high():
    events = _streak("Edit", ERROR_LOOP_THRESHOLD)
    hits = detect_error_loops("s1", events)
    assert len(hits) == 1
    assert hits[0].tool_name == "Edit"
    assert hits[0].consecutive_failures == ERROR_LOOP_THRESHOLD
    assert hits[0].severity == "high"


def test_at_critical_flags_critical():
    events = _streak("Bash", ERROR_LOOP_CRITICAL)
    hits = detect_error_loops("s1", events)
    assert hits[0].severity == "critical"


def test_success_resets_streak():
    events = (
        _streak("Edit", ERROR_LOOP_THRESHOLD - 1)
        + [_tool_use("Edit"), _tool_result(is_error=False)]
        + _streak("Edit", ERROR_LOOP_THRESHOLD - 1)
    )
    assert detect_error_loops("s1", events) == []


def test_error_marker_counts_as_error():
    # is_error=False but content has <tool_use_error>
    events: list[dict] = []
    for _ in range(ERROR_LOOP_THRESHOLD):
        events.append(_tool_use("Grep"))
        events.append(_tool_result(is_error=False, marker=True))
    hits = detect_error_loops("s1", events)
    assert len(hits) == 1 and hits[0].tool_name == "Grep"


def test_multiple_streaks_reported():
    events = (
        _streak("Edit", ERROR_LOOP_THRESHOLD)
        + [_tool_use("Edit"), _tool_result(is_error=False)]
        + _streak("Bash", ERROR_LOOP_CRITICAL)
    )
    hits = detect_error_loops("s1", events)
    assert len(hits) == 2
    assert hits[0].tool_name == "Edit" and hits[0].severity == "high"
    assert hits[1].tool_name == "Bash" and hits[1].severity == "critical"


def test_final_streak_flushed_at_eof():
    events = _streak("Grep", ERROR_LOOP_THRESHOLD)  # no success after — EOF streak
    hits = detect_error_loops("s1", events)
    assert len(hits) == 1
