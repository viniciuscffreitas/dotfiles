#!/usr/bin/env python3.13
"""
Weekly review CLI for captured instincts.

Usage:
  python3.13 hooks/instinct_review.py                  # current project
  python3.13 hooks/instinct_review.py --project NAME   # specific project
  python3.13 hooks/instinct_review.py --all            # all projects
  python3.13 hooks/instinct_review.py --json           # JSON output
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from analysis.instinct_store import Instinct, InstinctStore

_INSTINCTS_DIR = Path.home() / ".claude" / "devflow" / "instincts"
_DEFAULT_RULES_FILE = str(Path.home() / ".claude" / "rules" / "python" / "conventions.md")


def _get_projects() -> list[str]:
    if not _INSTINCTS_DIR.exists():
        return []
    return [p.stem for p in _INSTINCTS_DIR.glob("*.jsonl")]


def _print_report_header(report) -> None:
    print(
        f"[devflow:instincts] project={report.project} | "
        f"{report.pending_count} pending, "
        f"{report.promoted_count} promoted, "
        f"{report.dismissed_count} dismissed"
    )


def _promote(store: InstinctStore, instinct: Instinct, project: str) -> None:
    rules_path_str = input(f"  Promote to which rules file? [{_DEFAULT_RULES_FILE}] ").strip()
    if not rules_path_str:
        rules_path_str = _DEFAULT_RULES_FILE
    rules_path = Path(rules_path_str)
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    with rules_path.open("a", encoding="utf-8") as f:
        f.write(f"\n- {instinct.content}\n")
    store.update_status(instinct.id, project, "promoted", promoted_to=rules_path_str)
    print(f"  Promoted [{instinct.id}] → {rules_path_str}")


def _interactive_review(store: InstinctStore, project: str) -> None:
    pending = store.pending(project)
    if not pending:
        print("  No pending instincts.")
        return
    print(f"\nPENDING REVIEW ({len(pending)}):\n")
    for instinct in pending:
        print(f"  [{instinct.id}] {instinct.category} | confidence: {instinct.confidence}")
        print(f'  "{instinct.content}"')
        print("  → (p)romote to rule | (d)ismiss | (s)kip")
        choice = input("  Choice: ").strip().lower()
        if choice == "p":
            _promote(store, instinct, project)
        elif choice == "d":
            store.update_status(instinct.id, project, "dismissed")
            print(f"  Dismissed [{instinct.id}]")
        else:
            print(f"  Skipped [{instinct.id}]")
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review captured devflow instincts")
    parser.add_argument("--project", help="Specific project name")
    parser.add_argument("--all", action="store_true", dest="all_projects")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    store = InstinctStore()

    if args.all_projects:
        projects = _get_projects()
    elif args.project:
        projects = [args.project]
    else:
        projects = [Path(os.getcwd()).name]

    if args.as_json:
        reports = [dataclasses.asdict(store.report(p)) for p in projects]
        if len(reports) == 1:
            print(json.dumps(reports[0], indent=2))
        else:
            print(json.dumps(reports, indent=2))
        return 0

    for project in projects:
        report = store.report(project)
        _print_report_header(report)
        _interactive_review(store, project)

    return 0


if __name__ == "__main__":
    sys.exit(main())
