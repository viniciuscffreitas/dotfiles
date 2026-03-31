#!/usr/bin/env python3.13
"""
devflow harness health report.

Usage:
  python3.13 hooks/health_report.py              # full report
  python3.13 hooks/health_report.py --json       # JSON output
  python3.13 hooks/health_report.py --critical   # exit 1 if critical
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from analysis.harness_health import HarnessHealthChecker
from telemetry.store import TelemetryStore

_SKILLS_DIR = Path.home() / ".claude" / "skills"
_HOOKS_DIR = Path(__file__).parent


def main(
    argv: list[str] | None = None,
    _store: Optional[TelemetryStore] = None,
    _skills_dir: Optional[Path] = None,
    _hooks_dir: Optional[Path] = None,
) -> int:
    parser = argparse.ArgumentParser(description="devflow harness health report")
    parser.add_argument("--json", action="store_true", dest="as_json", help="JSON output")
    parser.add_argument(
        "--critical", action="store_true",
        help="Exit 1 if overall verdict is critical"
    )
    args = parser.parse_args(argv)

    store = _store if _store is not None else TelemetryStore()
    skills_dir = _skills_dir if _skills_dir is not None else _SKILLS_DIR
    hooks_dir = _hooks_dir if _hooks_dir is not None else _HOOKS_DIR

    checker = HarnessHealthChecker()
    report = checker.check(store, skills_dir, hooks_dir)

    if args.as_json:
        print(json.dumps(dataclasses.asdict(report), indent=2))
        return 1 if (args.critical and report.overall_verdict == "critical") else 0

    active = sum(1 for s in report.skill_health if s.verdict == "active")
    stale = sum(1 for s in report.skill_health if s.verdict == "stale")
    unused = sum(1 for s in report.skill_health if s.verdict == "unused")

    healthy_h = sum(1 for h in report.hook_health if h.verdict == "healthy")
    slow_h = sum(1 for h in report.hook_health if h.verdict == "slow")
    broken_h = sum(1 for h in report.hook_health if h.verdict == "broken")
    idle_h = sum(1 for h in report.hook_health if h.verdict == "idle")

    print(
        f"[devflow:health] Overall: {report.overall_verdict.upper()} | "
        f"Skills: {active} active, {stale} stale, {unused} unused"
    )
    print(f"Hooks: {healthy_h} healthy, {slow_h} slow, {broken_h} broken, {idle_h} idle")
    print(f"Complexity score: {report.complexity_score:.2f}")

    if report.simplification_candidates:
        print("\nSimplification candidates:")
        for c in report.simplification_candidates:
            print(f"  - {c}")
    else:
        print("\nSimplification candidates: none")

    print(f"\nSummary: {report.summary}")

    return 1 if (args.critical and report.overall_verdict == "critical") else 0


if __name__ == "__main__":
    sys.exit(main())
