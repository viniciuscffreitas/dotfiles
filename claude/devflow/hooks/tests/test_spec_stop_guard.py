import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parent.parent))

from spec_stop_guard import _has_active_spec


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
