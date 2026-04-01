"""
End-to-end integration tests for the complete devflow harness.

Core principle: exercises real data flow across module boundaries.
Mocks only external I/O: subprocess.run for 'claude -p' calls.
Uses real SQLite TelemetryStore in tmp_path.
Never mocks internal components.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from analysis.context_anxiety import ContextAnxietyDetector
from analysis.harness_health import HarnessHealthChecker
from analysis.weekly_report import WeeklyIntelligenceReport, WeeklyReportGenerator
from judge.evaluator import HarnessJudge, JudgePayload, JudgeResult
from judge.router import JudgeRouter
from linters.engine import LinterEngine
from risk.profiler import OversightLevel, TaskRiskProfiler
from telemetry.store import TelemetryStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts(days_ago: int = 0) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(days=days_ago)).isoformat()


def _make_judge_result(verdict: str, task_id: str = "t1") -> JudgeResult:
    return JudgeResult(
        task_id=task_id,
        verdict=verdict,
        lob_violation=(verdict == "fail"),
        lob_evidence="cross-feature import" if verdict == "fail" else None,
        duplication=False,
        duplication_evidence=None,
        type_contract_violation=False,
        type_contract_evidence=None,
        unjustified_complexity=False,
        complexity_evidence=None,
        naming_consistency_score=1.0,
        naming_evidence=None,
        edge_case_coverage="adequate",
        spec_fulfilled="yes" if verdict != "fail" else "no",
        spec_evidence=None,
        fail_reasons=["lob_violation"] if verdict == "fail" else [],
        raw_response=None,
    )


_PASS_JSON = json.dumps({
    "lob_violation": {"result": "no", "evidence": None},
    "duplication": {"result": "no", "evidence": None},
    "type_contract_violation": {"result": "na", "evidence": None},
    "unjustified_complexity": {"result": "no", "evidence": None},
    "naming_consistency": {"score": 0.9, "evidence": None},
    "edge_case_coverage": {"level": "adequate", "missing": []},
    "spec_fulfilled": {"result": "yes", "evidence": None},
    "overall_verdict": "pass",
    "fail_reasons": [],
})


# ---------------------------------------------------------------------------
# Scenario 1: Full task lifecycle (happy path)
# ---------------------------------------------------------------------------


class TestFullTaskLifecycle:
    def test_happy_path_complete_lifecycle(self, tmp_path):
        # 1. RiskProfiler scores a task producing standard oversight
        profiler = TaskRiskProfiler()
        ctx = {
            "stack": "python",
            "context_coverage": "partial",
            "task_complexity": "simple",
            "codebase_health": "mixed",
            "is_production": False,
            "files_to_modify": ["hooks/foo.py"],
            "test_coverage": "medium",
            "typed_language": True,
            "has_e2e": False,
            "has_external_dependency": False,
        }
        profile = profiler.profile(ctx)
        assert profile.oversight_level == OversightLevel.STANDARD

        # Write risk-profile.json (as pre_task_profiler hook does)
        risk_path = tmp_path / "risk-profile.json"
        risk_path.write_text(json.dumps({
            "oversight_level": profile.oversight_level.value,
            "probability": round(profile.probability, 4),
            "impact": round(profile.impact, 4),
            "detectability": round(profile.detectability, 4),
        }))

        # 2. ContextFirewall: standard oversight → no delegation
        oversight_level = json.loads(risk_path.read_text())["oversight_level"]
        assert oversight_level == "standard"  # firewall skips delegation for non-strict

        # 3. HarnessJudge evaluates the diff (subprocess mocked — external I/O)
        task_id = "integration-scenario-1"
        payload = JudgePayload(
            diff="diff --git a/hooks/foo.py\n+def bar(): pass",
            spec="add bar function to hooks/foo.py",
            harness_rules=["TDD required"],
            existing_code="def foo(): pass",
            feature_path="hooks/",
            task_id=task_id,
        )
        with patch("judge.evaluator.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=_PASS_JSON, stderr="")
            judge = HarnessJudge()
            result = judge.evaluate(payload)

        assert result.verdict == "pass"

        # 4. JudgeRouter handles result → writes judge-result.json
        router = JudgeRouter()
        exit_code = router.handle(oversight_level, result, tmp_path)

        # 5. TelemetryStore records the session (real SQLite in tmp_path)
        store = TelemetryStore(db_path=tmp_path / "devflow.db")
        store.record({
            "task_id": task_id,
            "judge_verdict": result.verdict,
            "oversight_level": oversight_level,
            "probability_score": profile.probability,
        })

        # 6. Verify system boundaries
        assert exit_code == 0  # task not blocked

        result_data = json.loads((tmp_path / "judge-result.json").read_text())
        assert result_data["verdict"] == "pass"
        assert result_data["oversight_level"] == "standard"

        sessions = store.get_recent(n=10)
        assert len(sessions) == 1
        assert sessions[0]["judge_verdict"] == "pass"
        assert sessions[0]["oversight_level"] == "standard"
        assert not (tmp_path / "pending_reviews").exists()


# ---------------------------------------------------------------------------
# Scenario 2: High-risk task with blocking (strict path)
# ---------------------------------------------------------------------------


class TestHighRiskBlocking:
    def test_strict_fail_blocks_and_records(self, tmp_path):
        # 1. Write risk-profile.json with strict oversight directly
        (tmp_path / "risk-profile.json").write_text(json.dumps({
            "oversight_level": "strict",
            "probability": 0.6,
            "impact": 0.8,
            "detectability": 0.5,
        }))

        # 2. HarnessJudge returns fail (subprocess mocked)
        task_id = "integration-scenario-2"
        payload = JudgePayload(
            diff="diff --git a/lib/features/auth/login.dart b/lib/features/auth/login.dart\n+import 'package:app/features/user/user.dart';",
            spec="add login screen",
            harness_rules=["no cross-feature imports"],
            existing_code="",
            feature_path="lib/features/auth/",
            task_id=task_id,
        )
        fail_json = json.dumps({
            "lob_violation": {"result": "yes", "evidence": "cross-feature import auth→user"},
            "duplication": {"result": "no", "evidence": None},
            "type_contract_violation": {"result": "no", "evidence": None},
            "unjustified_complexity": {"result": "no", "evidence": None},
            "naming_consistency": {"score": 0.9, "evidence": None},
            "edge_case_coverage": {"level": "adequate", "missing": []},
            "spec_fulfilled": {"result": "no", "evidence": "lob violation blocks spec"},
            "overall_verdict": "fail",
            "fail_reasons": ["lob_violation"],
        })
        with patch("judge.evaluator.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=fail_json, stderr="")
            judge = HarnessJudge()
            result = judge.evaluate(payload)

        assert result.verdict == "fail"

        # 3. JudgeRouter blocks on strict+fail
        router = JudgeRouter()
        exit_code = router.handle("strict", result, tmp_path)

        # 4. TelemetryStore records the session
        store = TelemetryStore(db_path=tmp_path / "devflow.db")
        store.record({
            "task_id": task_id,
            "judge_verdict": result.verdict,
            "oversight_level": "strict",
            "lob_violations": 1,
        })

        # 5. Verify system boundaries
        assert exit_code == 1  # blocked

        sessions = store.get_recent(n=10)
        assert sessions[0]["judge_verdict"] == "fail"

        # pending_reviews/ only created for human_review, NOT for strict
        assert not (tmp_path / "pending_reviews").exists()

        result_data = json.loads((tmp_path / "judge-result.json").read_text())
        assert result_data["oversight_level"] == "strict"


# ---------------------------------------------------------------------------
# Scenario 3: Context anxiety → weekly report pipeline
# ---------------------------------------------------------------------------


class TestAnxietyToWeeklyReport:
    def test_anxiety_pipeline_end_to_end(self, tmp_path):
        store = TelemetryStore(db_path=tmp_path / "devflow.db")
        now = _ts(0)

        # 1. Insert 5 synthetic sessions with varying anxiety proxies
        # context_tokens_at_first_action → anxiety_score = tokens / 200_000
        sessions_data = [
            # 2 pass, low anxiety (~0.2 → 40k tokens)
            {"task_id": "a1", "timestamp": now, "judge_verdict": "pass", "context_tokens_at_first_action": 40_000},
            {"task_id": "a2", "timestamp": now, "judge_verdict": "pass", "context_tokens_at_first_action": 40_000},
            # 2 fail, high anxiety (~0.75 → 150k tokens)
            {"task_id": "a3", "timestamp": now, "judge_verdict": "fail", "context_tokens_at_first_action": 150_000},
            {"task_id": "a4", "timestamp": now, "judge_verdict": "fail", "context_tokens_at_first_action": 150_000},
            # 1 pass, medium anxiety (~0.5 → 100k tokens)
            {"task_id": "a5", "timestamp": now, "judge_verdict": "pass", "context_tokens_at_first_action": 100_000},
        ]
        for s in sessions_data:
            store.record(s)

        # 2. Run ContextAnxietyDetector (sessions with tokens > 60k threshold)
        detector = ContextAnxietyDetector()
        anxiety_report = detector.analyze_store(store)
        assert anxiety_report.sessions_analyzed == 3  # only sessions with tokens > 60k threshold

        # 3. Run WeeklyReportGenerator
        skills_dir = tmp_path / "skills"
        hooks_dir = tmp_path / "hooks"
        skills_dir.mkdir()
        hooks_dir.mkdir()
        gen = WeeklyReportGenerator()
        report = gen.generate(store, skills_dir, hooks_dir)

        # 4. Verify WeeklyIntelligenceReport system boundaries
        assert isinstance(report, WeeklyIntelligenceReport)
        assert report.signals.sessions_total == 5
        assert abs(report.signals.judge_fail_rate - 0.4) < 0.05  # 2 fails out of 5
        assert report.signals.mean_anxiety_score > 0  # anxiety computed from tokens
        # fail rate 0.4 > 0.3 threshold → HIGH tune_hook recommendation
        assert any(r.priority == "high" for r in report.recommendations)
        assert report.next_prompt is not None


# ---------------------------------------------------------------------------
# Scenario 4: Linter → telemetry integration
# ---------------------------------------------------------------------------


class TestLinterToTelemetry:
    def test_linter_violation_flows_to_report(self, tmp_path):
        # 1. Synthetic diff with a Dart cross-feature import violation
        diff = (
            "diff --git a/lib/features/auth/login.dart b/lib/features/auth/login.dart\n"
            "--- a/lib/features/auth/login.dart\n"
            "+++ b/lib/features/auth/login.dart\n"
            "@@ -1,3 +1,4 @@\n"
            " import 'package:flutter/material.dart';\n"
            "+import 'package:myapp/features/user/profile.dart';\n"
        )

        # 2. Run LinterEngine against the diff
        engine = LinterEngine()
        results = engine.run_all(diff, tmp_path)

        # 3. import_boundary linter must flag the violation
        import_result = next(r for r in results if r.linter_name == "import_boundary")
        assert import_result.passed is False
        assert len(import_result.violations) >= 1
        assert "auth" in import_result.violations[0]
        assert "user" in import_result.violations[0]

        # 4. Insert session recording the violation into TelemetryStore
        store = TelemetryStore(db_path=tmp_path / "devflow.db")
        store.record({
            "task_id": "linter-session-01",
            "timestamp": _ts(0),
            "judge_verdict": "fail",
            "lob_violations": 5,  # above the >3 threshold for recommendation
            "judge_categories_failed": "lob_violation",
        })

        # 5. Run HarnessHealthChecker (no skills/hooks dirs needed for this check)
        skills_dir = tmp_path / "skills"
        hooks_dir = tmp_path / "hooks"
        skills_dir.mkdir()
        hooks_dir.mkdir()
        checker = HarnessHealthChecker()
        health = checker.check(store, skills_dir, hooks_dir)
        assert isinstance(health.overall_verdict, str)

        # 6. WeeklyReportGenerator: LoB violations exceed threshold → add_rule recommendation
        gen = WeeklyReportGenerator()
        report = gen.generate(store, skills_dir, hooks_dir)

        lob_recs = [
            r for r in report.recommendations
            if "LoB" in r.action or "boundary" in r.action.lower()
        ]
        assert len(lob_recs) >= 1
        assert report.signals.top_lob_violations == 5


# ---------------------------------------------------------------------------
# Scenario 5: Harness health → simplification pipeline
# ---------------------------------------------------------------------------


class TestHarnessHealthSimplification:
    def test_unused_skills_generate_recommendations(self, tmp_path):
        # 1. Create tmp skills_dir with 3 .md skill files
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        for name in ("skill-alpha", "skill-beta", "skill-gamma"):
            (skills_dir / f"{name}.md").write_text(f"# {name}\nNo content.")

        # 2. Create tmp hooks_dir with 2 .py hook files
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        for name in ("pre_task", "post_task"):
            (hooks_dir / f"{name}.py").write_text(f"# {name}\ndef main(): pass\n")

        # 3. Fresh TelemetryStore — no sessions → all skills have 0 usage
        store = TelemetryStore(db_path=tmp_path / "devflow.db")

        # 4. Run HarnessHealthChecker
        checker = HarnessHealthChecker()
        report = checker.check(store, skills_dir, hooks_dir)

        # 5. Verify system boundaries
        skill_verdicts = {s.skill_name: s.verdict for s in report.skill_health}
        assert all(v == "unused" for v in skill_verdicts.values())
        assert len(skill_verdicts) == 3

        # All unused skills appear in simplification candidates
        assert len(report.simplification_candidates) >= 3
        unused_candidates = [c for c in report.simplification_candidates if "never used" in c]
        assert len(unused_candidates) == 3

        # 6. Run WeeklyReportGenerator with same store
        gen = WeeklyReportGenerator()
        weekly = gen.generate(store, skills_dir, hooks_dir)
        assert isinstance(weekly, WeeklyIntelligenceReport)

        # 7. WeeklyReport reflects harness state from health check
        # Sessions = 0 → "low session count" LOW recommendation appears
        low_recs = [r for r in weekly.recommendations if r.priority == "low"]
        assert len(low_recs) >= 1
        # Health verdict is propagated to signals
        assert weekly.signals.harness_health in ("healthy", "degraded", "critical")
