"""Tests for pre_compact.py and post_compact_restore.py — tested together as they share state."""
import json
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parent.parent))

from pre_compact import _find_active_spec
from post_compact_restore import main as restore_main


# --- pre_compact: _find_active_spec ---

def test_find_active_spec_implementing(tmp_path):
    plans = tmp_path / ".claude" / "plans"
    plans.mkdir(parents=True)
    (plans / "task1.md").write_text("Status: IMPLEMENTING\nDo stuff")
    with patch("pre_compact.Path.home", return_value=tmp_path):
        result = _find_active_spec()
    assert result is not None
    assert result["status"] == "IMPLEMENTING"
    assert "task1.md" in result["plan_path"]


def test_find_active_spec_in_progress(tmp_path):
    plans = tmp_path / ".claude" / "plans"
    plans.mkdir(parents=True)
    (plans / "wip.md").write_text("This task is in_progress right now")
    with patch("pre_compact.Path.home", return_value=tmp_path):
        result = _find_active_spec()
    assert result is not None


def test_find_active_spec_none(tmp_path):
    plans = tmp_path / ".claude" / "plans"
    plans.mkdir(parents=True)
    (plans / "done.md").write_text("Status: COMPLETED\nAll done")
    with patch("pre_compact.Path.home", return_value=tmp_path):
        result = _find_active_spec()
    assert result is None


def test_find_active_spec_no_plans_dir(tmp_path):
    with patch("pre_compact.Path.home", return_value=tmp_path):
        result = _find_active_spec()
    assert result is None


# --- post_compact_restore ---

def test_restore_with_active_spec(tmp_path, capsys):
    state_dir = tmp_path / "state" / "test"
    state_dir.mkdir(parents=True)
    state = {
        "session_id": "test",
        "active_spec": {"plan_path": "/plans/feat.md", "status": "IMPLEMENTING"},
        "cwd": "/home/user/project",
    }
    (state_dir / "pre-compact.json").write_text(json.dumps(state))
    with patch("post_compact_restore.get_state_dir", return_value=state_dir):
        code = restore_main()
    assert code == 0
    output = capsys.readouterr().out
    assert "Context Restored" in output
    assert "feat.md" in output
    assert "IMPLEMENTING" in output
    assert "/home/user/project" in output


def test_restore_no_spec(tmp_path, capsys):
    state_dir = tmp_path / "state" / "test"
    state_dir.mkdir(parents=True)
    state = {"session_id": "test", "active_spec": None, "cwd": "/tmp"}
    (state_dir / "pre-compact.json").write_text(json.dumps(state))
    with patch("post_compact_restore.get_state_dir", return_value=state_dir):
        code = restore_main()
    assert code == 0
    output = capsys.readouterr().out
    assert "No active spec" in output


def test_restore_no_state_file(tmp_path, capsys):
    state_dir = tmp_path / "state" / "test"
    state_dir.mkdir(parents=True)
    with patch("post_compact_restore.get_state_dir", return_value=state_dir):
        code = restore_main()
    assert code == 0
    assert capsys.readouterr().out == ""


def test_restore_deletes_state_file(tmp_path):
    state_dir = tmp_path / "state" / "test"
    state_dir.mkdir(parents=True)
    state_file = state_dir / "pre-compact.json"
    state_file.write_text(json.dumps({"session_id": "test", "active_spec": None}))
    with patch("post_compact_restore.get_state_dir", return_value=state_dir):
        restore_main()
    assert not state_file.exists()


def test_restore_corrupt_json(tmp_path, capsys):
    state_dir = tmp_path / "state" / "test"
    state_dir.mkdir(parents=True)
    (state_dir / "pre-compact.json").write_text("{corrupt json!!!")
    with patch("post_compact_restore.get_state_dir", return_value=state_dir):
        code = restore_main()
    assert code == 0
    assert capsys.readouterr().out == ""
