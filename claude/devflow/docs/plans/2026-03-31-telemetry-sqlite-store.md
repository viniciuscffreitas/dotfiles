# Unified Telemetry SQLite Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a structured, queryable SQLite persistence layer that receives telemetry from every devflow hook session and enables analytics queries impossible with the append-only sessions.jsonl.

**Architecture:** TelemetryStore wraps a SQLite file at `~/.claude/devflow/telemetry/devflow.db`, auto-creates the schema on first run, and exposes upsert + query methods. The existing sessions.jsonl remains as the append-only audit log; SQLite is the analytics layer. task_telemetry.py dual-writes to both. A one-time migration seeds SQLite from sessions.jsonl.

**Tech Stack:** Python 3.13, sqlite3 (stdlib), pytest, unittest.mock

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `telemetry/__init__.py` | Makes `telemetry/` a Python package |
| Create | `telemetry/store.py` | TelemetryStore: schema + upsert + queries |
| Create | `telemetry/migrate_sessions.py` | One-time migration from sessions.jsonl |
| Create | `telemetry/cli.py` | CLI: stats / recent / anxiety commands |
| Create | `hooks/tests/test_telemetry_store.py` | Tests for TelemetryStore |
| Create | `hooks/tests/test_migrate_sessions.py` | Tests for migration script |
| Modify | `hooks/task_telemetry.py` | Dual-write to SQLite at end of main() |
| Modify | `hooks/tests/test_task_telemetry.py` | Test that TelemetryStore.record() is called |
| Modify | `docs/audit-20260331.md` | Document the prompt |

All paths are relative to `~/.claude/devflow/`.

---

## Task 1: TelemetryStore — schema + record()

**Files:**
- Create: `telemetry/__init__.py`
- Create: `telemetry/store.py`
- Create: `hooks/tests/test_telemetry_store.py` (RED phase only)

- [ ] **Step 1: Write failing tests for schema and record()**

Create `hooks/tests/test_telemetry_store.py`:

