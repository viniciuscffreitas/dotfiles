"""Tests for pre_compact.py and post_compact_restore.py — tested together as they share state."""
import json
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parent.parent))

from pre_compact import _find_active_spec
from post_compact_restore import main as restore_main


# --- pre_compact: _find_active_spec (reads active-spec.json via get_state_dir) ---

def test_find_active_spec_returns_plan_path_for_implementing(tmp_path):
    state_dir = tmp_path / "s" / "test"
    state_dir.mkdir(parents=True)
    data = {"status": "IMPLEMENTING", "plan_path": "/plans/feat.md"}
    (state_dir / "active-spec.json").write_text(json.dumps(data))
    with patch("pre_compact.get_state_dir", return_value=state_dir):
        result = _find_active_spec()
    assert result is not None
    assert result["plan_path"] == "/plans/feat.md"


def test_find_active_spec_returns_implementing_status(tmp_path):
    state_dir = tmp_path / "s" / "test"
    state_dir.mkdir(parents=True)
    data = {"status": "IMPLEMENTING", "plan_path": "/plans/feat.md"}
    (state_dir / "active-spec.json").write_text(json.dumps(data))
    with patch("pre_compact.get_state_dir", return_value=state_dir):
        result = _find_active_spec()
    assert result is not None
    assert result["status"] == "IMPLEMENTING"


def test_find_active_spec_returns_none_when_no_file(tmp_path):
    state_dir = tmp_path / "s" / "test"
    state_dir.mkdir(parents=True)
    with patch("pre_compact.get_state_dir", return_value=state_dir):
        result = _find_active_spec()
    assert result is None


def test_find_active_spec_returns_none_for_pending(tmp_path):
    state_dir = tmp_path / "s" / "test"
    state_dir.mkdir(parents=True)
    data = {"status": "PENDING", "plan_path": "/plans/task.md"}
    (state_dir / "active-spec.json").write_text(json.dumps(data))
    with patch("pre_compact.get_state_dir", return_value=state_dir):
        result = _find_active_spec()
    assert result is None


def test_find_active_spec_returns_none_for_completed(tmp_path):
    state_dir = tmp_path / "s" / "test"
    state_dir.mkdir(parents=True)
    data = {"status": "COMPLETED", "plan_path": "/plans/done.md"}
    (state_dir / "active-spec.json").write_text(json.dumps(data))
    with patch("pre_compact.get_state_dir", return_value=state_dir):
        result = _find_active_spec()
    assert result is None


def test_find_active_spec_returns_none_for_invalid_json(tmp_path):
    state_dir = tmp_path / "s" / "test"
    state_dir.mkdir(parents=True)
    (state_dir / "active-spec.json").write_text("{invalid json!!!")
    with patch("pre_compact.get_state_dir", return_value=state_dir):
        result = _find_active_spec()
    assert result is None


def test_find_active_spec_does_not_scan_md_files(tmp_path):
    """Verify no filesystem glob scanning of .md files occurs."""
    state_dir = tmp_path / "s" / "test"
    state_dir.mkdir(parents=True)
    data = {"status": "IMPLEMENTING", "plan_path": "/plans/feat.md"}
    (state_dir / "active-spec.json").write_text(json.dumps(data))
    with (
        patch("pre_compact.get_state_dir", return_value=state_dir),
        patch.object(Path, "glob") as mock_glob,
    ):
        _find_active_spec()
    mock_glob.assert_not_called()


def test_find_active_spec_returns_none_for_paused(tmp_path):
    state_dir = tmp_path / "s" / "test"
    state_dir.mkdir(parents=True)
    data = {"status": "PAUSED", "plan_path": "/plans/paused.md"}
    (state_dir / "active-spec.json").write_text(json.dumps(data))
    with patch("pre_compact.get_state_dir", return_value=state_dir):
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
