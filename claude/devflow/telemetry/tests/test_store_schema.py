"""
Tests for TelemetryStore schema columns: session_id and context_anxiety_score.
RED: these tests must fail before the schema is updated.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "telemetry"))
from store import TelemetryStore


@pytest.fixture
def store(tmp_path):
    return TelemetryStore(tmp_path / "test.db")


def _columns(store: TelemetryStore) -> list[str]:
    with store._connect() as conn:
        return [r[1] for r in conn.execute("PRAGMA table_info(task_executions)").fetchall()]


class TestSchemaColumns:
    def test_session_id_column_exists(self, store):
        assert "session_id" in _columns(store)

    def test_context_anxiety_score_column_exists(self, store):
        assert "context_anxiety_score" in _columns(store)

    def test_record_with_session_id(self, store):
        store.record({"session_id": "sess-abc", "task_category": "test"})
        rows = store.get_recent(n=1)
        assert rows[0]["session_id"] == "sess-abc"

    def test_record_with_context_anxiety_score(self, store):
        store.record({"context_anxiety_score": 42.5, "task_category": "test"})
        rows = store.get_recent(n=1)
        assert rows[0]["context_anxiety_score"] == pytest.approx(42.5)

    def test_migration_adds_columns_to_existing_db(self, tmp_path):
        """Columns must be added via ALTER TABLE on pre-existing databases."""
        import sqlite3
        db = tmp_path / "old.db"
        # Create a DB without the new columns
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE task_executions (task_id TEXT PRIMARY KEY, task_category TEXT)"
        )
        conn.commit()
        conn.close()
        # TelemetryStore migration should add them
        store = TelemetryStore(db)
        cols = _columns(store)
        assert "session_id" in cols
        assert "context_anxiety_score" in cols
