"""
devflow telemetry CLI — quick-stats commands.

Usage:
    python3.13 telemetry/cli.py stats              — summary statistics
    python3.13 telemetry/cli.py stats --by-model   — cost + runs grouped by model
    python3.13 telemetry/cli.py recent             — last 10 tasks
    python3.13 telemetry/cli.py anxiety            — context anxiety cases (>60k tokens at first action)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from telemetry.store import TelemetryStore


def _store() -> TelemetryStore:
    """Return a TelemetryStore, honouring DEVFLOW_DB env override for tests."""
    db_env = os.environ.get("DEVFLOW_DB")
    return TelemetryStore(db_path=Path(db_env)) if db_env else TelemetryStore()


def cmd_stats_by_model() -> None:
    """Cost + run count broken down per model. Legacy rows (model IS NULL)
    are shown explicitly so they don't silently drop out of the total."""
    store = _store()
    buckets = store.cost_by_model()
    if not buckets:
        print("No telemetry records yet.")
        return
    print(f"{'model':<34} {'runs':>6}  {'total_cost_usd':>14}")
    print("-" * 58)
    for row in buckets:
        print(
            f"{str(row['model']):<34} "
            f"{row['runs']:>6}  "
            f"${row['total_cost_usd']:>13.2f}"
        )


def cmd_stats() -> None:
    # Sub-flag: stats --by-model
    if "--by-model" in sys.argv[2:]:
        cmd_stats_by_model()
        return
    store = _store()
    s = store.summary_stats()
    print(f"{'Total tasks:':<26} {s['total_tasks']}")
    print(f"{'Pass rate:':<26} {s['pass_rate']:.1%}")
    print(f"{'Avg context tokens:':<26} {s['avg_context_tokens']:,.0f}")
    print(f"{'Spiral rate:':<26} {s['spiral_rate']:.1%}")
    iters = s["avg_iterations_by_category"]
    if iters:
        print("Avg iterations by category:")
        for cat, avg in sorted(iters.items()):
            print(f"  {cat}: {avg:.1f}")
    else:
        print("Avg iterations by category:  (no data)")


def cmd_recent() -> None:
    store = _store()
    records = store.get_recent(10)
    if not records:
        print("No records found.")
        return
    print(f"{'task_id':<14} {'timestamp':<26} {'category':<10} {'tokens':>10}  verdict")
    print("-" * 72)
    for r in records:
        print(
            f"{str(r.get('task_id', ''))[:13]:<14} "
            f"{str(r.get('timestamp', 'N/A'))[:25]:<26} "
            f"{str(r.get('task_category', '?')):<10} "
            f"{(r.get('context_tokens_consumed') or 0):>10,}  "
            f"{r.get('judge_verdict') or 'pending'}"
        )


def cmd_anxiety() -> None:
    store = _store()
    records = store.get_context_anxiety_cases()
    if not records:
        print("No context anxiety cases (threshold: 60,000 tokens at first action).")
        return
    print(f"Context anxiety cases — {len(records)} found (threshold: 60,000 tokens)")
    print(f"{'task_id':<14} {'tokens_at_first_action':>22}  stack")
    print("-" * 50)
    for r in records:
        print(
            f"{str(r.get('task_id', ''))[:13]:<14} "
            f"{(r.get('context_tokens_at_first_action') or 0):>22,}  "
            f"{r.get('stack') or '?'}"
        )


_COMMANDS = {"stats": cmd_stats, "recent": cmd_recent, "anxiety": cmd_anxiety}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd not in _COMMANDS:
        print(f"Unknown command: {cmd!r}. Available: {', '.join(_COMMANDS)}", file=sys.stderr)
        sys.exit(1)
    _COMMANDS[cmd]()
