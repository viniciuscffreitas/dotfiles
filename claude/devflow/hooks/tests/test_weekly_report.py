"""Tests for Weekly Intelligence Report."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from analysis.weekly_report import (
    HarnessRecommendation,
    WeeklyIntelligenceReport,
    WeeklyReportGenerator,
    WeeklySignals,
    _PRIORITY_ORDER,
)
from telemetry.store import TelemetryStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts(days_ago: int = 0) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(days=days_ago)).isoformat()


def _make_signals(**kwargs) -> WeeklySignals:
    defaults = dict(
        week_start="2026-03-30",
        week_end="2026-04-05",
        sessions_total=10,
        sessions_with_data=8,
        judge_pass_rate=0.8,
        judge_fail_rate=0.2,
        mean_anxiety_score=0.3,
        high_anxiety_sessions=1,
        top_fail_categories=[],
        top_lob_violations=0,
        top_duplication_count=0,
        harness_health="healthy",
        stale_skill_count=0,
        broken_hook_count=0,
        instincts_captured=0,
        instincts_pending=0,
    )
    defaults.update(kwargs)
    return WeeklySignals(**defaults)


def _make_rec(**kwargs) -> HarnessRecommendation:
    defaults = dict(
        priority="high",
        category="add_rule",
        action="Add something",
        evidence="Because of X",
        effort="minutes",
    )
    defaults.update(kwargs)
    return HarnessRecommendation(**defaults)


# ---------------------------------------------------------------------------
# WeeklySignals
# ---------------------------------------------------------------------------


def test_weekly_signals_instantiates():
    s = _make_signals()
    assert s.sessions_total == 10
    assert s.harness_health == "healthy"


def test_weekly_signals_pass_fail_rates_sum_to_at_most_one():
    s = _make_signals(judge_pass_rate=0.7, judge_fail_rate=0.3)
    assert s.judge_pass_rate + s.judge_fail_rate <= 1.0


def test_weekly_signals_pass_fail_rates_can_be_zero():
    s = _make_signals(judge_pass_rate=0.0, judge_fail_rate=0.0)
    assert s.judge_pass_rate + s.judge_fail_rate == 0.0


# ---------------------------------------------------------------------------
# HarnessRecommendation
# ---------------------------------------------------------------------------


def test_harness_recommendation_instantiates():
    r = _make_rec()
    assert r.priority == "high"
    assert r.category == "add_rule"


def test_harness_recommendation_valid_priorities():
    for p in ("high", "medium", "low"):
        r = _make_rec(priority=p)
        assert r.priority == p


def test_harness_recommendation_valid_categories():
    for c in ("add_rule", "remove_rule", "tune_hook", "investigate"):
        r = _make_rec(category=c)
        assert r.category == c


# ---------------------------------------------------------------------------
# WeeklyIntelligenceReport
# ---------------------------------------------------------------------------


def test_weekly_intelligence_report_instantiates():
    r = WeeklyIntelligenceReport(
        generated_at="2026-03-31T00:00:00+00:00",
        week_label="Week of 2026-03-30",
        signals=_make_signals(),
        recommendations=[],
        summary="S1. S2. S3.",
        next_prompt=None,
    )
    assert r.week_label == "Week of 2026-03-30"
    assert r.next_prompt is None


# ---------------------------------------------------------------------------
# _collect_signals
# ---------------------------------------------------------------------------


def test_collect_signals_returns_weekly_signals_type(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "t.db")
    gen = WeeklyReportGenerator()
    result = gen._collect_signals(store, n_days=7)
    assert isinstance(result, WeeklySignals)


def test_collect_signals_counts_sessions_within_n_days(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "t.db")
    store.record({"task_id": "a1", "timestamp": _ts(0), "judge_verdict": "pass"})
    store.record({"task_id": "a2", "timestamp": _ts(2), "judge_verdict": "pass"})
    store.record({"task_id": "a3", "timestamp": _ts(5), "judge_verdict": "fail"})
    store.record({"task_id": "a4", "timestamp": _ts(10), "judge_verdict": "pass"})  # outside 7d
    gen = WeeklyReportGenerator()
    result = gen._collect_signals(store, n_days=7)
    assert result.sessions_total == 3


def test_collect_signals_computes_pass_rate(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "t.db")
    store.record({"task_id": "b1", "timestamp": _ts(0), "judge_verdict": "pass"})
    store.record({"task_id": "b2", "timestamp": _ts(0), "judge_verdict": "pass"})
    store.record({"task_id": "b3", "timestamp": _ts(0), "judge_verdict": "fail"})
    gen = WeeklyReportGenerator()
    result = gen._collect_signals(store, n_days=7)
    assert abs(result.judge_pass_rate - 2 / 3) < 0.01
    assert abs(result.judge_fail_rate - 1 / 3) < 0.01


def test_collect_signals_empty_store_returns_zero_signals(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "t.db")
    gen = WeeklyReportGenerator()
    result = gen._collect_signals(store, n_days=7)
    assert result.sessions_total == 0
    assert result.judge_pass_rate == 0.0
    assert result.judge_fail_rate == 0.0
    assert result.mean_anxiety_score == 0.0


def test_collect_signals_never_raises_on_bad_store():
    bad_store = MagicMock()
    bad_store.get_recent.side_effect = Exception("db error")
    gen = WeeklyReportGenerator()
    result = gen._collect_signals(bad_store, n_days=7)
    assert isinstance(result, WeeklySignals)
    assert result.sessions_total == 0


def test_collect_signals_counts_lob_violations(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "t.db")
    store.record({"task_id": "c1", "timestamp": _ts(0), "lob_violations": 3})
    store.record({"task_id": "c2", "timestamp": _ts(0), "lob_violations": 2})
    gen = WeeklyReportGenerator()
    result = gen._collect_signals(store, n_days=7)
    assert result.top_lob_violations == 5


def test_collect_signals_counts_duplication(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "t.db")
    store.record({"task_id": "d1", "timestamp": _ts(0), "duplication_detected": 1})
    store.record({"task_id": "d2", "timestamp": _ts(0), "duplication_detected": 0})
    gen = WeeklyReportGenerator()
    result = gen._collect_signals(store, n_days=7)
    assert result.top_duplication_count == 1


# ---------------------------------------------------------------------------
# _generate_recommendations
# ---------------------------------------------------------------------------


from analysis.harness_health import HarnessHealthReport


def _make_health(stale=0, broken=0, verdict="healthy") -> HarnessHealthReport:
    return HarnessHealthReport(
        generated_at="2026-03-31T00:00:00+00:00",
        overall_verdict=verdict,
        skill_health=[],
        hook_health=[],
        stale_skill_count=stale,
        broken_hook_count=broken,
        simplification_candidates=[],
        complexity_score=0.0,
        summary="All good.",
    )


def test_generate_recommendations_broken_hook_produces_high_investigate():
    gen = WeeklyReportGenerator()
    signals = _make_signals(broken_hook_count=2)
    health = _make_health(broken=2)
    recs = gen._generate_recommendations(signals, health)
    high_inv = [r for r in recs if r.priority == "high" and r.category == "investigate"]
    assert len(high_inv) == 1
    assert "2" in high_inv[0].action


def test_generate_recommendations_high_fail_rate_produces_high_tune_hook():
    gen = WeeklyReportGenerator()
    signals = _make_signals(judge_fail_rate=0.35)
    health = _make_health()
    recs = gen._generate_recommendations(signals, health)
    tune = [r for r in recs if r.priority == "high" and r.category == "tune_hook"]
    assert len(tune) == 1
    assert "35%" in tune[0].action


def test_generate_recommendations_high_anxiety_produces_high_add_rule():
    gen = WeeklyReportGenerator()
    signals = _make_signals(mean_anxiety_score=0.65)
    health = _make_health()
    recs = gen._generate_recommendations(signals, health)
    add = [r for r in recs if r.priority == "high" and r.category == "add_rule"]
    assert len(add) == 1
    assert "0.65" in add[0].action


def test_generate_recommendations_stale_skills_produces_medium_remove_rule():
    gen = WeeklyReportGenerator()
    signals = _make_signals(stale_skill_count=3)
    health = _make_health(stale=3)
    recs = gen._generate_recommendations(signals, health)
    remove = [
        r for r in recs
        if r.priority == "medium" and r.category == "remove_rule"
        and "stale" in r.action.lower()
    ]
    assert len(remove) == 1
    assert "3" in remove[0].action


def test_generate_recommendations_lob_violations_produces_medium_add_rule():
    gen = WeeklyReportGenerator()
    signals = _make_signals(top_lob_violations=5)
    health = _make_health()
    recs = gen._generate_recommendations(signals, health)
    lob = [r for r in recs if r.priority == "medium" and r.category == "add_rule"]
    assert len(lob) == 1
    assert "5" in lob[0].action


def test_generate_recommendations_low_sessions_produces_low_investigate():
    gen = WeeklyReportGenerator()
    signals = _make_signals(sessions_total=3)
    health = _make_health()
    recs = gen._generate_recommendations(signals, health)
    low_inv = [r for r in recs if r.priority == "low" and r.category == "investigate"]
    assert len(low_inv) == 1


def test_generate_recommendations_all_healthy_returns_empty():
    gen = WeeklyReportGenerator()
    signals = _make_signals(
        sessions_total=15,
        judge_pass_rate=0.85,
        judge_fail_rate=0.15,
        mean_anxiety_score=0.3,
        broken_hook_count=0,
        stale_skill_count=0,
        top_lob_violations=1,
    )
    health = _make_health()
    recs = gen._generate_recommendations(signals, health)
    assert recs == []


def test_generate_recommendations_sorted_high_first():
    gen = WeeklyReportGenerator()
    signals = _make_signals(
        sessions_total=3,      # LOW
        judge_fail_rate=0.35,  # HIGH
        stale_skill_count=2,   # MEDIUM
    )
    health = _make_health(stale=2)
    recs = gen._generate_recommendations(signals, health)
    priorities = [r.priority for r in recs]
    assert priorities == sorted(priorities, key=lambda p: _PRIORITY_ORDER[p])


def test_generate_recommendations_high_pass_rate_produces_medium_remove_rule():
    gen = WeeklyReportGenerator()
    signals = _make_signals(
        sessions_total=25,
        judge_pass_rate=0.96,
        judge_fail_rate=0.04,
    )
    health = _make_health()
    recs = gen._generate_recommendations(signals, health)
    relax = [
        r for r in recs
        if r.priority == "medium" and r.category == "remove_rule"
        and "relaxing" in r.action.lower()
    ]
    assert len(relax) == 1


# ---------------------------------------------------------------------------
# _suggest_next_prompt
# ---------------------------------------------------------------------------


def test_suggest_next_prompt_high_investigate_returns_health_report_command():
    gen = WeeklyReportGenerator()
    recs = [_make_rec(priority="high", category="investigate")]
    result = gen._suggest_next_prompt(recs)
    assert result is not None
    assert "health_report" in result


def test_suggest_next_prompt_high_add_rule_returns_linter_suggestion():
    gen = WeeklyReportGenerator()
    recs = [_make_rec(priority="high", category="add_rule")]
    result = gen._suggest_next_prompt(recs)
    assert result is not None
    assert "linter" in result.lower()


def test_suggest_next_prompt_no_high_medium_returns_none():
    gen = WeeklyReportGenerator()
    recs = [_make_rec(priority="low", category="investigate")]
    result = gen._suggest_next_prompt(recs)
    assert result is None


def test_suggest_next_prompt_empty_returns_none():
    gen = WeeklyReportGenerator()
    result = gen._suggest_next_prompt([])
    assert result is None


def test_suggest_next_prompt_never_raises():
    gen = WeeklyReportGenerator()
    result = gen._suggest_next_prompt([MagicMock(priority="high", category="unknown_cat")])
    assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# _build_summary
# ---------------------------------------------------------------------------


def test_build_summary_returns_three_sentences():
    gen = WeeklyReportGenerator()
    signals = _make_signals(sessions_total=21, judge_pass_rate=0.81)
    recs = [_make_rec(priority="high", category="add_rule", action="Add X")]
    result = gen._build_summary(signals, recs)
    sentences = [s.strip() for s in result.split(".") if s.strip()]
    assert len(sentences) == 3


def test_build_summary_includes_session_count():
    gen = WeeklyReportGenerator()
    signals = _make_signals(sessions_total=42)
    result = gen._build_summary(signals, [])
    assert "42" in result


def test_build_summary_no_recs_says_no_critical_issues():
    gen = WeeklyReportGenerator()
    signals = _make_signals()
    result = gen._build_summary(signals, [])
    assert "No critical issues" in result or "operating well" in result


def test_build_summary_never_raises_on_empty_signals():
    gen = WeeklyReportGenerator()
    signals = _make_signals(sessions_total=0, judge_pass_rate=0.0)
    result = gen._build_summary(signals, [])
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# WeeklyReportGenerator.generate()
# ---------------------------------------------------------------------------

_SKILLS_DIR = Path.home() / ".claude" / "skills"
_HOOKS_DIR = Path(__file__).parent.parent


def test_generate_returns_weekly_intelligence_report(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "t.db")
    gen = WeeklyReportGenerator()
    report = gen.generate(store, _SKILLS_DIR, _HOOKS_DIR)
    assert isinstance(report, WeeklyIntelligenceReport)


def test_generate_week_label_contains_week_of(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "t.db")
    gen = WeeklyReportGenerator()
    report = gen.generate(store, _SKILLS_DIR, _HOOKS_DIR)
    assert report.week_label.startswith("Week of ")


def test_generate_recommendations_sorted_high_to_low(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "t.db")
    ts = _ts(0)
    for i in range(3):
        store.record({
            "task_id": f"g{i}",
            "timestamp": ts,
            "judge_verdict": "fail",
            "lob_violations": 5,
        })
    gen = WeeklyReportGenerator()
    report = gen.generate(store, _SKILLS_DIR, _HOOKS_DIR)
    priorities = [r.priority for r in report.recommendations]
    assert priorities == sorted(priorities, key=lambda p: _PRIORITY_ORDER[p])


def test_generate_never_raises_on_empty_store(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "t.db")
    gen = WeeklyReportGenerator()
    report = gen.generate(store, _SKILLS_DIR, _HOOKS_DIR)
    assert isinstance(report, WeeklyIntelligenceReport)


def test_generate_never_raises_on_store_failure():
    bad_store = MagicMock()
    bad_store.get_recent.side_effect = Exception("connection lost")
    gen = WeeklyReportGenerator()
    report = gen.generate(bad_store, _SKILLS_DIR, _HOOKS_DIR)
    assert isinstance(report, WeeklyIntelligenceReport)


# ---------------------------------------------------------------------------
# weekly_intelligence CLI
# ---------------------------------------------------------------------------

import subprocess as _subprocess

_CLI = str(Path(__file__).parent.parent / "weekly_intelligence.py")


def _run_cli(*args: str) -> tuple[str, int]:
    result = _subprocess.run(
        ["python3.13", _CLI, *args],
        capture_output=True,
        text=True,
    )
    return result.stdout + result.stderr, result.returncode


def test_cli_default_output_contains_devflow_label():
    out, code = _run_cli()
    assert code == 0
    assert "[devflow:weekly]" in out


def test_cli_json_output_is_parseable():
    out, code = _run_cli("--json")
    assert code == 0
    data = json.loads(out)
    assert "signals" in data
    assert "recommendations" in data
    assert "week_label" in data


def test_cli_json_has_required_signal_keys():
    out, _ = _run_cli("--json")
    data = json.loads(out)
    signals = data["signals"]
    for key in ("sessions_total", "judge_fail_rate", "mean_anxiety_score"):
        assert key in signals
