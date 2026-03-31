"""Concurrency and parallel-session tests for devflow harness."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pytest

# Path setup
_HOOKS_DIR = Path(__file__).parent.parent          # hooks/
_DEVFLOW_ROOT = Path(__file__).parent.parent.parent  # devflow/
sys.path.insert(0, str(_DEVFLOW_ROOT))
sys.path.insert(0, str(_HOOKS_DIR))

from telemetry.store import TelemetryStore


# ---------------------------------------------------------------------------
# Task 1: TelemetryStore WAL mode
# ---------------------------------------------------------------------------

class TestTelemetryStoreWAL:

    def test_wal_mode_enabled(self, tmp_path):
        TelemetryStore(db_path=tmp_path / "test.db")
        with closing(sqlite3.connect(str(tmp_path / "test.db"))) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_busy_timeout_set(self, tmp_path):
        store = TelemetryStore(db_path=tmp_path / "test.db")
        with closing(store._connect()) as conn:
            timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout >= 5000

    def test_concurrent_writes_no_errors(self, tmp_path):
        store = TelemetryStore(db_path=tmp_path / "test.db")
        errors: list[Exception] = []

        def write(i: int) -> None:
            try:
                store.record({"task_id": f"task-{i}", "task_category": "test"})
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=write, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(store.get_recent(n=10)) == 3

    def test_write_with_retry_retries_on_locked_error(self, tmp_path):
        store = TelemetryStore(db_path=tmp_path / "test.db")
        call_count = [0]

        def flaky(conn: sqlite3.Connection) -> None:
            call_count[0] += 1
            if call_count[0] == 1:
                raise sqlite3.OperationalError("database is locked")

        store._write_with_retry(flaky, max_retries=3)
        assert call_count[0] == 2

    def test_write_with_retry_raises_after_max_retries(self, tmp_path):
        store = TelemetryStore(db_path=tmp_path / "test.db")

        def always_locked(conn: sqlite3.Connection) -> None:
            raise sqlite3.OperationalError("database is locked")

        with pytest.raises(sqlite3.OperationalError, match="locked"):
            store._write_with_retry(always_locked, max_retries=3)


# ---------------------------------------------------------------------------
# Task 2: Session ID utility (_session.py)
# ---------------------------------------------------------------------------

class TestGetSessionId:

    def test_returns_claude_session_id_when_set(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-abc-123")
        monkeypatch.delenv("DEVFLOW_SESSION_ID", raising=False)
        import importlib
        import _session
        importlib.reload(_session)
        assert _session.get_session_id() == "claude-abc-123"

    def test_returns_devflow_session_id_when_claude_unset(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
        monkeypatch.setenv("DEVFLOW_SESSION_ID", "devflow-test-456")
        import importlib
        import _session
        importlib.reload(_session)
        assert _session.get_session_id() == "devflow-test-456"

    def test_returns_pid_fallback_when_both_unset(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
        monkeypatch.delenv("DEVFLOW_SESSION_ID", raising=False)
        import importlib
        import _session
        importlib.reload(_session)
        import os
        sid = _session.get_session_id()
        assert sid.startswith(f"pid-{os.getpid()}-")

    def test_fallback_is_unique_across_calls_with_different_timestamps(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
        monkeypatch.delenv("DEVFLOW_SESSION_ID", raising=False)
        import importlib
        import _session
        importlib.reload(_session)
        with patch("_session.time") as mock_time:
            mock_time.time.side_effect = [1000, 1001]
            sid1 = _session.get_session_id()
            sid2 = _session.get_session_id()
        assert sid1 != sid2

    def test_util_re_exports_get_session_id_from_session_module(self):
        """_util.py must import get_session_id from _session, not define it."""
        util_path = _HOOKS_DIR / "_util.py"
        content = util_path.read_text()
        assert "from _session import get_session_id" in content
        assert "def get_session_id" not in content

    def test_no_hook_reads_claude_session_id_directly(self):
        """No hook file should read CLAUDE_SESSION_ID via os.environ.get directly."""
        for py_file in _HOOKS_DIR.glob("*.py"):
            if py_file.name in ("_session.py",) or "test_" in py_file.name:
                continue
            content = py_file.read_text()
            assert 'os.environ.get("CLAUDE_SESSION_ID"' not in content, (
                f"{py_file.name} reads CLAUDE_SESSION_ID directly; use get_session_id()"
            )

    # --- is_safe_session ---

    def test_is_safe_session_true_when_real_id_set(self, monkeypatch):
        """Returns True when CLAUDE_SESSION_ID is a real non-default value."""
        monkeypatch.setenv("CLAUDE_SESSION_ID", "abc-123-real")
        import importlib, _session
        importlib.reload(_session)
        assert _session.is_safe_session() is True

    def test_is_safe_session_false_when_unset(self, monkeypatch):
        """Returns False when CLAUDE_SESSION_ID is not set."""
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
        import importlib, _session
        importlib.reload(_session)
        assert _session.is_safe_session() is False

    def test_is_safe_session_false_when_empty_string(self, monkeypatch):
        """Returns False when CLAUDE_SESSION_ID is an empty string."""
        monkeypatch.setenv("CLAUDE_SESSION_ID", "")
        import importlib, _session
        importlib.reload(_session)
        assert _session.is_safe_session() is False

    def test_is_safe_session_false_when_default(self, monkeypatch):
        """Returns False when CLAUDE_SESSION_ID is the sentinel 'default'."""
        monkeypatch.setenv("CLAUDE_SESSION_ID", "default")
        import importlib, _session
        importlib.reload(_session)
        assert _session.is_safe_session() is False

    def test_is_safe_session_false_when_whitespace_only(self, monkeypatch):
        """Returns False when CLAUDE_SESSION_ID is whitespace only."""
        monkeypatch.setenv("CLAUDE_SESSION_ID", "   ")
        import importlib, _session
        importlib.reload(_session)
        assert _session.is_safe_session() is False


# ---------------------------------------------------------------------------
# Task 3: TaskRegistry
# ---------------------------------------------------------------------------

from agents.task_registry import TaskRegistry


class TestTaskRegistry:

    def test_claim_unclaimed_task_returns_true(self, tmp_path):
        reg = TaskRegistry(registry_path=tmp_path / "registry.json")
        assert reg.claim("ISSUE-1", "session-a", "proj") is True

    def test_claim_already_claimed_returns_false(self, tmp_path):
        reg = TaskRegistry(registry_path=tmp_path / "registry.json")
        reg.claim("ISSUE-1", "session-a", "proj")
        assert reg.claim("ISSUE-1", "session-b", "proj") is False

    def test_claim_atomic_under_concurrency_only_one_wins(self, tmp_path):
        reg = TaskRegistry(registry_path=tmp_path / "registry.json")
        results: list[bool] = []

        def try_claim() -> None:
            results.append(
                reg.claim("ISSUE-1", f"s-{threading.get_ident()}", "proj")
            )

        threads = [threading.Thread(target=try_claim) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count(True) == 1
        assert results.count(False) == 2

    def test_release_updates_status_to_done(self, tmp_path):
        reg = TaskRegistry(registry_path=tmp_path / "registry.json")
        reg.claim("ISSUE-1", "session-a", "proj")
        reg.release("ISSUE-1", "session-a", "done")
        data = json.loads((tmp_path / "registry.json").read_text())
        assert data["tasks"]["ISSUE-1"]["status"] == "done"

    def test_release_by_wrong_session_is_noop(self, tmp_path):
        reg = TaskRegistry(registry_path=tmp_path / "registry.json")
        reg.claim("ISSUE-1", "session-a", "proj")
        reg.release("ISSUE-1", "session-b", "done")
        data = json.loads((tmp_path / "registry.json").read_text())
        assert data["tasks"]["ISSUE-1"]["status"] == "in_progress"

    def test_list_available_excludes_claimed_tasks(self, tmp_path):
        reg = TaskRegistry(registry_path=tmp_path / "registry.json")
        reg.claim("ISSUE-1", "session-a", "proj")
        available = reg.list_available(["ISSUE-1", "ISSUE-2"])
        assert "ISSUE-1" not in available
        assert "ISSUE-2" in available

    def test_list_available_reclaims_stale_tasks(self, tmp_path):
        reg = TaskRegistry(registry_path=tmp_path / "registry.json")
        reg.claim("ISSUE-1", "session-a", "proj")
        # Backdate claimed_at to simulate a 2-hour-old stale entry
        data = json.loads((tmp_path / "registry.json").read_text())
        data["tasks"]["ISSUE-1"]["claimed_at"] = "2020-01-01T00:00:00+00:00"
        (tmp_path / "registry.json").write_text(json.dumps(data))
        available = reg.list_available(["ISSUE-1", "ISSUE-2"])
        assert "ISSUE-1" in available

    def test_list_active_returns_only_in_progress_non_stale(self, tmp_path):
        reg = TaskRegistry(registry_path=tmp_path / "registry.json")
        reg.claim("ISSUE-1", "session-a", "proj")
        reg.claim("ISSUE-2", "session-b", "proj")
        reg.release("ISSUE-2", "session-b", "done")
        active = reg.list_active()
        assert len(active) == 1
        assert active[0]["task_id"] == "ISSUE-1"

    def test_never_raises_on_missing_registry_file(self, tmp_path):
        reg = TaskRegistry(registry_path=tmp_path / "sub" / "registry.json")
        result = reg.claim("ISSUE-1", "session-a", "proj")
        assert isinstance(result, bool)

    def test_never_raises_on_corrupted_registry_file(self, tmp_path):
        reg_path = tmp_path / "registry.json"
        reg_path.write_text("{{{ not valid json !!!")
        reg = TaskRegistry(registry_path=reg_path)
        result = reg.claim("ISSUE-1", "session-a", "proj")
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Task 4: parallel_launch.sh
# ---------------------------------------------------------------------------

_SCRIPT = _DEVFLOW_ROOT / "scripts" / "parallel_launch.sh"


class TestParallelLaunchScript:

    def test_dry_run_prints_table_no_files_created(self, tmp_path):
        result = subprocess.run(
            ["bash", str(_SCRIPT), "--dry-run", "ISSUE-123"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "ISSUE-123" in result.stdout
        # No worktree directories created
        assert not list(tmp_path.iterdir())

    def test_dry_run_accepts_multiple_issue_ids(self, tmp_path):
        result = subprocess.run(
            ["bash", str(_SCRIPT), "--dry-run", "ISSUE-1", "ISSUE-2", "ISSUE-3"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "ISSUE-1" in result.stdout
        assert "ISSUE-2" in result.stdout
        assert "ISSUE-3" in result.stdout

    def test_cleanup_prints_nothing_to_clean_when_no_worktrees(self, tmp_path):
        result = subprocess.run(
            ["bash", str(_SCRIPT), "--cleanup"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
        combined = (result.stdout + result.stderr).lower()
        assert "nothing" in combined
