"""
Tests for telemetry/cli.py — thin CLI wrapper over TelemetryStore.

Tests use subprocess to invoke the CLI as __main__ so that sys.argv handling
and the exit-code paths are exercised end-to-end without mocking internals.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# devflow root: telemetry/tests/ -> telemetry/ -> devflow root
_ROOT = Path(__file__).parent.parent.parent
_CLI = _ROOT / "telemetry" / "cli.py"


def run_cli(*args, env_db: Path | None = None) -> subprocess.CompletedProcess:
    """Run the CLI with optional DEVFLOW_DB env override."""
    cmd = [sys.executable, str(_CLI), *args]
    env = None
    if env_db is not None:
        env = {**os.environ, "DEVFLOW_DB": str(env_db)}
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


# ---------------------------------------------------------------------------
# cmd_stats
# ---------------------------------------------------------------------------

class TestCmdStats:
    def test_stats_exits_zero(self):
        result = run_cli("stats")
        assert result.returncode == 0

    def test_stats_contains_total_tasks_line(self):
        result = run_cli("stats")
        assert "Total tasks:" in result.stdout

    def test_stats_contains_pass_rate_line(self):
        result = run_cli("stats")
        assert "Pass rate:" in result.stdout

    def test_stats_contains_avg_context_tokens(self):
        result = run_cli("stats")
        assert "Avg context tokens:" in result.stdout

    def test_stats_contains_spiral_rate(self):
        result = run_cli("stats")
        assert "Spiral rate:" in result.stdout

    def test_stats_default_command_when_no_args(self):
        """Invoking with no args should default to stats output."""
        result = run_cli()
        assert result.returncode == 0
        assert "Total tasks:" in result.stdout


# ---------------------------------------------------------------------------
# cmd_recent
# ---------------------------------------------------------------------------

class TestCmdRecent:
    def test_recent_exits_zero(self):
        result = run_cli("recent")
        assert result.returncode == 0

    def test_recent_empty_db_prints_no_records(self, tmp_path):
        db = tmp_path / "empty.db"
        result = run_cli("recent", env_db=db)
        assert result.returncode == 0
        assert "No records found." in result.stdout

    def test_recent_with_data_prints_header(self, tmp_path):
        db = tmp_path / "with_data.db"
        _seed_db(db, [
            {"task_id": "t001", "task_category": "feat", "judge_verdict": "pass",
             "context_tokens_consumed": 12345},
        ])
        result = run_cli("recent", env_db=db)
        assert result.returncode == 0
        assert "task_id" in result.stdout
        assert "verdict" in result.stdout

    def test_recent_with_data_shows_task_id(self, tmp_path):
        db = tmp_path / "with_data.db"
        _seed_db(db, [
            {"task_id": "task-xyz-001", "task_category": "fix",
             "judge_verdict": "warn", "context_tokens_consumed": 5000},
        ])
        result = run_cli("recent", env_db=db)
        assert "task-xyz-001" in result.stdout

    def test_recent_pending_verdict_when_null(self, tmp_path):
        db = tmp_path / "pending.db"
        _seed_db(db, [{"task_id": "t-pending", "judge_verdict": None}])
        result = run_cli("recent", env_db=db)
        assert "pending" in result.stdout


# ---------------------------------------------------------------------------
# cmd_anxiety
# ---------------------------------------------------------------------------

class TestCmdAnxiety:
    def test_anxiety_exits_zero(self):
        result = run_cli("anxiety")
        assert result.returncode == 0

    def test_anxiety_empty_db_prints_no_cases(self, tmp_path):
        db = tmp_path / "empty.db"
        result = run_cli("anxiety", env_db=db)
        assert result.returncode == 0
        assert "No context anxiety cases" in result.stdout

    def test_anxiety_below_threshold_not_shown(self, tmp_path):
        db = tmp_path / "low.db"
        _seed_db(db, [{"task_id": "low-tok", "context_tokens_at_first_action": 1000}])
        result = run_cli("anxiety", env_db=db)
        assert "No context anxiety cases" in result.stdout

    def test_anxiety_above_threshold_shown(self, tmp_path):
        db = tmp_path / "high.db"
        _seed_db(db, [
            {"task_id": "high-tok", "context_tokens_at_first_action": 75000,
             "stack": "python"},
        ])
        result = run_cli("anxiety", env_db=db)
        assert result.returncode == 0
        assert "high-tok" in result.stdout
        assert "75,000" in result.stdout

    def test_anxiety_shows_count_in_header(self, tmp_path):
        db = tmp_path / "two.db"
        _seed_db(db, [
            {"task_id": "a1", "context_tokens_at_first_action": 80000},
            {"task_id": "a2", "context_tokens_at_first_action": 90000},
        ])
        result = run_cli("anxiety", env_db=db)
        assert "2 found" in result.stdout


# ---------------------------------------------------------------------------
# cmd_stats --by-model
# ---------------------------------------------------------------------------

class TestCmdStatsByModel:
    def test_by_model_exits_zero_on_empty_db(self, tmp_path):
        db = tmp_path / "empty.db"
        result = run_cli("stats", "--by-model", env_db=db)
        assert result.returncode == 0

    def test_by_model_shows_breakdown(self, tmp_path):
        db = tmp_path / "mix.db"
        _seed_db(db, [
            {"task_id": "a", "model": "claude-opus-4-7", "cost_usd": 1.20},
            {"task_id": "b", "model": "claude-opus-4-7", "cost_usd": 2.80},
            {"task_id": "c", "model": "claude-sonnet-4-6", "cost_usd": 0.15},
            {"task_id": "d", "model": None, "cost_usd": 0.05},  # legacy
        ])
        result = run_cli("stats", "--by-model", env_db=db)
        assert result.returncode == 0
        # Shows at least each model name and the numeric total
        assert "claude-opus-4-7" in result.stdout
        assert "claude-sonnet-4-6" in result.stdout
        assert "4.00" in result.stdout  # 1.20 + 2.80
        # Legacy rows are visibly labelled, not hidden
        assert "legacy" in result.stdout.lower() or "NULL" in result.stdout


# ---------------------------------------------------------------------------
# Unknown command
# ---------------------------------------------------------------------------

class TestUnknownCommand:
    def test_unknown_command_exits_nonzero(self):
        result = run_cli("bogus")
        assert result.returncode == 1

    def test_unknown_command_prints_to_stderr(self):
        result = run_cli("bogus")
        assert "Unknown command" in result.stderr
        assert "bogus" in result.stderr


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_db(db_path: Path, records: list[dict]) -> None:
    """Insert minimal records into a fresh DB via TelemetryStore."""
    sys.path.insert(0, str(_ROOT))
    from telemetry.store import TelemetryStore
    store = TelemetryStore(db_path=db_path)
    for r in records:
        store.record(r)
