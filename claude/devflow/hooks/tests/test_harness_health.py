"""Tests for Harness Health tracker."""
from __future__ import annotations

import contextlib
import io
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from telemetry.store import TelemetryStore
from analysis.harness_health import (
    HarnessHealthChecker,
    HarnessHealthReport,
    HookHealth,
    SkillHealth,
)


# ---------------------------------------------------------------------------
# TelemetryStore.get_skill_usage
# ---------------------------------------------------------------------------

def test_get_skill_usage_unknown_skill_returns_zeros(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    result = store.get_skill_usage("nonexistent-skill")
    assert result == {"last_used_at": None, "usage_count": 0}


def test_get_skill_usage_counts_matching_sessions(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    ts = datetime.now(tz=timezone.utc).isoformat()
    store.record({"task_id": "t1", "skills_loaded": "devflow-spec, my-skill", "timestamp": ts})
    store.record({"task_id": "t2", "skills_loaded": "my-skill, other", "timestamp": ts})
    store.record({"task_id": "t3", "skills_loaded": "other-skill"})
    result = store.get_skill_usage("my-skill")
    assert result["usage_count"] == 2
    assert result["last_used_at"] == ts


# ---------------------------------------------------------------------------
# TelemetryStore.get_hook_stats
# ---------------------------------------------------------------------------

def test_get_hook_stats_unknown_hook_returns_zeroes(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    result = store.get_hook_stats("nonexistent-hook")
    assert result["avg_execution_ms"] is None
    assert result["error_rate"] == 0.0
    assert result["last_triggered_at"] is None


def test_get_hook_stats_unknown_hook_is_structurally_correct(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    result = store.get_hook_stats("completely-unknown-hook-xyz")
    assert result == {"avg_execution_ms": None, "error_rate": 0.0, "last_triggered_at": None}


def test_get_hook_stats_computes_error_rate_from_records(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    ts = datetime.now(tz=timezone.utc).isoformat()
    # 3 sessions where "my_hook" is in rules_triggered, 1 failing
    store.record({"task_id": "h1", "rules_triggered": "my_hook", "judge_verdict": "pass", "timestamp": ts})
    store.record({"task_id": "h2", "rules_triggered": "my_hook", "judge_verdict": "fail", "timestamp": ts})
    store.record({"task_id": "h3", "rules_triggered": "my_hook", "judge_verdict": "pass", "timestamp": ts})
    store.record({"task_id": "h4", "rules_triggered": "other_hook", "judge_verdict": "fail"})
    result = store.get_hook_stats("my_hook")
    assert abs(result["error_rate"] - 1 / 3) < 0.01
    assert result["last_triggered_at"] == ts
    assert result["avg_execution_ms"] is None


def test_get_hook_stats_recognizes_post_task_judge_via_verdict(tmp_path):
    """post_task_judge doesn't populate rules_triggered — its invocations are
    recognizable by judge_verdict being non-null."""
    store = TelemetryStore(db_path=tmp_path / "test.db")
    ts = datetime.now(tz=timezone.utc).isoformat()
    store.record({"task_id": "j1", "judge_verdict": "pass", "timestamp": ts})
    store.record({"task_id": "j2", "judge_verdict": "fail", "timestamp": ts})
    store.record({"task_id": "j3", "judge_verdict": "judge_error", "timestamp": ts})
    store.record({"task_id": "other1"})  # unrelated row
    result = store.get_hook_stats("post_task_judge")
    assert result["last_triggered_at"] == ts
    # judge_error + fail both count as "not pass/warn"
    assert result["error_rate"] > 0.0


def test_get_hook_stats_recognizes_pre_task_firewall_via_column(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    ts = datetime.now(tz=timezone.utc).isoformat()
    store.record({"task_id": "f1", "firewall_delegated": True, "firewall_success": True, "timestamp": ts})
    store.record({"task_id": "f2", "firewall_delegated": True, "firewall_success": False, "timestamp": ts})
    store.record({"task_id": "other"})
    result = store.get_hook_stats("pre_task_firewall")
    assert result["last_triggered_at"] == ts
    assert abs(result["error_rate"] - 0.5) < 0.01


def test_get_hook_stats_recognizes_cost_tracker_via_column(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    ts = datetime.now(tz=timezone.utc).isoformat()
    store.record({"task_id": "c1", "cost_usd": 0.02, "timestamp": ts})
    store.record({"task_id": "c2", "estimated_usd": 0.05, "timestamp": ts})
    store.record({"task_id": "other"})
    result = store.get_hook_stats("cost_tracker")
    assert result["last_triggered_at"] == ts


def test_get_hook_stats_recognizes_instinct_capture_via_count(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    ts = datetime.now(tz=timezone.utc).isoformat()
    store.record({"task_id": "i1", "instincts_captured_count": 2, "timestamp": ts})
    store.record({"task_id": "i2", "instincts_captured_count": 0, "timestamp": ts})
    store.record({"task_id": "other"})
    result = store.get_hook_stats("instinct_capture")
    assert result["last_triggered_at"] == ts


def test_get_hook_stats_recognizes_pre_task_profiler_via_probability_score(tmp_path):
    """pre_task_profiler writes probability_score — signal it via that column
    instead of rules_triggered LIKE (which profiler doesn't self-populate)."""
    store = TelemetryStore(db_path=tmp_path / "test.db")
    ts = datetime.now(tz=timezone.utc).isoformat()
    store.record({"task_id": "p1", "probability_score": 0.3, "timestamp": ts})
    store.record({"task_id": "p2", "probability_score": 0.8, "timestamp": ts})
    store.record({"task_id": "other"})
    result = store.get_hook_stats("pre_task_profiler")
    assert result["last_triggered_at"] == ts


def test_get_hook_stats_recognizes_task_boundary_judge_via_verdict(tmp_path):
    """task_boundary_judge shares judge_verdict signal with post_task_judge —
    harness_health must surface it as fired, not idle."""
    store = TelemetryStore(db_path=tmp_path / "test.db")
    ts = datetime.now(tz=timezone.utc).isoformat()
    store.record({"task_id": "b1", "judge_verdict": "pass", "timestamp": ts})
    store.record({"task_id": "b2", "judge_verdict": "fail", "timestamp": ts})
    store.record({"task_id": "other"})
    result = store.get_hook_stats("task_boundary_judge")
    assert result["last_triggered_at"] == ts
    assert result["error_rate"] > 0.0


# ---------------------------------------------------------------------------
# SkillHealth verdict rules
# ---------------------------------------------------------------------------

def _active_skill(name: str = "my-skill") -> "SkillHealth":
    return SkillHealth(
        skill_name=name,
        last_used_at=datetime.now(tz=timezone.utc).isoformat(),
        usage_count=5,
        days_since_used=1,
        verdict="active",
        recommendation="Keep",
    )


def _stale_skill(name: str = "old-skill", days: int = 20) -> "SkillHealth":
    ts = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
    return SkillHealth(
        skill_name=name,
        last_used_at=ts,
        usage_count=2,
        days_since_used=days,
        verdict="stale",
        recommendation=f"Review or remove — last used {days} days ago",
    )


def _unused_skill(name: str = "dead-skill") -> "SkillHealth":
    return SkillHealth(
        skill_name=name,
        last_used_at=None,
        usage_count=0,
        days_since_used=None,
        verdict="unused",
        recommendation="Consider removing — no usage recorded",
    )


def test_skill_health_verdict_active():
    skill = _active_skill()
    assert skill.verdict == "active"
    assert skill.recommendation == "Keep"


def test_skill_health_verdict_stale():
    skill = _stale_skill(days=20)
    assert skill.verdict == "stale"
    assert "20 days" in skill.recommendation


def test_skill_health_verdict_unused():
    skill = _unused_skill()
    assert skill.verdict == "unused"
    assert "no usage" in skill.recommendation.lower()


def test_skill_health_recommendation_contains_skill_name():
    skill = _stale_skill(name="special-skill", days=30)
    assert skill.skill_name == "special-skill"
    assert "30 days" in skill.recommendation


# ---------------------------------------------------------------------------
# HookHealth verdict rules
# ---------------------------------------------------------------------------

def _healthy_hook(name: str = "good-hook") -> "HookHealth":
    return HookHealth(
        hook_name=name,
        avg_execution_ms=200.0,
        error_rate=0.0,
        last_triggered_at=datetime.now(tz=timezone.utc).isoformat(),
        verdict="healthy",
        recommendation="OK",
    )


def _broken_hook(name: str = "bad-hook", error_rate: float = 0.5) -> "HookHealth":
    return HookHealth(
        hook_name=name,
        avg_execution_ms=100.0,
        error_rate=error_rate,
        last_triggered_at=datetime.now(tz=timezone.utc).isoformat(),
        verdict="broken",
        recommendation=f"Investigate — {error_rate:.0%} error rate",
    )


def _slow_hook(name: str = "slow-hook", avg_ms: float = 8000.0) -> "HookHealth":
    return HookHealth(
        hook_name=name,
        avg_execution_ms=avg_ms,
        error_rate=0.0,
        last_triggered_at=datetime.now(tz=timezone.utc).isoformat(),
        verdict="slow",
        recommendation=f"Optimize — avg {avg_ms:.0f}ms exceeds 5000ms",
    )


def _idle_hook(name: str = "idle-hook") -> "HookHealth":
    return HookHealth(
        hook_name=name,
        avg_execution_ms=None,
        error_rate=0.0,
        last_triggered_at=None,
        verdict="idle",
        recommendation="Verify hook is registered in CLAUDE.md",
    )


def test_hook_health_verdict_healthy():
    hook = _healthy_hook()
    assert hook.verdict == "healthy"
    assert hook.recommendation == "OK"


def test_hook_health_verdict_broken_when_high_error_rate():
    hook = _broken_hook(error_rate=0.5)
    assert hook.verdict == "broken"
    assert "50%" in hook.recommendation


def test_hook_health_verdict_slow_when_avg_ms_exceeded():
    hook = _slow_hook(avg_ms=8000.0)
    assert hook.verdict == "slow"
    assert "8000ms" in hook.recommendation


def test_hook_health_verdict_idle_when_never_triggered():
    hook = _idle_hook()
    assert hook.verdict == "idle"
    assert hook.last_triggered_at is None
    assert "CLAUDE.md" in hook.recommendation


# ---------------------------------------------------------------------------
# _compute_complexity_score
# ---------------------------------------------------------------------------

def test_complexity_score_all_healthy_is_near_zero():
    checker = HarnessHealthChecker()
    skills = [_active_skill("s1"), _active_skill("s2")]
    hooks = [_healthy_hook("h1"), _healthy_hook("h2")]
    score = checker._compute_complexity_score(skills, hooks)
    assert score < 0.1


def test_complexity_score_all_stale_broken_is_near_one():
    checker = HarnessHealthChecker()
    skills = [_stale_skill("s1"), _stale_skill("s2")]
    hooks = [_broken_hook("h1"), _broken_hook("h2")]
    score = checker._compute_complexity_score(skills, hooks)
    assert score > 0.9


def test_complexity_score_mixed_is_weighted_average():
    checker = HarnessHealthChecker()
    # 1 stale out of 2 skills → stale_ratio = 0.5
    # 0 broken out of 2 hooks → broken_ratio = 0.0
    # score = (0.5 * 0.5) + (0.0 * 0.5) = 0.25
    skills = [_stale_skill("s1"), _active_skill("s2")]
    hooks = [_healthy_hook("h1"), _healthy_hook("h2")]
    score = checker._compute_complexity_score(skills, hooks)
    assert abs(score - 0.25) < 0.01


def test_complexity_score_clamped_to_zero_one():
    checker = HarnessHealthChecker()
    assert checker._compute_complexity_score([], []) == 0.0


# ---------------------------------------------------------------------------
# _check_skills
# ---------------------------------------------------------------------------

def test_check_skills_discovers_md_files(tmp_path):
    (tmp_path / "skill-a.md").write_text("content")
    (tmp_path / "skill-b.md").write_text("content")
    (tmp_path / "not-a-skill.txt").write_text("content")

    store = MagicMock()
    store.get_skill_usage.return_value = {"last_used_at": None, "usage_count": 0}

    checker = HarnessHealthChecker()
    results = checker._check_skills(tmp_path, store)

    assert len(results) == 2
    names = {r.skill_name for r in results}
    assert names == {"skill-a", "skill-b"}


def test_check_skills_returns_skill_health_per_file(tmp_path):
    (tmp_path / "my-skill.md").write_text("content")
    ts = datetime.now(tz=timezone.utc).isoformat()

    store = MagicMock()
    store.get_skill_usage.return_value = {"last_used_at": ts, "usage_count": 3}

    checker = HarnessHealthChecker()
    results = checker._check_skills(tmp_path, store)

    assert len(results) == 1
    assert results[0].skill_name == "my-skill"
    assert results[0].usage_count == 3
    assert results[0].verdict == "active"


def test_check_skills_falls_back_gracefully_when_store_raises(tmp_path):
    (tmp_path / "skill-x.md").write_text("content")

    store = MagicMock()
    store.get_skill_usage.side_effect = Exception("DB error")

    checker = HarnessHealthChecker()
    results = checker._check_skills(tmp_path, store)

    assert len(results) == 1
    assert results[0].verdict == "unused"
    assert results[0].usage_count == 0


def test_check_skills_nonexistent_dir_returns_empty():
    store = MagicMock()
    checker = HarnessHealthChecker()
    results = checker._check_skills(Path("/nonexistent/path/xyz"), store)
    assert results == []


# ---------------------------------------------------------------------------
# _check_hooks
# ---------------------------------------------------------------------------

def test_check_hooks_discovers_py_files_excluding_init(tmp_path):
    (tmp_path / "hook_a.py").write_text("content")
    (tmp_path / "hook_b.py").write_text("content")
    (tmp_path / "__init__.py").write_text("")

    store = MagicMock()
    store.get_hook_stats.return_value = {
        "avg_execution_ms": None, "error_rate": 0.0, "last_triggered_at": None
    }

    checker = HarnessHealthChecker()
    results = checker._check_hooks(tmp_path, store)

    names = {r.hook_name for r in results}
    assert "__init__" not in names
    assert "hook_a" in names
    assert "hook_b" in names


def test_check_hooks_excludes_utility_and_cli_files(tmp_path):
    (tmp_path / "real_hook.py").write_text("content")
    (tmp_path / "_util.py").write_text("content")          # utility module
    (tmp_path / "foo_report.py").write_text("content")     # CLI tool
    (tmp_path / "__init__.py").write_text("")               # package marker

    store = MagicMock()
    store.get_hook_stats.return_value = {
        "avg_execution_ms": None, "error_rate": 0.0, "last_triggered_at": None
    }

    checker = HarnessHealthChecker()
    results = checker._check_hooks(tmp_path, store)

    names = {r.hook_name for r in results}
    assert names == {"real_hook"}


def test_check_hooks_returns_hook_health_per_file(tmp_path):
    (tmp_path / "my_hook.py").write_text("content")
    ts = datetime.now(tz=timezone.utc).isoformat()

    store = MagicMock()
    store.get_hook_stats.return_value = {
        "avg_execution_ms": 300.0, "error_rate": 0.0, "last_triggered_at": ts
    }

    checker = HarnessHealthChecker()
    results = checker._check_hooks(tmp_path, store)

    assert len(results) == 1
    assert results[0].hook_name == "my_hook"
    assert results[0].verdict == "healthy"


def test_check_hooks_falls_back_gracefully_when_store_raises(tmp_path):
    (tmp_path / "broken_hook.py").write_text("content")

    store = MagicMock()
    store.get_hook_stats.side_effect = Exception("DB error")

    checker = HarnessHealthChecker()
    results = checker._check_hooks(tmp_path, store)

    assert len(results) == 1
    assert results[0].verdict == "idle"


def test_check_hooks_nonexistent_dir_returns_empty():
    store = MagicMock()
    checker = HarnessHealthChecker()
    results = checker._check_hooks(Path("/nonexistent/path/xyz"), store)
    assert results == []


# ---------------------------------------------------------------------------
# _build_simplification_candidates
# ---------------------------------------------------------------------------

def test_simplification_candidates_empty_when_all_healthy():
    checker = HarnessHealthChecker()
    skills = [_active_skill("s1")]
    hooks = [_healthy_hook("h1")]
    result = checker._build_simplification_candidates(skills, hooks)
    assert result == []


def test_simplification_candidates_one_entry_per_unused_skill():
    checker = HarnessHealthChecker()
    skills = [_unused_skill("old-skill"), _active_skill("live-skill")]
    result = checker._build_simplification_candidates(skills, [])
    unused_entries = [c for c in result if "old-skill" in c]
    assert len(unused_entries) == 1
    assert "never used" in unused_entries[0]


def test_simplification_candidates_one_entry_per_stale_skill():
    checker = HarnessHealthChecker()
    skills = [_stale_skill("stale-skill", days=20)]
    result = checker._build_simplification_candidates(skills, [])
    assert len(result) == 1
    assert "stale-skill" in result[0]
    assert "20 days" in result[0]


def test_simplification_candidates_one_entry_per_broken_hook():
    checker = HarnessHealthChecker()
    hooks = [_broken_hook("bad-hook", error_rate=0.5)]
    result = checker._build_simplification_candidates([], hooks)
    assert len(result) == 1
    assert "bad-hook" in result[0]
    assert "50%" in result[0]


def test_simplification_candidates_one_entry_per_idle_hook():
    checker = HarnessHealthChecker()
    hooks = [_idle_hook("unregistered-hook")]
    result = checker._build_simplification_candidates([], hooks)
    assert len(result) == 1
    assert "unregistered-hook" in result[0]
    assert "CLAUDE.md" in result[0]


def test_simplification_candidates_one_entry_per_slow_hook():
    checker = HarnessHealthChecker()
    hooks = [_slow_hook("slow-hook", avg_ms=8000.0)]
    result = checker._build_simplification_candidates([], hooks)
    assert len(result) == 1
    assert "slow-hook" in result[0]
    assert "8000ms" in result[0]


# ---------------------------------------------------------------------------
# _overall_verdict
# ---------------------------------------------------------------------------

def test_overall_verdict_critical_when_broken_hook():
    checker = HarnessHealthChecker()
    assert checker._overall_verdict(0.0, 1) == "critical"
    assert checker._overall_verdict(0.9, 2) == "critical"


def test_overall_verdict_degraded_when_high_complexity_no_broken():
    checker = HarnessHealthChecker()
    assert checker._overall_verdict(0.6, 0) == "degraded"
    assert checker._overall_verdict(1.0, 0) == "degraded"


def test_overall_verdict_healthy_when_all_good():
    checker = HarnessHealthChecker()
    assert checker._overall_verdict(0.0, 0) == "healthy"
    assert checker._overall_verdict(0.5, 0) == "healthy"


# ---------------------------------------------------------------------------
# HarnessHealthChecker.check (integration)
# ---------------------------------------------------------------------------

def test_checker_check_returns_report_with_correct_counts(tmp_path):
    skills_dir = tmp_path / "skills"
    hooks_dir = tmp_path / "hooks"
    skills_dir.mkdir()
    hooks_dir.mkdir()

    (skills_dir / "active-skill.md").write_text("content")
    (skills_dir / "stale-skill.md").write_text("content")
    (skills_dir / "unused-skill.md").write_text("content")
    (hooks_dir / "good_hook.py").write_text("content")

    ts_recent = datetime.now(tz=timezone.utc).isoformat()
    ts_old = (datetime.now(tz=timezone.utc) - timedelta(days=20)).isoformat()

    store = MagicMock()

    def skill_usage(name: str) -> dict:
        if name == "active-skill":
            return {"last_used_at": ts_recent, "usage_count": 3}
        if name == "stale-skill":
            return {"last_used_at": ts_old, "usage_count": 1}
        return {"last_used_at": None, "usage_count": 0}

    store.get_skill_usage.side_effect = skill_usage
    store.get_hook_stats.return_value = {
        "avg_execution_ms": None, "error_rate": 0.0, "last_triggered_at": ts_recent
    }

    checker = HarnessHealthChecker()
    report = checker.check(store, skills_dir, hooks_dir)

    assert isinstance(report, HarnessHealthReport)
    assert report.stale_skill_count == 1
    assert report.broken_hook_count == 0
    assert report.overall_verdict == "healthy"


def test_checker_check_overall_verdict_matches_computed_inputs(tmp_path):
    skills_dir = tmp_path / "skills"
    hooks_dir = tmp_path / "hooks"
    skills_dir.mkdir()
    hooks_dir.mkdir()
    (hooks_dir / "broken_hook.py").write_text("content")

    store = MagicMock()
    store.get_skill_usage.return_value = {"last_used_at": None, "usage_count": 0}
    store.get_hook_stats.return_value = {
        "avg_execution_ms": None, "error_rate": 0.5, "last_triggered_at": None
    }

    checker = HarnessHealthChecker()
    report = checker.check(store, skills_dir, hooks_dir)

    assert report.overall_verdict == "critical"
    assert report.broken_hook_count == 1


def test_checker_check_never_raises_on_empty_dirs(tmp_path):
    store = MagicMock()
    checker = HarnessHealthChecker()
    report = checker.check(store, tmp_path / "no-skills", tmp_path / "no-hooks")
    assert isinstance(report, HarnessHealthReport)
    assert report.overall_verdict == "healthy"


def test_checker_check_never_raises_on_store_failure(tmp_path):
    skills_dir = tmp_path / "skills"
    hooks_dir = tmp_path / "hooks"
    skills_dir.mkdir()
    hooks_dir.mkdir()
    (skills_dir / "s.md").write_text("content")
    (hooks_dir / "h.py").write_text("content")

    store = MagicMock()
    store.get_skill_usage.side_effect = RuntimeError("broken")
    store.get_hook_stats.side_effect = RuntimeError("broken")

    checker = HarnessHealthChecker()
    report = checker.check(store, skills_dir, hooks_dir)
    assert isinstance(report, HarnessHealthReport)


# ---------------------------------------------------------------------------
# health_report CLI
# ---------------------------------------------------------------------------

def test_health_report_default_output_contains_prefix(tmp_path):
    import hooks.health_report as hr

    store = TelemetryStore(db_path=tmp_path / "test.db")
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        hr.main([], _store=store, _skills_dir=tmp_path / "skills", _hooks_dir=tmp_path / "hooks")
    assert "[devflow:health]" in captured.getvalue()


def test_health_report_json_outputs_valid_json_with_overall_verdict(tmp_path):
    import hooks.health_report as hr
    import json as _json

    store = TelemetryStore(db_path=tmp_path / "test.db")
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        hr.main(["--json"], _store=store, _skills_dir=tmp_path / "skills", _hooks_dir=tmp_path / "hooks")
    data = _json.loads(captured.getvalue())
    assert "overall_verdict" in data
    assert data["overall_verdict"] in ("healthy", "degraded", "critical")


def test_health_report_critical_exits_0_when_healthy(tmp_path):
    import hooks.health_report as hr

    store = TelemetryStore(db_path=tmp_path / "test.db")
    ret = hr.main(["--critical"], _store=store, _skills_dir=tmp_path / "skills", _hooks_dir=tmp_path / "hooks")
    assert ret == 0


def test_health_report_critical_exits_1_when_critical(tmp_path):
    import hooks.health_report as hr

    db = tmp_path / "test.db"
    store = TelemetryStore(db_path=db)
    ts = datetime.now(tz=timezone.utc).isoformat()

    for i in range(3):
        store.record({
            "task_id": f"t{i}",
            "rules_triggered": "bad_hook",
            "judge_verdict": "fail",
            "timestamp": ts,
        })

    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()
    (hooks_dir / "bad_hook.py").write_text("# hook")

    ret = hr.main(
        ["--critical"],
        _store=store,
        _skills_dir=tmp_path / "skills",
        _hooks_dir=hooks_dir,
    )
    assert ret == 1
