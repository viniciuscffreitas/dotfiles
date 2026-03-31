import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from task_telemetry import (
    _cwd_to_slug,
    _extract_text,
    _find_session_jsonl,
    _is_source_file,
    _is_test_command,
    _is_test_success,
    _project_name,
    _tokens_for,
    _parse_phase_from_write,
    _parse_phase_from_bash,
    main,
    parse_session,
)


# ---------------------------------------------------------------------------
# _cwd_to_slug
# ---------------------------------------------------------------------------

def test_cwd_to_slug_simple():
    assert _cwd_to_slug("/Users/vini/Developer/agents") == "-Users-vini-Developer-agents"


def test_cwd_to_slug_root():
    assert _cwd_to_slug("/") == "-"


# ---------------------------------------------------------------------------
# _project_name
# ---------------------------------------------------------------------------

def test_project_name_extracts_last_segment():
    assert _project_name("/Users/vini/Developer/momease") == "momease"


def test_project_name_single_segment():
    assert _project_name("/agents") == "agents"


# ---------------------------------------------------------------------------
# _tokens_for
# ---------------------------------------------------------------------------

def test_tokens_for_all_fields():
    usage = {
        "input_tokens": 100,
        "cache_creation_input_tokens": 200,
        "cache_read_input_tokens": 500,
        "output_tokens": 50,
    }
    assert _tokens_for(usage) == 850


def test_tokens_for_partial_fields():
    assert _tokens_for({"input_tokens": 10, "output_tokens": 5}) == 15


def test_tokens_for_empty():
    assert _tokens_for({}) == 0


# ---------------------------------------------------------------------------
# _parse_phase_from_write
# ---------------------------------------------------------------------------

def test_parse_write_pending():
    inp = {
        "file_path": "/Users/vini/.claude/devflow/state/abc/active-spec.json",
        "content": json.dumps({"status": "PENDING", "plan_path": "docs/plans/feat-auth.md"}),
    }
    phase, task_id = _parse_phase_from_write(inp)
    assert phase == "PENDING"
    assert task_id == "docs/plans/feat-auth.md"


def test_parse_write_implementing():
    inp = {
        "file_path": "/some/path/active-spec.json",
        "content": json.dumps({"status": "IMPLEMENTING", "plan_path": "docs/plans/task.md"}),
    }
    phase, task_id = _parse_phase_from_write(inp)
    assert phase == "IMPLEMENTING"
    assert task_id == "docs/plans/task.md"


def test_parse_write_completed():
    inp = {
        "file_path": "/some/path/active-spec.json",
        "content": json.dumps({"status": "COMPLETED", "plan_path": "docs/plans/done.md"}),
    }
    phase, task_id = _parse_phase_from_write(inp)
    assert phase == "COMPLETED"


def test_parse_write_wrong_filename():
    inp = {
        "file_path": "/some/path/other-file.json",
        "content": json.dumps({"status": "PENDING"}),
    }
    phase, task_id = _parse_phase_from_write(inp)
    assert phase is None
    assert task_id is None


def test_parse_write_invalid_json_content():
    inp = {
        "file_path": "/path/active-spec.json",
        "content": "{not valid json",
    }
    phase, task_id = _parse_phase_from_write(inp)
    assert phase is None


def test_parse_write_no_status_field():
    inp = {
        "file_path": "/path/active-spec.json",
        "content": json.dumps({"plan_path": "docs/plans/foo.md"}),
    }
    phase, task_id = _parse_phase_from_write(inp)
    assert phase is None


# ---------------------------------------------------------------------------
# _parse_phase_from_bash
# ---------------------------------------------------------------------------

def test_parse_bash_implementing():
    cmd = """python3 -c "
import json; data['status'] = 'IMPLEMENTING'
state_file = Path.home() / '.claude/devflow/state/abc/active-spec.json'
state_file.write_text(json.dumps(data))
"
"""
    assert _parse_phase_from_bash({"command": cmd}) == "IMPLEMENTING"


def test_parse_bash_paused():
    cmd = "python3 -c \"data['status'] = 'PAUSED'; state_file.write_text(...); # active-spec.json\""
    assert _parse_phase_from_bash({"command": cmd}) == "PAUSED"


def test_parse_bash_no_active_spec():
    cmd = "echo hello world"
    assert _parse_phase_from_bash({"command": cmd}) is None


def test_parse_bash_active_spec_no_status():
    cmd = "cat ~/.claude/devflow/state/abc/active-spec.json"
    # Contains active-spec.json but no status keyword
    assert _parse_phase_from_bash({"command": cmd}) is None


# ---------------------------------------------------------------------------
# parse_session — integration over a synthetic JSONL
# ---------------------------------------------------------------------------

def _make_assistant_entry(ts: str, usage: dict, tool_uses: list[dict] | None = None) -> str:
    content = []
    if tool_uses:
        content = tool_uses
    entry = {
        "type": "assistant",
        "timestamp": ts,
        "message": {
            "role": "assistant",
            "usage": usage,
            "content": content,
        },
    }
    return json.dumps(entry)


def test_parse_session_no_spec_activity(tmp_path):
    jsonl = tmp_path / "session.jsonl"
    jsonl.write_text(
        _make_assistant_entry("2026-03-30T10:00:00.000Z", {"input_tokens": 100, "output_tokens": 10}) + "\n"
        + _make_assistant_entry("2026-03-30T10:01:00.000Z", {"input_tokens": 50, "output_tokens": 5}) + "\n"
    )
    result = parse_session(jsonl)
    assert result["phases"] == []
    assert result["total_tokens"] == 165


