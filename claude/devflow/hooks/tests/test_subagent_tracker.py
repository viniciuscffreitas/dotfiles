"""Tests for subagent_tracker — SubagentStart and SubagentStop hooks."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import subagent_tracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _start_data(subagent_type: str = "general-purpose", description: str = "do something") -> dict:
    return {
        "session_id": "sess-sa-1",
        "hook_event_name": "SubagentStart",
        "subagent_type": subagent_type,
        "description": description,
    }


def _stop_data(subagent_type: str = "general-purpose") -> dict:
    return {
        "session_id": "sess-sa-1",
        "hook_event_name": "SubagentStop",
        "subagent_type": subagent_type,
    }


def _run(hook_data: dict, state_dir: Path) -> tuple[int, str]:
    captured = io.StringIO()
    with (
        patch("subagent_tracker.read_hook_stdin", return_value=hook_data),
        patch("subagent_tracker._get_state_dir", return_value=state_dir),
        patch("sys.stdout", captured),
    ):
        code = subagent_tracker.main()
    return code, captured.getvalue()


# ---------------------------------------------------------------------------
# SubagentStart — output and persistence
# ---------------------------------------------------------------------------

def test_start_exits_zero(tmp_path):
    code, _ = _run(_start_data(), tmp_path)
    assert code == 0


def test_start_prints_devflow_prefix(tmp_path):
    _, out = _run(_start_data(), tmp_path)
    assert "[devflow:subagent]" in out


def test_start_shows_subagent_type(tmp_path):
    _, out = _run(_start_data(subagent_type="Explore"), tmp_path)
    assert "Explore" in out


def test_start_writes_jsonl_record(tmp_path):
    _run(_start_data(), tmp_path)
    log = tmp_path / "subagents.jsonl"
    assert log.exists()
    record = json.loads(log.read_text().strip().splitlines()[0])
    assert record["event"] == "start"
    assert record["subagent_type"] == "general-purpose"
    assert "ts" in record


def test_start_appends_multiple_records(tmp_path):
    _run(_start_data(subagent_type="Explore"), tmp_path)
    _run(_start_data(subagent_type="Plan"), tmp_path)
    log = tmp_path / "subagents.jsonl"
    lines = log.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["subagent_type"] == "Explore"
    assert json.loads(lines[1])["subagent_type"] == "Plan"


# ---------------------------------------------------------------------------
# SubagentStop — output and persistence
# ---------------------------------------------------------------------------

def test_stop_exits_zero(tmp_path):
    code, _ = _run(_stop_data(), tmp_path)
    assert code == 0


def test_stop_prints_devflow_prefix(tmp_path):
    _, out = _run(_stop_data(), tmp_path)
    assert "[devflow:subagent]" in out


def test_stop_writes_jsonl_record(tmp_path):
    _run(_stop_data(), tmp_path)
    log = tmp_path / "subagents.jsonl"
    assert log.exists()
    record = json.loads(log.read_text().strip().splitlines()[0])
    assert record["event"] == "stop"


# ---------------------------------------------------------------------------
# Edge cases — missing data exits 0, no raise
# ---------------------------------------------------------------------------

def test_missing_session_id_exits_zero(tmp_path):
    data = {"hook_event_name": "SubagentStart", "subagent_type": "general-purpose"}
    code, _ = _run(data, tmp_path)
    assert code == 0


def test_empty_hook_data_exits_zero(tmp_path):
    code, _ = _run({}, tmp_path)
    assert code == 0


def test_never_raises_on_garbage(tmp_path):
    import importlib
    importlib.reload(subagent_tracker)
    with (
        patch("subagent_tracker.read_hook_stdin", return_value={"subagent_type": None}),
        patch("subagent_tracker._get_state_dir", return_value=tmp_path),
        patch("sys.stdout", io.StringIO()),
    ):
        try:
            subagent_tracker.main()
        except Exception as exc:
            pytest.fail(f"main() raised: {exc}")
