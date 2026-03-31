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

def test_migrate_maps_all_fields_correctly(tmp_path):
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
    assert r["stack"] == "typescript"  # "startup" project → typescript
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
