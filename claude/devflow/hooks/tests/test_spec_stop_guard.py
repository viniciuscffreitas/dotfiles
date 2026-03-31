import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parent.parent))

from spec_stop_guard import _has_active_spec, main


def _make_state_dir(tmp_path):
    state_dir = tmp_path / "state" / "test-session"
    state_dir.mkdir(parents=True)
    return state_dir


def test_no_active_spec_file(tmp_path):
    state_dir = _make_state_dir(tmp_path)
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert not active
    assert desc == ""


def test_active_spec_implementing(tmp_path):
    state_dir = _make_state_dir(tmp_path)
    spec = {"status": "IMPLEMENTING", "plan_path": "/plans/feat.md"}
    (state_dir / "active-spec.json").write_text(json.dumps(spec))
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert active
    assert "IMPLEMENTING" in desc
    assert "feat.md" in desc


def test_active_spec_pending(tmp_path):
    state_dir = _make_state_dir(tmp_path)
    spec = {"status": "PENDING", "plan_path": "/plans/task.md"}
    (state_dir / "active-spec.json").write_text(json.dumps(spec))
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert active
    assert "PENDING" in desc


def test_active_spec_in_progress(tmp_path):
    state_dir = _make_state_dir(tmp_path)
    spec = {"status": "in_progress", "plan_path": "/plans/wip.md"}
    (state_dir / "active-spec.json").write_text(json.dumps(spec))
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert active


def test_active_spec_completed(tmp_path):
    state_dir = _make_state_dir(tmp_path)
    spec = {"status": "COMPLETED", "plan_path": "/plans/done.md"}
    (state_dir / "active-spec.json").write_text(json.dumps(spec))
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert not active


def test_active_spec_paused(tmp_path):
    state_dir = _make_state_dir(tmp_path)
    spec = {"status": "PAUSED", "plan_path": "/plans/paused.md"}
    (state_dir / "active-spec.json").write_text(json.dumps(spec))
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert not active


def test_corrupt_json_fails_closed(tmp_path):
    """Corrupt file should fail closed (assume spec is active)."""
    state_dir = _make_state_dir(tmp_path)
    (state_dir / "active-spec.json").write_text("{invalid json!!!")
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert active
    assert "corrupt" in desc


def test_expired_spec_not_active(tmp_path):
    """Spec older than 24h should not block exit."""
    state_dir = _make_state_dir(tmp_path)
    old_time = time.time() - (25 * 60 * 60)  # 25 hours ago
    spec = {"status": "IMPLEMENTING", "plan_path": "/plans/old.md", "started_at": old_time}
    (state_dir / "active-spec.json").write_text(json.dumps(spec))
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert not active


def test_recent_spec_still_active(tmp_path):
    """Spec younger than 24h should still block."""
    state_dir = _make_state_dir(tmp_path)
    recent_time = time.time() - (2 * 60 * 60)  # 2 hours ago
    spec = {"status": "IMPLEMENTING", "plan_path": "/plans/wip.md", "started_at": recent_time}
    (state_dir / "active-spec.json").write_text(json.dumps(spec))
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert active


def test_corrupt_json_old_file_not_active(tmp_path):
    """Corrupt file older than 24h should NOT block (fail-safe)."""
    state_dir = _make_state_dir(tmp_path)
    spec_file = state_dir / "active-spec.json"
    spec_file.write_text("{invalid json!!!")
    old_time = time.time() - (25 * 60 * 60)
    os.utime(spec_file, (old_time, old_time))
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert not active


# --- Fix 1a: session ID bypass ---

def test_empty_session_id_bypasses_guard(tmp_path, capsys, monkeypatch):
    """When CLAUDE_SESSION_ID is empty, guard must not block and must not read state."""
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    with (
        patch("spec_stop_guard.get_state_dir", return_value=tmp_path),
        patch("spec_stop_guard._has_active_spec") as mock_has_spec,
    ):
        rc = main()
    assert rc == 0
    assert "block" not in capsys.readouterr().out
    mock_has_spec.assert_not_called()


def test_default_session_id_bypasses_guard(tmp_path, capsys, monkeypatch):
    """Session ID 'default' is unsafe for isolation — guard must bypass."""
    monkeypatch.setenv("CLAUDE_SESSION_ID", "default")
    with (
        patch("spec_stop_guard.get_state_dir", return_value=tmp_path),
        patch("spec_stop_guard._has_active_spec") as mock_has_spec,
    ):
        rc = main()
    assert rc == 0
    assert "block" not in capsys.readouterr().out
    mock_has_spec.assert_not_called()


# --- Fix 1b: COMPLETED deletes file ---

def test_completed_spec_deletes_file(tmp_path):
    """_has_active_spec must delete active-spec.json when status is COMPLETED."""
    state_dir = _make_state_dir(tmp_path)
    spec_file = state_dir / "active-spec.json"
    spec = {"status": "COMPLETED", "plan_path": "/plans/done.md"}
    spec_file.write_text(json.dumps(spec))
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert not active
    assert not spec_file.exists()


def test_completed_spec_returns_not_active(tmp_path):
    """Return value is (False, '') for COMPLETED."""
    state_dir = _make_state_dir(tmp_path)
    spec = {"status": "COMPLETED", "plan_path": "/plans/done.md"}
    (state_dir / "active-spec.json").write_text(json.dumps(spec))
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert not active
    assert desc == ""


# --- Fix 1c: cwd ownership ---

def test_cwd_mismatch_bypasses_guard(tmp_path, monkeypatch):
    """Spec from a different project (cwd mismatch) must not block this session."""
    state_dir = _make_state_dir(tmp_path)
    spec = {"status": "PENDING", "plan_path": "/plans/task.md", "cwd": "/other/project"}
    (state_dir / "active-spec.json").write_text(json.dumps(spec))
    monkeypatch.chdir(tmp_path)  # current dir is tmp_path, not /other/project
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert not active


def test_cwd_match_still_blocks(tmp_path, monkeypatch):
    """Spec with matching cwd must still block — ownership confirmed."""
    state_dir = _make_state_dir(tmp_path)
    spec = {"status": "PENDING", "plan_path": "/plans/task.md", "cwd": str(tmp_path)}
    (state_dir / "active-spec.json").write_text(json.dumps(spec))
    monkeypatch.chdir(tmp_path)
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert active
    assert "task.md" in desc


def test_spec_without_cwd_field_still_blocks(tmp_path):
    """Old specs without a cwd field must still block (backwards compatibility)."""
    state_dir = _make_state_dir(tmp_path)
    spec = {"status": "PENDING", "plan_path": "/plans/legacy.md"}  # no cwd field
    (state_dir / "active-spec.json").write_text(json.dumps(spec))
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert active


def test_cwd_empty_string_does_not_bypass(tmp_path):
    """Empty cwd string in spec is treated as 'not set' — no bypass."""
    state_dir = _make_state_dir(tmp_path)
    spec = {"status": "PENDING", "plan_path": "/plans/task.md", "cwd": ""}
    (state_dir / "active-spec.json").write_text(json.dumps(spec))
    with patch("spec_stop_guard.get_state_dir", return_value=state_dir):
        active, desc = _has_active_spec()
    assert active
