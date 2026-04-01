#!/usr/bin/env python3.13
"""
devflow context anxiety report — investigation depth vs. action ratio.

Usage:
  python3.13 hooks/anxiety_report.py            # last 50 sessions
  python3.13 hooks/anxiety_report.py --n 20     # last 20 sessions
  python3.13 hooks/anxiety_report.py --json     # JSON output
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from analysis.context_anxiety import ContextAnxietyDetector
from telemetry.store import TelemetryStore


def _verdict_label(score: float) -> str:
    if score >= 0.7:
        return "HIGH"
    if score >= 0.4:
        return "MEDIUM"
    return "LOW"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="devflow context anxiety report")
    parser.add_argument("--n", type=int, default=50, help="Last N sessions (default: 50)")
    parser.add_argument("--json", action="store_true", dest="as_json", help="JSON output")
    args = parser.parse_args(argv)

    store = TelemetryStore()
    detector = ContextAnxietyDetector()
    report = detector.analyze_store(store, n=args.n)

    if args.as_json:
        print(json.dumps(dataclasses.asdict(report), indent=2))
        return

    print(
        f"[devflow:anxiety] Analyzed {report.sessions_analyzed} sessions | "
        f"HIGH: {report.high_anxiety_count} "
        f"MEDIUM: {report.medium_anxiety_count} "
        f"LOW: {report.low_anxiety_count}"
    )
    print(f"Mean score: {report.mean_score:.2f}")

    if report.top_anxious_categories:
        print("\nTop anxious categories:")
        for cat, score in report.top_anxious_categories:
            label = _verdict_label(score)
            print(f"  {cat:<20} : {score:.2f}  {label}")

    print(f"\nRecommendation: {report.recommendation}")


if __name__ == "__main__":
    main()
