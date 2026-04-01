# Parallel Session Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable 10+ simultaneous Claude Code sessions with full harness support — isolated state dirs, unique session IDs, collision-free SQLite writes, and a file-locked task registry.

**Architecture:** Three orthogonal fixes applied independently: (1) WAL mode + retry in TelemetryStore eliminates SQLite "database is locked" under concurrent multi-process writes; (2) a new `_session.py` utility provides a guaranteed-unique session ID (pid+ts fallback) so every session writes to its own state dir; (3) a file-locked `TaskRegistry` prevents two sessions from grabbing the same issue. A `parallel_launch.sh` script ties these together for operators.

**Tech Stack:** Python 3.13, SQLite WAL, `fcntl.flock`, `threading`, `subprocess`, bash

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `telemetry/store.py` | Modify | WAL PRAGMAs, `_write_with_retry`, updated `record()` |
| `hooks/_session.py` | **Create** | Single source of truth for session ID with pid fallback |
| `hooks/_util.py` | Modify | Re-export `get_session_id` from `_session`; remove local def |
| `hooks/spec_stop_guard.py` | Modify | Use `get_session_id()`; remove direct env var read |
| `hooks/tests/test_spec_stop_guard.py` | Modify | Update 1 test whose expectation changes |
| `agents/task_registry.py` | **Create** | File-locked registry; claim/release/list_available |
| `scripts/parallel_launch.sh` | **Create** | macOS worktree+Terminal orchestrator |
| `hooks/tests/test_parallel.py` | **Create** | All concurrency tests (WAL, session ID, registry, bash) |
| `docs/audit-20260331.md` | Modify | Append Prompt 14 entry |

---

## Task 1: TelemetryStore WAL Mode + Retry Logic

**Files:**
- Modify: `telemetry/store.py`
- Test: `hooks/tests/test_parallel.py` (create with WAL tests)

### What changes in `store.py`

`_connect()` gains two per-connection PRAGMAs. `_init_schema()` sets WAL mode (file-level, persists). A new `_write_with_retry(fn, max_retries)` method takes a `Callable[[Connection], None]`, acquires the lock, opens a connection, runs `fn(conn)` inside a transaction, and retries up to `max_retries` times sleeping `0.1 * (attempt+1)` seconds on each "locked" error. `record()` drops its manual lock+commit and delegates to `_write_with_retry`.

---

- [ ] **Step 1.1: Create `hooks/tests/test_parallel.py` with WAL tests (RED)**

Create the file at `hooks/tests/test_parallel.py`:

```python
"""Concurrency and parallel-session tests for devflow harness."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import pytest

# Path setup
_HOOKS_DIR = Path(__file__).parent.parent          # hooks/
_DEVFLOW_ROOT = Path(__file__).parent.parent.parent  # devflow/
sys.path.insert(0, str(_DEVFLOW_ROOT))
sys.path.insert(0, str(_HOOKS_DIR))

from telemetry.store import TelemetryStore


# ---------------------------------------------------------------------------
# Task 1: TelemetryStore WAL mode
# ---------------------------------------------------------------------------

class TestTelemetryStoreWAL:

    def test_wal_mode_enabled(self, tmp_path):
        TelemetryStore(db_path=tmp_path / "test.db")
        with closing(sqlite3.connect(str(tmp_path / "test.db"))) as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_busy_timeout_set(self, tmp_path):
        store = TelemetryStore(db_path=tmp_path / "test.db")
        with closing(store._connect()) as conn:
            timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout >= 5000

    def test_concurrent_writes_no_errors(self, tmp_path):
        store = TelemetryStore(db_path=tmp_path / "test.db")
        errors: list[Exception] = []

        def write(i: int) -> None:
            try:
                store.record({"task_id": f"task-{i}", "task_category": "test"})
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=write, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(store.get_recent(n=10)) == 3

    def test_write_with_retry_retries_on_locked_error(self, tmp_path):
        store = TelemetryStore(db_path=tmp_path / "test.db")
        call_count = [0]

        def flaky(conn: sqlite3.Connection) -> None:
            call_count[0] += 1
            if call_count[0] == 1:
                raise sqlite3.OperationalError("database is locked")

        store._write_with_retry(flaky, max_retries=3)
        assert call_count[0] == 2

    def test_write_with_retry_raises_after_max_retries(self, tmp_path):
        store = TelemetryStore(db_path=tmp_path / "test.db")

        def always_locked(conn: sqlite3.Connection) -> None:
            raise sqlite3.OperationalError("database is locked")

        with pytest.raises(sqlite3.OperationalError, match="locked"):
            store._write_with_retry(always_locked, max_retries=3)
```

