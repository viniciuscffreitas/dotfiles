"""Tests for Harness Health tracker."""
from __future__ import annotations

import contextlib
import io
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from telemetry.store import TelemetryStore
try:
    from analysis.harness_health import (
        HarnessHealthChecker,
        HarnessHealthReport,
        HookHealth,
        SkillHealth,
    )
    _harness_health_available = True
except ModuleNotFoundError:
    _harness_health_available = False


# ---------------------------------------------------------------------------
# TelemetryStore.get_skill_usage
# ---------------------------------------------------------------------------

def test_get_skill_usage_unknown_skill_returns_zeros(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    result = store.get_skill_usage("nonexistent-skill")
    assert result == {"last_used_at": None, "usage_count": 0}


def test_get_skill_usage_counts_matching_sessions(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    ts = datetime.now(tz=timezone.utc).isoformat()
    store.record({"task_id": "t1", "skills_loaded": "devflow-spec, my-skill", "timestamp": ts})
    store.record({"task_id": "t2", "skills_loaded": "my-skill, other", "timestamp": ts})
    store.record({"task_id": "t3", "skills_loaded": "other-skill"})
    result = store.get_skill_usage("my-skill")
    assert result["usage_count"] == 2
    assert result["last_used_at"] == ts


# ---------------------------------------------------------------------------
# TelemetryStore.get_hook_stats
# ---------------------------------------------------------------------------

def test_get_hook_stats_unknown_hook_returns_zeroes(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    result = store.get_hook_stats("nonexistent-hook")
    assert result["avg_execution_ms"] is None
    assert result["error_rate"] == 0.0
    assert result["last_triggered_at"] is None


def test_get_hook_stats_unknown_hook_is_structurally_correct(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    result = store.get_hook_stats("completely-unknown-hook-xyz")
    assert result == {"avg_execution_ms": None, "error_rate": 0.0, "last_triggered_at": None}


def test_get_hook_stats_computes_error_rate_from_records(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    ts = datetime.now(tz=timezone.utc).isoformat()
    # 3 sessions where "my_hook" is in rules_triggered, 1 failing
    store.record({"task_id": "h1", "rules_triggered": "my_hook", "judge_verdict": "pass", "timestamp": ts})
    store.record({"task_id": "h2", "rules_triggered": "my_hook", "judge_verdict": "fail", "timestamp": ts})
    store.record({"task_id": "h3", "rules_triggered": "my_hook", "judge_verdict": "pass", "timestamp": ts})
    store.record({"task_id": "h4", "rules_triggered": "other_hook", "judge_verdict": "fail"})
    result = store.get_hook_stats("my_hook")
    assert abs(result["error_rate"] - 1 / 3) < 0.01
    assert result["last_triggered_at"] == ts
    assert result["avg_execution_ms"] is None
