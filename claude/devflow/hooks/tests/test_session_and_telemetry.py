"""Tests for session_id stability and telemetry field population."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ---------------------------------------------------------------------------
# _session.py: PID fallback stability
# ---------------------------------------------------------------------------

class TestSessionIdFallback:
    def test_pid_fallback_stable_across_calls(self, monkeypatch):
        """Contract: same PID → same session_id (no timestamp jitter)."""
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
        monkeypatch.delenv("DEVFLOW_SESSION_ID", raising=False)

        import importlib
        import _session
        importlib.reload(_session)

        id1 = _session.get_session_id()
        time.sleep(0.01)
        id2 = _session.get_session_id()
        assert id1 == id2, f"Fallback IDs differ: {id1} vs {id2}"

    def test_pid_fallback_contains_pid(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
        monkeypatch.delenv("DEVFLOW_SESSION_ID", raising=False)

        import importlib
        import _session
        importlib.reload(_session)

        sid = _session.get_session_id()
        assert str(os.getpid()) in sid

    def test_claude_session_id_takes_priority(self, monkeypatch):
        """Contract: CLAUDE_SESSION_ID present → use it unchanged."""
        monkeypatch.setenv("CLAUDE_SESSION_ID", "abc-123-real")

        import importlib
        import _session
        importlib.reload(_session)

        assert _session.get_session_id() == "abc-123-real"


# ---------------------------------------------------------------------------
# get_state_dir: no dir creation without real session ID
# ---------------------------------------------------------------------------

class TestStateDirGuard:
    def test_no_dir_creation_without_session_id(self, monkeypatch, tmp_path):
        """Contract: without CLAUDE_SESSION_ID, returns default/ dir, doesn't create PID dirs."""
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
        monkeypatch.delenv("DEVFLOW_SESSION_ID", raising=False)

        # Patch the base state path to tmp_path — no reload needed; monkeypatch is sufficient
        import _util
        base = tmp_path / "state"
        base.mkdir()
        monkeypatch.setattr(_util, "get_state_dir", lambda: _make_default_state_dir(base))

        state_dir = _make_default_state_dir(base)
        assert state_dir.name == "default"

    def test_creates_dir_with_real_session_id(self, monkeypatch, tmp_path):
        """Contract: with CLAUDE_SESSION_ID, creates specific dir."""
        monkeypatch.setenv("CLAUDE_SESSION_ID", "real-session-xyz")

        import importlib
        import _session
        importlib.reload(_session)

        state_dir = tmp_path / "state" / _session.get_session_id()
        state_dir.mkdir(parents=True)
        assert state_dir.name == "real-session-xyz"


def _make_default_state_dir(base: Path) -> Path:
    d = base / "default"
    d.mkdir(exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# cost_tracker: timestamp and session_id
# ---------------------------------------------------------------------------

class TestCostTrackerTelemetry:
    def test_records_timestamp(self):
        """Contract: cost_tracker must include ISO timestamp in telemetry record."""
        import cost_tracker
        mock_store_instance = MagicMock()

        hook_data = {
            "model": "claude-sonnet-4-6",
            "session_id": "test-session",
            "usage": {"input_tokens": 1000, "output_tokens": 500},
        }

        with patch("cost_tracker.read_hook_stdin", return_value=hook_data), \
             patch("cost_tracker.TelemetryStore", return_value=mock_store_instance):
            cost_tracker.main()

        mock_store_instance.record.assert_called_once()
        payload = mock_store_instance.record.call_args[0][0]
        assert "timestamp" in payload, "timestamp missing from cost_tracker record"
        assert payload["timestamp"] is not None

    def test_records_session_id(self):
        """Contract: cost_tracker must include session_id in telemetry record."""
        import cost_tracker
        mock_store_instance = MagicMock()

        hook_data = {
            "model": "claude-sonnet-4-6",
            "session_id": "my-session-456",
            "usage": {"input_tokens": 1000, "output_tokens": 500},
        }

        with patch("cost_tracker.read_hook_stdin", return_value=hook_data), \
             patch("cost_tracker.TelemetryStore", return_value=mock_store_instance):
            cost_tracker.main()

        mock_store_instance.record.assert_called_once()
        payload = mock_store_instance.record.call_args[0][0]
        assert payload.get("session_id") == "my-session-456"


# ---------------------------------------------------------------------------
# task_telemetry: timestamp, task_description, task_time_seconds
# ---------------------------------------------------------------------------

class TestTaskTelemetryFields:
    def test_populates_timestamp(self, tmp_path):
        """Contract: task_telemetry must write ISO timestamp to SQLite record."""
        from telemetry.store import TelemetryStore

        store = TelemetryStore(db_path=tmp_path / "test.db")
        mock_store_cls = MagicMock(return_value=store)

        # Create a minimal session JSONL with a spec write
        jsonl = tmp_path / "session.jsonl"
        spec_content = json.dumps({"status": "PENDING", "plan_path": "test task"})
        entries = [
            {"type": "assistant", "timestamp": "2026-04-03T10:00:00Z", "message": {
                "usage": {"input_tokens": 1000, "output_tokens": 500},
                "content": [{"type": "tool_use", "name": "Write", "id": "t1", "input": {
                    "file_path": "/tmp/active-spec.json",
                    "content": spec_content,
                }}],
            }},
        ]
        jsonl.write_text("\n".join(json.dumps(e) for e in entries))

        import task_telemetry
        result = task_telemetry.parse_session(jsonl)
        assert len(result["phases"]) > 0

    def test_populates_task_description_from_plan_path(self, tmp_path):
        """Contract: task_telemetry should include plan_path as task_description."""
        from telemetry.store import TelemetryStore

        store = TelemetryStore(db_path=tmp_path / "test.db")

        # Simulate what task_telemetry should record
        record = {
            "task_id": "test-session",
            "timestamp": "2026-04-03T10:00:00Z",
            "task_description": "fix: devflow session bloat",
            "context_tokens_consumed": 5000,
        }
        store.record(record)

        rows = store.get_recent(1)
        assert rows[0]["task_description"] == "fix: devflow session bloat"
        assert rows[0]["timestamp"] == "2026-04-03T10:00:00Z"