- [ ] **Step 1.2: Run — confirm FAIL**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_parallel.py::TestTelemetryStoreWAL -v 2>&1 | tail -20
```

Expected: 5 FAILED (no WAL PRAGMAs, no `_write_with_retry`).

- [ ] **Step 1.3: Implement WAL changes in `telemetry/store.py`**

Add `import time` to imports section (after existing imports).

Replace `_connect()`:
```python
def _connect(self) -> sqlite3.Connection:
    conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn
```

In `_init_schema()`, add WAL line right after the `conn = ...` line inside the `with closing(...) as conn:` block (before `conn.execute(_CREATE_TABLE)`):
```python
conn.execute("PRAGMA journal_mode=WAL")
```

So `_init_schema` becomes:
```python
def _init_schema(self) -> None:
    self._db_path.parent.mkdir(parents=True, exist_ok=True)
    with self._lock:
        with closing(self._connect()) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(_CREATE_TABLE)
            _new_cols = [
                ("firewall_delegated", "BOOLEAN"),
                ("firewall_task_id", "TEXT"),
                ("firewall_success", "BOOLEAN"),
                ("firewall_duration_ms", "REAL"),
                ("instincts_captured_count", "INTEGER"),
            ]
            for col, col_type in _new_cols:
                try:
                    conn.execute(
                        f"ALTER TABLE task_executions ADD COLUMN {col} {col_type}"
                    )
                except sqlite3.OperationalError:
                    pass  # column already exists
            conn.commit()
```

Add `_write_with_retry` after `_init_schema`:
```python
def _write_with_retry(
    self, fn: "Callable[[sqlite3.Connection], None]", max_retries: int = 3
) -> None:
    """Execute fn(conn) inside a transaction; retry up to max_retries on lock errors."""
    for attempt in range(max_retries):
        try:
            with self._lock, closing(self._connect()) as conn:
                with conn:
                    fn(conn)
            return
        except sqlite3.OperationalError as e:
            if "locked" in str(e) and attempt < max_retries - 1:
                time.sleep(0.1 * (attempt + 1))
                continue
            raise
```

Add `from typing import Callable` to the typing import line (it already has `Optional`):
```python
from typing import Callable, Optional
```

Replace `record()` — remove the manual lock and commit, delegate to `_write_with_retry`:
```python
def record(self, payload: dict) -> None:
    """Upsert a task record. Missing columns default to None for new rows;
    existing non-null values are preserved for updates."""
    values = {col: payload.get(col) for col in _COLUMNS}
    cols = ", ".join(_COLUMNS)
    placeholders = ", ".join(f":{col}" for col in _COLUMNS)
    update_clauses = ", ".join(
        f"{col} = COALESCE(excluded.{col}, task_executions.{col})"
        for col in _COLUMNS
        if col != "task_id"
    )
    sql = (
        f"INSERT INTO task_executions ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT(task_id) DO UPDATE SET {update_clauses}"
    )
    self._write_with_retry(lambda conn: conn.execute(sql, values))
```

- [ ] **Step 1.4: Run WAL tests — confirm PASS**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_parallel.py::TestTelemetryStoreWAL -v 2>&1 | tail -10
```

Expected: 5 passed.

- [ ] **Step 1.5: Run full suite — confirm no regressions**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/ -q 2>&1 | tail -5
```

Expected: 664 + 5 = 669 passed.

- [ ] **Step 1.6: Commit**

```bash
cd /Users/vini/.claude/devflow
git add telemetry/store.py hooks/tests/test_parallel.py
git commit -m "feat(telemetry): WAL mode + write retry for concurrent session support

- journal_mode=WAL persists at file level; busy_timeout=5000 per-connection
- _write_with_retry retries up to 3x with backoff on OperationalError 'locked'
- record() delegates to _write_with_retry; drops manual lock+commit"
```

---

## Task 2: Session ID Utility + Hook Updates

**Files:**
- Create: `hooks/_session.py`
- Modify: `hooks/_util.py` (re-export; remove local def)
- Modify: `hooks/spec_stop_guard.py` (use get_session_id; drop direct env read)
- Modify: `hooks/tests/test_spec_stop_guard.py` (update 1 test)
- Test: `hooks/tests/test_parallel.py` (append session ID tests)

### What changes

`_session.py` defines `get_session_id()` with three-priority fallback. `_util.py` imports and re-exports it (hooks that already `from _util import get_session_id` need zero changes). `spec_stop_guard.py` is the only hook that bypassed `get_session_id()` by reading the env directly — it switches to `get_session_id()` and simplifies its bypass condition from `not session_id or session_id == "default"` to just `session_id == "default"` (since the pid fallback is never empty or "default").

---

- [ ] **Step 2.1: Append session ID tests to `test_parallel.py` (RED)**

Append to `hooks/tests/test_parallel.py`:

```python
# ---------------------------------------------------------------------------
# Task 2: Session ID utility (_session.py)
# ---------------------------------------------------------------------------