def test_parse_session_full_spec_cycle(tmp_path):
    spec_path = "/Users/vini/.claude/devflow/state/abc/active-spec.json"

    def _write_tool(status: str, plan: str) -> dict:
        return {
            "type": "tool_use",
            "name": "Write",
            "input": {
                "file_path": spec_path,
                "content": json.dumps({"status": status, "plan_path": plan}),
            },
        }

    lines = [
        # Turn 1: baseline tokens, PENDING written
        _make_assistant_entry(
            "2026-03-30T10:00:00.000Z",
            {"input_tokens": 1000, "cache_read_input_tokens": 5000, "output_tokens": 100},
            [_write_tool("PENDING", "docs/plans/feat-auth.md")],
        ),
        # Turn 2: more tokens
        _make_assistant_entry(
            "2026-03-30T10:01:00.000Z",
            {"input_tokens": 500, "cache_read_input_tokens": 2000, "output_tokens": 80},
        ),
        # Turn 3: IMPLEMENTING
        _make_assistant_entry(
            "2026-03-30T10:02:00.000Z",
            {"input_tokens": 200, "cache_read_input_tokens": 1000, "output_tokens": 50},
            [_write_tool("IMPLEMENTING", "docs/plans/feat-auth.md")],
        ),
        # Turn 4-5: build tokens
        _make_assistant_entry(
            "2026-03-30T10:03:00.000Z",
            {"input_tokens": 300, "cache_read_input_tokens": 8000, "output_tokens": 200},
        ),
        # Turn 6: COMPLETED
        _make_assistant_entry(
            "2026-03-30T10:04:00.000Z",
            {"input_tokens": 100, "cache_read_input_tokens": 3000, "output_tokens": 50},
            [_write_tool("COMPLETED", "docs/plans/feat-auth.md")],
        ),
    ]

    jsonl = tmp_path / "session.jsonl"
    jsonl.write_text("\n".join(lines) + "\n")

    result = parse_session(jsonl)
    phases = result["phases"]

    assert len(phases) == 3
    assert phases[0]["phase"] == "PENDING"
    assert phases[1]["phase"] == "IMPLEMENTING"
    assert phases[2]["phase"] == "COMPLETED"
    assert phases[0]["task_id"] == "docs/plans/feat-auth.md"

    # Tokens accumulate correctly
    turn1_tokens = 1000 + 5000 + 100  # 6100
    assert phases[0]["tokens_cumulative"] == turn1_tokens

    turn2_tokens = 500 + 2000 + 80  # 2580
    turn3_tokens = 200 + 1000 + 50  # 1250
    assert phases[1]["tokens_cumulative"] == turn1_tokens + turn2_tokens + turn3_tokens

    total = turn1_tokens + turn2_tokens + turn3_tokens + (300 + 8000 + 200) + (100 + 3000 + 50)
    assert result["total_tokens"] == total


def test_parse_session_skips_non_assistant_entries(tmp_path):
    user_entry = json.dumps({"type": "user", "message": {"role": "user", "content": "hello"}})
    assistant_entry = _make_assistant_entry(
        "2026-03-30T10:00:00.000Z",
        {"input_tokens": 50, "output_tokens": 5},
    )
    jsonl = tmp_path / "session.jsonl"
    jsonl.write_text(user_entry + "\n" + assistant_entry + "\n")

    result = parse_session(jsonl)
    assert result["total_tokens"] == 55


def test_parse_session_bash_phase_detection(tmp_path):
    bash_tool = {
        "type": "tool_use",
        "name": "Bash",
        "input": {
            "command": (
                "python3 -c \"\nimport json\ndata['status'] = 'PAUSED'\n"
                "Path('.claude/devflow/state/abc/active-spec.json').write_text(json.dumps(data))\n\""
            ),
            "description": "Pause spec",
        },
    }
    entry = _make_assistant_entry(
        "2026-03-30T10:00:00.000Z",
        {"input_tokens": 10, "output_tokens": 2},
        [bash_tool],
    )
    jsonl = tmp_path / "session.jsonl"
    jsonl.write_text(entry + "\n")

    result = parse_session(jsonl)
    assert len(result["phases"]) == 1
    assert result["phases"][0]["phase"] == "PAUSED"


def test_parse_session_malformed_lines_skipped(tmp_path):
    jsonl = tmp_path / "session.jsonl"
    jsonl.write_text(
        "not valid json\n"
        + _make_assistant_entry("2026-03-30T10:00:00.000Z", {"output_tokens": 5})
        + "\n{partial\n"
    )
    result = parse_session(jsonl)
    assert result["total_tokens"] == 5


# ---------------------------------------------------------------------------
# main() — resilience without /spec activity
# ---------------------------------------------------------------------------

def _make_jsonl_with_tokens(tmp_path: Path, session_id: str, cwd: str) -> Path:
    """Creates a JSONL with token usage but no spec phase markers."""
    slug = cwd.replace("/", "-")
    project_dir = tmp_path / "projects" / slug
    project_dir.mkdir(parents=True)
    jsonl = project_dir / f"{session_id}.jsonl"
    jsonl.write_text(
        _make_assistant_entry("2026-03-30T10:00:00.000Z", {"input_tokens": 500, "output_tokens": 50})
        + "\n"
    )
    return jsonl


def test_main_no_session_id_skips(tmp_path):
    """main() returns 0 without writing anything when session_id is unavailable."""
    telemetry_log = tmp_path / "sessions.jsonl"
    with (
        patch("task_telemetry.read_hook_stdin", return_value={}),
        patch("task_telemetry.get_session_id", return_value="default"),
        patch("task_telemetry.TELEMETRY_DIR", tmp_path),
    ):
        rc = main()
    assert rc == 0
    assert not telemetry_log.exists()


def test_main_no_spec_phases_writes_nothing(tmp_path):
    """Session with tokens but no /spec activity must NOT write to telemetry log."""
    session_id = "test-session-abc"
    cwd = "/Users/vini/Developer/agents"
    _make_jsonl_with_tokens(tmp_path, session_id, cwd)
    telemetry_log = tmp_path / "sessions.jsonl"

    with (
        patch("task_telemetry.read_hook_stdin", return_value={}),
        patch("task_telemetry.get_session_id", return_value=session_id),
        patch("os.getcwd", return_value=cwd),
        patch("task_telemetry.PROJECTS_DIR", tmp_path / "projects"),
        patch("task_telemetry.TELEMETRY_DIR", tmp_path),
    ):
        rc = main()

    assert rc == 0
    assert not telemetry_log.exists(), "must not write to log when no spec phases detected"