```python
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
        "iterations_to_completion", "context_tokens_consumed",
        "context_tokens_at_first_action", "spiral_detected",
        "judge_verdict", "judge_categories_failed",
        "probability_score", "impact_score", "oversight_level",
        "skills_loaded", "rules_triggered", "task_time_seconds",
    }
    assert required <= cols


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
    store.record({"task_id": "abc123", "task_category": "simple"})
    store.record({"task_id": "abc123", "task_category": "complex"})  # overwrite
    rows = store.get_recent(10)
    assert len(rows) == 1, "upsert must not create a duplicate"
    assert rows[0]["task_category"] == "complex"


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/.claude/devflow
python3.13 -m pytest hooks/tests/test_telemetry_store.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'telemetry'` (telemetry package doesn't exist yet)

- [ ] **Step 3: Create `telemetry/__init__.py`**

```python
```

(empty file — just marks the directory as a Python package)

- [ ] **Step 4: Create `telemetry/store.py`**

```python
"""
TelemetryStore — SQLite persistence layer for devflow task telemetry.

Dual-write partner to sessions.jsonl: structured, queryable, upsertable.
Default DB path: ~/.claude/devflow/telemetry/devflow.db
"""
from __future__ import annotations

import json
import sqlite3
import threading
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
            with self._connect() as conn:
                conn.execute(_CREATE_TABLE)
                conn.commit()

    def record(self, payload: dict) -> None:
        """Upsert a task record. Missing columns default to None."""
        values = {col: payload.get(col) for col in _COLUMNS}
        placeholders = ", ".join(f":{col}" for col in _COLUMNS)
        cols = ", ".join(_COLUMNS)
        sql = f"INSERT OR REPLACE INTO task_executions ({cols}) VALUES ({placeholders})"
        with self._lock:
            with self._connect() as conn:
                conn.execute(sql, values)
                conn.commit()

    def get_by_category(self, category: str) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_executions WHERE task_category = ?", (category,)
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_recent(self, n: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_executions ORDER BY rowid DESC LIMIT ?", (n,)
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_failure_patterns(self, days: int = 30) -> list[dict]:
        """Records where judge_verdict in ('warn', 'fail') within the last N days."""
        cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_executions "
                "WHERE judge_verdict IN ('warn', 'fail') AND timestamp >= ?",
                (cutoff,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_context_anxiety_cases(self, threshold: int = 60_000) -> list[dict]:
        """Records where context_tokens_at_first_action > threshold."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM task_executions WHERE context_tokens_at_first_action > ?",
                (threshold,),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def summary_stats(self) -> dict:
        with self._connect() as conn:
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
```

- [ ] **Step 5: Run tests — must pass**

```bash
cd ~/.claude/devflow
python3.13 -m pytest hooks/tests/test_telemetry_store.py -v
```

Expected: **13 passed**

- [ ] **Step 6: Run full suite — no regressions**

```bash
python3.13 -m pytest hooks/tests/ -q
```

Expected: **329 passed** (316 + 13)

- [ ] **Step 7: Commit**

```bash
cd ~/.claude/devflow
git add telemetry/__init__.py telemetry/store.py hooks/tests/test_telemetry_store.py
git commit -m "feat(telemetry): add TelemetryStore SQLite persistence layer

Schema: task_executions with 31 columns covering agent behavior signals,
quality signals, risk profile, harness signals, and business signals.
API: record() upsert, get_by_category(), get_recent(), get_failure_patterns(),
get_context_anxiety_cases(), summary_stats(). Thread-safe writes via Lock.
13 tests added."
```

---

## Task 2: Migration script — sessions.jsonl → SQLite

**Files:**
- Create: `telemetry/migrate_sessions.py`
- Create: `hooks/tests/test_migrate_sessions.py`

- [ ] **Step 1: Write failing migration tests**

Create `hooks/tests/test_migrate_sessions.py`:

```python
"""Tests for sessions.jsonl → SQLite migration."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from telemetry.store import TelemetryStore


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------

def test_migrate_maps_session_id_to_task_id(tmp_path):
    jsonl = tmp_path / "sessions.jsonl"
    ts_end = 1_774_932_691
    _write_jsonl(jsonl, [{
        "session_id": "abc123",
        "project": "startup",
        "cwd": "/Users/vini/Developer/startup",
        "ts_end": ts_end,
        "phases": [
            {"ts": "2026-03-31T00:00:00Z", "phase": "PENDING",
             "task_id": "implement auth", "tokens_cumulative": 1000},
            {"ts": "2026-03-31T00:01:00Z", "phase": "IMPLEMENTING",
             "task_id": "implement auth", "tokens_cumulative": 2000},
            {"ts": "2026-03-31T00:02:00Z", "phase": "COMPLETED",
             "task_id": "implement auth", "tokens_cumulative": 3000},
        ],
        "total_tokens": 5000,
    }])

    db = tmp_path / "test.db"
    from telemetry.migrate_sessions import migrate
    count = migrate(jsonl_path=jsonl, db_path=db)

    assert count == 1
    store = TelemetryStore(db_path=db)
    rows = store.get_recent(1)
    r = rows[0]
    assert r["task_id"] == "abc123"
    assert r["context_tokens_consumed"] == 5000
    assert r["iterations_to_completion"] == 3
    assert r["task_description"] == "implement auth"
    assert r["stack"] == "typescript"  # startup → typescript guess
    expected_ts = datetime.fromtimestamp(ts_end, tz=timezone.utc).isoformat()
    assert r["timestamp"] == expected_ts


def test_migrate_record_count_matches_jsonl(tmp_path):
    jsonl = tmp_path / "sessions.jsonl"
    records = [
        {
            "session_id": f"sess_{i}",
            "project": "test",
            "cwd": "/tmp/test",
            "ts_end": 1_000_000 + i,
            "phases": [],
            "total_tokens": 100 * i,
        }
        for i in range(5)
    ]
    _write_jsonl(jsonl, records)

    db = tmp_path / "test.db"
    from telemetry.migrate_sessions import migrate
    count = migrate(jsonl_path=jsonl, db_path=db)

    assert count == 5
    store = TelemetryStore(db_path=db)
    stats = store.summary_stats()
    assert stats["total_tasks"] == 5
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/.claude/devflow
python3.13 -m pytest hooks/tests/test_migrate_sessions.py -v 2>&1 | head -10
```

Expected: `ImportError: cannot import name 'migrate' from 'telemetry.migrate_sessions'`

- [ ] **Step 3: Create `telemetry/migrate_sessions.py`**

```python
"""
One-time migration: read sessions.jsonl → insert into SQLite via TelemetryStore.

Usage:
    python3.13 telemetry/migrate_sessions.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
from telemetry.store import TelemetryStore

_TELEMETRY_DIR = Path.home() / ".claude" / "devflow" / "telemetry"

# Best-guess mapping from known project names to stack
_PROJECT_STACK: dict[str, str] = {
    "momease": "dart",
    "startup": "typescript",
    "devflow": "python",
    "developer": "unknown",
}


def _project_to_stack(project: str) -> str:
    return _PROJECT_STACK.get(project.lower(), "unknown")


def migrate(
    jsonl_path: Optional[Path] = None,
    db_path: Optional[Path] = None,
) -> int:
    """
    Read all records from sessions.jsonl and upsert into SQLite.

    Returns number of records migrated.
    """
    if jsonl_path is None:
        jsonl_path = _TELEMETRY_DIR / "sessions.jsonl"
    if not jsonl_path.exists():
        print(f"[migrate] No sessions.jsonl at {jsonl_path}")
        return 0

    store = TelemetryStore(db_path=db_path)
    migrated = 0

    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            task_id = rec.get("session_id")
            if not task_id:
                continue

            phases = rec.get("phases") or []
            task_description = phases[0].get("task_id") if phases else None

            ts_end = rec.get("ts_end")
            timestamp = (
                datetime.fromtimestamp(ts_end, tz=timezone.utc).isoformat()
                if ts_end
                else None
            )

            store.record({
                "task_id": task_id,
                "timestamp": timestamp,
                "task_description": task_description,
                "stack": _project_to_stack(rec.get("project", "")),
                "context_tokens_consumed": rec.get("total_tokens"),
                "iterations_to_completion": len(phases),
            })
            migrated += 1

    print(f"[migrate] {migrated} records migrated from {jsonl_path.name} → devflow.db")
    return migrated


if __name__ == "__main__":
    sys.exit(0 if migrate() >= 0 else 1)
```

- [ ] **Step 4: Run migration tests — must pass**

```bash
cd ~/.claude/devflow
python3.13 -m pytest hooks/tests/test_migrate_sessions.py -v
```

Expected: **2 passed**

- [ ] **Step 5: Run full suite — no regressions**

```bash
python3.13 -m pytest hooks/tests/ -q
```

Expected: **331 passed** (329 + 2)

- [ ] **Step 6: Commit**

```bash
cd ~/.claude/devflow
git add telemetry/migrate_sessions.py hooks/tests/test_migrate_sessions.py
git commit -m "feat(telemetry): add sessions.jsonl → SQLite migration script

migrate() maps session_id→task_id, project→stack, total_tokens→context_tokens_consumed,
len(phases)→iterations_to_completion, ts_end→ISO timestamp.
Accepts optional jsonl_path/db_path for testability.
2 tests added."
```

---

## Task 3: Integrate TelemetryStore into task_telemetry.py

**Files:**
- Modify: `hooks/task_telemetry.py`
- Modify: `hooks/tests/test_task_telemetry.py`

- [ ] **Step 1: Write failing integration test**

Add this test to the **end** of `hooks/tests/test_task_telemetry.py`:

```python
# ---------------------------------------------------------------------------
# TelemetryStore integration
# ---------------------------------------------------------------------------

def test_main_writes_to_sqlite_after_sessions_jsonl(tmp_path):
    """Verify TelemetryStore.record() is called at end of main()."""
    # Build a minimal JSONL with a PENDING phase
    projects_dir = tmp_path / "projects"
    slug = "-Users-vini-Developer-agents"
    session_dir = projects_dir / slug
    session_dir.mkdir(parents=True)
    session_jsonl = session_dir / "sqlite-test-session.jsonl"
    session_jsonl.write_text(
        json.dumps({
            "type": "assistant",
            "timestamp": "2026-03-31T00:00:00Z",
            "message": {
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "content": [{
                    "type": "tool_use",
                    "id": "t1",
                    "name": "Write",
                    "input": {
                        "file_path": "/some/path/active-spec.json",
                        "content": json.dumps({
                            "status": "PENDING",
                            "plan_path": "test sqlite integration",
                        }),
                    },
                }],
            },
        }) + "\n",
        encoding="utf-8",
    )

    telemetry_dir = tmp_path / "telemetry"
    telemetry_dir.mkdir()

    import task_telemetry
    from unittest.mock import patch, MagicMock

    mock_store_instance = MagicMock()

    with (
        patch.object(task_telemetry, "TELEMETRY_DIR", telemetry_dir),
        patch.object(task_telemetry, "PROJECTS_DIR", projects_dir),
        patch("task_telemetry.read_hook_stdin", return_value={
            "session_id": "sqlite-test-session",
            "cwd": "/Users/vini/Developer/agents",
        }),
        patch("task_telemetry.TelemetryStore", return_value=mock_store_instance) as MockClass,
    ):
        result = main()

    assert result == 0
    MockClass.assert_called_once()
    mock_store_instance.record.assert_called_once()
    call_payload = mock_store_instance.record.call_args[0][0]
    assert call_payload["task_id"] == "sqlite-test-session"
    assert "context_tokens_consumed" in call_payload
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ~/.claude/devflow
python3.13 -m pytest hooks/tests/test_task_telemetry.py::test_main_writes_to_sqlite_after_sessions_jsonl -v
```

Expected: FAIL — `AttributeError: module 'task_telemetry' has no attribute 'TelemetryStore'`

- [ ] **Step 3: Modify `hooks/task_telemetry.py`**

Add these lines to the **imports section** right after the existing `sys.path.insert` line (line 26):

```python
sys.path.insert(0, str(Path(__file__).parent))
from _util import get_session_id, read_hook_stdin

# SQLite analytics layer — dual-write partner to sessions.jsonl
try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from telemetry.store import TelemetryStore
except ImportError:
    TelemetryStore = None  # type: ignore[assignment,misc]
```

Then add these lines at the **end of `main()`** right before `return 0` (after the `log_path.write_text(...)` try/except block):

```python
    # Dual-write to SQLite analytics layer
    if TelemetryStore is not None:
        try:
            TelemetryStore().record({
                "task_id": record["session_id"],
                "context_tokens_consumed": record["total_tokens"],
                "iterations_to_completion": len(record["phases"]),
                "stack": record["project"],
            })
        except Exception as exc:
            print(f"[devflow:telemetry] warning: SQLite write failed: {exc}", file=sys.stderr)

    return 0
```

Note: The existing `return 0` at line 337 must be replaced by the block above (which ends with `return 0`).

- [ ] **Step 4: Run integration test — must pass**

```bash
cd ~/.claude/devflow
python3.13 -m pytest hooks/tests/test_task_telemetry.py::test_main_writes_to_sqlite_after_sessions_jsonl -v
```

Expected: **1 passed**

- [ ] **Step 5: Run full suite — no regressions**

```bash
python3.13 -m pytest hooks/tests/ -q
```

Expected: **332 passed** (331 + 1)

- [ ] **Step 6: Commit**

```bash
cd ~/.claude/devflow
git add hooks/task_telemetry.py hooks/tests/test_task_telemetry.py
git commit -m "feat(telemetry): dual-write to SQLite at end of task_telemetry main()

Every future session now writes to sessions.jsonl (audit log) AND
devflow.db (queryable analytics layer) simultaneously.
TelemetryStore import is wrapped in try/except — hook never breaks if store unavailable.
1 test added."
```

---

## Task 4: CLI

**Files:**
- Create: `telemetry/cli.py`

- [ ] **Step 1: Create `telemetry/cli.py`**

```python
"""
devflow telemetry CLI — quick-stats commands.

Usage:
    python3.13 telemetry/cli.py stats     — summary statistics
    python3.13 telemetry/cli.py recent    — last 10 tasks
    python3.13 telemetry/cli.py anxiety   — context anxiety cases (>60k tokens at first action)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from telemetry.store import TelemetryStore


def cmd_stats() -> None:
    store = TelemetryStore()
    s = store.summary_stats()
    print(f"{'Total tasks:':<26} {s['total_tasks']}")
    print(f"{'Pass rate:':<26} {s['pass_rate']:.1%}")
    print(f"{'Avg context tokens:':<26} {s['avg_context_tokens']:,.0f}")
    print(f"{'Spiral rate:':<26} {s['spiral_rate']:.1%}")
    iters = s["avg_iterations_by_category"]
    if iters:
        print("Avg iterations by category:")
        for cat, avg in sorted(iters.items()):
            print(f"  {cat}: {avg:.1f}")
    else:
        print("Avg iterations by category:  (no data)")


def cmd_recent() -> None:
    store = TelemetryStore()
    records = store.get_recent(10)
    if not records:
        print("No records found.")
        return
    print(f"{'task_id':<14} {'timestamp':<26} {'category':<10} {'tokens':>10}  verdict")
    print("-" * 72)
    for r in records:
        print(
            f"{str(r.get('task_id', ''))[:13]:<14} "
            f"{str(r.get('timestamp', 'N/A'))[:25]:<26} "
            f"{str(r.get('task_category', '?')):<10} "
            f"{(r.get('context_tokens_consumed') or 0):>10,}  "
            f"{r.get('judge_verdict') or 'pending'}"
        )


def cmd_anxiety() -> None:
    store = TelemetryStore()
    records = store.get_context_anxiety_cases()
    if not records:
        print("No context anxiety cases (threshold: 60,000 tokens at first action).")
        return
    print(f"Context anxiety cases — {len(records)} found (threshold: 60,000 tokens)")
    print(f"{'task_id':<14} {'tokens_at_first_action':>22}  stack")
    print("-" * 50)
    for r in records:
        print(
            f"{str(r.get('task_id', ''))[:13]:<14} "
            f"{(r.get('context_tokens_at_first_action') or 0):>22,}  "
            f"{r.get('stack') or '?'}"
        )


_COMMANDS = {"stats": cmd_stats, "recent": cmd_recent, "anxiety": cmd_anxiety}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd not in _COMMANDS:
        print(f"Unknown command: {cmd!r}. Available: {', '.join(_COMMANDS)}", file=sys.stderr)
        sys.exit(1)
    _COMMANDS[cmd]()
```

- [ ] **Step 2: Commit**

```bash
cd ~/.claude/devflow
git add telemetry/cli.py
git commit -m "feat(telemetry): add CLI for quick-stats queries

Commands: stats (summary), recent (last 10 tasks), anxiety (context anxiety cases).
Run: python3.13 telemetry/cli.py stats"
```

---

## Task 5: Validation + Documentation

**Files:**
- Run: migration + CLI
- Modify: `docs/audit-20260331.md`

- [ ] **Step 1: Run full test suite (final baseline)**

```bash
cd ~/.claude/devflow
python3.13 -m pytest hooks/tests/ -q
```

Expected: **332 passed**, 0 failed. Record the exact count.

- [ ] **Step 2: Run migration against real sessions.jsonl**

```bash
cd ~/.claude/devflow
python3.13 telemetry/migrate_sessions.py
```

Expected output: `[migrate] 11 records migrated from sessions.jsonl → devflow.db`
(11 = current sessions.jsonl record count)

- [ ] **Step 3: Run CLI stats — must show total_tasks > 0**

```bash
cd ~/.claude/devflow
python3.13 telemetry/cli.py stats
```

Expected output (example):
```
Total tasks:               11
Pass rate:                 0.0%
Avg context tokens:        7,461,826
Spiral rate:               0.0%
Avg iterations by category:  (no data)
```

`total_tasks` must be > 0. Pass rate and spiral rate will be 0.0% because judge hasn't run yet — that is expected.

- [ ] **Step 4: Run CLI recent**

```bash
python3.13 telemetry/cli.py recent
```

Expected: a table showing the last 10 task records with task_id, timestamp, tokens.

- [ ] **Step 5: Document in audit-20260331.md**

Append this section to `docs/audit-20260331.md`:

```markdown
### Prompt 1: unified telemetry SQLite store — 16 tests added, 316 → 332 total (`2026-03-31`)

**Files created:**
- `telemetry/__init__.py` — Python package marker
- `telemetry/store.py` — TelemetryStore: 31-column task_executions schema, upsert, 5 query methods
- `telemetry/migrate_sessions.py` — one-time migration from sessions.jsonl
- `telemetry/cli.py` — CLI: stats / recent / anxiety commands

**Files modified:**
- `hooks/task_telemetry.py` — dual-write to SQLite at end of main()
- `hooks/tests/test_telemetry_store.py` — 13 new tests (schema ×2, record ×3, queries ×5, summary_stats ×3)
- `hooks/tests/test_migrate_sessions.py` — 2 new tests (field mapping, record count)
- `hooks/tests/test_task_telemetry.py` — 1 new test (TelemetryStore.record mock)

**Migration result:** 11 sessions.jsonl records seeded into devflow.db.
**CLI verified:** `python3.13 telemetry/cli.py stats` shows total_tasks > 0.
**Regressions:** 0.
```

(Replace `16` / `332` with actual counts from Step 1 if they differ.)

- [ ] **Step 6: Final commit**

```bash
cd ~/.claude/devflow
git add docs/audit-20260331.md
git commit -m "docs: record Prompt 1 telemetry SQLite store in audit log"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| TelemetryStore class with SQLite backend | Task 1 |
| 31-column task_executions schema | Task 1 |
| record() upsert, missing fields default None | Task 1 |
| get_by_category() | Task 1 |
| get_recent(n) | Task 1 |
| get_failure_patterns(days) | Task 1 |
| get_context_anxiety_cases(threshold) | Task 1 |
| summary_stats() | Task 1 |
| migrate_sessions.py with all field mappings | Task 2 |
| task_telemetry.py dual-write | Task 3 |
| CLI: stats / recent / anxiety | Task 4 |
| Run migration + verify total_tasks > 0 | Task 5 |
| All schema column tests | Task 1 |
| record() insert/upsert/missing tests | Task 1 |
| Query method tests | Task 1 |
| summary_stats pass_rate + spiral_rate tests | Task 1 |
| Migration field mapping test | Task 2 |
| Migration count == jsonl count test | Task 2 |
| task_telemetry mock test | Task 3 |
| audit-20260331.md documentation | Task 5 |

No gaps found.

**Placeholder scan:** No TBD, TODO, or "similar to" references. All code blocks are complete.

**Type consistency:**
- `TelemetryStore(db_path=db)` — consistent across all tasks
- `store.record({"task_id": ..., ...})` — consistent in Task 1, 2, 3
- `store.get_recent(n)` returns `list[dict]` — used consistently in tests
- `migrate(jsonl_path=..., db_path=...)` — consistent in Task 2 tests and script
- `task_telemetry.TelemetryStore` — the mock path in Task 3 matches the import added in Task 3
