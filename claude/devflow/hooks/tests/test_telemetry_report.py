import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from telemetry_report import (
    compute_phase_tokens,
    format_tokens,
    load_sessions,
)


# ---------------------------------------------------------------------------
# format_tokens
# ---------------------------------------------------------------------------

def test_format_tokens_under_1k():
    assert format_tokens(500) == "500"


def test_format_tokens_exactly_1k():
    assert format_tokens(1000) == "1.0k"


def test_format_tokens_thousands():
    assert format_tokens(45_300) == "45.3k"


def test_format_tokens_millions():
    assert format_tokens(1_500_000) == "1.5M"


def test_format_tokens_zero():
    assert format_tokens(0) == "0"


# ---------------------------------------------------------------------------
# compute_phase_tokens
# ---------------------------------------------------------------------------

def _phase(phase: str, cumulative: int, task_id: str = "docs/plans/feat.md") -> dict:
    return {"phase": phase, "tokens_cumulative": cumulative, "task_id": task_id, "ts": ""}


def test_compute_full_cycle():
    phases = [
        _phase("PENDING", 6_100),
        _phase("IMPLEMENTING", 9_930),
        _phase("COMPLETED", 21_580),
    ]
    result = compute_phase_tokens(phases)
    assert result["understand"] == 9_930 - 6_100
    assert result["build"] == 21_580 - 9_930


def test_compute_no_completed():
    phases = [
        _phase("PENDING", 1_000),
        _phase("IMPLEMENTING", 5_000),
    ]
    result = compute_phase_tokens(phases)
    assert result["understand"] == 4_000
    assert "build" not in result


def test_compute_only_pending():
    phases = [_phase("PENDING", 1_000)]
    result = compute_phase_tokens(phases)
    assert result == {}


def test_compute_empty_phases():
    assert compute_phase_tokens([]) == {}


def test_compute_out_of_order_phases():
    # phases not in order by timestamp — sorted by cumulative tokens
    phases = [
        _phase("COMPLETED", 21_580),
        _phase("PENDING", 6_100),
        _phase("IMPLEMENTING", 9_930),
    ]
    result = compute_phase_tokens(phases)
    assert result["understand"] == 9_930 - 6_100
    assert result["build"] == 21_580 - 9_930


def test_compute_duplicate_phases_uses_first():
    # Two PENDING markers — should use first (lowest cumulative)
    phases = [
        _phase("PENDING", 1_000),
        _phase("PENDING", 2_000),
        _phase("IMPLEMENTING", 8_000),
        _phase("COMPLETED", 20_000),
    ]
    result = compute_phase_tokens(phases)
    assert result["understand"] == 8_000 - 1_000


# ---------------------------------------------------------------------------
# load_sessions
# ---------------------------------------------------------------------------

def _session(project: str, task_id: str, pending: int, implementing: int, completed: int) -> dict:
    return {
        "session_id": "test-session",
        "project": project,
        "cwd": f"/Users/test/{project}",
        "ts_end": 1748000000,
        "total_tokens": completed,
        "phases": [
            {"phase": "PENDING", "tokens_cumulative": pending, "task_id": task_id, "ts": ""},
            {"phase": "IMPLEMENTING", "tokens_cumulative": implementing, "task_id": task_id, "ts": ""},
            {"phase": "COMPLETED", "tokens_cumulative": completed, "task_id": task_id, "ts": ""},
        ],
    }


def test_load_sessions_empty_file(tmp_path):
    log = tmp_path / "sessions.jsonl"
    log.write_text("")
    assert load_sessions(log) == []


def test_load_sessions_missing_file(tmp_path):
    assert load_sessions(tmp_path / "nonexistent.jsonl") == []


def test_load_sessions_valid(tmp_path):
    log = tmp_path / "sessions.jsonl"
    s1 = _session("agents", "docs/plans/feat-memory.md", 6100, 9930, 21580)
    s2 = _session("momease", "docs/plans/feat-auth.md", 15000, 55000, 140000)
    log.write_text(json.dumps(s1) + "\n" + json.dumps(s2) + "\n")

    sessions = load_sessions(log)
    assert len(sessions) == 2
    assert sessions[0]["project"] == "agents"
    assert sessions[1]["project"] == "momease"


def test_load_sessions_skips_invalid_lines(tmp_path):
    log = tmp_path / "sessions.jsonl"
    s = _session("agents", "task.md", 1000, 5000, 10000)
    log.write_text("not json\n" + json.dumps(s) + "\nbad{\n")

    sessions = load_sessions(log)
    assert len(sessions) == 1


def test_load_sessions_preserves_order(tmp_path):
    log = tmp_path / "sessions.jsonl"
    sessions = [_session(f"proj{i}", "task.md", i * 1000, i * 2000, i * 5000) for i in range(1, 6)]
    log.write_text("\n".join(json.dumps(s) for s in sessions) + "\n")

    loaded = load_sessions(log)
    assert [s["project"] for s in loaded] == [f"proj{i}" for i in range(1, 6)]
