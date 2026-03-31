"""
Harness Health tracker for devflow.

Detects stale skills, broken hooks, and unnecessary complexity.
Core principle: the harness is healthy when it's as small as possible
while still preventing the failure modes it was built to prevent.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telemetry.store import TelemetryStore


@dataclass
class SkillHealth:
    skill_name: str
    last_used_at: str | None       # ISO timestamp or None
    usage_count: int
    days_since_used: int | None    # None if never used
    verdict: str                   # "active" | "stale" | "unused"
    recommendation: str            # one-line action


@dataclass
class HookHealth:
    hook_name: str
    avg_execution_ms: float | None
    error_rate: float              # 0.0-1.0
    last_triggered_at: str | None
    verdict: str                   # "healthy" | "slow" | "broken" | "idle"
    recommendation: str


@dataclass
class HarnessHealthReport:
    generated_at: str              # ISO timestamp
    overall_verdict: str           # "healthy" | "degraded" | "critical"
    skill_health: list[SkillHealth]
    hook_health: list[HookHealth]
    stale_skill_count: int
    broken_hook_count: int
    simplification_candidates: list[str]
    complexity_score: float        # 0.0-1.0, higher = more bloat
    summary: str                   # 2-sentence human-readable summary


class HarnessHealthChecker:

    STALE_DAYS_THRESHOLD = 14
    SLOW_MS_THRESHOLD = 5000
    HIGH_ERROR_RATE = 0.2

    def check(
        self,
        store: "TelemetryStore",
        skills_dir: Path,
        hooks_dir: Path,
    ) -> HarnessHealthReport:
        """Orchestrates all checks. Never raises."""
        try:
            skills = self._check_skills(skills_dir, store)
            hooks = self._check_hooks(hooks_dir, store)

            stale_skill_count = sum(1 for s in skills if s.verdict == "stale")
            broken_hook_count = sum(1 for h in hooks if h.verdict == "broken")

            complexity_score = self._compute_complexity_score(skills, hooks)
            candidates = self._build_simplification_candidates(skills, hooks)
            overall = self._overall_verdict(complexity_score, broken_hook_count)

            if overall == "healthy":
                summary = (
                    "Harness is operating within expected parameters. "
                    "No immediate action required."
                )
            elif overall == "degraded":
                summary = (
                    f"Harness has {stale_skill_count} stale skill(s) adding complexity. "
                    "Review simplification candidates."
                )
            else:
                summary = (
                    f"Harness has {broken_hook_count} broken hook(s) requiring immediate attention. "
                    "Check error rates."
                )

            return HarnessHealthReport(
                generated_at=datetime.now(tz=timezone.utc).isoformat(),
                overall_verdict=overall,
                skill_health=skills,
                hook_health=hooks,
                stale_skill_count=stale_skill_count,
                broken_hook_count=broken_hook_count,
                simplification_candidates=candidates,
                complexity_score=round(complexity_score, 4),
                summary=summary,
            )
        except Exception:
            return HarnessHealthReport(
                generated_at=datetime.now(tz=timezone.utc).isoformat(),
                overall_verdict="healthy",
                skill_health=[],
                hook_health=[],
                stale_skill_count=0,
                broken_hook_count=0,
                simplification_candidates=[],
                complexity_score=0.0,
                summary="Health check failed to run. Defaulting to healthy.",
            )

    def _check_skills(
        self, skills_dir: Path, store: "TelemetryStore"
    ) -> list[SkillHealth]:
        results = []
        try:
            skill_files = list(skills_dir.glob("*.md")) if skills_dir.exists() else []
        except Exception:
            return []

        for skill_file in skill_files:
            skill_name = skill_file.stem
            try:
                usage = store.get_skill_usage(skill_name)
            except Exception:
                usage = {"last_used_at": None, "usage_count": 0}

            last_used_at = usage.get("last_used_at")
            usage_count = usage.get("usage_count", 0)

            days_since_used: int | None = None
            if last_used_at:
                try:
                    last_dt = datetime.fromisoformat(last_used_at)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    days_since_used = (datetime.now(tz=timezone.utc) - last_dt).days
                except Exception:
                    pass

            if usage_count == 0:
                verdict = "unused"
                recommendation = "Consider removing — no usage recorded"
            elif days_since_used is not None and days_since_used >= self.STALE_DAYS_THRESHOLD:
                verdict = "stale"
                recommendation = f"Review or remove — last used {days_since_used} days ago"
            else:
                verdict = "active"
                recommendation = "Keep"

            results.append(SkillHealth(
                skill_name=skill_name,
                last_used_at=last_used_at,
                usage_count=usage_count,
                days_since_used=days_since_used,
                verdict=verdict,
                recommendation=recommendation,
            ))

        return results

    def _check_hooks(
        self, hooks_dir: Path, store: "TelemetryStore"
    ) -> list[HookHealth]:
        results = []
        try:
            if not hooks_dir.exists():
                return []
            hook_files = [
                f for f in hooks_dir.glob("*.py")
                if f.name != "__init__.py"
                and not f.name.startswith("_")
                and not f.name.endswith("_report.py")
            ]
        except Exception:
            return []

        for hook_file in hook_files:
            hook_name = hook_file.stem
            try:
                stats = store.get_hook_stats(hook_name)
            except Exception:
                stats = {"avg_execution_ms": None, "error_rate": 0.0, "last_triggered_at": None}

            avg_ms = stats.get("avg_execution_ms")
            error_rate = stats.get("error_rate", 0.0)
            last_triggered_at = stats.get("last_triggered_at")

            if error_rate > self.HIGH_ERROR_RATE:
                verdict = "broken"
                recommendation = f"Investigate — {error_rate:.0%} error rate"
            elif avg_ms is not None and avg_ms > self.SLOW_MS_THRESHOLD:
                verdict = "slow"
                recommendation = f"Optimize — avg {avg_ms:.0f}ms exceeds {self.SLOW_MS_THRESHOLD}ms"
            elif last_triggered_at is None:
                verdict = "idle"
                recommendation = "Verify hook is registered in CLAUDE.md"
            else:
                verdict = "healthy"
                recommendation = "OK"

            results.append(HookHealth(
                hook_name=hook_name,
                avg_execution_ms=avg_ms,
                error_rate=error_rate,
                last_triggered_at=last_triggered_at,
                verdict=verdict,
                recommendation=recommendation,
            ))

        return results

    def _compute_complexity_score(
        self,
        skills: list[SkillHealth],
        hooks: list[HookHealth],
    ) -> float:
        stale_count = sum(1 for s in skills if s.verdict == "stale")
        stale_ratio = stale_count / max(len(skills), 1)

        broken_count = sum(1 for h in hooks if h.verdict == "broken")
        broken_ratio = broken_count / max(len(hooks), 1)

        score = (stale_ratio * 0.5) + (broken_ratio * 0.5)
        return max(0.0, min(1.0, score))

    def _build_simplification_candidates(
        self,
        skills: list[SkillHealth],
        hooks: list[HookHealth],
    ) -> list[str]:
        candidates: list[str] = []
        for s in skills:
            if s.verdict == "unused":
                candidates.append(f"Remove skill '{s.skill_name}' — never used")
            elif s.verdict == "stale":
                candidates.append(
                    f"Review skill '{s.skill_name}' — {s.days_since_used} days since last use"
                )
        for h in hooks:
            if h.verdict == "broken":
                candidates.append(f"Fix hook '{h.hook_name}' — error rate {h.error_rate:.0%}")
            elif h.verdict == "slow":
                candidates.append(f"Optimize hook '{h.hook_name}' — avg {h.avg_execution_ms:.0f}ms")
            elif h.verdict == "idle":
                candidates.append(f"Register hook '{h.hook_name}' in CLAUDE.md")
        return candidates

    def _overall_verdict(
        self,
        complexity_score: float,
        broken_hook_count: int,
    ) -> str:
        if broken_hook_count > 0:
            return "critical"
        if complexity_score > 0.5:
            return "degraded"
        return "healthy"
