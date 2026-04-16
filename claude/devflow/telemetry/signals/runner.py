"""Orchestrates the three behavior-signal detectors against the user's transcripts.

Returns a structured report — the CLI formats it, tests exercise it directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from telemetry.signals._transcripts import (
    CLAUDE_PROJECTS_DIR,
    iter_project_transcripts,
    iter_transcript_events,
)
from telemetry.signals.edit_thrashing import ThrashingHit, detect_edit_thrashing
from telemetry.signals.error_loop import ErrorLoopHit, detect_error_loops
from telemetry.signals.restart_cluster import (
    RestartCluster,
    SessionStart,
    detect_restart_clusters,
    extract_session_start,
)


@dataclass
class BehaviorReport:
    sessions_scanned: int = 0
    thrashing: list[ThrashingHit] = field(default_factory=list)
    error_loops: list[ErrorLoopHit] = field(default_factory=list)
    restart_clusters: list[RestartCluster] = field(default_factory=list)

    @property
    def total_signals(self) -> int:
        return len(self.thrashing) + len(self.error_loops) + len(self.restart_clusters)


def run_behavior_signals(projects_dir: Path = CLAUDE_PROJECTS_DIR) -> BehaviorReport:
    """Scan every transcript under `projects_dir` and run all 3 detectors."""
    report = BehaviorReport()
    session_starts: list[SessionStart] = []

    for transcript in iter_project_transcripts(projects_dir):
        session_id = transcript.stem
        events = list(iter_transcript_events(transcript))
        if not events:
            continue
        report.sessions_scanned += 1

        report.thrashing.extend(detect_edit_thrashing(session_id, events))
        report.error_loops.extend(detect_error_loops(session_id, events))

        start = extract_session_start(session_id, events)
        if start is not None and start.cwd:
            session_starts.append(start)

    report.restart_clusters = detect_restart_clusters(session_starts)
    return report
