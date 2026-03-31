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
