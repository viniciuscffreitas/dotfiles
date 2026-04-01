"""Tests for cost_tracker Stop hook — USD cost computation."""
from __future__ import annotations

import io
import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# devflow root is two levels up from hooks/tests/
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from telemetry.store import TelemetryStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hook_data(model: str, input_tokens: int, output_tokens: int, session_id: str = "sess-1") -> dict:
    return {
        "session_id": session_id,
        "model": model,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }


def _run_main(hook_data: dict, tmp_db: Path) -> tuple[int, str]:
    """Run cost_tracker.main() and return (exit_code, stdout)."""
    import importlib, types

    # Patch TelemetryStore to use tmp_db
    import hooks.cost_tracker as ct
    importlib.reload(ct)

    captured = io.StringIO()
    store = TelemetryStore(db_path=tmp_db)

    with (
        patch("hooks.cost_tracker.read_hook_stdin", return_value=hook_data),
        patch("hooks.cost_tracker.TelemetryStore", return_value=store),
        patch("sys.stdout", captured),
    ):
        code = ct.main()

    return code, captured.getvalue()


# ---------------------------------------------------------------------------
# USD calculation — correct per model
# ---------------------------------------------------------------------------

def test_cost_opus(tmp_path):
    """claude-opus-4-6: $15/M input, $75/M output."""
    db = tmp_path / "t.db"
    hook_data = _make_hook_data("claude-opus-4-6", input_tokens=1_000_000, output_tokens=1_000_000)
    code, out = _run_main(hook_data, db)
    assert code == 0
    # 1M input = $15, 1M output = $75 → $90.00
    assert "$90.00" in out


