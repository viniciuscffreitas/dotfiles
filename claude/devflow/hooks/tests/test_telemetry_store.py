"""Tests for TelemetryStore — SQLite persistence layer."""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

# devflow root is three levels up from hooks/tests/
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from telemetry.store import TelemetryStore


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

def test_schema_creates_table_on_first_run(tmp_path):
    db = tmp_path / "test.db"
    TelemetryStore(db_path=db)
    conn = sqlite3.connect(db)
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    conn.close()
    assert "task_executions" in tables


def test_schema_has_required_columns(tmp_path):
    db = tmp_path / "test.db"
    TelemetryStore(db_path=db)
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(task_executions)").fetchall()}
    conn.close()
    required = {
        "task_id", "timestamp", "task_category", "task_description", "stack",
        "iterations_to_completion", "tool_calls_total", "tool_calls_without_output",
        "context_tokens_consumed", "context_tokens_at_first_action",
        "backtrack_count", "compile_errors_first_attempt", "compaction_events", "spiral_detected",
        "judge_verdict", "judge_categories_failed", "lob_violations",
        "duplication_detected", "type_contract_violations", "unjustified_complexity",
        "naming_consistency_score", "edge_case_coverage", "arch_pattern_violations",
        "probability_score", "impact_score", "detectability_score", "oversight_level",
        "skills_loaded", "rules_triggered", "harness_drift_detected", "task_time_seconds",
    }
    assert required == cols


# ---------------------------------------------------------------------------
# record()
# ---------------------------------------------------------------------------

def test_record_inserts_new_task(tmp_path):
    db = tmp_path / "test.db"
    store = TelemetryStore(db_path=db)
    store.record({
        "task_id": "abc123",
        "task_category": "simple",
        "context_tokens_consumed": 10_000,
    })
    rows = store.get_recent(1)
    assert len(rows) == 1
    assert rows[0]["task_id"] == "abc123"
    assert rows[0]["task_category"] == "simple"
    assert rows[0]["context_tokens_consumed"] == 10_000


def test_record_upserts_existing_task_id(tmp_path):
    db = tmp_path / "test.db"
    store = TelemetryStore(db_path=db)
    store.record({"task_id": "abc123", "task_category": "simple", "context_tokens_consumed": 5000})
    store.record({"task_id": "abc123", "judge_verdict": "pass"})  # partial update
    rows = store.get_recent(10)
    assert len(rows) == 1, "upsert must not create a duplicate"
    assert rows[0]["judge_verdict"] == "pass"       # new field set
    assert rows[0]["task_category"] == "simple"     # existing field preserved
    assert rows[0]["context_tokens_consumed"] == 5000  # existing field preserved


def test_record_handles_missing_optional_fields(tmp_path):
    db = tmp_path / "test.db"
    store = TelemetryStore(db_path=db)
    # Only task_id provided — all other fields must default to None without raising
    store.record({"task_id": "minimal"})
    rows = store.get_recent(1)
    assert rows[0]["task_id"] == "minimal"
    assert rows[0]["context_tokens_consumed"] is None
    assert rows[0]["judge_verdict"] is None


# ---------------------------------------------------------------------------
# get_by_category()
# ---------------------------------------------------------------------------

def test_get_by_category_returns_correct_subset(tmp_path):
    db = tmp_path / "test.db"
    store = TelemetryStore(db_path=db)
    store.record({"task_id": "t1", "task_category": "simple"})
    store.record({"task_id": "t2", "task_category": "complex"})
    store.record({"task_id": "t3", "task_category": "simple"})
    result = store.get_by_category("simple")
    assert len(result) == 2
    assert all(r["task_category"] == "simple" for r in result)


# ---------------------------------------------------------------------------
# get_recent()
# ---------------------------------------------------------------------------

def test_get_recent_returns_n_records(tmp_path):
    db = tmp_path / "test.db"
    store = TelemetryStore(db_path=db)
    for i in range(7):
        store.record({"task_id": f"task_{i}"})
    result = store.get_recent(3)
    assert len(result) == 3


def test_get_recent_default_is_20(tmp_path):
    db = tmp_path / "test.db"
    store = TelemetryStore(db_path=db)
    for i in range(25):
        store.record({"task_id": f"task_{i}"})
    result = store.get_recent()
    assert len(result) == 20


def test_get_recent_returns_latest_first(tmp_path):
    """Records inserted later must appear first (rowid DESC order)."""
    db = tmp_path / "test.db"
    store = TelemetryStore(db_path=db)
    for i in range(3):
        store.record({"task_id": f"task_{i}"})
    result = store.get_recent(3)
    ids = [r["task_id"] for r in result]
    assert ids == ["task_2", "task_1", "task_0"]


# ---------------------------------------------------------------------------
# get_failure_patterns()
# ---------------------------------------------------------------------------

def test_get_failure_patterns_returns_only_warn_and_fail(tmp_path):
    db = tmp_path / "test.db"
    store = TelemetryStore(db_path=db)
    ts = datetime.now(tz=timezone.utc).isoformat()
    for verdict, tid in [
        ("pass", "p1"), ("warn", "w1"), ("fail", "f1"), ("skipped", "s1"), ("pending", "pe1"),
    ]:
        store.record({"task_id": tid, "judge_verdict": verdict, "timestamp": ts})
    result = store.get_failure_patterns(days=30)
    ids = {r["task_id"] for r in result}
    assert ids == {"w1", "f1"}


# ---------------------------------------------------------------------------
# get_context_anxiety_cases()
# ---------------------------------------------------------------------------

def test_get_context_anxiety_cases_filters_above_threshold(tmp_path):
    db = tmp_path / "test.db"
    store = TelemetryStore(db_path=db)
    store.record({"task_id": "low", "context_tokens_at_first_action": 30_000})
    store.record({"task_id": "high", "context_tokens_at_first_action": 80_000})
    store.record({"task_id": "exact", "context_tokens_at_first_action": 60_000})  # not > threshold
    result = store.get_context_anxiety_cases(threshold=60_000)
    ids = {r["task_id"] for r in result}
    assert ids == {"high"}


# ---------------------------------------------------------------------------
# summary_stats()
# ---------------------------------------------------------------------------

def test_summary_stats_empty_db(tmp_path):
    db = tmp_path / "test.db"
    store = TelemetryStore(db_path=db)
    stats = store.summary_stats()
    assert stats["total_tasks"] == 0
    assert stats["pass_rate"] == 0.0
    assert stats["spiral_rate"] == 0.0
    assert stats["avg_context_tokens"] == 0.0
    assert stats["avg_iterations_by_category"] == {}


def test_summary_stats_pass_rate(tmp_path):
    db = tmp_path / "test.db"
    store = TelemetryStore(db_path=db)
    store.record({"task_id": "p1", "judge_verdict": "pass"})
    store.record({"task_id": "p2", "judge_verdict": "pass"})
    store.record({"task_id": "f1", "judge_verdict": "fail"})
    store.record({"task_id": "u1"})  # no verdict — excluded from pass_rate calc
    stats = store.summary_stats()
    assert stats["total_tasks"] == 4
    assert abs(stats["pass_rate"] - 2 / 3) < 0.001


def test_summary_stats_spiral_rate(tmp_path):
    db = tmp_path / "test.db"
    store = TelemetryStore(db_path=db)
    store.record({"task_id": "s1", "spiral_detected": True})
    store.record({"task_id": "n1", "spiral_detected": False})
    store.record({"task_id": "n2"})  # spiral_detected NULL — not a spiral
    stats = store.summary_stats()
    assert abs(stats["spiral_rate"] - 1 / 3) < 0.001