# ---------------------------------------------------------------------------
# main() — debug stderr output (contract: CHANGES item 4)
# ---------------------------------------------------------------------------

def test_main_debug_logs_default_session_id(capsys):
    """main() emits stderr diagnostic when session_id resolves to 'default'."""
    with (
        patch("task_telemetry.read_hook_stdin", return_value={}),
        patch("task_telemetry.get_session_id", return_value="default"),
    ):
        rc = main()
    assert rc == 0
    err = capsys.readouterr().err
    assert err.strip(), "expected stderr diagnostic when session_id is default"


def test_main_debug_logs_missing_jsonl(tmp_path, capsys):
    """main() emits stderr diagnostic when the session JSONL cannot be found."""
    session_id = "no-jsonl-abc123"
    cwd = "/Users/vini/Developer/agents"
    with (
        patch("task_telemetry.read_hook_stdin", return_value={}),
        patch("task_telemetry.get_session_id", return_value=session_id),
        patch("os.getcwd", return_value=cwd),
        patch("task_telemetry.PROJECTS_DIR", tmp_path / "projects"),
    ):
        rc = main()
    assert rc == 0
    err = capsys.readouterr().err
    assert err.strip(), "expected stderr diagnostic when JSONL not found"


def test_main_debug_logs_no_phases(tmp_path, capsys):
    """main() emits stderr diagnostic when JSONL exists but contains no spec phases."""
    session_id = "no-phases-xyz456"
    cwd = "/Users/vini/Developer/agents"
    _make_jsonl_with_tokens(tmp_path, session_id, cwd)
    with (
        patch("task_telemetry.read_hook_stdin", return_value={}),
        patch("task_telemetry.get_session_id", return_value=session_id),
        patch("os.getcwd", return_value=cwd),
        patch("task_telemetry.PROJECTS_DIR", tmp_path / "projects"),
        patch("task_telemetry.TELEMETRY_DIR", tmp_path),
    ):
        rc = main()
    assert rc == 0
    err = capsys.readouterr().err
    assert err.strip(), "expected stderr diagnostic when no spec phases detected"


def test_main_with_spec_phases_writes_record(tmp_path):
    """Session with spec phases writes exactly one record to telemetry log."""
    session_id = "test-session-xyz"
    cwd = "/Users/vini/Developer/agents"
    slug = cwd.replace("/", "-")
    project_dir = tmp_path / "projects" / slug
    project_dir.mkdir(parents=True)

    spec_path = "/Users/vini/.claude/devflow/state/abc/active-spec.json"
    write_tool = {
        "type": "tool_use",
        "name": "Write",
        "input": {
            "file_path": spec_path,
            "content": json.dumps({"status": "IMPLEMENTING", "plan_path": "docs/plans/feat.md"}),
        },
    }
    jsonl = project_dir / f"{session_id}.jsonl"
    jsonl.write_text(
        _make_assistant_entry(
            "2026-03-30T10:00:00.000Z",
            {"input_tokens": 100, "output_tokens": 10},
            [write_tool],
        )
        + "\n"
    )
    telemetry_log = tmp_path / "sessions.jsonl"

    with (
        patch("task_telemetry.read_hook_stdin", return_value={}),
        patch("task_telemetry.get_session_id", return_value=session_id),
        patch("os.getcwd", return_value=cwd),
        patch("task_telemetry.PROJECTS_DIR", tmp_path / "projects"),
        patch("task_telemetry.TELEMETRY_DIR", tmp_path),
    ):
        rc = main()

    assert rc == 0
    assert telemetry_log.exists(), "must write to log when spec phases detected"
    records = [json.loads(line) for line in telemetry_log.read_text().splitlines() if line.strip()]
    assert len(records) == 1
    assert records[0]["project"] == "agents"
    assert records[0]["phases"][0]["phase"] == "IMPLEMENTING"


# ---------------------------------------------------------------------------
# main() — deduplication by session_id
# ---------------------------------------------------------------------------

def _make_spec_jsonl(tmp_path: Path, session_id: str, cwd: str) -> None:
    """Creates a JSONL with one IMPLEMENTING phase marker."""
    slug = cwd.replace("/", "-")
    project_dir = tmp_path / "projects" / slug
    project_dir.mkdir(parents=True, exist_ok=True)
    spec_path = "/Users/vini/.claude/devflow/state/abc/active-spec.json"
    write_tool = {
        "type": "tool_use",
        "name": "Write",
        "input": {
            "file_path": spec_path,
            "content": json.dumps({"status": "IMPLEMENTING", "plan_path": "feat.md"}),
        },
    }
    jsonl = project_dir / f"{session_id}.jsonl"
    jsonl.write_text(
        _make_assistant_entry(
            "2026-03-30T10:00:00.000Z",
            {"input_tokens": 100, "output_tokens": 10},
            [write_tool],
        )
        + "\n"
    )


def test_main_dedup_skips_second_write_same_session(tmp_path):
    """Stop hook called twice with same session_id produces exactly 1 record."""
    session_id = "dedup-session-abc"
    cwd = "/Users/vini/Developer/agents"
    _make_spec_jsonl(tmp_path, session_id, cwd)
    telemetry_log = tmp_path / "sessions.jsonl"

    patches = dict(
        read_hook_stdin=patch("task_telemetry.read_hook_stdin", return_value={}),
        get_session_id=patch("task_telemetry.get_session_id", return_value=session_id),
        getcwd=patch("os.getcwd", return_value=cwd),
        projects=patch("task_telemetry.PROJECTS_DIR", tmp_path / "projects"),
        telemetry=patch("task_telemetry.TELEMETRY_DIR", tmp_path),
    )
    with patches["read_hook_stdin"], patches["get_session_id"], patches["getcwd"], patches["projects"], patches["telemetry"]:
        main()
        main()

    records = [json.loads(l) for l in telemetry_log.read_text().splitlines() if l.strip()]
    assert len(records) == 1, f"expected 1 record, got {len(records)}"


