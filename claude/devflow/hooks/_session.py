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


def is_safe_session() -> bool:
    """Return True only when a stable, isolation-safe session ID is available.

    Returns False when CLAUDE_SESSION_ID is absent or the sentinel "default",
    meaning multiple sessions share the same state directory and per-session
    guards cannot be applied safely.
    """
    raw = os.environ.get("CLAUDE_SESSION_ID", "").strip()
    return bool(raw) and raw != "default"


