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

def _make_hook_data(
    model: str,
    input_tokens: int,
    output_tokens: int,
    session_id: str = "sess-1",
    cache_read_input_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
) -> dict:
    return {
        "session_id": session_id,
        "model": model,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_read_input_tokens": cache_read_input_tokens,
            "cache_creation_input_tokens": cache_creation_input_tokens,
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
    """claude-opus-4-6: $5/M input, $25/M output (official Anthropic pricing 2026)."""
    db = tmp_path / "t.db"
    hook_data = _make_hook_data("claude-opus-4-6", input_tokens=1_000_000, output_tokens=1_000_000)
    code, out = _run_main(hook_data, db)
    assert code == 0
    # 1M input = $5, 1M output = $25 → $30.00
    assert "$30.00" in out


def test_cost_opus_47(tmp_path):
    """claude-opus-4-7: same $5/$25 pricing as 4.6 (different tokenizer behavior)."""
    db = tmp_path / "t.db"
    hook_data = _make_hook_data("claude-opus-4-7", input_tokens=1_000_000, output_tokens=1_000_000)
    code, out = _run_main(hook_data, db)
    assert code == 0
    # 1M input = $5, 1M output = $25 → $30.00
    assert "$30.00" in out


def test_cost_sonnet(tmp_path):
    """claude-sonnet-4-6: $3/M input, $15/M output."""
    db = tmp_path / "t.db"
    hook_data = _make_hook_data("claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=1_000_000)
    code, out = _run_main(hook_data, db)
    assert code == 0
    # 1M input = $3, 1M output = $15 → $18.00
    assert "$18.00" in out


def test_cost_haiku(tmp_path):
    """claude-haiku-4-5-20251001: $1/M input, $5/M output (official pricing 2026)."""
    db = tmp_path / "t.db"
    hook_data = _make_hook_data("claude-haiku-4-5-20251001", input_tokens=1_000_000, output_tokens=1_000_000)
    code, out = _run_main(hook_data, db)
    assert code == 0
    # 1M input = $1, 1M output = $5 → $6.00
    assert "$6.00" in out


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


def test_unknown_model_warns_on_stderr(tmp_path, capsys):
    """Fallback to sonnet pricing must emit a stderr warning for visibility."""
    db = tmp_path / "t.db"
    import hooks.cost_tracker as ct
    from importlib import reload
    reload(ct)
    hook_data = _make_hook_data("claude-future-model-99", input_tokens=100, output_tokens=100)
    store = TelemetryStore(db_path=db)
    with (
        patch("hooks.cost_tracker.read_hook_stdin", return_value=hook_data),
        patch("hooks.cost_tracker.TelemetryStore", return_value=store),
    ):
        ct.main()
    captured = capsys.readouterr()
    assert "claude-future-model-99" in captured.err
    assert "devflow:cost" in captured.err or "fallback" in captured.err.lower()


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


def test_model_written_to_store(tmp_path):
    """cost_tracker must persist the model name for by-model aggregation."""
    db = tmp_path / "t.db"
    hook_data = _make_hook_data(
        "claude-opus-4-7",
        input_tokens=500,
        output_tokens=300,
        session_id="sess-opus47-persist",
    )
    _run_main(hook_data, db)
    store = TelemetryStore(db_path=db)
    rows = store.get_recent(1)
    assert rows[0]["model"] == "claude-opus-4-7"


def test_token_breakdown_written_to_store(tmp_path):
    """cost_tracker persists input/output/cache token counts for cache-hit analysis."""
    db = tmp_path / "t.db"
    hook_data = _make_hook_data(
        "claude-sonnet-4-6",
        input_tokens=12_345,
        output_tokens=2_500,
        session_id="sess-token-breakdown",
        cache_read_input_tokens=8_000,
        cache_creation_input_tokens=1_200,
    )
    _run_main(hook_data, db)
    store = TelemetryStore(db_path=db)
    rows = store.get_recent(1)
    assert rows[0]["input_tokens"] == 12_345
    assert rows[0]["output_tokens"] == 2_500
    assert rows[0]["cache_read_tokens"] == 8_000
    assert rows[0]["cache_creation_tokens"] == 1_200


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


# ---------------------------------------------------------------------------
# Cache token pricing — distinct rates vs regular input
# ---------------------------------------------------------------------------

def test_cache_read_sonnet_cheaper_than_input(tmp_path):
    """cache_read_input_tokens costs $0.30/M on sonnet (10% of input $3/M)."""
    db = tmp_path / "t.db"
    hook_data = _make_hook_data(
        "claude-sonnet-4-6",
        input_tokens=0,
        output_tokens=0,
        session_id="sess-cache-read",
        cache_read_input_tokens=1_000_000,
    )
    code, out = _run_main(hook_data, db)
    assert code == 0
    store = TelemetryStore(db_path=db)
    rows = store.get_recent(1)
    # $0.30/M * 1M = $0.30
    assert abs(rows[0]["cost_usd"] - 0.30) < 0.001


def test_cache_creation_sonnet_more_expensive_than_input(tmp_path):
    """cache_creation_input_tokens costs $3.75/M on sonnet (125% of input $3/M)."""
    db = tmp_path / "t.db"
    hook_data = _make_hook_data(
        "claude-sonnet-4-6",
        input_tokens=0,
        output_tokens=0,
        session_id="sess-cache-create",
        cache_creation_input_tokens=1_000_000,
    )
    code, out = _run_main(hook_data, db)
    assert code == 0
    store = TelemetryStore(db_path=db)
    rows = store.get_recent(1)
    # $3.75/M * 1M = $3.75
    assert abs(rows[0]["cost_usd"] - 3.75) < 0.001


def test_cache_read_opus(tmp_path):
    """cache_read_input_tokens costs $0.50/M on opus (10% of $5 input)."""
    db = tmp_path / "t.db"
    hook_data = _make_hook_data(
        "claude-opus-4-6",
        input_tokens=0,
        output_tokens=0,
        session_id="sess-opus-cache-read",
        cache_read_input_tokens=1_000_000,
    )
    code, out = _run_main(hook_data, db)
    assert code == 0
    store = TelemetryStore(db_path=db)
    rows = store.get_recent(1)
    assert abs(rows[0]["cost_usd"] - 0.50) < 0.001


def test_cache_creation_opus(tmp_path):
    """cache_creation_input_tokens costs $6.25/M on opus (125% of $5 input)."""
    db = tmp_path / "t.db"
    hook_data = _make_hook_data(
        "claude-opus-4-6",
        input_tokens=0,
        output_tokens=0,
        session_id="sess-opus-cache-create",
        cache_creation_input_tokens=1_000_000,
    )
    code, out = _run_main(hook_data, db)
    assert code == 0
    store = TelemetryStore(db_path=db)
    rows = store.get_recent(1)
    assert abs(rows[0]["cost_usd"] - 6.25) < 0.001


def test_cache_read_opus_47(tmp_path):
    """Opus 4.7 inherits same cache_read pricing as 4.6: $0.50/M."""
    db = tmp_path / "t.db"
    hook_data = _make_hook_data(
        "claude-opus-4-7",
        input_tokens=0,
        output_tokens=0,
        session_id="sess-opus47-cache-read",
        cache_read_input_tokens=1_000_000,
    )
    code, out = _run_main(hook_data, db)
    assert code == 0
    store = TelemetryStore(db_path=db)
    rows = store.get_recent(1)
    assert abs(rows[0]["cost_usd"] - 0.50) < 0.001


def test_cache_read_haiku(tmp_path):
    """cache_read_input_tokens costs $0.10/M on haiku (10% of $1 input)."""
    db = tmp_path / "t.db"
    hook_data = _make_hook_data(
        "claude-haiku-4-5-20251001",
        input_tokens=0,
        output_tokens=0,
        session_id="sess-haiku-cache-read",
        cache_read_input_tokens=1_000_000,
    )
    code, out = _run_main(hook_data, db)
    assert code == 0
    store = TelemetryStore(db_path=db)
    rows = store.get_recent(1)
    assert abs(rows[0]["cost_usd"] - 0.10) < 0.001


def test_mixed_all_token_types_sonnet(tmp_path):
    """All 4 token types together on sonnet — costs sum correctly."""
    db = tmp_path / "t.db"
    # 1M each: input=$3, output=$15, cache_read=$0.30, cache_creation=$3.75 → $22.05
    hook_data = _make_hook_data(
        "claude-sonnet-4-6",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        session_id="sess-mixed",
        cache_read_input_tokens=1_000_000,
        cache_creation_input_tokens=1_000_000,
    )
    code, out = _run_main(hook_data, db)
    assert code == 0
    store = TelemetryStore(db_path=db)
    rows = store.get_recent(1)
    assert abs(rows[0]["cost_usd"] - 22.05) < 0.001


def test_cache_tokens_absent_defaults_to_zero(tmp_path):
    """Hook data without cache fields behaves same as zero cache tokens."""
    db = tmp_path / "t.db"
    # Old-style hook data without cache fields
    hook_data = {
        "session_id": "sess-no-cache",
        "model": "claude-sonnet-4-6",
        "usage": {"input_tokens": 1_000_000, "output_tokens": 0},
    }
    code, out = _run_main(hook_data, db)
    assert code == 0
    store = TelemetryStore(db_path=db)
    rows = store.get_recent(1)
    # No cache fields → only input cost $3.00
    assert abs(rows[0]["cost_usd"] - 3.00) < 0.001


def test_output_shows_cache_stats_when_present(tmp_path):
    """Output line includes cache token counts when cache tokens > 0."""
    db = tmp_path / "t.db"
    hook_data = _make_hook_data(
        "claude-sonnet-4-6",
        input_tokens=1_000,
        output_tokens=500,
        cache_read_input_tokens=50_000,
        cache_creation_input_tokens=5_000,
    )
    _, out = _run_main(hook_data, db)
    assert "cache_read" in out or "cr=" in out or "50.0k" in out


def test_output_no_cache_stats_when_absent(tmp_path):
    """Output line does not mention cache when cache tokens are 0."""
    db = tmp_path / "t.db"
    hook_data = _make_hook_data("claude-sonnet-4-6", input_tokens=10_000, output_tokens=2_000)
    _, out = _run_main(hook_data, db)
    assert "cache" not in out.lower()