def test_main_dedup_allows_different_sessions(tmp_path):
    """Two distinct session_ids each get their own record in the log."""
    cwd = "/Users/vini/Developer/agents"
    for sid in ("session-one", "session-two"):
        _make_spec_jsonl(tmp_path, sid, cwd)

    telemetry_log = tmp_path / "sessions.jsonl"

    for sid in ("session-one", "session-two"):
        with (
            patch("task_telemetry.read_hook_stdin", return_value={}),
            patch("task_telemetry.get_session_id", return_value=sid),
            patch("os.getcwd", return_value=cwd),
            patch("task_telemetry.PROJECTS_DIR", tmp_path / "projects"),
            patch("task_telemetry.TELEMETRY_DIR", tmp_path),
        ):
            main()

    records = [json.loads(l) for l in telemetry_log.read_text().splitlines() if l.strip()]
    assert len(records) == 2, f"expected 2 records, got {len(records)}"
    session_ids = {r["session_id"] for r in records}
    assert session_ids == {"session-one", "session-two"}


def test_main_dedup_corrupt_line_does_not_produce_duplicate(tmp_path, capsys):
    """Malformed line in sessions.jsonl must not break dedup for a valid session already recorded."""
    session_id = "dedup-session-corrupt"
    cwd = "/Users/vini/Developer/agents"
    _make_spec_jsonl(tmp_path, session_id, cwd)
    telemetry_log = tmp_path / "sessions.jsonl"

    # Write one valid record + one corrupt line into the log
    valid_record = json.dumps({"session_id": session_id, "project": "agents", "phases": [], "total_tokens": 0})
    telemetry_log.write_text(valid_record + "\n" + "not valid json\n")

    with (
        patch("task_telemetry.read_hook_stdin", return_value={}),
        patch("task_telemetry.get_session_id", return_value=session_id),
        patch("os.getcwd", return_value=cwd),
        patch("task_telemetry.PROJECTS_DIR", tmp_path / "projects"),
        patch("task_telemetry.TELEMETRY_DIR", tmp_path),
    ):
        rc = main()

    assert rc == 0
    lines = [l for l in telemetry_log.read_text().splitlines() if l.strip()]
    # Corrupt line is preserved; no duplicate appended
    valid_lines = [l for l in lines if l.startswith("{")]
    records = [json.loads(l) for l in valid_lines]
    assert len(records) == 1, f"expected 1 valid record, got {len(records)}"
    assert records[0]["session_id"] == session_id
    # Warn about corrupt line
    err = capsys.readouterr().err
    assert "corrupt" in err


# ---------------------------------------------------------------------------
# main() — upsert: stop hook fires multiple times per session
# ---------------------------------------------------------------------------

def _make_partial_jsonl(tmp_path: Path, session_id: str, cwd: str, *, with_completed: bool) -> Path:
    """
    Creates a JSONL simulating a live session.
    with_completed=False → only PENDING written (turn 1 state)
    with_completed=True  → full cycle PENDING+IMPLEMENTING+COMPLETED (turn N state)
    """
    slug = cwd.replace("/", "-")
    project_dir = tmp_path / "projects" / slug
    project_dir.mkdir(parents=True, exist_ok=True)
    spec_path = "/Users/vini/.claude/devflow/state/abc/active-spec.json"

    def _spec_write(status: str) -> dict:
        return {
            "type": "tool_use", "id": f"id-{status}", "name": "Write",
            "input": {
                "file_path": spec_path,
                "content": json.dumps({"status": status, "plan_path": "docs/plans/feat.md"}),
            },
        }

    turn1 = _make_assistant_entry(
        "2026-03-31T10:00:00.000Z",
        {"input_tokens": 800, "output_tokens": 80},
        [_spec_write("PENDING")],
    )
    lines = [turn1]

    if with_completed:
        turn2 = _make_assistant_entry(
            "2026-03-31T10:01:00.000Z",
            {"input_tokens": 400, "output_tokens": 40},
            [_spec_write("IMPLEMENTING")],
        )
        turn3 = _make_assistant_entry(
            "2026-03-31T10:02:00.000Z",
            {"input_tokens": 200, "output_tokens": 20},
            [_spec_write("COMPLETED")],
        )
        lines += [turn2, turn3]

    jsonl = project_dir / f"{session_id}.jsonl"
    jsonl.write_text("\n".join(lines) + "\n")
    return jsonl


def test_main_lifecycle_pending_then_completed(tmp_path):
    """
    Stop hook fires after turn 1 (PENDING only) → record has 1 phase.
    Stop hook fires again after turn N (full cycle) → record is REPLACED with 3 phases.
    This is the exact scenario that caused 5 production sessions to stay at PENDING.
    """
    session_id = "lifecycle-session-abc"
    cwd = "/Users/vini/Developer/agents"

    # Turn 1: JSONL has only PENDING
    jsonl = _make_partial_jsonl(tmp_path, session_id, cwd, with_completed=False)
    telemetry_log = tmp_path / "sessions.jsonl"

    patches = dict(
        stdin=patch("task_telemetry.read_hook_stdin", return_value={}),
        sid=patch("task_telemetry.get_session_id", return_value=session_id),
        cwd_=patch("os.getcwd", return_value=cwd),
        proj=patch("task_telemetry.PROJECTS_DIR", tmp_path / "projects"),
        tel=patch("task_telemetry.TELEMETRY_DIR", tmp_path),
    )
    with patches["stdin"], patches["sid"], patches["cwd_"], patches["proj"], patches["tel"]:
        main()

    records = [json.loads(l) for l in telemetry_log.read_text().splitlines() if l.strip()]
    assert len(records) == 1
    assert len(records[0]["phases"]) == 1
    assert records[0]["phases"][0]["phase"] == "PENDING"

    # Turn N: JSONL now has full PENDING → IMPLEMENTING → COMPLETED cycle
    _make_partial_jsonl(tmp_path, session_id, cwd, with_completed=True)

    with patches["stdin"], patches["sid"], patches["cwd_"], patches["proj"], patches["tel"]:
        main()

    records = [json.loads(l) for l in telemetry_log.read_text().splitlines() if l.strip()]
    assert len(records) == 1, "must have exactly 1 record (upsert, not duplicate)"
    phases = [p["phase"] for p in records[0]["phases"]]
    assert "PENDING" in phases
    assert "IMPLEMENTING" in phases
    assert "COMPLETED" in phases


