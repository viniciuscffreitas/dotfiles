"""
Stop dispatcher — single entry point replacing 6 sequential Stop hooks.

Tiers:
  Gate    (sync, every turn):   spec_stop_guard — can block (exit 1)
  Fast    (sync, every turn):   cost_tracker, task_telemetry — sub-200ms
  Notify  (sync, phase change): desktop_notify — any spec status transition
  Boundary (COMPLETED only):
    oversight=strict → post_task_judge sync, instinct_capture async
    oversight!=strict → both async via boundary_worker

Boundary detection reads active-spec.json BEFORE spec_stop_guard runs,
because spec_stop_guard deletes the file when status==COMPLETED.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

_HOOKS_DIR = Path(__file__).parent
_DEVFLOW_ROOT = _HOOKS_DIR.parent
_STATE_BASE = Path.home() / ".claude" / "devflow" / "state"

# ctypes is only available (and needed) on Windows for the PID-alive check.
# Imported at module level so tests can patch stop_dispatcher._ctypes cleanly.
if sys.platform == "win32":
    import ctypes as _ctypes
else:
    _ctypes = None  # type: ignore[assignment]

# Ensure hooks dir is importable
sys.path.insert(0, str(_HOOKS_DIR))
sys.path.insert(0, str(_DEVFLOW_ROOT))


# ---------------------------------------------------------------------------
# Stdin: read once via shared cache, replay for each hook
# ---------------------------------------------------------------------------

def _read_stdin() -> str:
    # Use shared cache so session_id is resolved from the same payload
    # and stdin is never consumed twice across modules.
    try:
        from _stdin_cache import get as _cache_get
        data = _cache_get()
        if data:
            return json.dumps(data)
    except Exception:
        pass
    try:
        return sys.stdin.read()
    except OSError:
        return "{}"


def _patch_stdin(data: str) -> None:
    sys.stdin = io.StringIO(data)


# ---------------------------------------------------------------------------
# Hook runner — importlib so we avoid 6x Python interpreter startups
# ---------------------------------------------------------------------------

def _run_hook(name: str, stdin_data: str) -> int:
    """Import and call hook's main(), replaying stdin each time."""
    import importlib.util

    _patch_stdin(stdin_data)
    try:
        spec = importlib.util.spec_from_file_location(
            f"devflow_hook_{name}", _HOOKS_DIR / f"{name}.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.main()
        return result if isinstance(result, int) else 0
    except SystemExit as e:
        # Defense: hook called sys.exit() directly despite guard
        return e.code if isinstance(e.code, int) else 0
    except Exception as e:
        print(f"[devflow:dispatcher] {name} error: {e}", file=sys.stderr)
        return 0


# ---------------------------------------------------------------------------
# Boundary detection
# ---------------------------------------------------------------------------

def _get_state_dir() -> Path:
    from _util import get_state_dir
    return get_state_dir()


def _detect_boundary(state_dir: Path) -> tuple[bool, bool]:
    """
    Returns (phase_changed, task_completed).

    phase_changed: any spec status transition this turn (for desktop_notify)
    task_completed: status just became COMPLETED (for judge + instinct_capture)

    Must run BEFORE spec_stop_guard — which deletes active-spec.json on COMPLETED.
    Stores last-known status in state_dir/.last-spec-status for comparison.
    """
    spec_path = state_dir / "active-spec.json"
    marker_path = state_dir / ".last-spec-status"

    current_status = ""
    if spec_path.exists():
        try:
            current_status = json.loads(spec_path.read_text()).get("status", "")
        except (json.JSONDecodeError, OSError):
            pass

    last_status = ""
    if marker_path.exists():
        try:
            last_status = marker_path.read_text().strip()
        except OSError:
            pass

    # Update marker before spec_stop_guard can delete active-spec.json
    try:
        if current_status:
            marker_path.write_text(current_status)
        elif marker_path.exists():
            marker_path.unlink(missing_ok=True)
    except OSError:
        pass

    phase_changed = bool(current_status) and current_status != last_status
    task_completed = current_status == "COMPLETED"

    return phase_changed, task_completed


def _get_oversight_level(state_dir: Path) -> str:
    risk_path = state_dir / "risk-profile.json"
    if risk_path.exists():
        try:
            return json.loads(risk_path.read_text()).get("oversight_level", "standard")
        except (json.JSONDecodeError, OSError):
            pass
    return "standard"


# ---------------------------------------------------------------------------
# Boundary worker launcher
# ---------------------------------------------------------------------------

def _is_pid_alive_posix(pid: int) -> bool:
    """POSIX PID probe via os.kill(pid, 0) — no-op signal, raises if PID gone."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError) as exc:
        # ProcessLookupError → PID gone; PermissionError → PID exists, foreign owner
        return isinstance(exc, PermissionError)
    except OSError:
        return False


def _is_pid_alive_win32(pid: int) -> bool:
    """Windows PID probe via OpenProcess + GetExitCodeProcess — never sends signals.

    On Windows, os.kill(pid, 0) sends CTRL_C_EVENT (signal 0 == CTRL_C_EVENT),
    which is semantically wrong for a probe. This uses the kernel32 API instead:
    - OpenProcess with PROCESS_QUERY_LIMITED_INFORMATION
    - GetExitCodeProcess: STILL_ACTIVE (259) means the process is running
    """
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _STILL_ACTIVE = 259  # STATUS_PENDING — process has not yet exited

    handle = _ctypes.windll.kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not handle:
        return False  # NULL handle → PID not found or access denied
    try:
        code = _ctypes.c_ulong()
        ok = _ctypes.windll.kernel32.GetExitCodeProcess(handle, _ctypes.byref(code))
        return bool(ok) and code.value == _STILL_ACTIVE
    finally:
        _ctypes.windll.kernel32.CloseHandle(handle)


def _is_pid_alive(pid: int) -> bool:
    """Return True if the process with the given PID is still running.

    Dispatches to the platform-appropriate implementation:
    - win32: ctypes.kernel32 (signal-free probe)
    - POSIX: os.kill(pid, 0)
    """
    if sys.platform == "win32":
        return _is_pid_alive_win32(pid)
    return _is_pid_alive_posix(pid)


def _launch_boundary_worker(skip_judge: bool, state_dir: Path) -> None:
    """
    Launch boundary_worker.py as a detached process (fire-and-forget).

    Lock file stores the worker PID so stale locks (process killed with SIGKILL)
    are detected and cleared automatically. Without PID tracking, a crashed worker
    leaves the lock forever, silently breaking judge + instinct_capture.

    CLAUDE_SESSION_ID and cwd are inherited from the dispatcher process,
    so the worker's hooks can resolve session/state without stdin.
    """
    lock_file = state_dir / "boundary_worker.lock"

    if lock_file.exists():
        try:
            stored_pid = int(lock_file.read_text().strip())
            if _is_pid_alive(stored_pid):
                return  # live worker already running for this task
            # Stale lock — previous worker died without cleanup (SIGKILL, crash)
            lock_file.unlink(missing_ok=True)
        except Exception:
            # Catches ValueError (corrupt PID text), OSError (file I/O), and
            # ctypes.ArgumentError (Windows kernel32 probe failure — does not
            # inherit from OSError). Any probe failure is treated as stale lock.
            lock_file.unlink(missing_ok=True)

    env = os.environ.copy()
    if skip_judge:
        env["DEVFLOW_SKIP_JUDGE"] = "1"
    env["DEVFLOW_LOCK_FILE"] = str(lock_file)

    proc = subprocess.Popen(
        [sys.executable, str(_HOOKS_DIR / "boundary_worker.py")],
        env=env,
        start_new_session=True,  # detach from parent — survives dispatcher exit
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,  # worker logs to file instead
    )
    # Write worker PID so stale lock detection works after crashes
    try:
        if proc is not None:
            lock_file.write_text(str(proc.pid))
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    stdin_data = _read_stdin()
    state_dir = _get_state_dir()

    # Boundary detection must happen before spec_stop_guard deletes COMPLETED file
    phase_changed, task_completed = _detect_boundary(state_dir)

    # Tier 1: gate — only hook that can block (exit 1)
    exit_code = _run_hook("spec_stop_guard", stdin_data)
    if exit_code != 0:
        return exit_code

    # Tier 2: fast sync — no LLM calls, sub-200ms each
    _run_hook("cost_tracker", stdin_data)
    _run_hook("task_telemetry", stdin_data)

    # Tier 3: phase-boundary notification (any status transition)
    if phase_changed:
        _run_hook("desktop_notify", stdin_data)

    # Tier 4: task boundary (COMPLETED only)
    if task_completed:
        oversight = _get_oversight_level(state_dir)
        if oversight == "strict":
            # Sync — user waits, judge can block, instinct async
            _run_hook("post_task_judge", stdin_data)
            _launch_boundary_worker(skip_judge=True, state_dir=state_dir)
        else:
            # Standard/vibe — fully async, user unblocked immediately
            _launch_boundary_worker(skip_judge=False, state_dir=state_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
