"""
TelemetryStore — SQLite persistence layer for devflow task telemetry.

Dual-write partner to sessions.jsonl: structured, queryable, upsertable.
Default DB path: ~/.claude/devflow/telemetry/devflow.db
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, Optional

_TELEMETRY_DIR = Path.home() / ".claude" / "devflow" / "telemetry"
_DEFAULT_DB = _TELEMETRY_DIR / "devflow.db"


def _resolve_default_db() -> Path:
    """Resolve the default DB path at call time.

    Honors DEVFLOW_TELEMETRY_DB so tests (and power-users) can redirect writes
    away from the production store. Resolved per-call — not cached — so pytest
    fixtures that set the env var via monkeypatch work even after the module
    has already been imported.
    """
    override = os.environ.get("DEVFLOW_TELEMETRY_DB")
    return Path(override) if override else _DEFAULT_DB

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
    "firewall_delegated",
    "firewall_task_id",
    "firewall_success",
    "firewall_duration_ms",
    "estimated_usd",
    "test_retry_count",
    "tdd_followthrough_rate",
    "instincts_captured_count",
    "cost_usd",
    "session_id",
    "context_anxiety_score",
    "model",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_creation_tokens",
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
    task_time_seconds               INTEGER,
    firewall_delegated              BOOLEAN,
    firewall_task_id                TEXT,
    firewall_success                BOOLEAN,
    firewall_duration_ms            REAL,
    estimated_usd                   REAL,
    test_retry_count                INTEGER,
    tdd_followthrough_rate          REAL,
    instincts_captured_count        INTEGER,
    cost_usd                        REAL,
    session_id                      TEXT,
    context_anxiety_score           REAL,
    model                           TEXT,
    input_tokens                    INTEGER,
    output_tokens                   INTEGER,
    cache_read_tokens               INTEGER,
    cache_creation_tokens           INTEGER
)
"""


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


