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
