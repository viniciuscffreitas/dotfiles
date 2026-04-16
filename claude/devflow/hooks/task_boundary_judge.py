"""
UserPromptSubmit hook — evaluates pending tasks at task boundaries.

Runs on every user prompt. Checks TelemetryStore for the most recent task
with judge_verdict IS NULL and oversight_level != 'vibe'. If found, runs
HarnessJudge and records the verdict.

This closes the gap where /clear between tasks prevents the Stop-event
judge from ever evaluating completed work.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_DEVFLOW_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_DEVFLOW_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from _util import read_hook_stdin
from judge.evaluator import HarnessJudge, JudgePayload
from judge.router import JudgeRouter

try:
    from telemetry.store import TelemetryStore
except ImportError:
    TelemetryStore = None  # type: ignore[assignment,misc]

STATE_ROOT = Path.home() / ".claude" / "devflow" / "state"


def _find_pending_task() -> dict | None:
    """Find the most recent task with judge_verdict IS NULL and non-vibe oversight."""
    if TelemetryStore is None:
        return None
    try:
        store = TelemetryStore()
        import sqlite3
        from contextlib import closing
        with closing(store._connect()) as conn:
            conn.execute("PRAGMA busy_timeout = 3000")  # 3s max wait on locked DB
            row = conn.execute(
                "SELECT task_id, oversight_level FROM task_executions "
                "WHERE judge_verdict IS NULL "
                "AND oversight_level IS NOT NULL "
                "AND oversight_level != 'vibe' "
                "ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        if row:
            return {"task_id": row["task_id"], "oversight_level": row["oversight_level"]}
    except Exception:
        pass
    return None


def _get_state_dir_for_task(task_id: str) -> Path:
    """Return the state directory for a given task/session ID."""
    return STATE_ROOT / task_id


def _get_diff() -> str:
    """Return git diff HEAD~1, falling back to git diff (unstaged)."""
    import subprocess
    for cmd in [["git", "diff", "HEAD~1"], ["git", "diff"]]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.stdout.strip():
                return result.stdout
        except Exception:
            pass
    return ""


def _read_spec(state_dir: Path) -> str:
    spec_path = state_dir / "active-spec.json"
    if not spec_path.exists():
        return ""
    try:
        spec = json.loads(spec_path.read_text())
        return str(spec.get("plan_path", ""))
    except (json.JSONDecodeError, OSError):
        return ""


def _read_harness_rules() -> list:
    claude_md = Path.home() / ".claude" / "CLAUDE.md"
    if not claude_md.exists():
        return []
    try:
        lines = claude_md.read_text().splitlines()[:50]
        return [line for line in lines if line.strip()]
    except OSError:
        return []


def _read_feature_path(state_dir: Path) -> str:
    profile_path = state_dir / "project-profile.json"
    if profile_path.exists():
        try:
            profile = json.loads(profile_path.read_text())
            return profile.get("feature_path") or "."
        except (json.JSONDecodeError, OSError):
            pass
    return "."


def _check_spec_overwrite(state_dir: Path) -> bool:
    """Warn if active-spec.json was recently overwritten (spec_phase_tracker ran first)."""
    spec_path = state_dir / "active-spec.json"
    if not spec_path.exists():
        return False
    try:
        spec = json.loads(spec_path.read_text())
        if spec.get("status") == "PENDING":
            started_at = spec.get("started_at", 0)
            if abs(time.time() - started_at) < 5:
                print(
                    "[devflow:boundary-judge] WARNING: active-spec.json has "
                    "status=PENDING with recent timestamp — spec_phase_tracker "
                    "may have run before boundary judge. Check hook ordering.",
                    file=sys.stderr,
                )
                return True
    except (json.JSONDecodeError, OSError):
        pass
    return False


def run() -> int:
    pending = _find_pending_task()
    if pending is None:
        return 0

    task_id = pending["task_id"]
    oversight_level = pending["oversight_level"]

    router = JudgeRouter()
    if not router.should_run(oversight_level):
        return 0

    state_dir = _get_state_dir_for_task(task_id)
    _check_spec_overwrite(state_dir)

    diff = _get_diff()
    spec = _read_spec(state_dir)

    payload = JudgePayload(
        diff=diff,
        spec=spec,
        harness_rules=_read_harness_rules(),
        existing_code="",
        feature_path=_read_feature_path(state_dir),
        task_id=task_id,
    )

    judge = HarnessJudge()
    result = judge.evaluate(payload)

    # If judge returned "skipped" (timeout, parse error, etc.), record as judge_error
    verdict = result.verdict
    if verdict == "skipped":
        verdict = "judge_error"

    router.handle(oversight_level, result, state_dir)

    if TelemetryStore is not None:
        try:
            store = TelemetryStore()
            store.record({
                "task_id": task_id,
                "judge_verdict": verdict,
                "judge_categories_failed": json.dumps(result.fail_reasons),
                "lob_violations": 1 if result.lob_violation else 0,
                "duplication_detected": result.duplication,
                "type_contract_violations": 1 if result.type_contract_violation else 0,
                "unjustified_complexity": result.unjustified_complexity,
                "naming_consistency_score": result.naming_consistency_score,
                "edge_case_coverage": result.edge_case_coverage,
            })
        except Exception:
            pass

    print(
        f"[devflow:boundary-judge] evaluated {task_id} → {verdict.upper()}",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    try:
        read_hook_stdin()  # consume stdin (required by hook protocol)
        return run()
    except Exception as exc:
        print(f"[devflow:boundary-judge] error: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
