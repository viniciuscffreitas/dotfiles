"""
Stop hook — LLM-as-judge orchestrator.

Runs after a task completes. Reads oversight_level from risk-profile.json,
evaluates the diff via HarnessJudge, routes result through JudgeRouter,
updates TelemetryStore, and exits with the router's exit code.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_DEVFLOW_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_DEVFLOW_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

# Skip evaluation when running inside a Paperweight subprocess.
# Paperweight sets PAPERWEIGHT_RUN_ID for all claude -p calls it dispatches.
# Without this guard, post_task_judge fires after EVERY pipeline phase
# instead of once at the end of the complete task.
import os as _os
if _os.environ.get("PAPERWEIGHT_RUN_ID"):
    sys.exit(0)

from _util import get_session_id, get_state_dir
from judge.evaluator import HarnessJudge, JudgePayload
from judge.router import JudgeRouter

try:
    from telemetry.store import TelemetryStore
except ImportError:
    TelemetryStore = None  # type: ignore[assignment,misc]


def _get_state_dir() -> Path:
    return get_state_dir()


def _get_diff() -> str:
    """Return git diff HEAD~1, falling back to git diff (unstaged)."""
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
        plan_path = spec.get("plan_path", "")
        if plan_path and not plan_path.startswith("/"):
            candidate = _DEVFLOW_ROOT / plan_path
            if candidate.exists():
                return candidate.read_text()
        return str(plan_path)
    except (json.JSONDecodeError, OSError):
        return ""


def _read_harness_rules() -> list:
    claude_md = Path.home() / ".claude" / "CLAUDE.md"
    if not claude_md.exists():
        return []
    try:
        lines = claude_md.read_text().splitlines()[:50]
        return [l for l in lines if l.strip()]
    except OSError:
        return []


def _read_existing_code(diff: str) -> str:
    """Read first 100 lines of each file modified in the diff."""
    parts = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            file_path = line[6:].strip()
            candidate = Path(file_path)
            if not candidate.exists():
                candidate = Path.cwd() / file_path
            if candidate.exists():
                try:
                    content_lines = candidate.read_text().splitlines()[:100]
                    parts.append(f"# {file_path}\n" + "\n".join(content_lines))
                except OSError:
                    pass
    return "\n\n".join(parts)


def _read_feature_path(state_dir: Path) -> str:
    profile_path = state_dir / "project-profile.json"
    if profile_path.exists():
        try:
            profile = json.loads(profile_path.read_text())
            return profile.get("feature_path") or "."
        except (json.JSONDecodeError, OSError):
            pass
    return "."


def _is_already_judged(task_id: str, store=None) -> bool:
    """Check if this task already has a judge_verdict in TelemetryStore.

    Accepts an optional store to avoid creating a second TelemetryStore()
    instance when called from run() which already holds one.
    """
    if TelemetryStore is None:
        return False
    try:
        from contextlib import closing
        s = store if store is not None else TelemetryStore()
        with closing(s._connect()) as conn:
            conn.execute("PRAGMA busy_timeout = 3000")
            row = conn.execute(
                "SELECT judge_verdict FROM task_executions WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return row is not None and row["judge_verdict"] is not None
    except Exception:
        return False


def run(state_dir: Path) -> int:
    state_dir = Path(state_dir)

    # Read oversight_level — default to "strict" when profile absent (fail-safe)
    risk_path = state_dir / "risk-profile.json"
    oversight_level = "strict"
    if risk_path.exists():
        try:
            risk = json.loads(risk_path.read_text())
            oversight_level = risk.get("oversight_level", "strict")
        except (json.JSONDecodeError, OSError):
            pass

    router = JudgeRouter()

    if not router.should_run(oversight_level):
        print("[devflow:judge] skipped (vibe)")
        return 0

    task_id = get_session_id()

    # Build store once — reused for both the duplicate check and the verdict write
    store = None
    if TelemetryStore is not None:
        try:
            store = TelemetryStore()
        except Exception:
            pass

    # Double-judging guard: skip if boundary judge already evaluated this task
    if _is_already_judged(task_id, store=store):
        print("[devflow:judge] skipped (already judged by boundary judge)")
        return 0

    # Build payload
    diff = _get_diff()

    payload = JudgePayload(
        diff=diff,
        spec=_read_spec(state_dir),
        harness_rules=_read_harness_rules(),
        existing_code=_read_existing_code(diff),
        feature_path=_read_feature_path(state_dir),
        task_id=task_id,
    )

    # Evaluate
    judge = HarnessJudge()
    result = judge.evaluate(payload)

    # If judge returned "skipped" (timeout, parse error), record as judge_error
    verdict = result.verdict
    if verdict == "skipped":
        verdict = "judge_error"

    # Route
    exit_code = router.handle(oversight_level, result, state_dir)

    # Telemetry — reuse store created above
    if store is not None:
        try:
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

    return exit_code


def main() -> int:
    if os.environ.get("DEVFLOW_JUDGE_SUBPROCESS") == "1":
        print("[devflow:judge] skipped (subprocess guard)", file=sys.stderr)
        return 0
    try:
        return run(_get_state_dir())
    except Exception as exc:
        print(f"[devflow:judge] error: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
