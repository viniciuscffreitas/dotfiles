"""Tests for restart-cluster detector."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from telemetry.signals.restart_cluster import (
    RESTART_CRITICAL,
    RESTART_MIN_SESSIONS,
    RESTART_WINDOW,
    SessionStart,
    detect_restart_clusters,
    extract_session_start,
)

T0 = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)


def _session(sid: str, cwd: str, minutes_from_t0: float) -> SessionStart:
    return SessionStart(session_id=sid, cwd=cwd, started_at=T0 + timedelta(minutes=minutes_from_t0))


def test_under_min_returns_empty():
    sessions = [_session(f"s{i}", "/p", i * 2) for i in range(RESTART_MIN_SESSIONS - 1)]
    assert detect_restart_clusters(sessions) == []


def test_at_min_in_window_flags():
    sessions = [_session(f"s{i}", "/p", i * 2) for i in range(RESTART_MIN_SESSIONS)]
    clusters = detect_restart_clusters(sessions)
    assert len(clusters) == 1
    assert clusters[0].cwd == "/p"
    assert clusters[0].severity == "high"
    assert len(clusters[0].session_ids) == RESTART_MIN_SESSIONS


def test_critical_size_upgrades_severity():
    sessions = [_session(f"s{i}", "/p", i) for i in range(RESTART_CRITICAL)]
    clusters = detect_restart_clusters(sessions)
    assert clusters[0].severity == "critical"


def test_outside_window_does_not_cluster():
    sessions = [
        _session("s0", "/p", 0),
        _session("s1", "/p", 1),
        _session("s2", "/p", RESTART_WINDOW.total_seconds() / 60 + 5),  # well past window
    ]
    assert detect_restart_clusters(sessions) == []


def test_different_cwds_do_not_cluster():
    sessions = [
        _session("s0", "/a", 0),
        _session("s1", "/b", 1),
        _session("s2", "/c", 2),
    ]
    assert detect_restart_clusters(sessions) == []


def test_two_clusters_separated_by_gap():
    w = RESTART_WINDOW.total_seconds() / 60
    sessions = (
        [_session(f"a{i}", "/p", i) for i in range(RESTART_MIN_SESSIONS)]
        + [_session(f"b{i}", "/p", w + 60 + i) for i in range(RESTART_MIN_SESSIONS)]
    )
    clusters = detect_restart_clusters(sessions)
    assert len(clusters) == 2


def test_empty_cwd_ignored():
    sessions = [_session(f"s{i}", "", i) for i in range(RESTART_CRITICAL)]
    assert detect_restart_clusters(sessions) == []


# ---------------------------------------------------------------------------
# extract_session_start
# ---------------------------------------------------------------------------

def test_extract_session_start_picks_earliest_and_cwd():
    events = [
        {"timestamp": "2026-04-16T12:05:00Z", "cwd": "/late"},
        {"timestamp": "2026-04-16T12:00:00Z", "cwd": "/early"},
        {"timestamp": "2026-04-16T12:10:00Z"},
    ]
    start = extract_session_start("s1", events)
    assert start is not None
    assert start.started_at == T0
    # first cwd seen (iteration order) wins — "/late" in this fixture
    assert start.cwd == "/late"


def test_extract_session_start_ignores_malformed_timestamp():
    events = [
        {"timestamp": "not-a-date", "cwd": "/p"},
        {"timestamp": "2026-04-16T12:00:00+00:00", "cwd": "/p"},
    ]
    start = extract_session_start("s1", events)
    assert start is not None and start.started_at == T0


def test_extract_session_start_returns_none_when_no_timestamp():
    assert extract_session_start("s1", [{"cwd": "/p"}]) is None
