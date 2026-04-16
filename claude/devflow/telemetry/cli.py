"""
devflow telemetry CLI — quick-stats commands.

Usage:
    python3.13 telemetry/cli.py stats              — summary statistics
    python3.13 telemetry/cli.py stats --by-model   — cost + runs grouped by model
    python3.13 telemetry/cli.py recent             — last 10 tasks
    python3.13 telemetry/cli.py anxiety            — context anxiety cases (>60k tokens at first action)
    python3.13 telemetry/cli.py behavior           — scan transcripts for thrashing / error-loops / restart-clusters
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from telemetry.signals.runner import run_behavior_signals
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
    print(f"{'Avg estimated USD:':<26} ${s.get('avg_estimated_usd', 0.0):.4f}")
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


def cmd_behavior() -> None:
    """Scan ~/.claude/projects/ transcripts for behavior anti-patterns."""
    report = run_behavior_signals()
    if report.sessions_scanned == 0:
        print("No transcripts found under ~/.claude/projects/.")
        return
    print(
        f"Scanned {report.sessions_scanned} sessions — "
        f"{report.total_signals} signal(s): "
        f"{len(report.thrashing)} thrashing, "
        f"{len(report.error_loops)} error-loops, "
        f"{len(report.restart_clusters)} restart-clusters."
    )
    if report.thrashing:
        print("\n── Edit thrashing (file edited ≥5x) ──")
        print(f"{'session':<14} {'edits':>6}  {'sev':<9}  file")
        for hit in report.thrashing[:20]:
            print(f"{hit.session_id[:13]:<14} {hit.edit_count:>6}  {hit.severity:<9}  {hit.file_path}")
    if report.error_loops:
        print("\n── Error loops (consecutive tool failures) ──")
        print(f"{'session':<14} {'fails':>6}  {'sev':<9}  tool")
        for hit in report.error_loops[:20]:
            print(
                f"{hit.session_id[:13]:<14} {hit.consecutive_failures:>6}  "
                f"{hit.severity:<9}  {hit.tool_name}"
            )
    if report.restart_clusters:
        print("\n── Restart clusters (≥3 sessions in 30min, same cwd) ──")
        print(f"{'sessions':>9}  {'window_min':>10}  {'sev':<9}  cwd")
        for cluster in report.restart_clusters[:20]:
            print(
                f"{len(cluster.session_ids):>9}  {cluster.window_minutes:>10}  "
                f"{cluster.severity:<9}  {cluster.cwd}"
            )


_COMMANDS = {
    "stats": cmd_stats,
    "recent": cmd_recent,
    "anxiety": cmd_anxiety,
    "behavior": cmd_behavior,
}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"
    if cmd not in _COMMANDS:
        print(f"Unknown command: {cmd!r}. Available: {', '.join(_COMMANDS)}", file=sys.stderr)
        sys.exit(1)
    _COMMANDS[cmd]()