def test_main_upsert_replaces_stale_pending_record(tmp_path):
    """
    Pre-existing PENDING-only record in sessions.jsonl is replaced when
    stop hook fires with a complete JSONL (3 phases).
    """
    session_id = "upsert-session-xyz"
    cwd = "/Users/vini/Developer/agents"
    _make_partial_jsonl(tmp_path, session_id, cwd, with_completed=True)

    # Seed sessions.jsonl with a stale PENDING-only record
    telemetry_log = tmp_path / "sessions.jsonl"
    stale = json.dumps({
        "session_id": session_id,
        "project": "agents",
        "cwd": cwd,
        "ts_end": 1_000_000,
        "phases": [{"ts": "T", "phase": "PENDING", "task_id": None, "tokens_cumulative": 100}],
        "total_tokens": 100,
    })
    telemetry_log.write_text(stale + "\n")

    with (
        patch("task_telemetry.read_hook_stdin", return_value={}),
        patch("task_telemetry.get_session_id", return_value=session_id),
        patch("os.getcwd", return_value=cwd),
        patch("task_telemetry.PROJECTS_DIR", tmp_path / "projects"),
        patch("task_telemetry.TELEMETRY_DIR", tmp_path),
    ):
        main()

    records = [json.loads(l) for l in telemetry_log.read_text().splitlines() if l.strip()]
    assert len(records) == 1, "stale record must be replaced, not duplicated"
    phases = [p["phase"] for p in records[0]["phases"]]
    assert "IMPLEMENTING" in phases, "replaced record must contain IMPLEMENTING"
    assert "COMPLETED" in phases, "replaced record must contain COMPLETED"


def test_main_completed_record_has_non_null_key_fields(tmp_path):
    """
    A completed session record must have:
    - total_tokens > 0  (context_tokens proxy)
    - phases with IMPLEMENTING and COMPLETED  (phase_durations derivable)
    - at least one phase with non-null task_id  (task_category proxy)
    """
    session_id = "quality-session-abc"
    cwd = "/Users/vini/Developer/agents"

    # Seed a stale PENDING-only record so dedup bug would hide the full data
    slug = cwd.replace("/", "-")
    project_dir = tmp_path / "projects" / slug
    project_dir.mkdir(parents=True)
    spec_path = "/Users/vini/.claude/devflow/state/abc/active-spec.json"

    def _spec_write(status: str, plan: str) -> dict:
        return {
            "type": "tool_use", "id": f"q-{status}", "name": "Write",
            "input": {
                "file_path": spec_path,
                "content": json.dumps({"status": status, "plan_path": plan}),
            },
        }

    lines = [
        _make_assistant_entry(
            "2026-03-31T10:00:00.000Z",
            {"input_tokens": 1000, "output_tokens": 100},
            [_spec_write("PENDING", "docs/plans/my-feature.md")],
        ),
        _make_assistant_entry(
            "2026-03-31T10:01:00.000Z",
            {"input_tokens": 500, "output_tokens": 50},
            [_spec_write("IMPLEMENTING", "docs/plans/my-feature.md")],
        ),
        _make_assistant_entry(
            "2026-03-31T10:02:00.000Z",
            {"input_tokens": 200, "output_tokens": 20},
            [_spec_write("COMPLETED", "docs/plans/my-feature.md")],
        ),
    ]
    jsonl = project_dir / f"{session_id}.jsonl"
    jsonl.write_text("\n".join(lines) + "\n")

    # Seed stale PENDING-only record (simulates the production bug)
    telemetry_log = tmp_path / "sessions.jsonl"
    stale = json.dumps({
        "session_id": session_id, "project": "agents", "cwd": cwd,
        "ts_end": 1_000_000,
        "phases": [{"ts": "T", "phase": "PENDING", "task_id": "docs/plans/my-feature.md",
                    "tokens_cumulative": 100}],
        "total_tokens": 100,
    })
    telemetry_log.write_text(stale + "\n")

    with (
        patch("task_telemetry.read_hook_stdin", return_value={}),
        patch("task_telemetry.get_session_id", return_value=session_id),
        patch("os.getcwd", return_value=cwd),
        patch("task_telemetry.PROJECTS_DIR", tmp_path / "projects"),
        patch("task_telemetry.TELEMETRY_DIR", tmp_path),
    ):
        main()

    records = [json.loads(l) for l in telemetry_log.read_text().splitlines() if l.strip()]
    assert len(records) == 1
    rec = records[0]

    # context_tokens proxy
    assert rec["total_tokens"] > 0, "total_tokens must be non-zero"

    # phase_durations proxy: need both IMPLEMENTING and COMPLETED
    phase_names = [p["phase"] for p in rec["phases"]]
    assert "IMPLEMENTING" in phase_names, "IMPLEMENTING phase must be present"
    assert "COMPLETED" in phase_names, "COMPLETED phase must be present"

    # task_category proxy: at least one phase with non-null task_id
    task_ids = [p.get("task_id") for p in rec["phases"] if p.get("task_id")]
    assert task_ids, "at least one phase must have a non-null task_id"


# ---------------------------------------------------------------------------
# _is_source_file
# ---------------------------------------------------------------------------

