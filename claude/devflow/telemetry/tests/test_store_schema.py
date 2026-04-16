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

    def test_model_column_exists(self, store):
        assert "model" in _columns(store)

    def test_token_breakdown_columns_exist(self, store):
        cols = _columns(store)
        assert "input_tokens" in cols
        assert "output_tokens" in cols
        assert "cache_read_tokens" in cols
        assert "cache_creation_tokens" in cols

    def test_record_persists_token_breakdown(self, store):
        store.record({
            "task_id": "t-tokens",
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_read_tokens": 200,
            "cache_creation_tokens": 50,
        })
        rows = store.get_recent(n=1)
        assert rows[0]["input_tokens"] == 1000
        assert rows[0]["output_tokens"] == 500
        assert rows[0]["cache_read_tokens"] == 200
        assert rows[0]["cache_creation_tokens"] == 50

    def test_record_with_session_id(self, store):
        store.record({"session_id": "sess-abc", "task_category": "test"})
        rows = store.get_recent(n=1)
        assert rows[0]["session_id"] == "sess-abc"

    def test_record_with_context_anxiety_score(self, store):
        store.record({"context_anxiety_score": 42.5, "task_category": "test"})
        rows = store.get_recent(n=1)
        assert rows[0]["context_anxiety_score"] == pytest.approx(42.5)

    def test_record_with_model(self, store):
        store.record({"task_id": "t-model", "model": "claude-opus-4-7"})
        rows = store.get_recent(n=1)
        assert rows[0]["model"] == "claude-opus-4-7"

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
        assert "model" in cols

    def test_cost_by_model_aggregates(self, store):
        """cost_by_model() groups cost_usd and run count per model, including NULL."""
        store.record({"task_id": "a", "model": "claude-opus-4-7", "cost_usd": 1.50})
        store.record({"task_id": "b", "model": "claude-opus-4-7", "cost_usd": 2.00})
        store.record({"task_id": "c", "model": "claude-sonnet-4-6", "cost_usd": 0.30})
        store.record({"task_id": "d", "model": None, "cost_usd": 0.10})  # legacy row
        buckets = store.cost_by_model()
        # buckets is list[dict] sorted by total cost desc
        by_model = {row["model"]: row for row in buckets}
        assert by_model["claude-opus-4-7"]["runs"] == 2
        assert by_model["claude-opus-4-7"]["total_cost_usd"] == pytest.approx(3.50)
        assert by_model["claude-sonnet-4-6"]["runs"] == 1
        assert by_model["claude-sonnet-4-6"]["total_cost_usd"] == pytest.approx(0.30)
        # Legacy rows come back with a stable sentinel
        assert any(row["model"] in (None, "NULL (legacy)") for row in buckets)
