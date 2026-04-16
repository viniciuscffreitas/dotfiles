"""
Tests for the 5 performance bug fixes — behavior contract proof.

Contract: perf-audit deep performance fix of devflow hooks
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

_HOOKS_DIR = Path(__file__).parent.parent
_DEVFLOW_ROOT = _HOOKS_DIR.parent
sys.path.insert(0, str(_HOOKS_DIR))
sys.path.insert(0, str(_DEVFLOW_ROOT))


# ===========================================================================
# Fix 1: Stale lock detection in stop_dispatcher._launch_boundary_worker
# ===========================================================================

class TestStaleLockDetection:
    """
    Contract: lock file with a dead PID is cleared; new worker spawns.
    Contract: lock file with a live PID blocks new spawn.
    """

    def _load(self):
        import importlib, stop_dispatcher
        importlib.reload(stop_dispatcher)
        return stop_dispatcher

    def test_stale_lock_pid_is_cleared_and_worker_spawns(self, tmp_path):
        sd = self._load()
        lock = tmp_path / "boundary_worker.lock"
        # Write a PID that definitely does not exist
        lock.write_text("9999999")

        spawned = []
        with patch.object(sd.subprocess, "Popen", side_effect=lambda *a, **kw: spawned.append(1)) as mock_popen:
            sd._launch_boundary_worker(skip_judge=False, state_dir=tmp_path)

        assert len(spawned) == 1, "worker should spawn after clearing stale lock"
        assert not lock.exists() or lock.read_text() != "9999999"

    def test_live_lock_prevents_spawn(self, tmp_path):
        sd = self._load()
        lock = tmp_path / "boundary_worker.lock"
        # Write current process's PID — definitely alive
        lock.write_text(str(os.getpid()))

        spawned = []
        with patch.object(sd.subprocess, "Popen", side_effect=lambda *a, **kw: spawned.append(1)):
            sd._launch_boundary_worker(skip_judge=False, state_dir=tmp_path)

        assert len(spawned) == 0, "worker must NOT spawn when lock holds a live PID"

    def test_no_lock_spawns_worker_and_writes_pid(self, tmp_path):
        sd = self._load()
        lock = tmp_path / "boundary_worker.lock"

        mock_proc = MagicMock()
        mock_proc.pid = 42424242
        with patch.object(sd.subprocess, "Popen", return_value=mock_proc):
            sd._launch_boundary_worker(skip_judge=False, state_dir=tmp_path)

        assert lock.exists(), "lock file must be created"
        assert lock.read_text().strip() == "42424242", "lock must contain worker PID"

    def test_worker_deletes_lock_on_finish(self, tmp_path, monkeypatch):
        import boundary_worker as bw
        importlib.reload(bw)
        lock = tmp_path / "boundary_worker.lock"
        lock.write_text("12345")
        monkeypatch.setenv("DEVFLOW_LOCK_FILE", str(lock))
        monkeypatch.setenv("DEVFLOW_SKIP_JUDGE", "1")

        with patch("boundary_worker._run_hook"):
            bw.main()

        assert not lock.exists(), "worker must delete lock in finally block"


# ===========================================================================
# Fix 2: TelemetryStore process-level singleton
# ===========================================================================

class TestTelemetryStoreSingleton:
    """
    Contract: get_store() returns the same instance within a process.
    Contract: each instance still writes independently (no shared state corruption).
    """

    def test_get_store_returns_same_instance(self):
        from telemetry.store import get_store
        a = get_store()
        b = get_store()
        assert a is b, "get_store() must return the same TelemetryStore instance per process"

    def test_get_store_different_from_direct_instantiation(self):
        from telemetry.store import TelemetryStore, get_store
        singleton = get_store()
        direct = TelemetryStore()
        # direct construction still works (not broken)
        assert direct is not singleton

    def test_singleton_record_is_thread_safe(self, tmp_path):
        """Singleton still uses threading.Lock — concurrent writes don't corrupt."""
        import threading
        from telemetry.store import get_store, _reset_store
        _reset_store()  # ensure clean state for this test
        store = get_store()

        errors = []
        def write():
            try:
                store.record({"task_id": f"t-{threading.current_thread().name}"})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write, name=str(i)) for i in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        assert not errors, f"concurrent writes raised: {errors}"


# ===========================================================================
# Fix 3: _is_already_judged reuses the store passed from run()
# ===========================================================================

