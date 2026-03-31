import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from task_telemetry import (
    _cwd_to_slug,
    _find_session_jsonl,
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