class TestGetSessionId:

    def test_returns_claude_session_id_when_set(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-abc-123")
        monkeypatch.delenv("DEVFLOW_SESSION_ID", raising=False)
        import importlib
        import _session
        importlib.reload(_session)
        assert _session.get_session_id() == "claude-abc-123"

    def test_returns_devflow_session_id_when_claude_unset(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
        monkeypatch.setenv("DEVFLOW_SESSION_ID", "devflow-test-456")
        import importlib
        import _session
        importlib.reload(_session)
        assert _session.get_session_id() == "devflow-test-456"

    def test_returns_pid_fallback_when_both_unset(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
        monkeypatch.delenv("DEVFLOW_SESSION_ID", raising=False)
        import importlib
        import _session
        importlib.reload(_session)
        import os
        sid = _session.get_session_id()
        assert sid.startswith(f"pid-{os.getpid()}-")

    def test_fallback_is_unique_across_calls_with_different_timestamps(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
        monkeypatch.delenv("DEVFLOW_SESSION_ID", raising=False)
        import importlib
        import _session
        importlib.reload(_session)
        with patch("_session.time") as mock_time:
            mock_time.time.side_effect = [1000, 1001]
            sid1 = _session.get_session_id()
            sid2 = _session.get_session_id()
        assert sid1 != sid2

    def test_util_re_exports_get_session_id_from_session_module(self):
        """_util.py must import get_session_id from _session, not define it."""
        util_path = _HOOKS_DIR / "_util.py"
        content = util_path.read_text()
        assert "from _session import get_session_id" in content
        assert "def get_session_id" not in content

    def test_no_hook_reads_claude_session_id_directly(self):
        """No hook file should read CLAUDE_SESSION_ID via os.environ.get directly."""
        for py_file in _HOOKS_DIR.glob("*.py"):
            if py_file.name in ("_session.py",) or "test_" in py_file.name:
                continue
            content = py_file.read_text()
            assert 'os.environ.get("CLAUDE_SESSION_ID"' not in content, (
                f"{py_file.name} reads CLAUDE_SESSION_ID directly; use get_session_id()"
            )
```

- [ ] **Step 2.2: Run — confirm FAIL**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_parallel.py::TestGetSessionId -v 2>&1 | tail -15
```

Expected: 6 FAILED (`_session` module not found).

- [ ] **Step 2.3: Create `hooks/_session.py`**

```python
"""Session ID utility for devflow hooks.

Single source of truth — every hook must import get_session_id from here.
"""
from __future__ import annotations

import os
import time


def get_session_id() -> str:
    """Return a unique, stable session identifier.

    Priority:
    1. CLAUDE_SESSION_ID — set by Claude Code; stable for the session lifetime.
    2. DEVFLOW_SESSION_ID — manual override for testing / scripted launches.
    3. pid-{pid}-{ts}     — fallback that guarantees uniqueness when neither
                            env var is set (e.g. running hooks outside Claude).
    """
    return (
        os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("DEVFLOW_SESSION_ID")
        or f"pid-{os.getpid()}-{int(time.time())}"
    )
```

- [ ] **Step 2.4: Update `hooks/_util.py`**

Remove the existing `get_session_id` function (lines 121-122):
```python
def get_session_id() -> str:
    return os.environ.get("CLAUDE_SESSION_ID", "default")
```

Add one import line after the stdlib imports block (after `from typing import Optional`):
```python
from _session import get_session_id  # noqa: F401 — re-exported for hook imports
```

The `get_state_dir()` function below it already calls `get_session_id()` and continues to work unchanged.

- [ ] **Step 2.5: Update `hooks/spec_stop_guard.py`**

In the import section (line 14), change:
```python
from _util import get_state_dir, hook_block
```
to:
```python
from _session import get_session_id
from _util import get_state_dir, hook_block
```

In `main()`, replace lines 67-71:
```python
    session_id = os.environ.get("CLAUDE_SESSION_ID", "").strip()
    if not session_id or session_id == "default":
        print("[devflow] no session ID — guard bypassed", file=sys.stderr)
        _cleanup_discovery_marker()
        return 0
```
with:
```python
    session_id = get_session_id()
    if session_id == "default":
        print("[devflow] session ID is 'default' — guard bypassed", file=sys.stderr)
        _cleanup_discovery_marker()
        return 0
```

Also remove the `import os` that is now unused in `spec_stop_guard.py` (check: the only use was on line 67 and in `_has_active_spec` for `os.getcwd()`). Actually `os.getcwd()` is used on line 35, so keep `import os`.

- [ ] **Step 2.6: Update `hooks/tests/test_spec_stop_guard.py`**

Locate `test_empty_session_id_bypasses_guard` (around line 120) and replace it:

```python
def test_empty_session_id_uses_pid_fallback(tmp_path, capsys, monkeypatch):
    """When CLAUDE_SESSION_ID is empty, guard uses pid-based fallback and checks state.
    Since state dir is empty (no active-spec.json), it does not block — but it DOES
    call _has_active_spec, unlike the old bypass behaviour."""
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.delenv("DEVFLOW_SESSION_ID", raising=False)
    with (
        patch("spec_stop_guard.get_state_dir", return_value=tmp_path),
        patch("spec_stop_guard._has_active_spec", return_value=(False, "")) as mock_has_spec,
    ):
        rc = main()
    assert rc == 0
    assert "block" not in capsys.readouterr().out
    mock_has_spec.assert_called_once()
```

- [ ] **Step 2.7: Run session ID tests — confirm PASS**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_parallel.py::TestGetSessionId -v 2>&1 | tail -15
```

Expected: 6 passed.

- [ ] **Step 2.8: Run full suite — confirm no regressions**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/ -q 2>&1 | tail -5
```

Expected: 675 passed (664 + 5 WAL + 6 session).

- [ ] **Step 2.9: Commit**

```bash
cd /Users/vini/.claude/devflow
git add hooks/_session.py hooks/_util.py hooks/spec_stop_guard.py \
        hooks/tests/test_spec_stop_guard.py hooks/tests/test_parallel.py
git commit -m "feat(session): _session.py with pid-fallback session ID

- get_session_id() tries CLAUDE_SESSION_ID → DEVFLOW_SESSION_ID → pid-{pid}-{ts}
- _util.py re-exports from _session; all hooks unchanged
- spec_stop_guard uses get_session_id(); bypass only for explicit 'default'"
```

---

## Task 3: Task Registry

**Files:**
- Create: `agents/task_registry.py`
- Test: `hooks/tests/test_parallel.py` (append registry tests)

### What changes

`TaskRegistry` stores task ownership in `~/.claude/devflow/state/task_registry.json`. All mutations are guarded by an exclusive `fcntl.flock` on a separate `.lock` file. `claim()` reclaims stale entries (> 1 hour old) atomically. All public methods are exception-safe (never raise to caller).

---

- [ ] **Step 3.1: Append registry tests to `test_parallel.py` (RED)**

Append to `hooks/tests/test_parallel.py`:

```python
# ---------------------------------------------------------------------------
# Task 3: TaskRegistry
# ---------------------------------------------------------------------------

from agents.task_registry import TaskRegistry


class TestTaskRegistry:

    def test_claim_unclaimed_task_returns_true(self, tmp_path):
        reg = TaskRegistry(registry_path=tmp_path / "registry.json")
        assert reg.claim("ISSUE-1", "session-a", "proj") is True

    def test_claim_already_claimed_returns_false(self, tmp_path):
        reg = TaskRegistry(registry_path=tmp_path / "registry.json")
        reg.claim("ISSUE-1", "session-a", "proj")
        assert reg.claim("ISSUE-1", "session-b", "proj") is False

    def test_claim_atomic_under_concurrency_only_one_wins(self, tmp_path):
        reg = TaskRegistry(registry_path=tmp_path / "registry.json")
        results: list[bool] = []

        def try_claim() -> None:
            results.append(
                reg.claim("ISSUE-1", f"s-{threading.get_ident()}", "proj")
            )

        threads = [threading.Thread(target=try_claim) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results.count(True) == 1
        assert results.count(False) == 2

    def test_release_updates_status_to_done(self, tmp_path):
        reg = TaskRegistry(registry_path=tmp_path / "registry.json")
        reg.claim("ISSUE-1", "session-a", "proj")
        reg.release("ISSUE-1", "session-a", "done")
        data = json.loads((tmp_path / "registry.json").read_text())
        assert data["tasks"]["ISSUE-1"]["status"] == "done"

    def test_release_by_wrong_session_is_noop(self, tmp_path):
        reg = TaskRegistry(registry_path=tmp_path / "registry.json")
        reg.claim("ISSUE-1", "session-a", "proj")
        reg.release("ISSUE-1", "session-b", "done")
        data = json.loads((tmp_path / "registry.json").read_text())
        assert data["tasks"]["ISSUE-1"]["status"] == "in_progress"

    def test_list_available_excludes_claimed_tasks(self, tmp_path):
        reg = TaskRegistry(registry_path=tmp_path / "registry.json")
        reg.claim("ISSUE-1", "session-a", "proj")
        available = reg.list_available(["ISSUE-1", "ISSUE-2"])
        assert "ISSUE-1" not in available
        assert "ISSUE-2" in available

    def test_list_available_reclaims_stale_tasks(self, tmp_path):
        reg = TaskRegistry(registry_path=tmp_path / "registry.json")
        reg.claim("ISSUE-1", "session-a", "proj")
        # Backdate claimed_at to simulate a 2-hour-old stale entry
        data = json.loads((tmp_path / "registry.json").read_text())
        data["tasks"]["ISSUE-1"]["claimed_at"] = "2020-01-01T00:00:00+00:00"
        (tmp_path / "registry.json").write_text(json.dumps(data))
        available = reg.list_available(["ISSUE-1", "ISSUE-2"])
        assert "ISSUE-1" in available

    def test_list_active_returns_only_in_progress_non_stale(self, tmp_path):
        reg = TaskRegistry(registry_path=tmp_path / "registry.json")
        reg.claim("ISSUE-1", "session-a", "proj")
        reg.claim("ISSUE-2", "session-b", "proj")
        reg.release("ISSUE-2", "session-b", "done")
        active = reg.list_active()
        assert len(active) == 1
        assert active[0]["task_id"] == "ISSUE-1"

    def test_never_raises_on_missing_registry_file(self, tmp_path):
        # registry_path inside a subdirectory that does not exist yet
        reg = TaskRegistry(registry_path=tmp_path / "sub" / "registry.json")
        result = reg.claim("ISSUE-1", "session-a", "proj")
        assert isinstance(result, bool)

    def test_never_raises_on_corrupted_registry_file(self, tmp_path):
        reg_path = tmp_path / "registry.json"
        reg_path.write_text("{{{ not valid json !!!")
        reg = TaskRegistry(registry_path=reg_path)
        result = reg.claim("ISSUE-1", "session-a", "proj")
        assert isinstance(result, bool)
```

- [ ] **Step 3.2: Run — confirm FAIL**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_parallel.py::TestTaskRegistry -v 2>&1 | tail -15
```

Expected: 10 FAILED (`agents.task_registry` not found).

- [ ] **Step 3.3: Create `agents/task_registry.py`**

```python
"""File-locked task registry for parallel devflow session coordination.

Storage: ~/.claude/devflow/state/task_registry.json
Lock:    ~/.claude/devflow/state/task_registry.lock  (exclusive flock)

Multiple Claude Code windows (or test threads) safely claim tasks without
collision. Tasks older than STALE_THRESHOLD seconds are automatically
reclaimed so dead sessions don't block work forever.
"""
from __future__ import annotations

import fcntl
import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Optional

_DEVFLOW_STATE = Path.home() / ".claude" / "devflow" / "state"


class TaskRegistry:
    REGISTRY_PATH = _DEVFLOW_STATE / "task_registry.json"
    LOCK_TIMEOUT = 10.0   # seconds before TimeoutError
    STALE_THRESHOLD = 3600  # 1 hour — reclaim tasks from dead sessions

    def __init__(self, registry_path: Optional[Path] = None) -> None:
        self._path = Path(registry_path) if registry_path else self.REGISTRY_PATH

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def claim(self, task_id: str, session_id: str, project: str) -> bool:
        """Atomically claim *task_id* for *session_id*.

        Returns True if claimed, False if already taken by a live session.
        Never raises — returns False on any unexpected error.
        """
        try:
            with self._lock():
                data = self._read()
                existing = data["tasks"].get(task_id)
                if (
                    existing
                    and existing.get("status") == "in_progress"
                    and not self._is_stale(existing)
                ):
                    return False
                data["tasks"][task_id] = {
                    "session_id": session_id,
                    "claimed_at": datetime.now(tz=timezone.utc).isoformat(),
                    "project": project,
                    "status": "in_progress",
                }
                self._write(data)
                return True
        except Exception:
            return False

    def release(self, task_id: str, session_id: str, status: str) -> None:
        """Mark *task_id* as *status*. No-op if *session_id* does not own it."""
        try:
            with self._lock():
                data = self._read()
                entry = data["tasks"].get(task_id)
                if entry and entry.get("session_id") == session_id:
                    entry["status"] = status
                    self._write(data)
        except Exception:
            pass

    def list_active(self) -> list[dict]:
        """Return all in_progress tasks that are not stale."""
        try:
            data = self._read()
            return [
                {"task_id": tid, **entry}
                for tid, entry in data["tasks"].items()
                if entry.get("status") == "in_progress" and not self._is_stale(entry)
            ]
        except Exception:
            return []

    def list_available(self, all_tasks: list[str]) -> list[str]:
        """Return *all_tasks* minus those actively claimed by a live session.

        Stale entries are reclaimed (deleted from the registry) as a side-effect.
        """
        try:
            with self._lock():
                data = self._read()
                tasks = data["tasks"]
                stale_keys = [
                    tid
                    for tid, entry in tasks.items()
                    if entry.get("status") == "in_progress" and self._is_stale(entry)
                ]
                for tid in stale_keys:
                    del tasks[tid]
                if stale_keys:
                    self._write(data)
                active = {
                    tid
                    for tid, entry in tasks.items()
                    if entry.get("status") == "in_progress"
                }
                return [t for t in all_tasks if t not in active]
        except Exception:
            return list(all_tasks)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _lock(self) -> Generator[None, None, None]:
        """Exclusive flock on a separate .lock file; raises TimeoutError after LOCK_TIMEOUT."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self._path.with_suffix(".lock")
        deadline = time.monotonic() + self.LOCK_TIMEOUT
        with open(lock_path, "w") as lf:
            while True:
                try:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            f"Registry lock not acquired within {self.LOCK_TIMEOUT}s"
                        )
                    time.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    def _read(self) -> dict:
        try:
            if self._path.exists():
                raw = self._path.read_text(encoding="utf-8")
                data = json.loads(raw)
                if isinstance(data, dict) and "tasks" in data:
                    return data
        except (json.JSONDecodeError, OSError):
            pass
        return {"tasks": {}}

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _is_stale(self, entry: dict) -> bool:
        claimed_at = entry.get("claimed_at", "")
        if not claimed_at:
            return True
        try:
            claimed_ts = datetime.fromisoformat(claimed_at).timestamp()
            return (time.time() - claimed_ts) > self.STALE_THRESHOLD
        except (ValueError, TypeError):
            return True
```

- [ ] **Step 3.4: Run registry tests — confirm PASS**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_parallel.py::TestTaskRegistry -v 2>&1 | tail -15
```

Expected: 10 passed.

- [ ] **Step 3.5: Run full suite — confirm no regressions**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/ -q 2>&1 | tail -5
```

Expected: 685 passed (675 + 10 registry).

- [ ] **Step 3.6: Commit**

```bash
cd /Users/vini/.claude/devflow
git add agents/task_registry.py hooks/tests/test_parallel.py
git commit -m "feat(registry): file-locked TaskRegistry for parallel session coordination

- claim() atomically owns a task using fcntl.flock; stale tasks auto-reclaimed
- release() is session-scoped: only the claiming session can update status
- list_available() filters active + reclaims stale entries in one locked op"
```

---

## Task 4: Parallel Launch Script

**Files:**
- Create: `scripts/parallel_launch.sh`
- Test: `hooks/tests/test_parallel.py` (append bash tests)

---

- [ ] **Step 4.1: Append bash tests to `test_parallel.py` (RED)**

Append to `hooks/tests/test_parallel.py`:

```python
# ---------------------------------------------------------------------------
# Task 4: parallel_launch.sh
# ---------------------------------------------------------------------------

_SCRIPT = _DEVFLOW_ROOT / "scripts" / "parallel_launch.sh"


class TestParallelLaunchScript:

    def test_dry_run_prints_table_no_files_created(self, tmp_path):
        result = subprocess.run(
            ["bash", str(_SCRIPT), "--dry-run", "ISSUE-123"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "ISSUE-123" in result.stdout
        # No worktree directories created
        assert not list(tmp_path.iterdir())

    def test_dry_run_accepts_multiple_issue_ids(self, tmp_path):
        result = subprocess.run(
            ["bash", str(_SCRIPT), "--dry-run", "ISSUE-1", "ISSUE-2", "ISSUE-3"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "ISSUE-1" in result.stdout
        assert "ISSUE-2" in result.stdout
        assert "ISSUE-3" in result.stdout

    def test_cleanup_prints_nothing_to_clean_when_no_worktrees(self, tmp_path):
        result = subprocess.run(
            ["bash", str(_SCRIPT), "--cleanup"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
        combined = (result.stdout + result.stderr).lower()
        assert "nothing" in combined
```

- [ ] **Step 4.2: Run — confirm FAIL**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_parallel.py::TestParallelLaunchScript -v 2>&1 | tail -10
```

Expected: 3 FAILED (script does not exist).

- [ ] **Step 4.3: Create `scripts/parallel_launch.sh`**

First create the scripts directory:

```bash
mkdir -p /Users/vini/.claude/devflow/scripts
```

Then create `scripts/parallel_launch.sh`:

```bash
#!/usr/bin/env bash
# parallel_launch.sh — Spawn isolated Claude Code sessions for multiple issues.
#
# Usage:
#   ./scripts/parallel_launch.sh ISSUE-123 ISSUE-124 ISSUE-125
#   ./scripts/parallel_launch.sh --project mom-ease ISSUE-123
#   ./scripts/parallel_launch.sh --dry-run ISSUE-123 ISSUE-124
#   ./scripts/parallel_launch.sh --cleanup
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
    echo "Usage: $(basename "$0") [--dry-run] [--project NAME] ISSUE-ID..."
    echo "       $(basename "$0") --cleanup"
    exit 1
}

DRY_RUN=false
CLEANUP=false
PROJECT=""
ISSUES=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)  DRY_RUN=true;     shift ;;
        --cleanup)  CLEANUP=true;     shift ;;
        --project)  PROJECT="$2";     shift 2 ;;
        --*)        echo "Unknown option: $1"; usage ;;
        *)          ISSUES+=("$1");   shift ;;
    esac
done

# ------------------------------------------------------------------
# --cleanup: remove all devflow-ISSUE-* worktrees
# ------------------------------------------------------------------
if $CLEANUP; then
    found=0
    for wt_dir in "$PROJECT_ROOT"/../devflow-ISSUE-*/; do
        [[ -d "$wt_dir" ]] || continue
        issue_id="$(basename "$wt_dir" | sed 's/^devflow-//')"
        echo "Removing worktree: $wt_dir"
        git -C "$PROJECT_ROOT" worktree remove --force "$wt_dir" 2>/dev/null || true
        git -C "$PROJECT_ROOT" branch -D "fix/$issue_id" 2>/dev/null || true
        found=$(( found + 1 ))
    done
    if [[ $found -eq 0 ]]; then
        echo "Nothing to clean."
    fi
    exit 0
fi

[[ ${#ISSUES[@]} -gt 0 ]] || usage

# ------------------------------------------------------------------
# Print summary table header
# ------------------------------------------------------------------
printf "%-15s  %-40s  %-25s\n" "Issue" "Worktree" "Branch"
printf "%-15s  %-40s  %-25s\n" "-----" "--------" "------"

for ISSUE in "${ISSUES[@]}"; do
    WORKTREE="$PROJECT_ROOT/../devflow-$ISSUE"
    BRANCH="fix/$ISSUE"
    SESSION_ID="pid-$$-$ISSUE"

    printf "%-15s  %-40s  %-25s\n" "$ISSUE" "$WORKTREE" "$BRANCH"

    $DRY_RUN && continue

    # Create worktree + branch
    git -C "$PROJECT_ROOT" worktree add "$WORKTREE" -b "$BRANCH" 2>/dev/null

    # Copy harness config into worktree
    [[ -f "$PROJECT_ROOT/CLAUDE.md" ]] && cp "$PROJECT_ROOT/CLAUDE.md" "$WORKTREE/CLAUDE.md"
    [[ -d "$PROJECT_ROOT/.claude" ]]   && cp -r "$PROJECT_ROOT/.claude" "$WORKTREE/.claude"

    # Open new Terminal.app window (macOS); gracefully degrade on non-macOS
    osascript -e "
        tell application \"Terminal\"
            activate
            do script \"export DEVFLOW_SESSION_ID='$SESSION_ID'; cd '$WORKTREE' && claude --dangerously-skip-permissions\"
        end tell
    " 2>/dev/null || {
        echo "  [warn] Terminal window unavailable for $ISSUE"
        echo "         Run manually: export DEVFLOW_SESSION_ID='$SESSION_ID'; cd '$WORKTREE' && claude"
    }
done
```

Make it executable:

```bash
chmod +x /Users/vini/.claude/devflow/scripts/parallel_launch.sh
```

- [ ] **Step 4.4: Run bash tests — confirm PASS**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_parallel.py::TestParallelLaunchScript -v 2>&1 | tail -10
```

Expected: 3 passed.

- [ ] **Step 4.5: Run full suite — confirm no regressions**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/ -q 2>&1 | tail -5
```

Expected: 688 passed (685 + 3 bash).

- [ ] **Step 4.6: Commit**

```bash
cd /Users/vini/.claude/devflow
git add scripts/parallel_launch.sh hooks/tests/test_parallel.py
git commit -m "feat(scripts): parallel_launch.sh orchestrator for multi-session launch

- --dry-run prints table without creating worktrees or opening Terminal
- Each issue gets git worktree + unique DEVFLOW_SESSION_ID exported
- --cleanup removes all devflow-ISSUE-* worktrees and their branches"
```

---

## Task 5: Run Concurrency Smoke Test + Full Validation

No new files — validate the complete implementation end-to-end.

- [ ] **Step 5.1: Run the concurrency smoke test**

```bash
cd /Users/vini/.claude/devflow
python3.13 -c "
import threading, sys
sys.path.insert(0, 'hooks')
sys.path.insert(0, 'telemetry')
from store import TelemetryStore
import tempfile, pathlib

with tempfile.TemporaryDirectory() as d:
    store = TelemetryStore(pathlib.Path(d) / 'test.db')
    errors = []
    def write():
        try:
            store.record({'session_id': f'test-{threading.get_ident()}',
                         'task_category': 'test'})
        except Exception as e:
            errors.append(e)
    threads = [threading.Thread(target=write) for _ in range(10)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    print(f'Errors: {len(errors)}')
    print(f'Records: {len(store.get_recent(n=20))}')
"
```

Expected output:
```
Errors: 0
Records: 10
```

If errors > 0: the WAL implementation has a bug. Re-check `_write_with_retry` lock acquisition and ensure `record()` no longer acquires `self._lock` directly.

- [ ] **Step 5.2: Run complete test suite**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/ -q 2>&1 | tail -5
```

Expected: `688 passed` (or higher if regressions were fixed along the way).

---

## Task 6: Update docs/audit-20260331.md

**Files:**
- Modify: `docs/audit-20260331.md`

- [ ] **Step 6.1: Append Prompt 14 entry**

Read the end of the file and append:

```markdown

---

## Prompt 14 — Parallel Session Support (2026-03-31)

**Problem:** devflow assumed a single active session. Running 10+ concurrent Claude Code windows caused:
- SQLite `database is locked` errors in `TelemetryStore` (single-writer, no WAL)
- All sessions colliding in `state/default/` (empty `CLAUDE_SESSION_ID`)
- Multiple sessions claiming the same issue (no coordination)

**Changes:**

| File | Change |
|------|--------|
| `telemetry/store.py` | WAL mode, `PRAGMA busy_timeout=5000`, `_write_with_retry` |
| `hooks/_session.py` | New — `get_session_id()` with pid+ts fallback |
| `hooks/_util.py` | Re-exports from `_session`; removed local `get_session_id` def |
| `hooks/spec_stop_guard.py` | Uses `get_session_id()`; bypass only for explicit "default" |
| `agents/task_registry.py` | New — `fcntl.flock`-guarded task claim/release/list |
| `scripts/parallel_launch.sh` | New — macOS worktree orchestrator |

**Tests added:** 24 (5 WAL + 6 session + 10 registry + 3 bash)

**Baseline → Final:** 664 → 688 tests passing
```

- [ ] **Step 6.2: Commit**

```bash
cd /Users/vini/.claude/devflow
git add docs/audit-20260331.md
git commit -m "docs: audit entry for Prompt 14 — parallel session support"
```

---

## Self-Review

### Spec coverage check

| Spec requirement | Task |
|-----------------|------|
| WAL mode + busy_timeout=5000 | Task 1 |
| `_write_with_retry` with retry logic | Task 1 |
| `_session.py` with 3-priority fallback | Task 2 |
| All hooks import from `_session` (via re-export) | Task 2 |
| `spec_stop_guard` uses `get_session_id()` | Task 2 |
| `TaskRegistry.claim()` atomic, flock-guarded | Task 3 |
| `TaskRegistry.release()` session-scoped | Task 3 |
| `TaskRegistry.list_active()` / `list_available()` | Task 3 |
| Stale task reclaim (> 1 hour) | Task 3 |
| `parallel_launch.sh` --dry-run / --cleanup | Task 4 |
| Git worktree + DEVFLOW_SESSION_ID per issue | Task 4 |
| test_parallel.py with all specified tests | Tasks 1-4 |
| docs/audit-20260331.md Prompt 14 entry | Task 6 |
| Concurrency smoke test (10 threads, 0 errors) | Task 5 |

All requirements covered. No gaps identified.

### Placeholder scan

No TBD, TODO, or "implement later" present. All steps contain actual code.

### Type consistency

- `_write_with_retry(fn: Callable[[sqlite3.Connection], None])` — used as `lambda conn: conn.execute(sql, values)` in `record()`. Consistent.
- `TaskRegistry.claim()` → `bool`, `release()` → `None`, `list_active()` → `list[dict]`, `list_available()` → `list[str]`. Consistent across tests and implementation.
- `get_session_id()` → `str`. Consistent in `_session.py`, `_util.py` re-export, `spec_stop_guard.py` usage.