class TestJudgeStoreReuse:
    """
    Contract: _is_already_judged accepts an optional store parameter.
    Contract: when store is passed, no new TelemetryStore() is instantiated.
    """

    def _load(self):
        import post_task_judge
        importlib.reload(post_task_judge)
        return post_task_judge

    def test_already_judged_accepts_store_param(self, tmp_path):
        ptj = self._load()
        mock_store = MagicMock()
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_row = MagicMock()
        mock_row.__getitem__ = MagicMock(return_value="pass")
        mock_conn.execute.return_value.fetchone.return_value = mock_row
        mock_store._connect.return_value = mock_conn

        # Should work without raising and use the passed store
        result = ptj._is_already_judged("task-123", store=mock_store)
        mock_store._connect.assert_called()

    def test_already_judged_no_extra_store_instantiation(self, tmp_path):
        """When store is passed, TelemetryStore() must NOT be called inside _is_already_judged."""
        ptj = self._load()
        mock_store = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_store._connect.return_value = mock_conn

        with patch("post_task_judge.TelemetryStore") as mock_cls:
            ptj._is_already_judged("task-123", store=mock_store)
            mock_cls.assert_not_called()

    def test_already_judged_none_verdict_returns_false(self, tmp_path):
        ptj = self._load()
        mock_store = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None
        mock_store._connect.return_value = mock_conn

        result = ptj._is_already_judged("task-999", store=mock_store)
        assert result is False

    def test_already_judged_with_verdict_returns_true(self):
        ptj = self._load()
        mock_store = MagicMock()
        mock_row = {"judge_verdict": "pass"}
        mock_store._connect.return_value.execute.return_value.fetchone.return_value = mock_row
        result = ptj._is_already_judged("task-123", store=mock_store)
        assert result is True


# ===========================================================================
# Fix 4: instinct_capture._call_haiku retry with backoff
# ===========================================================================

class TestInstinctCaptureRetry:
    """
    Contract: _call_haiku retries once on SubprocessError/TimeoutExpired.
    Contract: raises after max retries exhausted.
    Contract: succeeds without retry when first call works.
    """

    def _load(self):
        import instinct_capture
        importlib.reload(instinct_capture)
        return instinct_capture

    def test_first_call_success_no_retry(self):
        ic = self._load()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '[{"content": "tip", "category": "pattern", "confidence": 0.9}]'

        with patch("instinct_capture.subprocess.run", return_value=mock_result) as mock_run:
            result = ic._call_haiku("some transcript")

        assert mock_run.call_count == 1
        assert len(result) == 1

    def test_timeout_triggers_retry(self):
        ic = self._load()
        import subprocess as sp
        good_result = MagicMock()
        good_result.returncode = 0
        good_result.stdout = '[{"content": "tip", "category": "pattern", "confidence": 0.8}]'

        side_effects = [sp.TimeoutExpired(cmd="claude", timeout=30), good_result]
        with patch("instinct_capture.subprocess.run", side_effect=side_effects) as mock_run:
            with patch("instinct_capture.time.sleep"):  # don't actually sleep in tests
                result = ic._call_haiku("transcript")

        assert mock_run.call_count == 2
        assert len(result) == 1

    def test_two_failures_raises(self):
        ic = self._load()
        import subprocess as sp

        with patch("instinct_capture.subprocess.run", side_effect=sp.TimeoutExpired(cmd="claude", timeout=30)):
            with patch("instinct_capture.time.sleep"):
                with pytest.raises(sp.SubprocessError):
                    ic._call_haiku("transcript")

    def test_nonzero_exit_on_retry_raises(self):
        ic = self._load()
        bad_result = MagicMock()
        bad_result.returncode = 1
        bad_result.stderr = "error"
        import subprocess as sp

        with patch("instinct_capture.subprocess.run", return_value=bad_result):
            with pytest.raises(sp.SubprocessError):
                ic._call_haiku("transcript")


# ===========================================================================
# Fix 5: discovery_scan profile cache (skip globs within 60s)
# ===========================================================================

