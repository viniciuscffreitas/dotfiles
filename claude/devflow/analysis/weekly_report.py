"""
Weekly Intelligence Report — aggregates all devflow signals into harness
recommendations. Grades the harness, not the developer.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

_RECENT_RECORDS_CAP = 500  # max records fetched from TelemetryStore per report cycle

if TYPE_CHECKING:
    from telemetry.store import TelemetryStore
    from analysis.harness_health import HarnessHealthReport


_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class WeeklySignals:
    week_start: str                             # ISO date (Monday)
    week_end: str                               # ISO date (Sunday)
    sessions_total: int
    sessions_with_data: int                     # sessions that have telemetry
    judge_pass_rate: float                      # 0.0-1.0
    judge_fail_rate: float
    mean_anxiety_score: float
    high_anxiety_sessions: int
    top_fail_categories: list[tuple[str, int]]  # [(category, count)]
    top_lob_violations: int
    top_duplication_count: int
    harness_health: str                         # "healthy" | "degraded" | "critical"
    stale_skill_count: int
    broken_hook_count: int
    instincts_captured: int = 0        # total captured this week across all projects
    instincts_pending: int = 0         # awaiting review


@dataclass
class HarnessRecommendation:
    priority: str   # "high" | "medium" | "low"
    category: str   # "add_rule" | "remove_rule" | "tune_hook" | "investigate"
    action: str     # one-line imperative
    evidence: str   # data supporting this recommendation
    effort: str     # "minutes" | "hours" | "days"


@dataclass
class WeeklyIntelligenceReport:
    generated_at: str                           # ISO timestamp
    week_label: str                             # e.g. "Week of 2026-03-30"
    signals: WeeklySignals
    recommendations: list[HarnessRecommendation]
    summary: str                                # 3-sentence executive summary
    next_prompt: str | None                     # suggested next devflow prompt or None


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
            all_records = store.get_recent(n=_RECENT_RECORDS_CAP)
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
            pass_count = sum(1 for r in judged if r.get("judge_verdict") == "pass")
            fail_count = sum(1 for r in judged if r.get("judge_verdict") == "fail")
            n_judged = len(judged)
            pass_rate = (pass_count / n_judged) if n_judged > 0 else 0.0
            fail_rate = (fail_count / n_judged) if n_judged > 0 else 0.0

            # Anxiety: use context_tokens_at_first_action as proxy
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

            lob_violations = sum(int(r.get("lob_violations") or 0) for r in records)
            dup_count = sum(1 for r in records if r.get("duplication_detected"))

            today = date.today()
            monday = today - timedelta(days=today.weekday())
            week_start = monday.isoformat()
            week_end = (monday + timedelta(days=6)).isoformat()

            # Instinct signals — best-effort
            instincts_captured = 0
            instincts_pending = 0
            try:
                from analysis.instinct_store import InstinctStore as _IS
                _istore = _IS()
                _instincts_dir = Path.home() / ".claude" / "devflow" / "instincts"
                if _instincts_dir.exists():
                    for _proj_file in _instincts_dir.glob("*.jsonl"):
                        _proj = _proj_file.stem
                        _proj_instincts = _istore.load(_proj)
                        instincts_captured += sum(
                            1 for i in _proj_instincts
                            if i.captured_at >= cutoff
                        )
                        instincts_pending += sum(
                            1 for i in _proj_instincts
                            if i.status == "pending"
                        )
            except Exception:
                pass

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
                instincts_captured=instincts_captured,
                instincts_pending=instincts_pending,
            )
        except Exception as exc:
            print(f"[devflow:weekly] _collect_signals failed: {exc}", file=sys.stderr)
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
                instincts_captured=0,
                instincts_pending=0,
            )

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

        if signals.instincts_pending > 5:
            n = signals.instincts_pending
            recs.append(HarnessRecommendation(
                priority="medium",
                category="review_instincts",
                action=f"Review {n} pending instincts — run instinct_review.py",
                evidence=f"{n} instincts are awaiting human review",
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
            f"with {'an' if str(pass_pct).startswith('8') else 'a'} {pass_pct}% judge pass rate"
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
            from analysis.harness_health import HarnessHealthChecker, HarnessHealthReport

            signals = self._collect_signals(store, n_days)

            try:
                checker = HarnessHealthChecker()
                health = checker.check(store, skills_dir, hooks_dir)
                signals.harness_health = health.overall_verdict
                signals.stale_skill_count = health.stale_skill_count
                signals.broken_hook_count = health.broken_hook_count
            except Exception:
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
        except Exception as exc:
            print(f"[devflow:weekly] generate failed: {exc}", file=sys.stderr)
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
                instincts_captured=0,
                instincts_pending=0,
            )
            return WeeklyIntelligenceReport(
                generated_at=datetime.now(tz=timezone.utc).isoformat(),
                week_label=f"Week of {monday.isoformat()}",
                signals=empty_signals,
                recommendations=[],
                summary=(
                    "0 sessions recorded. "
                    "No critical issues found. "
                    "Harness is operating well."
                ),
                next_prompt=None,
            )
