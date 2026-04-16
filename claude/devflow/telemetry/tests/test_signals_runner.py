"""Integration test: runner scans a temp projects dir and fires all 3 detectors."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from telemetry.signals.runner import run_behavior_signals


def _write_jsonl(path: Path, events: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event) + "\n")


def test_runner_empty_dir(tmp_path):
    rep = run_behavior_signals(tmp_path)
    assert rep.sessions_scanned == 0 and rep.total_signals == 0


def test_runner_detects_thrashing_error_loops_and_clusters(tmp_path):
    projects = tmp_path / "projects"
    proj = projects / "-proj"

    # Session 1: thrashing on /a.py (6 edits)
    thrash_events = [
        {"type": "attachment", "timestamp": "2026-04-16T12:00:00Z", "cwd": "/work"},
    ] + [
        {"type": "assistant", "timestamp": f"2026-04-16T12:00:{i:02d}Z", "message": {"content": [
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "/a.py"}},
        ]}}
        for i in range(6)
    ]
    _write_jsonl(proj / "sess1.jsonl", thrash_events)

    # Session 2: 4 consecutive Bash errors
    err_events = [{"type": "attachment", "timestamp": "2026-04-16T12:05:00Z", "cwd": "/work"}]
    for _ in range(4):
        err_events.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {}},
        ]}})
        err_events.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "is_error": True, "content": "fail"},
        ]}})
    _write_jsonl(proj / "sess2.jsonl", err_events)

    # Session 3: just starts near session 1 (same cwd, within 30 min) → cluster of 3
    _write_jsonl(
        proj / "sess3.jsonl",
        [{"type": "attachment", "timestamp": "2026-04-16T12:10:00Z", "cwd": "/work"}],
    )

    rep = run_behavior_signals(projects)
    assert rep.sessions_scanned == 3
    assert len(rep.thrashing) == 1 and rep.thrashing[0].edit_count == 6
    assert len(rep.error_loops) == 1 and rep.error_loops[0].consecutive_failures == 4
    assert len(rep.restart_clusters) == 1
    assert set(rep.restart_clusters[0].session_ids) == {"sess1", "sess2", "sess3"}