class TestDiscoveryScanCache:
    """
    Contract: if project-profile.json is < 60s old, skip re-detection and print cached data.
    Contract: if profile is >= 60s old or missing, run full detection.
    """

    def _load(self):
        import discovery_scan
        importlib.reload(discovery_scan)
        return discovery_scan

    def test_fresh_cache_skips_glob_detection(self, tmp_path):
        ds = self._load()
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        profile = {
            "project_root": str(tmp_path),
            "toolchain": "NODEJS",
            "issue_tracker": "linear",
            "design_system": None,
            "test_framework": "vitest",
            "injected_skills": [],
            "all_learned_skills": [],
            "in_project": True,
        }
        (state_dir / "project-profile.json").write_text(json.dumps(profile))
        # mtime is right now — fresh

        with patch.object(ds, "detect_design_system") as mock_glob, \
             patch.object(ds, "get_state_dir", return_value=state_dir), \
             patch.object(ds, "_manage_symlinks", return_value=[]), \
             patch.object(ds, "_count_all_learned_skills", return_value=[]):
            ds.main()

        mock_glob.assert_not_called()

    def test_stale_cache_runs_full_detection(self, tmp_path):
        ds = self._load()
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        profile = {"project_root": str(tmp_path), "toolchain": "NODEJS",
                   "issue_tracker": "linear", "design_system": None,
                   "test_framework": "vitest", "injected_skills": [],
                   "all_learned_skills": [], "in_project": True}
        profile_path = state_dir / "project-profile.json"
        profile_path.write_text(json.dumps(profile))
        # Force stale mtime (70 seconds ago)
        stale_time = time.time() - 70
        os.utime(profile_path, (stale_time, stale_time))

        with patch.object(ds, "detect_design_system", return_value=None) as mock_glob, \
             patch.object(ds, "get_state_dir", return_value=state_dir), \
             patch.object(ds, "detect_toolchain", return_value=(None, None)), \
             patch.object(ds, "detect_issue_tracker", return_value="none"), \
             patch.object(ds, "detect_test_framework", return_value="unknown"), \
             patch.object(ds, "_manage_symlinks", return_value=[]), \
             patch.object(ds, "_ensure_learned_skills_dir"), \
             patch.object(ds, "_count_all_learned_skills", return_value=[]):
            ds.main()

        mock_glob.assert_called_once()

    def test_missing_profile_runs_full_detection(self, tmp_path):
        ds = self._load()
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        # No profile file

        with patch.object(ds, "detect_design_system", return_value=None) as mock_glob, \
             patch.object(ds, "get_state_dir", return_value=state_dir), \
             patch.object(ds, "detect_toolchain", return_value=(None, None)), \
             patch.object(ds, "detect_issue_tracker", return_value="none"), \
             patch.object(ds, "detect_test_framework", return_value="unknown"), \
             patch.object(ds, "_manage_symlinks", return_value=[]), \
             patch.object(ds, "_ensure_learned_skills_dir"), \
             patch.object(ds, "_count_all_learned_skills", return_value=[]):
            ds.main()

        mock_glob.assert_called_once()


# ===========================================================================
# Fix 6: _is_pid_alive PermissionError handling (critical bug fix)
# ===========================================================================

class TestIsPidAlive:
    """
    Contract: _is_pid_alive returns True for PermissionError (PID exists, foreign owner).
    Contract: _is_pid_alive returns False for ProcessLookupError (PID gone).
    These tests cover _is_pid_alive_posix directly (platform-independent via mock).
    """

    def _load(self):
        import importlib, stop_dispatcher
        importlib.reload(stop_dispatcher)
        return stop_dispatcher

    def test_permission_error_means_pid_alive(self):
        """PermissionError from os.kill(pid, 0) means PID exists but owned by another user."""
        sd = self._load()
        with patch("stop_dispatcher.os.kill", side_effect=PermissionError("not owner")):
            assert sd._is_pid_alive_posix(99999) is True

    def test_process_lookup_error_means_pid_gone(self):
        """ProcessLookupError from os.kill(pid, 0) means PID does not exist."""
        sd = self._load()
        with patch("stop_dispatcher.os.kill", side_effect=ProcessLookupError("no such process")):
            assert sd._is_pid_alive_posix(99999) is False

    def test_no_error_means_pid_alive(self):
        """No exception from os.kill(pid, 0) means PID is alive and owned by us."""
        sd = self._load()
        with patch("stop_dispatcher.os.kill", return_value=None):
            assert sd._is_pid_alive_posix(99999) is True

    def test_os_error_means_unknown_returns_false(self):
        """Other OSError → conservatively return False to avoid blocking spawn."""
        sd = self._load()
        with patch("stop_dispatcher.os.kill", side_effect=OSError("other")):
            assert sd._is_pid_alive_posix(99999) is False


# ===========================================================================
# Fix 7: _is_pid_alive cross-platform — Windows uses ctypes, not os.kill
# ===========================================================================