def test_is_source_file_python():
    assert _is_source_file("/project/src/main.py")


def test_is_source_file_dart():
    assert _is_source_file("/app/lib/widget.dart")


def test_is_source_file_java():
    assert _is_source_file("/src/main/java/Foo.java")


def test_is_source_file_typescript():
    assert _is_source_file("/frontend/src/App.tsx")


def test_is_source_file_swift():
    assert _is_source_file("/ios/App.swift")


def test_is_source_file_rejects_json():
    assert not _is_source_file("/path/active-spec.json")


def test_is_source_file_rejects_markdown():
    assert not _is_source_file("/docs/README.md")


def test_is_source_file_rejects_yaml():
    assert not _is_source_file("/config/app.yaml")


# ---------------------------------------------------------------------------
# _is_test_command
# ---------------------------------------------------------------------------

def test_is_test_command_pytest():
    assert _is_test_command("pytest tests/")


def test_is_test_command_flutter():
    assert _is_test_command("flutter test")


def test_is_test_command_mvn():
    assert _is_test_command("mvn clean test")


def test_is_test_command_dart():
    assert _is_test_command("dart test")


def test_is_test_command_mvnw():
    assert _is_test_command("./mvnw test")


def test_is_test_command_rejects_ls():
    assert not _is_test_command("ls -la")


def test_is_test_command_rejects_git():
    assert not _is_test_command("git commit -m 'add tests'")


# ---------------------------------------------------------------------------
# _is_test_success
# ---------------------------------------------------------------------------

def test_is_test_success_pytest_passed():
    assert _is_test_success("30 passed in 1.2s")


def test_is_test_success_flutter_passed():
    assert _is_test_success("All tests passed!")


def test_is_test_success_maven_build_success():
    assert _is_test_success("[INFO] BUILD SUCCESS\n[INFO] Tests run: 5, Failures: 0, Errors: 0")


def test_is_test_success_rejects_pytest_failure():
    assert not _is_test_success("2 failed, 28 passed in 1.2s")


def test_is_test_success_rejects_maven_failure():
    assert not _is_test_success("[ERROR] Tests run: 5, Failures: 2, Errors: 0\n[INFO] BUILD FAILURE")


def test_is_test_success_rejects_empty():
    assert not _is_test_success("")


# ---------------------------------------------------------------------------
# _extract_text
# ---------------------------------------------------------------------------

def test_extract_text_string():
    assert _extract_text("hello world") == "hello world"


def test_extract_text_list_of_blocks():
    blocks = [{"type": "text", "text": "3 passed"}, {"type": "text", "text": " in 0.1s"}]
    assert _extract_text(blocks) == "3 passed  in 0.1s"


def test_extract_text_empty_list():
    assert _extract_text([]) == ""


def test_extract_text_none():
    assert _extract_text(None) == ""


# ---------------------------------------------------------------------------
# parse_session — IMPLEMENTING inference
# ---------------------------------------------------------------------------

SPEC_PATH = "/Users/vini/.claude/devflow/state/abc/active-spec.json"


def _write_tool_use(tool_id: str, file_path: str, content: str = "code") -> dict:
    return {"type": "tool_use", "id": tool_id, "name": "Write",
            "input": {"file_path": file_path, "content": content}}


def _edit_tool_use(tool_id: str, file_path: str) -> dict:
    return {"type": "tool_use", "id": tool_id, "name": "Edit",
            "input": {"file_path": file_path, "old_string": "a", "new_string": "b"}}


def _bash_tool_use(tool_id: str, command: str) -> dict:
    return {"type": "tool_use", "id": tool_id, "name": "Bash",
            "input": {"command": command}}


def _tool_result(tool_use_id: str, content: str) -> dict:
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content}


def _assistant(ts: str, usage: dict, tool_uses: list) -> str:
    return json.dumps({
        "type": "assistant", "timestamp": ts,
        "message": {"role": "assistant", "usage": usage, "content": tool_uses},
    })


def _user(tool_results: list) -> str:
    return json.dumps({
        "type": "user",
        "message": {"role": "user", "content": tool_results},
    })


def _pending_write(tool_id: str, plan: str = "feat.md") -> dict:
    return _write_tool_use(tool_id, SPEC_PATH,
                           json.dumps({"status": "PENDING", "plan_path": plan}))


def test_parse_session_infers_implementing_from_source_write(tmp_path):
    """IMPLEMENTING inferred when source file written after PENDING, no explicit IMPLEMENTING."""
    lines = [
        _assistant("T1", {"input_tokens": 500, "output_tokens": 50}, [_pending_write("t1", "feat.md")]),
        _assistant("T2", {"input_tokens": 200, "output_tokens": 20}, [_write_tool_use("t2", "/project/src/main.py")]),
    ]
    jsonl = tmp_path / "s.jsonl"
    jsonl.write_text("\n".join(lines) + "\n")

    result = parse_session(jsonl)
    phases = [p["phase"] for p in result["phases"]]
    assert "IMPLEMENTING" in phases
    impl = next(p for p in result["phases"] if p["phase"] == "IMPLEMENTING")
    assert impl["task_id"] == "feat.md"


def test_parse_session_infers_implementing_from_edit(tmp_path):
    """IMPLEMENTING inferred from Edit (not just Write) to source file."""
    lines = [
        _assistant("T1", {"input_tokens": 100, "output_tokens": 10}, [_pending_write("t1")]),
        _assistant("T2", {"input_tokens": 100, "output_tokens": 10}, [_edit_tool_use("t2", "/app/lib/screen.dart")]),
    ]
    jsonl = tmp_path / "s.jsonl"
    jsonl.write_text("\n".join(lines) + "\n")

    result = parse_session(jsonl)
    assert any(p["phase"] == "IMPLEMENTING" for p in result["phases"])


