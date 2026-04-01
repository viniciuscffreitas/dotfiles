# Weekly Intelligence Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a weekly aggregation report that grades the devflow harness (not the developer) and outputs prioritized recommendations to improve hooks, rules, and skills.

**Architecture:** `analysis/weekly_report.py` holds all dataclasses and `WeeklyReportGenerator`; `hooks/weekly_intelligence.py` is the standalone CLI; tests live in `hooks/tests/test_weekly_report.py`. The generator uses `TelemetryStore.get_recent(n=500)` filtered by timestamp, plus `HarnessHealthChecker.check()` for stale/broken counts.

**Tech Stack:** Python 3.13, dataclasses, datetime, argparse, pytest, TelemetryStore (SQLite), HarnessHealthChecker

---

## Task 1: Dataclass definitions — WeeklySignals, HarnessRecommendation, WeeklyIntelligenceReport

**Files:**
- Create: `analysis/weekly_report.py`
- Test: `hooks/tests/test_weekly_report.py`

- [ ] **Step 1: Write failing tests for all three dataclasses**

```python
# hooks/tests/test_weekly_report.py
"""Tests for Weekly Intelligence Report."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from analysis.weekly_report import (
    HarnessRecommendation,
    WeeklyIntelligenceReport,
    WeeklySignals,
)


# ---------------------------------------------------------------------------
# WeeklySignals
# ---------------------------------------------------------------------------

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
    )
    defaults.update(kwargs)
    return WeeklySignals(**defaults)


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
    from analysis.weekly_report import WeeklyIntelligenceReport
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_weekly_report.py -q 2>&1 | head -20
```
Expected: `ModuleNotFoundError: No module named 'analysis.weekly_report'`

- [ ] **Step 3: Implement dataclasses in analysis/weekly_report.py**

```python
# analysis/weekly_report.py
"""
Weekly Intelligence Report — aggregates all devflow signals into harness
recommendations. Grades the harness, not the developer.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WeeklySignals:
    week_start: str                           # ISO date (Monday)
    week_end: str                             # ISO date (Sunday)
    sessions_total: int
    sessions_with_data: int                   # sessions that have telemetry
    judge_pass_rate: float                    # 0.0-1.0
    judge_fail_rate: float
    mean_anxiety_score: float
    high_anxiety_sessions: int
    top_fail_categories: list[tuple[str, int]]   # [(category, count)]
    top_lob_violations: int
    top_duplication_count: int
    harness_health: str                       # "healthy" | "degraded" | "critical"
    stale_skill_count: int
    broken_hook_count: int


@dataclass
class HarnessRecommendation:
    priority: str    # "high" | "medium" | "low"
    category: str    # "add_rule" | "remove_rule" | "tune_hook" | "investigate"
    action: str      # one-line imperative
    evidence: str    # data supporting this recommendation
    effort: str      # "minutes" | "hours" | "days"


@dataclass
class WeeklyIntelligenceReport:
    generated_at: str                          # ISO timestamp
    week_label: str                            # e.g. "Week of 2026-03-30"
    signals: WeeklySignals
    recommendations: list[HarnessRecommendation]
    summary: str                               # 3-sentence executive summary
    next_prompt: str | None                    # suggested next devflow prompt or None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_weekly_report.py -q
```
Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/vini/.claude/devflow
git add analysis/weekly_report.py hooks/tests/test_weekly_report.py
git commit -m "feat(weekly-report): add WeeklySignals, HarnessRecommendation, WeeklyIntelligenceReport dataclasses"
```

---

## Task 2: _collect_signals — filter TelemetryStore by n_days

**Files:**
- Modify: `analysis/weekly_report.py`
- Modify: `hooks/tests/test_weekly_report.py`

- [ ] **Step 1: Write failing tests for _collect_signals**

Append to `hooks/tests/test_weekly_report.py`:

```python
# ---------------------------------------------------------------------------
# _collect_signals
# ---------------------------------------------------------------------------

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
from telemetry.store import TelemetryStore
from analysis.weekly_report import WeeklyReportGenerator


def _ts(days_ago: int = 0) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(days=days_ago)).isoformat()


def test_collect_signals_returns_weekly_signals_type(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "t.db")
    gen = WeeklyReportGenerator()
    result = gen._collect_signals(store, n_days=7)
    assert isinstance(result, WeeklySignals)


