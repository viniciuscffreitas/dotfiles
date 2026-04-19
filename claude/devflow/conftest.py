"""
Root conftest for devflow — test isolation guardrails.

Autouse fixture redirects TelemetryStore writes to a per-test SQLite file via
DEVFLOW_TELEMETRY_DB. Prevents the test suite from polluting the production
telemetry DB at ~/.claude/devflow/telemetry/devflow.db.

Context: before this guard was added, test runs accumulated ~12k rows with
task_id='pid-<pid>' in the production DB, corrupting cli stats / recent /
anxiety queries and causing flaky cross-test interference via
_is_already_judged() in post_task_judge.py.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_telemetry_db(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVFLOW_TELEMETRY_DB", str(tmp_path / "telemetry_test.db"))
