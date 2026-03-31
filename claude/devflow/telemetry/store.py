"""
TelemetryStore — SQLite persistence layer for devflow task telemetry.

Dual-write partner to sessions.jsonl: structured, queryable, upsertable.
Default DB path: ~/.claude/devflow/telemetry/devflow.db
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

_TELEMETRY_DIR = Path.home() / ".claude" / "devflow" / "telemetry"
_DEFAULT_DB = _TELEMETRY_DIR / "devflow.db"

_COLUMNS = [
    "task_id", "timestamp", "task_category", "task_description", "stack",
    "iterations_to_completion", "tool_calls_total", "tool_calls_without_output",
    "context_tokens_consumed", "context_tokens_at_first_action",
    "backtrack_count", "compile_errors_first_attempt", "compaction_events",
    "spiral_detected",
    "judge_verdict", "judge_categories_failed", "lob_violations",
    "duplication_detected", "type_contract_violations", "unjustified_complexity",
    "naming_consistency_score", "edge_case_coverage", "arch_pattern_violations",
    "probability_score", "impact_score", "detectability_score", "oversight_level",
    "skills_loaded", "rules_triggered", "harness_drift_detected",
    "task_time_seconds",
]

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS task_executions (
    task_id                         TEXT PRIMARY KEY,
    timestamp                       TEXT,
    task_category                   TEXT,
    task_description                TEXT,
    stack                           TEXT,
    iterations_to_completion        INTEGER,
    tool_calls_total                INTEGER,
    tool_calls_without_output       INTEGER,
    context_tokens_consumed         INTEGER,
    context_tokens_at_first_action  INTEGER,
    backtrack_count                 INTEGER,
    compile_errors_first_attempt    INTEGER,
    compaction_events               INTEGER,
    spiral_detected                 BOOLEAN,
    judge_verdict                   TEXT,
    judge_categories_failed         TEXT,
    lob_violations                  INTEGER,
    duplication_detected            BOOLEAN,
    type_contract_violations        INTEGER,
    unjustified_complexity          BOOLEAN,
    naming_consistency_score        REAL,
    edge_case_coverage              TEXT,
    arch_pattern_violations         INTEGER,
    probability_score               REAL,
    impact_score                    REAL,
    detectability_score             REAL,
    oversight_level                 TEXT,
    skills_loaded                   TEXT,
    rules_triggered                 TEXT,
    harness_drift_detected          BOOLEAN,
    task_time_seconds               INTEGER
)
"""


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


class TelemetryStore:
    """Thread-safe SQLite store for devflow task telemetry."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with closing(self._connect()) as conn:
                conn.execute(_CREATE_TABLE)
                conn.commit()

    def record(self, payload: dict) -> None:
        """Upsert a task record. Missing columns default to None for new rows;
        existing non-null values are preserved for updates."""
        values = {col: payload.get(col) for col in _COLUMNS}
        cols = ", ".join(_COLUMNS)
        placeholders = ", ".join(f":{col}" for col in _COLUMNS)
        update_clauses = ", ".join(
            f"{col} = COALESCE(excluded.{col}, task_executions.{col})"
            for col in _COLUMNS
            if col != "task_id"
        )
        sql = (
            f"INSERT INTO task_executions ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT(task_id) DO UPDATE SET {update_clauses}"
        )
        with self._lock:
            with closing(self._connect()) as conn:
                conn.execute(sql, values)
                conn.commit()

    def get_by_category(self, category: str) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM task_executions WHERE task_category = ?", (category,)
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_recent(self, n: int = 20) -> list[dict]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM task_executions ORDER BY rowid DESC LIMIT ?", (n,)
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_failure_patterns(self, days: int = 30) -> list[dict]:
        """Records where judge_verdict in ('warn', 'fail') within the last N days.

        Timestamps must be ISO 8601 with UTC offset (e.g. '2026-03-31T00:00:00+00:00')
        for lexicographic comparison to be correct.
        """
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM task_executions "
                "WHERE judge_verdict IN ('warn', 'fail') AND timestamp >= ?",
                (cutoff,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_context_anxiety_cases(self, threshold: int = 60_000) -> list[dict]:
        """Records where context_tokens_at_first_action > threshold."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT * FROM task_executions WHERE context_tokens_at_first_action > ?",
                (threshold,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def summary_stats(self) -> dict:
        with closing(self._connect()) as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM task_executions"
            ).fetchone()[0]

            judged = conn.execute(
                "SELECT COUNT(*) FROM task_executions "
                "WHERE judge_verdict IN ('pass', 'warn', 'fail')"
            ).fetchone()[0]
            passed = conn.execute(
                "SELECT COUNT(*) FROM task_executions WHERE judge_verdict = 'pass'"
            ).fetchone()[0]

            avg_tokens = conn.execute(
                "SELECT AVG(context_tokens_consumed) FROM task_executions"
            ).fetchone()[0] or 0.0

            spirals = conn.execute(
                "SELECT COUNT(*) FROM task_executions WHERE spiral_detected = 1"
            ).fetchone()[0]

            cat_rows = conn.execute(
                "SELECT task_category, AVG(iterations_to_completion) "
                "FROM task_executions "
                "WHERE task_category IS NOT NULL AND iterations_to_completion IS NOT NULL "
                "GROUP BY task_category"
            ).fetchall()

        return {
            "total_tasks": total,
            "pass_rate": (passed / judged) if judged > 0 else 0.0,
            "avg_context_tokens": avg_tokens,
            "spiral_rate": (spirals / total) if total > 0 else 0.0,
            "avg_iterations_by_category": {r[0]: r[1] for r in cat_rows},
        }

    def get_skill_usage(self, skill_name: str) -> dict:
        """
        Returns {"last_used_at": str|None, "usage_count": int}.
        Searches skills_loaded for skill_name as a substring.
        Falls back to zeros if the store raises.
        """
        try:
            with closing(self._connect()) as conn:
                row = conn.execute(
                    "SELECT MAX(timestamp), COUNT(*) FROM task_executions "
                    "WHERE skills_loaded LIKE ?",
                    (f"%{skill_name}%",),
                ).fetchone()
            return {"last_used_at": row[0], "usage_count": row[1] or 0}
        except Exception:
            return {"last_used_at": None, "usage_count": 0}

    def get_hook_stats(self, hook_name: str) -> dict:
        """
        Returns {"avg_execution_ms": float|None, "error_rate": float, "last_triggered_at": str|None}.
        Proxies hook activity from rules_triggered and judge_verdict columns.
        avg_execution_ms is always None (not stored).
        Falls back to zeroes if the store raises.
        """
        try:
            with closing(self._connect()) as conn:
                last_row = conn.execute(
                    "SELECT MAX(timestamp) FROM task_executions "
                    "WHERE rules_triggered LIKE ?",
                    (f"%{hook_name}%",),
                ).fetchone()
                total_row = conn.execute(
                    "SELECT COUNT(*) FROM task_executions "
                    "WHERE rules_triggered LIKE ?",
                    (f"%{hook_name}%",),
                ).fetchone()
                fail_row = conn.execute(
                    "SELECT COUNT(*) FROM task_executions "
                    "WHERE rules_triggered LIKE ? AND judge_verdict = 'fail'",
                    (f"%{hook_name}%",),
                ).fetchone()
            total = total_row[0] or 0
            failed = fail_row[0] or 0
            error_rate = (failed / total) if total > 0 else 0.0
            return {
                "avg_execution_ms": None,
                "error_rate": error_rate,
                "last_triggered_at": last_row[0],
            }
        except Exception:
            return {"avg_execution_ms": None, "error_rate": 0.0, "last_triggered_at": None}