def test_collect_signals_counts_sessions_within_n_days(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "t.db")
    # 3 recent, 1 old
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
    assert abs(result.judge_pass_rate - 2/3) < 0.01
    assert abs(result.judge_fail_rate - 1/3) < 0.01


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_weekly_report.py::test_collect_signals_returns_weekly_signals_type -q
```
Expected: `ImportError` or `AttributeError: 'module' has no attribute 'WeeklyReportGenerator'`

- [ ] **Step 3: Implement _collect_signals in analysis/weekly_report.py**

Add imports at the top and the WeeklyReportGenerator class:

```python
# Add to analysis/weekly_report.py — after the dataclass definitions

from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telemetry.store import TelemetryStore
    from analysis.harness_health import HarnessHealthReport

_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


class WeeklyReportGenerator:

    def _collect_signals(
        self, store: "TelemetryStore", n_days: int
    ) -> WeeklySignals:
        """
        Queries TelemetryStore for the past n_days of data.
        Falls back gracefully to zeroes if store is empty or raises.
        """
        try:
            cutoff = (
                datetime.now(tz=timezone.utc) - timedelta(days=n_days)
            ).isoformat()
            all_records = store.get_recent(n=500)
            records = [
                r for r in all_records
                if r.get("timestamp") and r["timestamp"] >= cutoff
            ]

            total = len(records)
            with_data = sum(
                1 for r in records if r.get("judge_verdict") is not None
            )

            judged = [
                r for r in records
                if r.get("judge_verdict") in ("pass", "warn", "fail")
            ]
            pass_count = sum(
                1 for r in judged if r.get("judge_verdict") == "pass"
            )
            fail_count = sum(
                1 for r in judged if r.get("judge_verdict") == "fail"
            )
            n_judged = len(judged)
            pass_rate = (pass_count / n_judged) if n_judged > 0 else 0.0
            fail_rate = (fail_count / n_judged) if n_judged > 0 else 0.0

            # Anxiety: use context_tokens_at_first_action as proxy
            # score = min(tokens / 200_000, 1.0)
            anxiety_scores = []
            for r in records:
                tokens = r.get("context_tokens_at_first_action")
                if tokens is not None:
                    anxiety_scores.append(min(float(tokens) / 200_000, 1.0))
            mean_anxiety = (
                sum(anxiety_scores) / len(anxiety_scores)
                if anxiety_scores else 0.0
            )
            high_anxiety = sum(1 for s in anxiety_scores if s >= 0.7)

            # Fail categories from judge_categories_failed (comma-separated)
            cat_counts: dict[str, int] = {}
            for r in records:
                if r.get("judge_verdict") == "fail" and r.get("judge_categories_failed"):
                    for cat in str(r["judge_categories_failed"]).split(","):
                        cat = cat.strip()
                        if cat:
                            cat_counts[cat] = cat_counts.get(cat, 0) + 1
            top_fail = sorted(cat_counts.items(), key=lambda x: -x[1])

            lob_violations = sum(
                int(r.get("lob_violations") or 0) for r in records
            )
            dup_count = sum(
                1 for r in records if r.get("duplication_detected")
            )

            today = date.today()
            monday = today - timedelta(days=today.weekday())
            week_start = monday.isoformat()
            week_end = (monday + timedelta(days=6)).isoformat()

            return WeeklySignals(
                week_start=week_start,
                week_end=week_end,
                sessions_total=total,
                sessions_with_data=with_data,
                judge_pass_rate=pass_rate,
                judge_fail_rate=fail_rate,
                mean_anxiety_score=mean_anxiety,
                high_anxiety_sessions=high_anxiety,
                top_fail_categories=top_fail,
                top_lob_violations=lob_violations,
                top_duplication_count=dup_count,
                harness_health="healthy",   # filled by generate()
                stale_skill_count=0,        # filled by generate()
                broken_hook_count=0,        # filled by generate()
            )
        except Exception:
            today = date.today()
            monday = today - timedelta(days=today.weekday())
            return WeeklySignals(
                week_start=monday.isoformat(),
                week_end=(monday + timedelta(days=6)).isoformat(),
                sessions_total=0,
                sessions_with_data=0,
                judge_pass_rate=0.0,
                judge_fail_rate=0.0,
                mean_anxiety_score=0.0,
                high_anxiety_sessions=0,
                top_fail_categories=[],
                top_lob_violations=0,
                top_duplication_count=0,
                harness_health="healthy",
                stale_skill_count=0,
                broken_hook_count=0,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_weekly_report.py -k "collect_signals" -q
```
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/vini/.claude/devflow
git add analysis/weekly_report.py hooks/tests/test_weekly_report.py
git commit -m "feat(weekly-report): implement _collect_signals with n_days filtering and graceful fallback"
```

---

## Task 3: _generate_recommendations — priority-ordered rules engine

**Files:**
- Modify: `analysis/weekly_report.py`
- Modify: `hooks/tests/test_weekly_report.py`

- [ ] **Step 1: Write failing tests for _generate_recommendations**

Append to `hooks/tests/test_weekly_report.py`:

```python
# ---------------------------------------------------------------------------
# _generate_recommendations
# ---------------------------------------------------------------------------

from analysis.harness_health import HarnessHealthReport, SkillHealth, HookHealth


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
    remove = [r for r in recs if r.priority == "medium" and r.category == "remove_rule"
              and "stale" in r.action.lower()]
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
        sessions_total=3,          # LOW
        judge_fail_rate=0.35,      # HIGH
        stale_skill_count=2,       # MEDIUM
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
    relax = [r for r in recs if r.priority == "medium" and r.category == "remove_rule"
             and "relaxing" in r.action.lower()]
    assert len(relax) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_weekly_report.py -k "generate_recommendations" -q
```
Expected: `AttributeError: 'WeeklyReportGenerator' object has no attribute '_generate_recommendations'`

- [ ] **Step 3: Implement _generate_recommendations in analysis/weekly_report.py**

Add inside `WeeklyReportGenerator`:

```python
    def _generate_recommendations(
        self,
        signals: WeeklySignals,
        health: "HarnessHealthReport",
    ) -> list[HarnessRecommendation]:
        recs: list[HarnessRecommendation] = []

        # HIGH priority
        if signals.broken_hook_count > 0:
            n = signals.broken_hook_count
            recs.append(HarnessRecommendation(
                priority="high",
                category="investigate",
                action=f"Fix broken hook — {n} hooks have >20% error rate",
                evidence=f"{n} hooks exceeded HIGH_ERROR_RATE threshold this week",
                effort="hours",
            ))

        if signals.judge_fail_rate > 0.3:
            rate = signals.judge_fail_rate
            recs.append(HarnessRecommendation(
                priority="high",
                category="tune_hook",
                action=f"Tighten judge rubric — {rate:.0%} fail rate this week",
                evidence=f"Judge fail rate {rate:.0%} exceeds 30% threshold",
                effort="hours",
            ))

        if signals.mean_anxiety_score > 0.6:
            score = signals.mean_anxiety_score
            recs.append(HarnessRecommendation(
                priority="high",
                category="add_rule",
                action=f"Add spec specificity rule — anxiety score {score:.2f}",
                evidence=f"Mean anxiety score {score:.2f} exceeds 0.60 threshold",
                effort="minutes",
            ))

        # MEDIUM priority
        if signals.stale_skill_count > 0:
            n = signals.stale_skill_count
            recs.append(HarnessRecommendation(
                priority="medium",
                category="remove_rule",
                action=f"Remove {n} stale skills — unused for 14+ days",
                evidence=f"{n} skills have no usage in the past 14 days",
                effort="minutes",
            ))

        if signals.top_lob_violations > 3:
            n = signals.top_lob_violations
            recs.append(HarnessRecommendation(
                priority="medium",
                category="add_rule",
                action=f"Add LoB boundary to CLAUDE.md — {n} violations this week",
                evidence=f"{n} LoB violations detected across sessions this week",
                effort="minutes",
            ))

        if signals.judge_pass_rate > 0.95 and signals.sessions_total > 20:
            recs.append(HarnessRecommendation(
                priority="medium",
                category="remove_rule",
                action="Consider relaxing strict checks — 95%+ pass rate",
                evidence=(
                    f"Pass rate {signals.judge_pass_rate:.0%} with "
                    f"{signals.sessions_total} sessions suggests rules may be too lenient "
                    "or harness is over-instrumented"
                ),
                effort="hours",
            ))

        # LOW priority
        if signals.sessions_total < 5:
            recs.append(HarnessRecommendation(
                priority="low",
                category="investigate",
                action="Low session count — harness may not be triggering",
                evidence=f"Only {signals.sessions_total} sessions recorded in the past week",
                effort="hours",
            ))

        if signals.sessions_total > 0 and (
            signals.high_anxiety_sessions > signals.sessions_total * 0.3
        ):
            recs.append(HarnessRecommendation(
                priority="low",
                category="tune_hook",
                action="30%+ high-anxiety sessions — review task spec quality",
                evidence=(
                    f"{signals.high_anxiety_sessions}/{signals.sessions_total} sessions "
                    "had high anxiety scores"
                ),
                effort="hours",
            ))

        return sorted(recs, key=lambda r: _PRIORITY_ORDER[r.priority])
```

Note: `_PRIORITY_ORDER` must be a module-level constant: `_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}` (already defined in Task 2 step).

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_weekly_report.py -k "generate_recommendations" -q
```
Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/vini/.claude/devflow
git add analysis/weekly_report.py hooks/tests/test_weekly_report.py
git commit -m "feat(weekly-report): implement _generate_recommendations with 8-rule priority engine"
```

---

## Task 4: _suggest_next_prompt, _build_summary, and generate()

**Files:**
- Modify: `analysis/weekly_report.py`
- Modify: `hooks/tests/test_weekly_report.py`

- [ ] **Step 1: Write failing tests**

Append to `hooks/tests/test_weekly_report.py`:

```python
# ---------------------------------------------------------------------------
# _suggest_next_prompt
# ---------------------------------------------------------------------------

def test_suggest_next_prompt_high_investigate_returns_health_report_command():
    gen = WeeklyReportGenerator()
    recs = [
        _make_rec(priority="high", category="investigate"),
    ]
    result = gen._suggest_next_prompt(recs)
    assert result is not None
    assert "health_report" in result


def test_suggest_next_prompt_high_add_rule_returns_linter_suggestion():
    gen = WeeklyReportGenerator()
    recs = [
        _make_rec(priority="high", category="add_rule"),
    ]
    result = gen._suggest_next_prompt(recs)
    assert result is not None
    assert "linter" in result.lower()


def test_suggest_next_prompt_no_high_medium_returns_none():
    gen = WeeklyReportGenerator()
    recs = [
        _make_rec(priority="low", category="investigate"),
    ]
    result = gen._suggest_next_prompt(recs)
    assert result is None


def test_suggest_next_prompt_empty_returns_none():
    gen = WeeklyReportGenerator()
    result = gen._suggest_next_prompt([])
    assert result is None


def test_suggest_next_prompt_never_raises():
    gen = WeeklyReportGenerator()
    # Bad data — should never raise
    result = gen._suggest_next_prompt([MagicMock(priority="high", category="unknown_cat")])
    # Should return something (or None) but never raise
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
    # Insert data that triggers multiple recommendations
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_weekly_report.py -k "suggest_next or build_summary or test_generate" -q
```
Expected: `AttributeError: 'WeeklyReportGenerator' object has no attribute '_suggest_next_prompt'`

- [ ] **Step 3: Implement the remaining three methods in analysis/weekly_report.py**

Add inside `WeeklyReportGenerator` (after `_generate_recommendations`):

```python
    def _suggest_next_prompt(
        self, recommendations: list[HarnessRecommendation]
    ) -> str | None:
        """Returns a one-line next-step suggestion based on highest-priority rec."""
        _next: dict[tuple[str, str], str] = {
            ("high", "investigate"): "Run: python3 hooks/health_report.py --critical",
            ("high", "add_rule"): "Write a new linter for the violation pattern",
            ("high", "tune_hook"): "Run: python3 hooks/health_report.py --json",
            ("medium", "remove_rule"): "Run: python3 hooks/health_report.py --json",
        }
        for rec in recommendations:
            key = (rec.priority, rec.category)
            if key in _next:
                return _next[key]
        return None

    def _build_summary(
        self,
        signals: WeeklySignals,
        recommendations: list[HarnessRecommendation],
    ) -> str:
        """3-sentence executive summary."""
        pass_pct = int(signals.judge_pass_rate * 100)
        s1 = (
            f"Harness recorded {signals.sessions_total} sessions this week "
            f"with a {pass_pct}% judge pass rate"
        )

        high_recs = [r for r in recommendations if r.priority == "high"]
        if high_recs:
            s2 = f"The top issue is {high_recs[0].action.lower()}"
        else:
            s2 = "No critical issues found this week"

        if recommendations:
            top = recommendations[0]
            s3 = f"{top.action} before the next sprint"
        else:
            s3 = "Harness is operating well"

        return f"{s1}. {s2}. {s3}."

    def generate(
        self,
        store: "TelemetryStore",
        skills_dir: Path,
        hooks_dir: Path,
        n_days: int = 7,
    ) -> WeeklyIntelligenceReport:
        """Orchestrates signal collection and recommendation generation. Never raises."""
        try:
            from analysis.harness_health import HarnessHealthChecker

            signals = self._collect_signals(store, n_days)

            try:
                checker = HarnessHealthChecker()
                health = checker.check(store, skills_dir, hooks_dir)
                signals.harness_health = health.overall_verdict
                signals.stale_skill_count = health.stale_skill_count
                signals.broken_hook_count = health.broken_hook_count
            except Exception:
                health_verdict = "healthy"
                from analysis.harness_health import HarnessHealthReport
                health = HarnessHealthReport(
                    generated_at=datetime.now(tz=timezone.utc).isoformat(),
                    overall_verdict="healthy",
                    skill_health=[],
                    hook_health=[],
                    stale_skill_count=0,
                    broken_hook_count=0,
                    simplification_candidates=[],
                    complexity_score=0.0,
                    summary="Health check unavailable.",
                )

            recommendations = self._generate_recommendations(signals, health)
            summary = self._build_summary(signals, recommendations)
            next_prompt = self._suggest_next_prompt(recommendations)

            today = date.today()
            monday = today - timedelta(days=today.weekday())
            week_label = f"Week of {monday.isoformat()}"

            return WeeklyIntelligenceReport(
                generated_at=datetime.now(tz=timezone.utc).isoformat(),
                week_label=week_label,
                signals=signals,
                recommendations=recommendations,
                summary=summary,
                next_prompt=next_prompt,
            )
        except Exception:
            today = date.today()
            monday = today - timedelta(days=today.weekday())
            empty_signals = WeeklySignals(
                week_start=monday.isoformat(),
                week_end=(monday + timedelta(days=6)).isoformat(),
                sessions_total=0,
                sessions_with_data=0,
                judge_pass_rate=0.0,
                judge_fail_rate=0.0,
                mean_anxiety_score=0.0,
                high_anxiety_sessions=0,
                top_fail_categories=[],
                top_lob_violations=0,
                top_duplication_count=0,
                harness_health="healthy",
                stale_skill_count=0,
                broken_hook_count=0,
            )
            return WeeklyIntelligenceReport(
                generated_at=datetime.now(tz=timezone.utc).isoformat(),
                week_label=f"Week of {monday.isoformat()}",
                signals=empty_signals,
                recommendations=[],
                summary="0 sessions recorded. No critical issues found. Harness is operating well.",
                next_prompt=None,
            )
```

- [ ] **Step 4: Run all tests so far**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_weekly_report.py -q
```
Expected: all tests pass (aim for ~40)

- [ ] **Step 5: Commit**

```bash
cd /Users/vini/.claude/devflow
git add analysis/weekly_report.py hooks/tests/test_weekly_report.py
git commit -m "feat(weekly-report): implement _suggest_next_prompt, _build_summary, and generate()"
```

---

## Task 5: CLI — hooks/weekly_intelligence.py

**Files:**
- Create: `hooks/weekly_intelligence.py`
- Modify: `hooks/tests/test_weekly_report.py`

- [ ] **Step 1: Write failing CLI tests**

Append to `hooks/tests/test_weekly_report.py`:

```python
# ---------------------------------------------------------------------------
# weekly_intelligence CLI
# ---------------------------------------------------------------------------

import contextlib
import io
import json
import subprocess
import sys as _sys

_CLI = str(Path(__file__).parent.parent / "weekly_intelligence.py")


def _run_cli(*args: str) -> tuple[str, int]:
    """Run weekly_intelligence.py with args, return (stdout, returncode)."""
    result = subprocess.run(
        ["python3.13", _CLI, *args],
        capture_output=True,
        text=True,
    )
    return result.stdout + result.stderr, result.returncode


def test_cli_default_output_starts_with_devflow_weekly():
    out, code = _run_cli()
    assert out.startswith("[devflow:weekly]"), f"Got: {out[:80]!r}"


def test_cli_json_outputs_valid_json_with_week_label():
    out, code = _run_cli("--json")
    data = json.loads(out)
    assert "week_label" in data
    assert data["week_label"].startswith("Week of ")


def test_cli_slack_output_contains_bold_formatting():
    out, code = _run_cli("--slack")
    assert "*" in out  # Slack bold uses *text*


def test_cli_days_parameter_is_accepted():
    out, code = _run_cli("--days", "14")
    assert out.startswith("[devflow:weekly]")


def test_cli_exit_code_zero():
    _, code = _run_cli()
    assert code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_weekly_report.py -k "cli" -q
```
Expected: `FileNotFoundError` or process exits non-zero

- [ ] **Step 3: Implement hooks/weekly_intelligence.py**

```python
#!/usr/bin/env python3.13
"""
devflow Weekly Intelligence Report — closes the flywheel.

Usage:
  python3.13 hooks/weekly_intelligence.py           # current week
  python3.13 hooks/weekly_intelligence.py --days 14 # last 2 weeks
  python3.13 hooks/weekly_intelligence.py --json    # full JSON output
  python3.13 hooks/weekly_intelligence.py --slack   # Slack-formatted output
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from analysis.weekly_report import WeeklyReportGenerator
from telemetry.store import TelemetryStore

_SKILLS_DIR = Path.home() / ".claude" / "skills"
_HOOKS_DIR = Path(__file__).parent


def _format_default(report) -> str:
    from analysis.weekly_report import WeeklyIntelligenceReport
    s = report.signals
    pass_pct = int(s.judge_pass_rate * 100)
    lines = [
        f"[devflow:weekly] {report.week_label} | Sessions: {s.sessions_total} | Pass rate: {pass_pct}%",
        "",
        "SIGNALS",
        f"  Judge: {pass_pct}% pass, {int(s.judge_fail_rate * 100)}% fail",
        f"  Anxiety: mean {s.mean_anxiety_score:.2f} | {s.high_anxiety_sessions} high-anxiety sessions",
        f"  Health: {s.harness_health.upper()} | {s.broken_hook_count} broken hooks, {s.stale_skill_count} stale skills",
    ]

    if report.recommendations:
        lines.append("")
        lines.append(f"RECOMMENDATIONS ({len(report.recommendations)})")
        for r in report.recommendations:
            lines.append(
                f"  [{r.priority.upper():<6}] {r.category:<11} {r.action} ({r.effort})"
            )
    else:
        lines.append("")
        lines.append("RECOMMENDATIONS (0)")
        lines.append("  No recommendations — harness is operating well.")

    if report.next_prompt:
        lines.append("")
        lines.append(f"NEXT: {report.next_prompt}")

    lines.append("")
    lines.append("---")
    lines.append(report.summary)
    return "\n".join(lines)


def _format_slack(report) -> str:
    s = report.signals
    pass_pct = int(s.judge_pass_rate * 100)
    lines = [
        f"*[devflow:weekly] {report.week_label}*",
        f"Sessions: *{s.sessions_total}* | Pass rate: *{pass_pct}%*",
        "",
        "*SIGNALS*",
        f"• Judge: *{pass_pct}%* pass, *{int(s.judge_fail_rate * 100)}%* fail",
        f"• Anxiety: mean *{s.mean_anxiety_score:.2f}* | *{s.high_anxiety_sessions}* high-anxiety sessions",
        f"• Health: *{s.harness_health.upper()}* | *{s.broken_hook_count}* broken hooks, *{s.stale_skill_count}* stale skills",
    ]

    if report.recommendations:
        lines.append("")
        lines.append(f"*RECOMMENDATIONS ({len(report.recommendations)})*")
        for r in report.recommendations:
            lines.append(
                f"• *[{r.priority.upper()}]* `{r.category}` {r.action} _({r.effort})_"
            )

    if report.next_prompt:
        lines.append("")
        lines.append(f"*NEXT:* {report.next_prompt}")

    lines.append("")
    lines.append(f"_{report.summary}_")
    return "\n".join(lines)


def main(
    argv: list[str] | None = None,
    _store=None,
    _skills_dir: Path | None = None,
    _hooks_dir: Path | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="devflow Weekly Intelligence Report")
    parser.add_argument("--days", type=int, default=7, help="Days to look back (default: 7)")
    parser.add_argument("--json", action="store_true", dest="as_json", help="JSON output")
    parser.add_argument("--slack", action="store_true", help="Slack-formatted output")
    args = parser.parse_args(argv)

    store = _store if _store is not None else TelemetryStore()
    skills_dir = _skills_dir if _skills_dir is not None else _SKILLS_DIR
    hooks_dir = _hooks_dir if _hooks_dir is not None else _HOOKS_DIR

    gen = WeeklyReportGenerator()
    report = gen.generate(store, skills_dir, hooks_dir, n_days=args.days)

    if args.as_json:
        print(json.dumps(dataclasses.asdict(report), indent=2))
        return 0

    if args.slack:
        print(_format_slack(report))
        return 0

    print(_format_default(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run all tests**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_weekly_report.py -q
```
Expected: all tests pass

- [ ] **Step 5: Smoke test**

```bash
cd /Users/vini/.claude/devflow
python3.13 hooks/weekly_intelligence.py
```
Expected output starts with: `[devflow:weekly] Week of 2026-03-31 | Sessions: N | Pass rate: X%`

- [ ] **Step 6: Commit**

```bash
cd /Users/vini/.claude/devflow
git add hooks/weekly_intelligence.py hooks/tests/test_weekly_report.py
git commit -m "feat(weekly-report): implement weekly_intelligence.py CLI with default/json/slack output"
```

---

## Task 6: Full test suite verification + audit doc update

**Files:**
- Modify: `docs/audit-20260331.md`

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/ -q
```
Expected: `541 + N tests passing` (N = number of tests added by this feature)

- [ ] **Step 2: Count new tests added**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_weekly_report.py --co -q | tail -3
```
Note the count and compute: `total = 541 + count`.

- [ ] **Step 3: Update audit-20260331.md**

Append to `docs/audit-20260331.md`:

```markdown
### Prompt 9: Weekly Intelligence Report — N tests added, 541 → M total (`2026-03-31`)

**Files created:**
- `analysis/weekly_report.py` — `WeeklySignals`, `HarnessRecommendation`, `WeeklyIntelligenceReport` dataclasses + `WeeklyReportGenerator`: `_collect_signals()` (filters TelemetryStore by n_days, anxiety proxy via context_tokens_at_first_action), `_generate_recommendations()` (8-rule priority engine: 3 HIGH, 3 MEDIUM, 2 LOW), `_suggest_next_prompt()` (maps top rec to actionable CLI command), `_build_summary()` (3-sentence: stats, top issue, next action), `generate()` (orchestrates all, never raises)
- `hooks/weekly_intelligence.py` — standalone CLI: default/--json/--slack/--days modes; default output shows header + SIGNALS + RECOMMENDATIONS + NEXT + summary; Slack mode uses *bold* formatting

**Tests added (N):**

| Class | Tests | What's covered |
|-------|-------|----------------|
| WeeklySignals dataclass | 3 | instantiation, pass+fail sum ≤ 1.0, zero rates |
| HarnessRecommendation dataclass | 3 | instantiation, priority values, category values |
| WeeklyIntelligenceReport dataclass | 1 | instantiation, next_prompt=None |
| _collect_signals | 7 | type, session count filter, pass rate, empty store, never raises, lob violations, duplication |
| _generate_recommendations | 9 | broken hook HIGH, high fail rate HIGH, high anxiety HIGH, stale skills MEDIUM, LoB violations MEDIUM, low sessions LOW, all healthy → empty, sort order, high pass rate MEDIUM |
| _suggest_next_prompt | 5 | investigate→health_report cmd, add_rule→linter, no high/medium→None, empty→None, never raises |
| _build_summary | 4 | 3 sentences, includes count, no recs message, never raises |
| generate() | 5 | returns report, week_label format, sorted recs, never raises on empty store, never raises on store failure |
| CLI | 5 | default prefix, --json valid JSON, --slack has *, --days accepted, exit code 0 |

**hooks/tests/ baseline:** 541 → M (N net added)
**Smoke test:** `python3.13 hooks/weekly_intelligence.py` → `[devflow:weekly] Week of ... | Sessions: N | Pass rate: X%` ✓
**Regressions:** 0
```

- [ ] **Step 4: Final verification**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/ -q && echo "ALL TESTS PASS"
python3.13 hooks/weekly_intelligence.py
python3.13 hooks/weekly_intelligence.py --json | python3.13 -c "import sys,json; d=json.load(sys.stdin); print(d['week_label'])"
python3.13 hooks/weekly_intelligence.py --slack | head -3
```

- [ ] **Step 5: Commit**

```bash
cd /Users/vini/.claude/devflow
git add docs/audit-20260331.md
git commit -m "docs: audit prompt 9 — weekly intelligence report, 541 → M tests"
```
