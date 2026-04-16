"""Session ID utility for devflow hooks.

Single source of truth — every hook must import get_session_id from here.
"""
from __future__ import annotations

import os


def get_session_id() -> str:
    """Return a unique, stable session identifier.

    Priority:
    1. CLAUDE_SESSION_ID   — env var set by Claude Code; stable for the session.
    2. DEVFLOW_SESSION_ID  — manual override for testing / scripted launches.
    3. stdin session_id    — parsed from hook JSON payload (Claude Code passes
                             session_id in the stdin JSON when env var is absent).
    4. pid-{pid}           — last resort; creates one dir per invocation —
                             AVOID: causes state dir explosion (138k dirs/2 days).
    """
    if sid := os.environ.get("CLAUDE_SESSION_ID"):
        return sid
    if sid := os.environ.get("DEVFLOW_SESSION_ID"):
        return sid
    # Try stdin JSON payload — Claude Code includes session_id there
    try:
        from _stdin_cache import get as _stdin
        if sid := _stdin().get("session_id"):
            return sid
    except Exception:
        pass
    return f"pid-{os.getpid()}"


def is_safe_session() -> bool:
    """Return True only when a stable, isolation-safe session ID is available.

    Returns False when CLAUDE_SESSION_ID is absent or the sentinel "default",
    meaning multiple sessions share the same state directory and per-session
    guards cannot be applied safely.
    """
    raw = os.environ.get("CLAUDE_SESSION_ID", "").strip()
    return bool(raw) and raw != "default"