def test_parse_session_no_implementing_inference_without_pending(tmp_path):
    """Source file write without prior PENDING must NOT produce inferred IMPLEMENTING."""
    lines = [
        _assistant("T1", {"input_tokens": 100, "output_tokens": 10},
                   [_write_tool_use("t1", "/project/src/main.py")]),
    ]
    jsonl = tmp_path / "s.jsonl"
    jsonl.write_text("\n".join(lines) + "\n")

    result = parse_session(jsonl)
    assert not any(p["phase"] == "IMPLEMENTING" for p in result["phases"])


def test_parse_session_no_double_implementing_when_explicit(tmp_path):
    """Explicit IMPLEMENTING write must NOT produce a second inferred IMPLEMENTING."""
    explicit_impl = _write_tool_use(
        "t2", SPEC_PATH,
        json.dumps({"status": "IMPLEMENTING", "plan_path": "feat.md"}),
    )
    lines = [
        _assistant("T1", {"input_tokens": 200, "output_tokens": 20}, [_pending_write("t1")]),
        _assistant("T2", {"input_tokens": 200, "output_tokens": 20}, [explicit_impl]),
        _assistant("T3", {"input_tokens": 100, "output_tokens": 10},
                   [_write_tool_use("t3", "/project/src/main.py")]),
    ]
    jsonl = tmp_path / "s.jsonl"
    jsonl.write_text("\n".join(lines) + "\n")

    result = parse_session(jsonl)
    impl_phases = [p for p in result["phases"] if p["phase"] == "IMPLEMENTING"]
    assert len(impl_phases) == 1


def test_parse_session_non_source_write_does_not_trigger_implementing(tmp_path):
    """Writing a .json or .md file after PENDING must NOT infer IMPLEMENTING."""
    lines = [
        _assistant("T1", {"input_tokens": 100, "output_tokens": 10}, [_pending_write("t1")]),
        _assistant("T2", {"input_tokens": 100, "output_tokens": 10},
                   [_write_tool_use("t2", "/docs/notes.md")]),
        _assistant("T3", {"input_tokens": 100, "output_tokens": 10},
                   [_write_tool_use("t3", "/config/app.json")]),
    ]
    jsonl = tmp_path / "s.jsonl"
    jsonl.write_text("\n".join(lines) + "\n")

    result = parse_session(jsonl)
    assert not any(p["phase"] == "IMPLEMENTING" for p in result["phases"])


# ---------------------------------------------------------------------------
# parse_session — COMPLETED inference
# ---------------------------------------------------------------------------

def test_parse_session_infers_completed_from_successful_test_run(tmp_path):
    """COMPLETED inferred from test run success after inferred IMPLEMENTING."""
    lines = [
        _assistant("T1", {"input_tokens": 500, "output_tokens": 50}, [_pending_write("t1")]),
        _assistant("T2", {"input_tokens": 200, "output_tokens": 20},
                   [_write_tool_use("t2", "/project/src/main.py")]),
        _assistant("T3", {"input_tokens": 100, "output_tokens": 10},
                   [_bash_tool_use("t3", "pytest tests/")]),
        _user([_tool_result("t3", "30 passed in 1.2s")]),
    ]
    jsonl = tmp_path / "s.jsonl"
    jsonl.write_text("\n".join(lines) + "\n")

    result = parse_session(jsonl)
    phases = [p["phase"] for p in result["phases"]]
    assert "IMPLEMENTING" in phases
    assert "COMPLETED" in phases


def test_parse_session_no_completed_when_tests_fail(tmp_path):
    """Failing test run must NOT produce inferred COMPLETED."""
    lines = [
        _assistant("T1", {"input_tokens": 500, "output_tokens": 50}, [_pending_write("t1")]),
        _assistant("T2", {"input_tokens": 200, "output_tokens": 20},
                   [_write_tool_use("t2", "/project/src/main.py")]),
        _assistant("T3", {"input_tokens": 100, "output_tokens": 10},
                   [_bash_tool_use("t3", "pytest tests/")]),
        _user([_tool_result("t3", "2 failed, 5 passed in 0.5s")]),
    ]
    jsonl = tmp_path / "s.jsonl"
    jsonl.write_text("\n".join(lines) + "\n")

    result = parse_session(jsonl)
    assert not any(p["phase"] == "COMPLETED" for p in result["phases"])


def test_parse_session_completed_uses_last_successful_test(tmp_path):
    """Multiple test runs: COMPLETED tokens must match the LAST successful run, not the first."""
    lines = [
        _assistant("T1", {"input_tokens": 500, "output_tokens": 50}, [_pending_write("t1")]),
        _assistant("T2", {"input_tokens": 200, "output_tokens": 20},
                   [_write_tool_use("t2", "/project/src/main.py")]),
        # First run: 1 passed (early TDD green)
        _assistant("T3", {"input_tokens": 100, "output_tokens": 10},
                   [_bash_tool_use("t3", "pytest tests/")]),
        _user([_tool_result("t3", "1 passed in 0.1s")]),
        # Middle: more code
        _assistant("T4", {"input_tokens": 300, "output_tokens": 30},
                   [_write_tool_use("t4", "/project/src/util.py")]),
        # Final run: 10 passed
        _assistant("T5", {"input_tokens": 100, "output_tokens": 10},
                   [_bash_tool_use("t5", "pytest tests/")]),
        _user([_tool_result("t5", "10 passed in 0.5s")]),
    ]
    jsonl = tmp_path / "s.jsonl"
    jsonl.write_text("\n".join(lines) + "\n")

    result = parse_session(jsonl)
    completed = next(p for p in result["phases"] if p["phase"] == "COMPLETED")
    impl = next(p for p in result["phases"] if p["phase"] == "IMPLEMENTING")

    # COMPLETED tokens must be > first test run tokens (i.e., from the last run)
    assert completed["tokens_cumulative"] > impl["tokens_cumulative"]