class TelemetryStore:
    """Thread-safe SQLite store for devflow task telemetry."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = Path(db_path) if db_path else _resolve_default_db()
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_schema(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with closing(self._connect()) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute(_CREATE_TABLE)
                # Migrate existing databases — idempotent via try/except
                _new_cols = [
                    ("firewall_delegated", "BOOLEAN"),
                    ("firewall_task_id", "TEXT"),
                    ("firewall_success", "BOOLEAN"),
                    ("firewall_duration_ms", "REAL"),
                    ("estimated_usd", "REAL"),
                    ("test_retry_count", "INTEGER"),
                    ("tdd_followthrough_rate", "REAL"),
                    ("instincts_captured_count", "INTEGER"),
                    ("cost_usd", "REAL"),
                    ("session_id", "TEXT"),
                    ("context_anxiety_score", "REAL"),
                    ("model", "TEXT"),
                    ("input_tokens", "INTEGER"),
                    ("output_tokens", "INTEGER"),
                    ("cache_read_tokens", "INTEGER"),
                    ("cache_creation_tokens", "INTEGER"),
                ]
                for col, col_type in _new_cols:
                    try:
                        conn.execute(
                            f"ALTER TABLE task_executions ADD COLUMN {col} {col_type}"
                        )
                    except sqlite3.OperationalError:
                        pass  # column already exists
                conn.commit()

    def _write_with_retry(
        self, fn: "Callable[[sqlite3.Connection], None]", max_retries: int = 3
    ) -> None:
        """Execute fn(conn) inside a transaction; retry up to max_retries on lock errors."""
        for attempt in range(max_retries):
            try:
                with self._lock, closing(self._connect()) as conn:
                    with conn:
                        fn(conn)
                return
            except sqlite3.OperationalError as e:
                if "locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(0.1 * (attempt + 1))
                    continue
                raise

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
        self._write_with_retry(lambda conn: conn.execute(sql, values))

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

    def cost_by_model(self) -> list[dict]:
        """Aggregate runs and total cost grouped by model.

        Rows where model IS NULL (legacy, pre-2026-04-16) are returned under
        the sentinel "NULL (legacy)" so they surface in reports instead of
        silently disappearing into a NULL bucket.
        Sorted by total_cost_usd descending.
        """
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT "
                "  COALESCE(model, 'NULL (legacy)') AS model, "
                "  COUNT(*) AS runs, "
                "  COALESCE(SUM(cost_usd), 0.0) AS total_cost_usd "
                "FROM task_executions "
                "GROUP BY model "
                "ORDER BY total_cost_usd DESC, runs DESC"
            ).fetchall()
        return [dict(r) for r in rows]

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

            avg_usd = conn.execute(
                "SELECT AVG(estimated_usd) FROM task_executions WHERE estimated_usd IS NOT NULL"
            ).fetchone()[0] or 0.0

        return {
            "total_tasks": total,
            "pass_rate": (passed / judged) if judged > 0 else 0.0,
            "avg_context_tokens": avg_tokens,
            "spiral_rate": (spirals / total) if total > 0 else 0.0,
            "avg_iterations_by_category": {r[0]: r[1] for r in cat_rows},
            "avg_estimated_usd": avg_usd,
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

    # Hooks that populate a dedicated column are recognized via that column,
    # not via rules_triggered (which hooks rarely self-populate). Each entry is
    # (presence_clause, fail_clause) — fail_clause=None means "can't derive error".
    _HOOK_SIGNAL_CLAUSES = {
        "post_task_judge": (
            "judge_verdict IS NOT NULL AND judge_verdict != ''",
            "judge_verdict IN ('fail', 'judge_error')",
        ),
        "pre_task_firewall": (
            "firewall_delegated IS NOT NULL",
            "firewall_success = 0",
        ),
        "cost_tracker": (
            "(cost_usd IS NOT NULL OR estimated_usd IS NOT NULL)",
            None,
        ),
        "instinct_capture": (
            "instincts_captured_count IS NOT NULL",
            None,
        ),
        "task_telemetry": (
            "iterations_to_completion IS NOT NULL",
            None,
        ),
        "pre_task_profiler": (
            "probability_score IS NOT NULL",
            None,
        ),
        "task_boundary_judge": (
            "judge_verdict IS NOT NULL AND judge_verdict != ''",
            "judge_verdict IN ('fail', 'judge_error')",
        ),
    }

    def get_hook_stats(self, hook_name: str) -> dict:
        """
        Returns {"avg_execution_ms": float|None, "error_rate": float, "last_triggered_at": str|None}.

        Hooks with dedicated telemetry columns (see _HOOK_SIGNAL_CLAUSES) are
        recognized via those columns; others fall back to rules_triggered LIKE.
        avg_execution_ms is always None (not stored today).
        Falls back to zeroes if the store raises.
        """
        try:
            presence_clause, fail_clause = self._HOOK_SIGNAL_CLAUSES.get(
                hook_name, (None, None)
            )
            if presence_clause is None:
                presence_clause = "rules_triggered LIKE ?"
                args = (f"%{hook_name}%",)
                fail_sql = (
                    "SELECT COUNT(*) FROM task_executions "
                    "WHERE rules_triggered LIKE ? AND judge_verdict = 'fail'"
                )
                fail_args = args
            else:
                args = ()
                if fail_clause:
                    fail_sql = (
                        f"SELECT COUNT(*) FROM task_executions "
                        f"WHERE ({presence_clause}) AND ({fail_clause})"
                    )
                    fail_args = ()
                else:
                    fail_sql = None
                    fail_args = ()

            with closing(self._connect()) as conn:
                last_row = conn.execute(
                    f"SELECT MAX(timestamp) FROM task_executions WHERE {presence_clause}",
                    args,
                ).fetchone()
                total_row = conn.execute(
                    f"SELECT COUNT(*) FROM task_executions WHERE {presence_clause}",
                    args,
                ).fetchone()
                if fail_sql is not None:
                    fail_row = conn.execute(fail_sql, fail_args).fetchone()
                    failed = fail_row[0] or 0
                else:
                    failed = 0

            total = total_row[0] or 0
            error_rate = (failed / total) if (total > 0 and fail_sql is not None) else 0.0
            return {
                "avg_execution_ms": None,
                "error_rate": error_rate,
                "last_triggered_at": last_row[0],
            }
        except Exception:
            return {"avg_execution_ms": None, "error_rate": 0.0, "last_triggered_at": None}


# ---------------------------------------------------------------------------
# Process-level singleton — avoids N TelemetryStore() instantiations per Stop
# ---------------------------------------------------------------------------

_process_store: "TelemetryStore | None" = None


def get_store(db_path: "Path | None" = None) -> "TelemetryStore":
    """Return the process-level TelemetryStore singleton.

    Hooks running inside stop_dispatcher (same process) share one instance:
    one threading.Lock, one SQLite connection setup, one schema init.
    Direct TelemetryStore() construction still works and remains independent.
    """
    global _process_store
    if _process_store is None:
        _process_store = TelemetryStore(db_path)
    return _process_store


def _reset_store() -> None:
    """Reset the singleton — for test isolation only."""
    global _process_store
    _process_store = None
