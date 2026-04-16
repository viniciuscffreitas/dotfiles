"""Tests for edit-thrashing detector."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from telemetry.signals.edit_thrashing import (
    THRASHING_CRITICAL,
    THRASHING_THRESHOLD,
    detect_edit_thrashing,
)


def _edit_event(tool_name: str, file_path: str) -> dict:
    return {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_use", "name": tool_name, "input": {"file_path": file_path}},
            ]
        },
    }


def test_under_threshold_returns_nothing():
    events = [_edit_event("Edit", "/a.py")] * (THRASHING_THRESHOLD - 1)
    assert detect_edit_thrashing("s1", events) == []


def test_at_threshold_flags_high():
    events = [_edit_event("Edit", "/a.py")] * THRASHING_THRESHOLD
    hits = detect_edit_thrashing("s1", events)
    assert len(hits) == 1
    assert hits[0].file_path == "/a.py"
    assert hits[0].edit_count == THRASHING_THRESHOLD
    assert hits[0].severity == "high"


def test_at_critical_flags_critical():
    events = [_edit_event("Write", "/b.py")] * THRASHING_CRITICAL
    hits = detect_edit_thrashing("s1", events)
    assert hits[0].severity == "critical"


def test_multiple_files_each_reported():
    events = (
        [_edit_event("Edit", "/a.py")] * THRASHING_THRESHOLD
        + [_edit_event("Edit", "/b.py")] * THRASHING_THRESHOLD
    )
    hits = detect_edit_thrashing("s1", events)
    assert {h.file_path for h in hits} == {"/a.py", "/b.py"}


def test_non_edit_tools_ignored():
    events = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"file_path": "/a.py"}},
        ]}}
    ] * 20
    assert detect_edit_thrashing("s1", events) == []


def test_multiedit_and_notebookedit_counted():
    events = (
        [_edit_event("MultiEdit", "/a.py")] * 3
        + [_edit_event("NotebookEdit", "/a.py")] * 2
    )
    hits = detect_edit_thrashing("s1", events)
    assert len(hits) == 1 and hits[0].edit_count == 5


def test_missing_file_path_ignored():
    events = [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Edit", "input": {}},
    ]}}] * 10
    assert detect_edit_thrashing("s1", events) == []


def test_sorted_by_count_descending():
    events = (
        [_edit_event("Edit", "/low.py")] * THRASHING_THRESHOLD
        + [_edit_event("Edit", "/hi.py")] * (THRASHING_CRITICAL + 2)
    )
    hits = detect_edit_thrashing("s1", events)
    assert hits[0].file_path == "/hi.py"
