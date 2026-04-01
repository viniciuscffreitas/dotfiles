"""
PreToolUse hook — Task Risk Profiler.

Matcher: Bash (git / write operations).
Reads context from project-profile.json and active-spec.json, runs the
TaskRiskProfiler, writes risk-profile.json to state dir, logs to TelemetryStore,
and prints the oversight level for Claude Code to consume.

Exit 0 always — this hook is informational, never blocking.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# Allow imports from project root and risk package
_DEVFLOW_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_DEVFLOW_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from _util import get_session_id, get_state_dir
from risk.profiler import TaskRiskProfiler

# TelemetryStore imported lazily so the hook survives if telemetry/ is missing
try:
    from telemetry.store import TelemetryStore
except ImportError:
    TelemetryStore = None  # type: ignore[assignment,misc]


def _get_state_dir() -> Path:
    return get_state_dir()


def _load_context(state_dir: Path) -> dict:
    """Build context dict from available devflow state files and git."""
    ctx: dict = {}

    # --- stack from project-profile.json ---
    profile_path = state_dir / "project-profile.json"
    if profile_path.exists():
        try:
            profile = json.loads(profile_path.read_text())
            raw_stack = (profile.get("toolchain") or "").lower()
            if "typescript" in raw_stack or "nodejs" in raw_stack or "node" in raw_stack:
                ctx["stack"] = "typescript"
            elif "python" in raw_stack:
                ctx["stack"] = "python"
            elif "flutter" in raw_stack or "dart" in raw_stack:
                ctx["stack"] = "dart"
            else:
                ctx["stack"] = "other" if raw_stack else "other"

            # typed_language: TypeScript, Dart, Python with type hints → True
            ctx["typed_language"] = ctx.get("stack") in ("typescript", "dart", "python")
        except (json.JSONDecodeError, OSError):
            pass

    ctx.setdefault("stack", "other")
    ctx.setdefault("typed_language", False)

    # --- task_complexity from active-spec.json ---
    spec_path = state_dir / "active-spec.json"
    if spec_path.exists():
        try:
            spec = json.loads(spec_path.read_text())
            plan = str(spec.get("plan_path") or "")
            if len(plan) > 200:
                ctx["task_complexity"] = "complex"
            elif len(plan) > 50:
                ctx["task_complexity"] = "simple"
            else:
                ctx["task_complexity"] = "trivial"
        except (json.JSONDecodeError, OSError):
            pass

    ctx.setdefault("task_complexity", "simple")

    # --- files_to_modify from git diff ---
    try:
        result = subprocess.run(
            ["git", "diff", "--stat", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        lines = [l for l in result.stdout.splitlines() if "|" in l]
        ctx["files_to_modify"] = lines
    except Exception:
        ctx["files_to_modify"] = []

    # --- coverage heuristic: presence of coverage report ---
    coverage_xml = Path.cwd() / "coverage.xml"
    coverage_dir = Path.cwd() / "htmlcov"
    if coverage_xml.exists() or coverage_dir.exists():
        ctx["test_coverage"] = "medium"  # has coverage tooling
    else:
        ctx["test_coverage"] = "low"

    # --- conservative defaults for unmeasurable signals ---
    ctx.setdefault("context_coverage", "partial")
    ctx.setdefault("codebase_health", "mixed")
    ctx.setdefault("is_production", False)
    ctx.setdefault("has_external_dependency", False)
    ctx.setdefault("has_e2e", False)

    return ctx


def run(state_dir: Path) -> None:
    ctx = _load_context(state_dir)
    profiler = TaskRiskProfiler()
    profile = profiler.profile(ctx)

    # Write risk-profile.json
    risk_file = state_dir / "risk-profile.json"
    risk_file.write_text(json.dumps({
        "oversight_level": profile.oversight_level.value,
        "probability": round(profile.probability, 4),
        "impact": round(profile.impact, 4),
        "detectability": round(profile.detectability, 4),
        "factors": profile.factors,
    }, indent=2))

    # Log to TelemetryStore (upsert — creates or updates the session record)
    store_cls = TelemetryStore
    if store_cls is not None:
        try:
            store = store_cls()
            store.record({
                "task_id": get_session_id(),
                "probability_score": profile.probability,
                "impact_score": profile.impact,
                "detectability_score": profile.detectability,
                "oversight_level": profile.oversight_level.value,
            })
        except Exception:
            pass

    # Print for Claude Code context
    print(
        f"[devflow:risk] oversight={profile.oversight_level.value.upper()} "
        f"probability={profile.probability:.2f} "
        f"impact={profile.impact:.2f} "
        f"detectability={profile.detectability:.2f}"
    )


def main() -> int:
    try:
        run(_get_state_dir())
    except Exception as exc:
        print(f"[devflow:risk] error: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
