import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from spec_phase_tracker import _extract_spec_description, _write_pending, main


# ---------------------------------------------------------------------------
# _extract_spec_description
# ---------------------------------------------------------------------------

def test_extract_description_plain():
    assert _extract_spec_description("/spec add pagination to users") == "add pagination to users"


def test_extract_description_fix_prefix():
    assert _extract_spec_description("/spec fix: login not working") == "fix: login not working"


def test_extract_description_quoted():
    assert _extract_spec_description('/spec "add auth flow"') == "add auth flow"


def test_extract_description_no_description():
    assert _extract_spec_description("/spec") == "unnamed spec"


def test_extract_description_multiword():
    desc = _extract_spec_description("/spec refactor auth middleware to support OAuth")
    assert desc == "refactor auth middleware to support OAuth"


# ---------------------------------------------------------------------------
# _write_pending
# ---------------------------------------------------------------------------

def test_write_pending_creates_file(tmp_path):
    _write_pending("session-abc", "add pagination", state_root=tmp_path)
    spec_file = tmp_path / "session-abc" / "active-spec.json"
    assert spec_file.exists()
    data = json.loads(spec_file.read_text())
    assert data["status"] == "PENDING"
    assert data["plan_path"] == "add pagination"
    assert "started_at" in data
    assert isinstance(data["started_at"], int)


def test_write_pending_overwrites_existing(tmp_path):
    _write_pending("sess-1", "old spec", state_root=tmp_path)
    _write_pending("sess-1", "new spec", state_root=tmp_path)
    spec_file = tmp_path / "sess-1" / "active-spec.json"
    data = json.loads(spec_file.read_text())
    assert data["plan_path"] == "new spec"


def test_write_pending_creates_state_dir(tmp_path):
    _write_pending("new-session-xyz", "feat", state_root=tmp_path)
    assert (tmp_path / "new-session-xyz").is_dir()


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def test_main_spec_message_writes_pending(tmp_path):
    hook_data = {"session_id": "real-session-id", "prompt": "/spec add user search"}
    with (
        patch("spec_phase_tracker.read_hook_stdin", return_value=hook_data),
        patch("spec_phase_tracker.STATE_ROOT", tmp_path),
    ):
        rc = main()
    assert rc == 0
    spec_file = tmp_path / "real-session-id" / "active-spec.json"
    assert spec_file.exists()
    data = json.loads(spec_file.read_text())
    assert data["status"] == "PENDING"
    assert data["plan_path"] == "add user search"


def test_main_no_spec_in_message_does_nothing(tmp_path):
    hook_data = {"session_id": "real-session-id", "prompt": "explain this function"}
    with (
        patch("spec_phase_tracker.read_hook_stdin", return_value=hook_data),
        patch("spec_phase_tracker.STATE_ROOT", tmp_path),
    ):
        rc = main()
    assert rc == 0
    assert not (tmp_path / "real-session-id").exists()


def test_main_uses_session_id_from_hook_data(tmp_path):
    hook_data = {"session_id": "hook-session-99", "prompt": "/spec feat"}
    with (
        patch("spec_phase_tracker.read_hook_stdin", return_value=hook_data),
        patch("spec_phase_tracker.STATE_ROOT", tmp_path),
    ):
        main()
    assert (tmp_path / "hook-session-99" / "active-spec.json").exists()


def test_main_falls_back_to_default_session(tmp_path):
    hook_data = {"prompt": "/spec something"}  # no session_id in hook data
    with (
        patch("spec_phase_tracker.read_hook_stdin", return_value=hook_data),
        patch("spec_phase_tracker.get_session_id", return_value="default"),
        patch("spec_phase_tracker.STATE_ROOT", tmp_path),
    ):
        rc = main()
    assert rc == 0
    assert (tmp_path / "default" / "active-spec.json").exists()


def test_main_spec_in_middle_of_message(tmp_path):
    hook_data = {"session_id": "s1", "prompt": "please /spec add notifications"}
    with (
        patch("spec_phase_tracker.read_hook_stdin", return_value=hook_data),
        patch("spec_phase_tracker.STATE_ROOT", tmp_path),
    ):
        main()
    assert (tmp_path / "s1" / "active-spec.json").exists()


def test_main_empty_prompt_does_nothing(tmp_path):
    hook_data = {"session_id": "s1", "prompt": ""}
    with (
        patch("spec_phase_tracker.read_hook_stdin", return_value=hook_data),
        patch("spec_phase_tracker.STATE_ROOT", tmp_path),
    ):
        rc = main()
    assert rc == 0
    assert not (tmp_path / "s1").exists()


def test_main_returns_zero_always(tmp_path):
    """Hook must never block user prompt — always returns 0."""
    hook_data = {"session_id": "s1", "prompt": "/spec something"}
    with (
        patch("spec_phase_tracker.read_hook_stdin", return_value=hook_data),
        patch("spec_phase_tracker.STATE_ROOT", tmp_path),
    ):
        assert main() == 0
