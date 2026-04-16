"""Restart-cluster: multiple sessions started within a short window on the same cwd.

Rapid session restarts signal either abandon-and-retry (spiral) or a chain of
failed attempts. Devflow has no cross-session live hook, so this detector runs
offline against transcript metadata.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

RESTART_WINDOW = timedelta(minutes=30)
RESTART_MIN_SESSIONS = 3                # ≥3 sessions in window to flag
RESTART_CRITICAL = 5                    # upgrade severity


@dataclass(frozen=True)
class SessionStart:
    session_id: str
    cwd: str
    started_at: datetime


@dataclass(frozen=True)
class RestartCluster:
    cwd: str
    session_ids: tuple[str, ...]
    window_minutes: int
    severity: str                       # "high" | "critical"


def _parse_ts(raw: str) -> datetime | None:
    """Accept both 'Z' suffix and explicit offset. Return None on garbage."""
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def extract_session_start(session_id: str, events: list[dict]) -> SessionStart | None:
    """First event with a cwd+timestamp wins — Claude Code writes attachment/meta up top."""
    earliest: datetime | None = None
    cwd: str | None = None
    for event in events:
        ts = _parse_ts(event.get("timestamp", ""))
        if ts is None:
            continue
        if earliest is None or ts < earliest:
            earliest = ts
        if cwd is None and isinstance(event.get("cwd"), str):
            cwd = event["cwd"]
    if earliest is None or cwd is None:
        return SessionStart(session_id=session_id, cwd=cwd or "", started_at=earliest) if earliest else None
    return SessionStart(session_id=session_id, cwd=cwd, started_at=earliest)


def detect_restart_clusters(sessions: list[SessionStart]) -> list[RestartCluster]:
    """Group session starts by cwd, then sweep a sliding window of RESTART_WINDOW."""
    by_cwd: dict[str, list[SessionStart]] = {}
    for sess in sessions:
        if not sess.cwd:
            continue
        by_cwd.setdefault(sess.cwd, []).append(sess)

    clusters: list[RestartCluster] = []
    for cwd, group in by_cwd.items():
        group_sorted = sorted(group, key=lambda s: s.started_at)
        # Greedy sweep: anchor i, extend j while within window; record max cluster then skip past j.
        i = 0
        while i < len(group_sorted):
            j = i
            while (
                j + 1 < len(group_sorted)
                and group_sorted[j + 1].started_at - group_sorted[i].started_at <= RESTART_WINDOW
            ):
                j += 1
            size = j - i + 1
            if size >= RESTART_MIN_SESSIONS:
                window = group_sorted[j].started_at - group_sorted[i].started_at
                clusters.append(
                    RestartCluster(
                        cwd=cwd,
                        session_ids=tuple(s.session_id for s in group_sorted[i : j + 1]),
                        window_minutes=int(window.total_seconds() // 60),
                        severity="critical" if size >= RESTART_CRITICAL else "high",
                    )
                )
                i = j + 1
            else:
                i += 1

    return clusters
