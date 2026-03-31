#!/usr/bin/env python3
"""
devflow telemetry report — tokens per phase per task per project.

Reads ~/.claude/devflow/telemetry/sessions.jsonl and displays:
  - tokens spent in understand/plan phase (PENDING → IMPLEMENTING)
  - tokens spent in build/verify phase (IMPLEMENTING → COMPLETED)
  - ratio as proxy for context dispersion (high ratio = scattered codebase)

Usage:
  python3 telemetry_report.py
  python3 telemetry_report.py --last 20
  python3 telemetry_report.py --project agents
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

TELEMETRY_LOG = Path.home() / ".claude" / "devflow" / "telemetry" / "sessions.jsonl"


def load_sessions(log: Path) -> list[dict]:
    if not log.exists():
        return []
    sessions = []
    with open(log, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                sessions.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return sessions


def compute_phase_tokens(phases: list[dict]) -> dict:
    """
    Compute tokens spent between consecutive phases.

    Returns subset of: {"understand": int, "build": int}
    Absent keys mean the corresponding phase transition was not observed.
    """
    ordered = sorted(phases, key=lambda p: p.get("tokens_cumulative", 0))

    pending = implementing = completed = None
    for p in ordered:
        phase = p.get("phase")
        cum = p.get("tokens_cumulative", 0)
        if phase == "PENDING" and pending is None:
            pending = cum
        elif phase == "IMPLEMENTING" and implementing is None:
            implementing = cum
        elif phase == "COMPLETED" and completed is None:
            completed = cum

    result = {}
    if pending is not None and implementing is not None:
        result["understand"] = implementing - pending
    if implementing is not None and completed is not None:
        result["build"] = completed - implementing
    return result


def format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _task_label(session: dict) -> str:
    phases = session.get("phases", [])
    task_id = next(
        (p.get("task_id") for p in phases if p.get("task_id")),
        None,
    )
    if task_id:
        return Path(task_id).stem
    return session.get("session_id", "?")[:8]


def main() -> None:
    parser = argparse.ArgumentParser(description="devflow telemetry report")
    parser.add_argument("--last", type=int, default=50, help="Last N sessions (default: 50)")
    parser.add_argument("--project", type=str, default=None, help="Filter by project name")
    args = parser.parse_args()

    sessions = load_sessions(TELEMETRY_LOG)
    if not sessions:
        print("No telemetry data yet. Data is recorded when specs complete.")
        print(f"Log: {TELEMETRY_LOG}")
        return

    if args.project:
        sessions = [s for s in sessions if s.get("project") == args.project]
    sessions = sessions[-args.last:]

    by_project: dict[str, list[dict]] = defaultdict(list)
    for s in sessions:
        by_project[s.get("project", "unknown")].append(s)

    for project, proj_sessions in sorted(by_project.items()):
        print(f"\nPROJECT: {project}")
        for s in proj_sessions:
            phases = s.get("phases", [])
            total = s.get("total_tokens", 0)
            label = _task_label(s)
            pt = compute_phase_tokens(phases)
            understand = pt.get("understand")
            build = pt.get("build")

            if understand is not None and build is not None:
                ratio = understand / build if build > 0 else 0.0
                warn = " ⚠" if ratio > 0.5 else ""
                print(
                    f"  {label:<50} "
                    f"understand: {format_tokens(understand):>7} | "
                    f"build: {format_tokens(build):>7} | "
                    f"ratio: {ratio:.2f}{warn}"
                )
            elif total > 0:
                phase_names = [p.get("phase", "?") for p in phases]
                phases_str = ", ".join(phase_names) if phase_names else "none"
                print(
                    f"  {label:<50} "
                    f"total: {format_tokens(total):>7}  "
                    f"(phases: {phases_str})"
                )

    print()


if __name__ == "__main__":
    main()
