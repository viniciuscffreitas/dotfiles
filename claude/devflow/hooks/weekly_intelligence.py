#!/usr/bin/env python3.13
"""
devflow weekly intelligence report.

Usage:
  python3.13 hooks/weekly_intelligence.py            # human-readable output
  python3.13 hooks/weekly_intelligence.py --json     # JSON output
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from analysis.weekly_report import WeeklyReportGenerator
from telemetry.store import TelemetryStore

_SKILLS_DIR = Path.home() / ".claude" / "skills"
_HOOKS_DIR = Path(__file__).parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="devflow weekly intelligence report")
    parser.add_argument("--json", action="store_true", dest="as_json", help="JSON output")
    args = parser.parse_args(argv)

    store = TelemetryStore()
    gen = WeeklyReportGenerator()
    report = gen.generate(store, _SKILLS_DIR, _HOOKS_DIR)

    if args.as_json:
        print(json.dumps(dataclasses.asdict(report), indent=2))
        return 0

    print(
        f"[devflow:weekly] {report.week_label} | "
        f"Sessions: {report.signals.sessions_total} | "
        f"Pass rate: {report.signals.judge_pass_rate:.0%} | "
        f"Health: {report.signals.harness_health.upper()}"
    )
    print(f"Summary: {report.summary}")
    print(
        f"Instincts: {report.signals.instincts_captured} captured, "
        f"{report.signals.instincts_pending} pending review"
    )

    if report.recommendations:
        print("\nRecommendations:")
        for r in report.recommendations:
            print(f"  [{r.priority.upper()}] {r.action}  ({r.effort})")

    if report.next_prompt:
        print(f"\nNext step: {report.next_prompt}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
