#!/usr/bin/env python3.13
"""
Weekly review CLI for captured instincts.

Usage:
  python3.13 hooks/instinct_review.py                            # non-interactive (default, safe in Claude Code)
  python3.13 hooks/instinct_review.py --project NAME             # specific project
  python3.13 hooks/instinct_review.py --all                      # all projects
  python3.13 hooks/instinct_review.py --json                     # JSON output
  python3.13 hooks/instinct_review.py --promote ID PATH          # promote single instinct
  python3.13 hooks/instinct_review.py --dismiss ID               # dismiss single instinct
  python3.13 hooks/instinct_review.py --promote-all              # promote all above threshold (default 0.85)
  python3.13 hooks/instinct_review.py --promote-threshold 0.7    # override threshold
  python3.13 hooks/instinct_review.py --interactive              # interactive p/d/s prompts (requires TTY)
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


def _suggest_rules_path(project: str) -> str:
    """Infer the conventions file path from the project name."""
    return str(Path.home() / ".claude" / "rules" / project / "conventions.md")


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
    """Interactive promote — asks for destination path via input()."""
    default_path = _suggest_rules_path(project)
    rules_path_str = input(f"  Promote to which rules file? [{default_path}] ").strip()
    if not rules_path_str:
        rules_path_str = default_path
    _write_to_rules(store, instinct, project, rules_path_str)
    print(f"  Promoted [{instinct.id}] → {rules_path_str}")


def _write_to_rules(store: InstinctStore, instinct: Instinct, project: str, rules_path_str: str) -> None:
    rules_path = Path(rules_path_str)
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    with rules_path.open("a", encoding="utf-8") as f:
        f.write(f"\n- {instinct.content}\n")
    store.update_status(instinct.id, project, "promoted", promoted_to=rules_path_str)


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


def _non_interactive_review(store: InstinctStore, project: str) -> None:
    report = store.report(project)
    _print_report_header(report)
    pending = store.pending(project)
    if not pending:
        return
    print(f"\nPENDING REVIEW ({len(pending)}):\n")
    for instinct in pending:
        print(f"  [{instinct.id}] {instinct.category} | confidence: {instinct.confidence}")
        print(f'  "{instinct.content}"')
        print()
    suggested_path = _suggest_rules_path(project)
    script = "instinct_review.py"
    first_id = pending[0].id
    print("  ---")
    print(f"  To promote:  {script} --promote {first_id} {suggested_path}")
    print(f"  To dismiss:  {script} --dismiss {first_id}")
    print(f"  To promote all ≥0.85: {script} --promote-all --project {project}")
    print(f"  To review interactively: {script} --interactive --project {project}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Review captured devflow instincts")
    parser.add_argument("--project", help="Specific project name")
    parser.add_argument("--all", action="store_true", dest="all_projects")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--promote", nargs=2, metavar=("ID", "PATH"))
    parser.add_argument("--dismiss", metavar="ID")
    parser.add_argument("--promote-all", action="store_true", dest="promote_all")
    parser.add_argument("--promote-threshold", type=float, default=0.85, dest="promote_threshold")
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

    project = projects[0] if projects else Path(os.getcwd()).name

    if args.promote:
        instinct_id, rules_path = args.promote
        all_instincts = store.load(project)
        target = next((i for i in all_instincts if i.id == instinct_id), None)
        if target is None:
            print(f"  [devflow:instincts] ID {instinct_id!r} not found in project {project!r}")
            return 1
        _write_to_rules(store, target, project, rules_path)
        print(f"  [devflow:instincts] Promoted [{instinct_id}] → {rules_path}")
        return 0

    if args.dismiss:
        instinct_id = args.dismiss
        result = store.update_status(instinct_id, project, "dismissed")
        if not result:
            print(f"  [devflow:instincts] ID {instinct_id!r} not found in project {project!r}")
            return 1
        print(f"  [devflow:instincts] Dismissed [{instinct_id}]")
        return 0

    if args.promote_all:
        pending = store.pending(project)
        rules_path = _suggest_rules_path(project)
        promoted = 0
        for instinct in pending:
            if instinct.confidence >= args.promote_threshold:
                _write_to_rules(store, instinct, project, rules_path)
                promoted += 1
        print(f"  [devflow:instincts] Promoted {promoted} instincts to {rules_path}")
        return 0

    if args.interactive:
        for p in projects:
            report = store.report(p)
            _print_report_header(report)
            _interactive_review(store, p)
        return 0

    # Default: non-interactive listing
    for p in projects:
        _non_interactive_review(store, p)

    return 0


if __name__ == "__main__":
    sys.exit(main())
