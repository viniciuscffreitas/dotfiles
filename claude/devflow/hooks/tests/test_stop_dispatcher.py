"""Tests for stop_dispatcher.py — boundary detection and hook orchestration."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

_HOOKS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_HOOKS_DIR))
sys.path.insert(0, str(_HOOKS_DIR.parent))

import stop_dispatcher as sd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_spec(state_dir: Path, status: str) -> None:
    (state_dir / "active-spec.json").write_text(json.dumps({"status": status}))


def _write_marker(state_dir: Path, status: str) -> None:
    (state_dir / ".last-spec-status").write_text(status)


def _write_risk(state_dir: Path, level: str) -> None:
    (state_dir / "risk-profile.json").write_text(json.dumps({"oversight_level": level}))


# ---------------------------------------------------------------------------
# _detect_boundary
# ---------------------------------------------------------------------------

class TestDetectBoundary:
    def test_no_spec_no_marker(self, tmp_path):
        phase_changed, task_completed = sd._detect_boundary(tmp_path)
        assert not phase_changed
        assert not task_completed

    def test_first_pending_is_phase_change(self, tmp_path):
        _write_spec(tmp_path, "PENDING")
        phase_changed, task_completed = sd._detect_boundary(tmp_path)
        assert phase_changed
        assert not task_completed

    def test_same_status_twice_is_not_change(self, tmp_path):
        _write_spec(tmp_path, "IMPLEMENTING")
        _write_marker(tmp_path, "IMPLEMENTING")
        phase_changed, task_completed = sd._detect_boundary(tmp_path)
        assert not phase_changed
        assert not task_completed

    def test_transition_to_completed_is_task_completed(self, tmp_path):
        _write_spec(tmp_path, "COMPLETED")
        _write_marker(tmp_path, "IMPLEMENTING")
        phase_changed, task_completed = sd._detect_boundary(tmp_path)
        assert phase_changed
        assert task_completed

    def test_transition_pending_to_implementing_is_phase_not_task(self, tmp_path):
        _write_spec(tmp_path, "IMPLEMENTING")
        _write_marker(tmp_path, "PENDING")
        phase_changed, task_completed = sd._detect_boundary(tmp_path)
        assert phase_changed
        assert not task_completed

    def test_marker_updated_after_detection(self, tmp_path):
        _write_spec(tmp_path, "IMPLEMENTING")
        _write_marker(tmp_path, "PENDING")
        sd._detect_boundary(tmp_path)
        assert (tmp_path / ".last-spec-status").read_text() == "IMPLEMENTING"

    def test_marker_removed_when_no_spec(self, tmp_path):
        _write_marker(tmp_path, "IMPLEMENTING")
        sd._detect_boundary(tmp_path)
        assert not (tmp_path / ".last-spec-status").exists()

    def test_corrupt_spec_returns_no_boundary(self, tmp_path):
        (tmp_path / "active-spec.json").write_text("not json {{{")
        phase_changed, task_completed = sd._detect_boundary(tmp_path)
        assert not phase_changed
        assert not task_completed


# ---------------------------------------------------------------------------
# _get_oversight_level
# ---------------------------------------------------------------------------

class TestGetOversightLevel:
    def test_defaults_to_standard(self, tmp_path):
        assert sd._get_oversight_level(tmp_path) == "standard"

    def test_reads_strict(self, tmp_path):
        _write_risk(tmp_path, "strict")
        assert sd._get_oversight_level(tmp_path) == "strict"

    def test_corrupt_risk_file_defaults_to_standard(self, tmp_path):
        (tmp_path / "risk-profile.json").write_text("bad json")
        assert sd._get_oversight_level(tmp_path) == "standard"


# ---------------------------------------------------------------------------
# main() orchestration
# ---------------------------------------------------------------------------

class TestMainOrchestration:
    """Verify hook call patterns without executing any real hook logic."""

    def _make_state_dir(self, tmp_path: Path) -> Path:
        return tmp_path

    @patch("stop_dispatcher._get_state_dir")
    @patch("stop_dispatcher._run_hook")
    @patch("stop_dispatcher._launch_boundary_worker")
    def test_non_boundary_runs_tier1_and_tier2_only(
        self, mock_launch, mock_run, mock_state_dir, tmp_path
    ):
        mock_state_dir.return_value = tmp_path
        mock_run.return_value = 0
        # No spec file → no boundary

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = "{}"
            sd.main()

        called = [c[0][0] for c in mock_run.call_args_list]
        assert "spec_stop_guard" in called
        assert "cost_tracker" in called
        assert "task_telemetry" in called
        assert "desktop_notify" not in called
        assert "post_task_judge" not in called
        mock_launch.assert_not_called()

    @patch("stop_dispatcher._get_state_dir")
    @patch("stop_dispatcher._run_hook")
    @patch("stop_dispatcher._launch_boundary_worker")
    def test_phase_change_triggers_desktop_notify(
        self, mock_launch, mock_run, mock_state_dir, tmp_path
    ):
        mock_state_dir.return_value = tmp_path
        mock_run.return_value = 0
        _write_spec(tmp_path, "IMPLEMENTING")
        _write_marker(tmp_path, "PENDING")

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = "{}"
            sd.main()

        called = [c[0][0] for c in mock_run.call_args_list]
        assert "desktop_notify" in called
        mock_launch.assert_not_called()  # not COMPLETED

    @patch("stop_dispatcher._get_state_dir")
    @patch("stop_dispatcher._run_hook")
    @patch("stop_dispatcher._launch_boundary_worker")
    def test_completed_standard_launches_boundary_worker_async(
        self, mock_launch, mock_run, mock_state_dir, tmp_path
    ):
        mock_state_dir.return_value = tmp_path
        mock_run.return_value = 0
        _write_spec(tmp_path, "COMPLETED")
        _write_marker(tmp_path, "IMPLEMENTING")
        # oversight=standard (no risk file)

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = "{}"
            sd.main()

        mock_launch.assert_called_once()
        assert mock_launch.call_args.kwargs.get("skip_judge") is False
        called = [c[0][0] for c in mock_run.call_args_list]
        assert "post_task_judge" not in called

    @patch("stop_dispatcher._get_state_dir")
    @patch("stop_dispatcher._run_hook")
    @patch("stop_dispatcher._launch_boundary_worker")
    def test_completed_strict_runs_judge_sync_then_worker_skip(
        self, mock_launch, mock_run, mock_state_dir, tmp_path
    ):
        mock_state_dir.return_value = tmp_path
        mock_run.return_value = 0
        _write_spec(tmp_path, "COMPLETED")
        _write_marker(tmp_path, "IMPLEMENTING")
        _write_risk(tmp_path, "strict")

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = "{}"
            sd.main()

        called = [c[0][0] for c in mock_run.call_args_list]
        assert "post_task_judge" in called
        mock_launch.assert_called_once()
        assert mock_launch.call_args.kwargs.get("skip_judge") is True

    @patch("stop_dispatcher._get_state_dir")
    @patch("stop_dispatcher._run_hook")
    @patch("stop_dispatcher._launch_boundary_worker")
    def test_spec_stop_guard_block_aborts_all_subsequent_hooks(
        self, mock_launch, mock_run, mock_state_dir, tmp_path
    ):
        mock_state_dir.return_value = tmp_path
        mock_run.return_value = 1  # guard blocks

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = "{}"
            result = sd.main()

        assert result == 1
        # Only spec_stop_guard should have been called
        assert mock_run.call_count == 1
        assert mock_run.call_args[0][0] == "spec_stop_guard"
        mock_launch.assert_not_called()