def test_cost_sonnet(tmp_path):
    """claude-sonnet-4-6: $3/M input, $15/M output."""
    db = tmp_path / "t.db"
    hook_data = _make_hook_data("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=1_000_000)
    code, out = _run_main(hook_data, db)
    assert code == 0
    # 1M input = $3, 1M output = $15 → $18.00
    assert "$18.00" in out


def test_cost_haiku(tmp_path):
    """claude-haiku-4-5-20251001: $0.80/M input, $4/M output."""
    db = tmp_path / "t.db"
    hook_data = _make_hook_data("claude-haiku-4-5-20251001", input_tokens=1_000_000, output_tokens=1_000_000)
    code, out = _run_main(hook_data, db)
    assert code == 0
    # 1M input = $0.80, 1M output = $4 → $4.80
    assert "$4.80" in out


def test_cost_small_session_sonnet(tmp_path):
    """Typical small session: 12.3k input, 4.1k output on sonnet."""
    db = tmp_path / "t.db"
    hook_data = _make_hook_data("claude-sonnet-4-6", input_tokens=12_300, output_tokens=4_100)
    code, out = _run_main(hook_data, db)
    assert code == 0
    # $3 * 12.3k/1M + $15 * 4.1k/1M = 0.0369 + 0.0615 = 0.0984... ≈ $0.09..
    assert "$0.0" in out  # some cents


# ---------------------------------------------------------------------------
# Fallback — unknown model uses sonnet pricing
# ---------------------------------------------------------------------------

def test_fallback_unknown_model_uses_sonnet_pricing(tmp_path):
    db = tmp_path / "t.db"
    hook_data = _make_hook_data("claude-future-model-99", input_tokens=1_000_000, output_tokens=1_000_000)
    code, out = _run_main(hook_data, db)
    assert code == 0
    assert "$18.00" in out


# ---------------------------------------------------------------------------
# Output format — [devflow:cost] prefix
# ---------------------------------------------------------------------------

def test_output_has_devflow_prefix(tmp_path):
    db = tmp_path / "t.db"
    hook_data = _make_hook_data("claude-sonnet-4-6", input_tokens=10_000, output_tokens=2_000)
    _, out = _run_main(hook_data, db)
    assert out.startswith("[devflow:cost]")


def test_output_contains_model_name(tmp_path):
    db = tmp_path / "t.db"
    hook_data = _make_hook_data("claude-sonnet-4-6", input_tokens=10_000, output_tokens=2_000)
    _, out = _run_main(hook_data, db)
    assert "sonnet-4-6" in out


def test_output_contains_token_counts(tmp_path):
    db = tmp_path / "t.db"
    hook_data = _make_hook_data("claude-sonnet-4-6", input_tokens=12_300, output_tokens=4_100)
    _, out = _run_main(hook_data, db)
    assert "12.3k" in out
    assert "4.1k" in out


# ---------------------------------------------------------------------------
# Missing token data — exit 0, no raise
# ---------------------------------------------------------------------------

def test_missing_usage_field_exits_zero(tmp_path):
    db = tmp_path / "t.db"
    hook_data = {"session_id": "sess-x", "model": "claude-sonnet-4-6"}
    code, _ = _run_main(hook_data, db)
    assert code == 0


def test_missing_model_field_exits_zero(tmp_path):
    db = tmp_path / "t.db"
    hook_data = {"session_id": "sess-x", "usage": {"input_tokens": 100, "output_tokens": 50}}
    code, _ = _run_main(hook_data, db)
    assert code == 0


def test_empty_stdin_exits_zero(tmp_path):
    db = tmp_path / "t.db"
    code, _ = _run_main({}, db)
    assert code == 0


def test_never_raises_on_bad_data(tmp_path):
    """main() must not raise regardless of garbage input."""
    db = tmp_path / "t.db"
    import hooks.cost_tracker as ct
    from importlib import reload
    reload(ct)

    with (
        patch("hooks.cost_tracker.read_hook_stdin", return_value={"model": None, "usage": None}),
        patch("hooks.cost_tracker.TelemetryStore", return_value=TelemetryStore(db_path=db)),
        patch("sys.stdout", io.StringIO()),
    ):
        try:
            ct.main()
        except Exception as exc:
            pytest.fail(f"main() raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# TelemetryStore — cost_usd column present after migration
# ---------------------------------------------------------------------------

def test_telemetry_store_has_cost_usd_column(tmp_path):
    db = tmp_path / "t.db"
    TelemetryStore(db_path=db)
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(task_executions)").fetchall()}
    conn.close()
    assert "cost_usd" in cols


def test_telemetry_store_existing_db_migrated(tmp_path):
    """cost_usd column is added to a DB created before the migration."""
    db = tmp_path / "legacy.db"
    # Create DB without cost_usd (simulate old schema)
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE task_executions (task_id TEXT PRIMARY KEY, context_tokens_consumed INTEGER)"
    )
    conn.commit()
    conn.close()

    # Initialising TelemetryStore should migrate it
    TelemetryStore(db_path=db)
    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(task_executions)").fetchall()}
    conn.close()
    assert "cost_usd" in cols


# ---------------------------------------------------------------------------
# TelemetryStore — cost_usd written correctly
# ---------------------------------------------------------------------------

def test_cost_usd_written_to_store(tmp_path):
    db = tmp_path / "t.db"
    hook_data = _make_hook_data("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=0, session_id="sess-write")
    _run_main(hook_data, db)
    store = TelemetryStore(db_path=db)
    rows = store.get_recent(1)
    assert rows, "expected at least one record"
    cost = rows[0]["cost_usd"]
    assert cost is not None
    # $3/M input, 1M tokens → $3.00
    assert abs(cost - 3.00) < 0.001


def test_cost_usd_zero_tokens_writes_zero(tmp_path):
    db = tmp_path / "t.db"
    hook_data = _make_hook_data("claude-sonnet-4-6", input_tokens=0, output_tokens=0, session_id="sess-zero")
    _run_main(hook_data, db)
    store = TelemetryStore(db_path=db)
    rows = store.get_recent(1)
    assert rows[0]["cost_usd"] == 0.0


def test_cost_output_only_sonnet(tmp_path):
    """Output-only session: $15/M output on sonnet."""
    db = tmp_path / "t.db"
    hook_data = _make_hook_data("claude-sonnet-4-6", input_tokens=0, output_tokens=1_000_000, session_id="sess-out-only")
    code, out = _run_main(hook_data, db)
    assert code == 0
    assert "$15.00" in out
    store = TelemetryStore(db_path=db)
    rows = store.get_recent(1)
    assert abs(rows[0]["cost_usd"] - 15.00) < 0.001
