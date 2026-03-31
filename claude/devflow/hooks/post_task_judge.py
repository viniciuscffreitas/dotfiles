"""
Stop hook — LLM-as-judge orchestrator.

Runs after a task completes. Reads oversight_level from risk-profile.json,
evaluates the diff via HarnessJudge, routes result through JudgeRouter,
updates TelemetryStore, and exits with the router's exit code.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_DEVFLOW_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_DEVFLOW_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

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


def run(state_dir: Path) -> int:
    state_dir = Path(state_dir)

    # Read oversight_level
    risk_path = state_dir / "risk-profile.json"
    oversight_level = "standard"
    if risk_path.exists():
        try:
            risk = json.loads(risk_path.read_text())
            oversight_level = risk.get("oversight_level", "standard")
        except (json.JSONDecodeError, OSError):
            pass

    router = JudgeRouter()

    if not router.should_run(oversight_level):
        print("[devflow:judge] skipped (vibe)")
        return 0

    # Build payload
    diff = _get_diff()
    task_id = get_session_id()

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

    # Route
    exit_code = router.handle(oversight_level, result, state_dir)

    # Telemetry
    store_cls = TelemetryStore
    if store_cls is not None:
        try:
            store = store_cls()
            store.record({
                "task_id": task_id,
                "judge_verdict": result.verdict,
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
    try:
        return run(_get_state_dir())
    except Exception as exc:
        print(f"[devflow:judge] error: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
