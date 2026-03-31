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