class TestIsPidAliveWin32:
    """
    Contract: on Windows, _is_pid_alive_win32 uses ctypes.kernel32 — never sends signals.
    Contract: live process (STILL_ACTIVE exit code) → True.
    Contract: dead/nonexistent process (NULL handle or non-STILL_ACTIVE code) → False.
    """

    def _load(self):
        import importlib, stop_dispatcher
        importlib.reload(stop_dispatcher)
        return stop_dispatcher

    def _make_kernel32(self, handle: int, exit_code: int, get_exit_ok: bool = True):
        """Build a mock kernel32 with OpenProcess + GetExitCodeProcess + CloseHandle."""
        mock_k32 = MagicMock()
        mock_k32.OpenProcess.return_value = handle

        # GetExitCodeProcess fills the DWORD pointer by-ref; we simulate with side_effect
        def _fill_exit_code(h, ptr):
            ptr.value = exit_code
            return get_exit_ok

        mock_k32.GetExitCodeProcess.side_effect = _fill_exit_code
        return mock_k32

    def test_live_process_returns_true(self):
        """Valid handle + exit code STILL_ACTIVE (259) → True."""
        sd = self._load()
        mock_k32 = self._make_kernel32(handle=42, exit_code=259)
        with patch("stop_dispatcher._ctypes") as mock_ctypes:
            mock_ctypes.windll.kernel32 = mock_k32
            mock_ctypes.c_ulong = MagicMock(return_value=MagicMock(value=0))
            # Simulate c_ulong side_effect: value is set by GetExitCodeProcess
            actual_ulong = MagicMock()
            actual_ulong.value = 259
            mock_ctypes.c_ulong.return_value = actual_ulong
            result = sd._is_pid_alive_win32(12345)
        assert result is True
        mock_k32.CloseHandle.assert_called_once_with(42)

    def test_null_handle_returns_false(self):
        """OpenProcess returns 0 (NULL handle) when PID doesn't exist → False."""
        sd = self._load()
        mock_k32 = MagicMock()
        mock_k32.OpenProcess.return_value = 0  # NULL — process not found
        with patch("stop_dispatcher._ctypes") as mock_ctypes:
            mock_ctypes.windll.kernel32 = mock_k32
            result = sd._is_pid_alive_win32(99999)
        assert result is False
        mock_k32.CloseHandle.assert_not_called()

    def test_exited_process_returns_false(self):
        """Valid handle but exit code is not STILL_ACTIVE → process has exited → False."""
        sd = self._load()
        mock_k32 = self._make_kernel32(handle=77, exit_code=0)  # exited with 0
        with patch("stop_dispatcher._ctypes") as mock_ctypes:
            mock_ctypes.windll.kernel32 = mock_k32
            actual_ulong = MagicMock()
            actual_ulong.value = 0  # not STILL_ACTIVE
            mock_ctypes.c_ulong.return_value = actual_ulong
            result = sd._is_pid_alive_win32(12345)
        assert result is False
        mock_k32.CloseHandle.assert_called_once_with(77)

    def test_os_kill_not_called(self):
        """win32 path must never call os.kill (would send CTRL_C_EVENT)."""
        sd = self._load()
        mock_k32 = MagicMock()
        mock_k32.OpenProcess.return_value = 0
        with patch("stop_dispatcher._ctypes") as mock_ctypes, \
             patch("stop_dispatcher.os.kill") as mock_kill:
            mock_ctypes.windll.kernel32 = mock_k32
            sd._is_pid_alive_win32(12345)
        mock_kill.assert_not_called()

    def test_dispatch_uses_win32_on_windows(self):
        """_is_pid_alive dispatches to _is_pid_alive_win32 on win32."""
        sd = self._load()
        with patch("stop_dispatcher.sys") as mock_sys, \
             patch.object(sd, "_is_pid_alive_win32", return_value=True) as mock_win32, \
             patch.object(sd, "_is_pid_alive_posix", return_value=False) as mock_posix:
            mock_sys.platform = "win32"
            result = sd._is_pid_alive(12345)
        assert result is True
        mock_win32.assert_called_once_with(12345)
        mock_posix.assert_not_called()

    def test_dispatch_uses_posix_on_linux(self):
        """_is_pid_alive dispatches to _is_pid_alive_posix on non-win32."""
        sd = self._load()
        with patch("stop_dispatcher.sys") as mock_sys, \
             patch.object(sd, "_is_pid_alive_win32", return_value=False) as mock_win32, \
             patch.object(sd, "_is_pid_alive_posix", return_value=True) as mock_posix:
            mock_sys.platform = "linux"
            result = sd._is_pid_alive(12345)
        assert result is True
        mock_posix.assert_called_once_with(12345)
        mock_win32.assert_not_called()