def test_parse_session_no_completed_without_implementing(tmp_path):
    """Successful test run without PENDING+IMPLEMENTING must NOT infer COMPLETED."""
    lines = [
        _assistant("T1", {"input_tokens": 100, "output_tokens": 10},
                   [_bash_tool_use("t1", "pytest tests/")]),
        _user([_tool_result("t1", "5 passed in 0.2s")]),
    ]
    jsonl = tmp_path / "s.jsonl"
    jsonl.write_text("\n".join(lines) + "\n")

    result = parse_session(jsonl)
    assert not any(p["phase"] == "COMPLETED" for p in result["phases"])


def test_parse_session_no_double_completed_when_explicit(tmp_path):
    """Explicit COMPLETED write + successful test run must produce only one COMPLETED."""
    explicit_completed = _write_tool_use(
        "t4", SPEC_PATH,
        json.dumps({"status": "COMPLETED", "plan_path": "feat.md"}),
    )
    lines = [
        _assistant("T1", {"input_tokens": 500, "output_tokens": 50}, [_pending_write("t1")]),
        _assistant("T2", {"input_tokens": 200, "output_tokens": 20},
                   [_write_tool_use("t2", "/project/src/main.py")]),
        _assistant("T3", {"input_tokens": 100, "output_tokens": 10},
                   [_bash_tool_use("t3", "pytest tests/")]),
        _user([_tool_result("t3", "10 passed in 0.5s")]),
        _assistant("T4", {"input_tokens": 50, "output_tokens": 5}, [explicit_completed]),
    ]
    jsonl = tmp_path / "s.jsonl"
    jsonl.write_text("\n".join(lines) + "\n")

    result = parse_session(jsonl)
    completed_phases = [p for p in result["phases"] if p["phase"] == "COMPLETED"]
    assert len(completed_phases) == 1


def test_parse_session_phases_ordered_by_tokens(tmp_path):
    """Phases must be sorted by tokens_cumulative regardless of insertion order."""
    lines = [
        _assistant("T1", {"input_tokens": 500, "output_tokens": 50}, [_pending_write("t1")]),
        _assistant("T2", {"input_tokens": 200, "output_tokens": 20},
                   [_write_tool_use("t2", "/project/src/main.py")]),
        _assistant("T3", {"input_tokens": 100, "output_tokens": 10},
                   [_bash_tool_use("t3", "pytest tests/")]),
        _user([_tool_result("t3", "5 passed in 0.2s")]),
    ]
    jsonl = tmp_path / "s.jsonl"
    jsonl.write_text("\n".join(lines) + "\n")

    result = parse_session(jsonl)
    tokens = [p["tokens_cumulative"] for p in result["phases"]]
    assert tokens == sorted(tokens)


# ---------------------------------------------------------------------------
# Regression: review-gate bug fixes
# ---------------------------------------------------------------------------

def test_is_test_success_not_fooled_by_zero_errors():
    """'0 errors' in output must NOT trigger failure detection (maven success output)."""
    assert _is_test_success("[INFO] Tests run: 5, Failures: 0, Errors: 0, Skipped: 0")


def test_is_test_failure_detects_nonzero_errors():
    """'2 errors' must be detected as failure."""
    assert not _is_test_success("Tests run: 5, Failures: 0, Errors: 2")


def test_parse_session_second_spec_cycle_resets_inference_state(tmp_path):
    """Two /spec cycles in one session: second cycle must infer phases independently."""
    # Cycle 1: PENDING → explicit IMPLEMENTING → COMPLETED (explicit)
    explicit_impl = _write_tool_use("t2", SPEC_PATH,
                                    json.dumps({"status": "IMPLEMENTING", "plan_path": "feat1.md"}))
    explicit_done = _write_tool_use("t3", SPEC_PATH,
                                    json.dumps({"status": "COMPLETED", "plan_path": "feat1.md"}))
    # Cycle 2: new PENDING → source write → test success (should infer IMPLEMENTING + COMPLETED)
    lines = [
        _assistant("T1", {"input_tokens": 200, "output_tokens": 20}, [_pending_write("t1", "feat1.md")]),
        _assistant("T2", {"input_tokens": 100, "output_tokens": 10}, [explicit_impl]),
        _assistant("T3", {"input_tokens": 100, "output_tokens": 10}, [explicit_done]),
        # Start of cycle 2
        _assistant("T4", {"input_tokens": 200, "output_tokens": 20}, [_pending_write("t4", "feat2.md")]),
        _assistant("T5", {"input_tokens": 100, "output_tokens": 10},
                   [_write_tool_use("t5", "/project/src/feature2.py")]),
        _assistant("T6", {"input_tokens": 50, "output_tokens": 5},
                   [_bash_tool_use("t6", "pytest tests/")]),
        _user([_tool_result("t6", "8 passed in 0.4s")]),
    ]
    jsonl = tmp_path / "s.jsonl"
    jsonl.write_text("\n".join(lines) + "\n")

    result = parse_session(jsonl)
    phases = result["phases"]

    # Should have: PENDING(feat1), IMPLEMENTING(feat1 explicit), COMPLETED(feat1 explicit),
    #              PENDING(feat2), IMPLEMENTING(feat2 inferred), COMPLETED(feat2 inferred)
    phase_names = [p["phase"] for p in phases]
    assert phase_names.count("PENDING") == 2
    assert phase_names.count("IMPLEMENTING") == 2
    assert phase_names.count("COMPLETED") == 2

    # Second cycle's task_id must be feat2, not feat1
    second_impl = [p for p in phases if p["phase"] == "IMPLEMENTING"][1]
    assert second_impl["task_id"] == "feat2.md"


# ---------------------------------------------------------------------------
# TelemetryStore integration
# ---------------------------------------------------------------------------

def test_main_writes_to_sqlite_after_sessions_jsonl(tmp_path):
    """Verify TelemetryStore.record() is called at end of main()."""
    from unittest.mock import patch, MagicMock
    import task_telemetry

    # Build a minimal session JSONL with a PENDING phase
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
    assert "iterations_to_completion" in call_payload
    assert "stack" in call_payload
