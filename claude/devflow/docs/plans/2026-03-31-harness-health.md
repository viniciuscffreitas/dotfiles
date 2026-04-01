# Harness Health Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a health-monitoring system to the devflow harness that detects stale skills, broken hooks, and unnecessary complexity — so the harness shrinks as models improve.

**Architecture:** Two new TelemetryStore query methods proxy skill usage and hook stats from existing `task_executions` data. A pure `HarnessHealthChecker` class in `analysis/harness_health.py` aggregates the health signals into a `HarnessHealthReport` dataclass. A standalone `hooks/health_report.py` CLI surfaces the report to the user and CI.

**Tech Stack:** Python 3.13, SQLite (via existing TelemetryStore), dataclasses, argparse, pytest, unittest.mock

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `telemetry/store.py` | Modify | Add `get_skill_usage()` and `get_hook_stats()` |
| `analysis/harness_health.py` | Create | Dataclasses + `HarnessHealthChecker` |
| `hooks/health_report.py` | Create | Standalone CLI |
| `hooks/tests/test_harness_health.py` | Create | Full test suite (all 4 tasks) |
| `docs/audit-20260331.md` | Modify | Append Prompt 5 entry |

---

## Task 1: TelemetryStore — `get_skill_usage` and `get_hook_stats`

**Files:**
- Modify: `telemetry/store.py`
- Test: `hooks/tests/test_harness_health.py` (TelemetryStore section)

### Step 1.1: Write the failing tests for `get_skill_usage`

Add to `hooks/tests/test_harness_health.py`:

```python
"""Tests for Harness Health tracker."""
from __future__ import annotations

import contextlib
import io
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

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
```

- [ ] **Step 1.2: Run tests — verify they FAIL**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_harness_health.py::test_get_skill_usage_unknown_skill_returns_zeros hooks/tests/test_harness_health.py::test_get_skill_usage_counts_matching_sessions -v
```

Expected: `AttributeError: 'TelemetryStore' object has no attribute 'get_skill_usage'`

- [ ] **Step 1.3: Implement `get_skill_usage` in `telemetry/store.py`**

Add after the `summary_stats` method (line 188):

```python
def get_skill_usage(self, skill_name: str) -> dict:
    """
    Returns {"last_used_at": str|None, "usage_count": int}.
    Searches skills_loaded for skill_name as a substring.
    Falls back to zeros if the store raises.
    """
    try:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT MAX(timestamp), COUNT(*) FROM task_executions "
                "WHERE skills_loaded LIKE ?",
                (f"%{skill_name}%",),
            ).fetchone()
        return {"last_used_at": row[0], "usage_count": row[1] or 0}
    except Exception:
        return {"last_used_at": None, "usage_count": 0}
```

- [ ] **Step 1.4: Run tests — verify they PASS**

```bash
python3.13 -m pytest hooks/tests/test_harness_health.py::test_get_skill_usage_unknown_skill_returns_zeros hooks/tests/test_harness_health.py::test_get_skill_usage_counts_matching_sessions -v
```

Expected: `2 passed`

### Step 1.5: Write the failing tests for `get_hook_stats`

Append to `hooks/tests/test_harness_health.py`:

```python
# ---------------------------------------------------------------------------
# TelemetryStore.get_hook_stats
# ---------------------------------------------------------------------------

def test_get_hook_stats_unknown_hook_returns_zeroes(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    result = store.get_hook_stats("nonexistent-hook")
    assert result["avg_execution_ms"] is None
    assert result["error_rate"] == 0.0
    assert result["last_triggered_at"] is None


def test_get_hook_stats_never_raises(tmp_path):
    store = TelemetryStore(db_path=tmp_path / "test.db")
    result = store.get_hook_stats("")
    assert isinstance(result, dict)
    assert "error_rate" in result
    assert "last_triggered_at" in result
    assert "avg_execution_ms" in result
```

- [ ] **Step 1.6: Run tests — verify they FAIL**

```bash
python3.13 -m pytest hooks/tests/test_harness_health.py::test_get_hook_stats_unknown_hook_returns_zeroes hooks/tests/test_harness_health.py::test_get_hook_stats_never_raises -v
```

Expected: `AttributeError: 'TelemetryStore' object has no attribute 'get_hook_stats'`

- [ ] **Step 1.7: Implement `get_hook_stats` in `telemetry/store.py`**

Add after `get_skill_usage`:

```python
def get_hook_stats(self, hook_name: str) -> dict:
    """
    Returns {"avg_execution_ms": float|None, "error_rate": float, "last_triggered_at": str|None}.
    Proxies hook activity from rules_triggered and judge_verdict columns.
    avg_execution_ms is always None (not stored).
    Falls back to zeroes if the store raises.
    """
    try:
        with closing(self._connect()) as conn:
            last_row = conn.execute(
                "SELECT MAX(timestamp) FROM task_executions "
                "WHERE rules_triggered LIKE ?",
                (f"%{hook_name}%",),
            ).fetchone()
            total_row = conn.execute(
                "SELECT COUNT(*) FROM task_executions "
                "WHERE rules_triggered LIKE ?",
                (f"%{hook_name}%",),
            ).fetchone()
            fail_row = conn.execute(
                "SELECT COUNT(*) FROM task_executions "
                "WHERE rules_triggered LIKE ? AND judge_verdict = 'fail'",
                (f"%{hook_name}%",),
            ).fetchone()
        total = total_row[0] or 0
        failed = fail_row[0] or 0
        error_rate = (failed / total) if total > 0 else 0.0
        return {
            "avg_execution_ms": None,
            "error_rate": error_rate,
            "last_triggered_at": last_row[0],
        }
    except Exception:
        return {"avg_execution_ms": None, "error_rate": 0.0, "last_triggered_at": None}
```

- [ ] **Step 1.8: Run tests — verify they PASS**

```bash
python3.13 -m pytest hooks/tests/test_harness_health.py::test_get_hook_stats_unknown_hook_returns_zeroes hooks/tests/test_harness_health.py::test_get_hook_stats_never_raises -v
```

Expected: `2 passed`

- [ ] **Step 1.9: Commit**

```bash
cd /Users/vini/.claude/devflow
git add telemetry/store.py hooks/tests/test_harness_health.py
git commit -m "feat(telemetry): add get_skill_usage and get_hook_stats to TelemetryStore"
```

---

## Task 2: `analysis/harness_health.py` — dataclasses + HarnessHealthChecker

**Files:**
- Create: `analysis/harness_health.py`
- Test: `hooks/tests/test_harness_health.py` (checker section)

### Step 2.1: Write the failing tests for SkillHealth verdict logic

Append to `hooks/tests/test_harness_health.py`:

```python
# ---------------------------------------------------------------------------
# SkillHealth verdict rules
# ---------------------------------------------------------------------------

def _active_skill(name: str = "my-skill") -> SkillHealth:
    return SkillHealth(
        skill_name=name,
        last_used_at=datetime.now(tz=timezone.utc).isoformat(),
        usage_count=5,
        days_since_used=1,
        verdict="active",
        recommendation="Keep",
    )


def _stale_skill(name: str = "old-skill", days: int = 20) -> SkillHealth:
    ts = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
    return SkillHealth(
        skill_name=name,
        last_used_at=ts,
        usage_count=2,
        days_since_used=days,
        verdict="stale",
        recommendation=f"Review or remove — last used {days} days ago",
    )


def _unused_skill(name: str = "dead-skill") -> SkillHealth:
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
```

- [ ] **Step 2.2: Run tests — verify they FAIL**

```bash
python3.13 -m pytest hooks/tests/test_harness_health.py -k "test_skill_health" -v
```

Expected: `ImportError` (harness_health module does not exist yet)

- [ ] **Step 2.3: Create `analysis/harness_health.py` with dataclasses**

```python
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
```

- [ ] **Step 2.4: Run SkillHealth tests — verify they PASS**

```bash
python3.13 -m pytest hooks/tests/test_harness_health.py -k "test_skill_health" -v
```

Expected: `4 passed`

### Step 2.5: Write the failing tests for HookHealth verdict logic

Append to `hooks/tests/test_harness_health.py`:

```python
# ---------------------------------------------------------------------------
# HookHealth verdict rules
# ---------------------------------------------------------------------------

def _healthy_hook(name: str = "good-hook") -> HookHealth:
    return HookHealth(
        hook_name=name,
        avg_execution_ms=200.0,
        error_rate=0.0,
        last_triggered_at=datetime.now(tz=timezone.utc).isoformat(),
        verdict="healthy",
        recommendation="OK",
    )


def _broken_hook(name: str = "bad-hook", error_rate: float = 0.5) -> HookHealth:
    return HookHealth(
        hook_name=name,
        avg_execution_ms=100.0,
        error_rate=error_rate,
        last_triggered_at=datetime.now(tz=timezone.utc).isoformat(),
        verdict="broken",
        recommendation=f"Investigate — {error_rate:.0%} error rate",
    )


def _slow_hook(name: str = "slow-hook", avg_ms: float = 8000.0) -> HookHealth:
    return HookHealth(
        hook_name=name,
        avg_execution_ms=avg_ms,
        error_rate=0.0,
        last_triggered_at=datetime.now(tz=timezone.utc).isoformat(),
        verdict="slow",
        recommendation=f"Optimize — avg {avg_ms:.0f}ms exceeds 5000ms",
    )


def _idle_hook(name: str = "idle-hook") -> HookHealth:
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
```

- [ ] **Step 2.6: Run HookHealth tests — verify they PASS**

```bash
python3.13 -m pytest hooks/tests/test_harness_health.py -k "test_hook_health" -v
```

Expected: `4 passed`

### Step 2.7: Write the failing tests for `_compute_complexity_score`

Append to `hooks/tests/test_harness_health.py`:

```python
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
```

- [ ] **Step 2.8: Run complexity score tests — verify they PASS**

```bash
python3.13 -m pytest hooks/tests/test_harness_health.py -k "test_complexity_score" -v
```

Expected: `4 passed`

### Step 2.9: Write the failing tests for `_check_skills` (with mock store + tmp_path)

Append to `hooks/tests/test_harness_health.py`:

```python
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
```

- [ ] **Step 2.10: Run `_check_skills` tests — verify they PASS**

```bash
python3.13 -m pytest hooks/tests/test_harness_health.py -k "test_check_skills" -v
```

Expected: `4 passed`

### Step 2.11: Write the failing tests for `_check_hooks` (with mock store + tmp_path)

Append to `hooks/tests/test_harness_health.py`:

```python
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
```

- [ ] **Step 2.12: Run `_check_hooks` tests — verify they PASS**

```bash
python3.13 -m pytest hooks/tests/test_harness_health.py -k "test_check_hooks" -v
```

Expected: `4 passed`

### Step 2.13: Write the failing tests for `_build_simplification_candidates`

Append to `hooks/tests/test_harness_health.py`:

```python
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
```

- [ ] **Step 2.14: Run simplification candidates tests — verify they PASS**

```bash
python3.13 -m pytest hooks/tests/test_harness_health.py -k "test_simplification_candidates" -v
```

Expected: `5 passed`

### Step 2.15: Write the failing tests for `_overall_verdict`

Append to `hooks/tests/test_harness_health.py`:

```python
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
```

- [ ] **Step 2.16: Run `_overall_verdict` tests — verify they PASS**

```bash
python3.13 -m pytest hooks/tests/test_harness_health.py -k "test_overall_verdict" -v
```

Expected: `3 passed`

### Step 2.17: Write the failing tests for `HarnessHealthChecker.check`

Append to `hooks/tests/test_harness_health.py`:

```python
# ---------------------------------------------------------------------------
# HarnessHealthChecker.check (integration)
# ---------------------------------------------------------------------------

def test_checker_check_returns_report_with_correct_counts(tmp_path):
    skills_dir = tmp_path / "skills"
    hooks_dir = tmp_path / "hooks"
    skills_dir.mkdir()
    hooks_dir.mkdir()

    # 1 active skill, 1 stale skill, 1 unused skill
    (skills_dir / "active-skill.md").write_text("content")
    (skills_dir / "stale-skill.md").write_text("content")
    (skills_dir / "unused-skill.md").write_text("content")

    # 1 healthy hook
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
    # error_rate 0.5 → broken verdict → critical overall
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
    # Nonexistent directories — must not raise
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
```

- [ ] **Step 2.18: Run checker integration tests — verify they PASS**

```bash
python3.13 -m pytest hooks/tests/test_harness_health.py -k "test_checker_check" -v
```

Expected: `4 passed`

- [ ] **Step 2.19: Commit**

```bash
cd /Users/vini/.claude/devflow
git add analysis/harness_health.py hooks/tests/test_harness_health.py
git commit -m "feat(analysis): add HarnessHealthChecker with skill/hook health signals"
```

---

## Task 3: `hooks/health_report.py` CLI

**Files:**
- Create: `hooks/health_report.py`
- Test: `hooks/tests/test_harness_health.py` (CLI section)

### Step 3.1: Write the failing tests for the CLI

Append to `hooks/tests/test_harness_health.py`:

```python
# ---------------------------------------------------------------------------
# health_report CLI
# ---------------------------------------------------------------------------

# Lazy import to avoid issues with module-level sys.path insertion
def _import_health_report():
    import importlib
    import hooks.health_report as hr  # noqa: E402
    return hr


def test_health_report_default_output_contains_prefix(tmp_path):
    import hooks.health_report as hr

    store = TelemetryStore(db_path=tmp_path / "test.db")
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        hr.main([], _store=store, _skills_dir=tmp_path / "skills", _hooks_dir=tmp_path / "hooks")
    assert "[devflow:health]" in captured.getvalue()


def test_health_report_json_outputs_valid_json_with_overall_verdict(tmp_path):
    import hooks.health_report as hr

    store = TelemetryStore(db_path=tmp_path / "test.db")
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        hr.main(["--json"], _store=store, _skills_dir=tmp_path / "skills", _hooks_dir=tmp_path / "hooks")
    import json as _json
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

    # Add 3 sessions where 'bad_hook' is rules_triggered and all fail
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
```

- [ ] **Step 3.2: Run CLI tests — verify they FAIL**

```bash
python3.13 -m pytest hooks/tests/test_harness_health.py -k "test_health_report" -v
```

Expected: `ModuleNotFoundError: No module named 'hooks.health_report'`

- [ ] **Step 3.3: Create `hooks/health_report.py`**

```python
#!/usr/bin/env python3.13
"""
devflow harness health report.

Usage:
  python3.13 hooks/health_report.py              # full report
  python3.13 hooks/health_report.py --json       # JSON output
  python3.13 hooks/health_report.py --critical   # exit 1 if critical
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from analysis.harness_health import HarnessHealthChecker
from telemetry.store import TelemetryStore

_SKILLS_DIR = Path.home() / ".claude" / "skills"
_HOOKS_DIR = Path(__file__).parent


def main(
    argv: list[str] | None = None,
    _store: Optional[TelemetryStore] = None,
    _skills_dir: Optional[Path] = None,
    _hooks_dir: Optional[Path] = None,
) -> int:
    parser = argparse.ArgumentParser(description="devflow harness health report")
    parser.add_argument("--json", action="store_true", dest="as_json", help="JSON output")
    parser.add_argument(
        "--critical", action="store_true",
        help="Exit 1 if overall verdict is critical"
    )
    args = parser.parse_args(argv)

    store = _store if _store is not None else TelemetryStore()
    skills_dir = _skills_dir if _skills_dir is not None else _SKILLS_DIR
    hooks_dir = _hooks_dir if _hooks_dir is not None else _HOOKS_DIR

    checker = HarnessHealthChecker()
    report = checker.check(store, skills_dir, hooks_dir)

    if args.as_json:
        print(json.dumps(dataclasses.asdict(report), indent=2))
        return 1 if (args.critical and report.overall_verdict == "critical") else 0

    active = sum(1 for s in report.skill_health if s.verdict == "active")
    stale = sum(1 for s in report.skill_health if s.verdict == "stale")
    unused = sum(1 for s in report.skill_health if s.verdict == "unused")

    healthy_h = sum(1 for h in report.hook_health if h.verdict == "healthy")
    slow_h = sum(1 for h in report.hook_health if h.verdict == "slow")
    broken_h = sum(1 for h in report.hook_health if h.verdict == "broken")
    idle_h = sum(1 for h in report.hook_health if h.verdict == "idle")

    print(
        f"[devflow:health] Overall: {report.overall_verdict.upper()} | "
        f"Skills: {active} active, {stale} stale, {unused} unused"
    )
    print(f"Hooks: {healthy_h} healthy, {slow_h} slow, {broken_h} broken, {idle_h} idle")
    print(f"Complexity score: {report.complexity_score:.2f}")

    if report.simplification_candidates:
        print("\nSimplification candidates:")
        for c in report.simplification_candidates:
            print(f"  - {c}")
    else:
        print("\nSimplification candidates: none")

    print(f"\nSummary: {report.summary}")

    return 1 if (args.critical and report.overall_verdict == "critical") else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3.4: Run CLI tests — verify they PASS**

```bash
python3.13 -m pytest hooks/tests/test_harness_health.py -k "test_health_report" -v
```

Expected: `4 passed`

- [ ] **Step 3.5: Run smoke test**

```bash
cd /Users/vini/.claude/devflow
python3.13 hooks/health_report.py
```

Expected output contains: `[devflow:health] Overall: HEALTHY | Skills:`

- [ ] **Step 3.6: Commit**

```bash
git add hooks/health_report.py hooks/tests/test_harness_health.py
git commit -m "feat(hooks): add health_report CLI with --json and --critical flags"
```

---

## Task 4: Full test suite validation + audit doc

**Files:**
- Verify: `hooks/tests/test_harness_health.py` (full run)
- Modify: `docs/audit-20260331.md`

- [ ] **Step 4.1: Run the full test file**

```bash
cd /Users/vini/.claude/devflow
python3.13 -m pytest hooks/tests/test_harness_health.py -q
```

Expected: All tests in file pass. Count them.

- [ ] **Step 4.2: Run the full test suite (regression check)**

```bash
python3.13 -m pytest hooks/tests/ -q
```

Expected: 435 (baseline) + N new tests, 0 failures.

- [ ] **Step 4.3: Append Prompt 5 entry to audit doc**

Add after the last `###` entry in `docs/audit-20260331.md`:

```markdown
### Prompt 5: Harness Health tracker — N tests added, 435 → M total (`2026-03-31`)

**Files created:**
- `analysis/harness_health.py` — `SkillHealth`, `HookHealth`, `HarnessHealthReport` dataclasses + `HarnessHealthChecker`: `check()` (orchestrates, never raises), `_check_skills()` (scans .md files in skills_dir, queries TelemetryStore.get_skill_usage), `_check_hooks()` (scans *.py in hooks_dir excluding __init__.py, queries TelemetryStore.get_hook_stats), `_compute_complexity_score()` (stale_ratio*0.5 + broken_ratio*0.5), `_build_simplification_candidates()` (one entry per unused/stale skill, broken/slow/idle hook), `_overall_verdict()` (critical > degraded > healthy)
- `hooks/health_report.py` — standalone CLI: `--json` (dataclasses.asdict output), `--critical` (exit 1 if overall_verdict==critical); default output shows `[devflow:health]` summary line + hook counts + complexity score + simplification candidates

**Files modified:**
- `telemetry/store.py` — added `get_skill_usage(skill_name)` (searches skills_loaded LIKE), `get_hook_stats(hook_name)` (proxy from rules_triggered + judge_verdict; avg_execution_ms always None)
- `hooks/tests/test_harness_health.py` — N tests across TelemetryStore, SkillHealth, HookHealth, _compute_complexity_score, _check_skills, _check_hooks, _build_simplification_candidates, _overall_verdict, check(), CLI

**hooks/tests/ baseline:** 435 → M (N net added)
**Smoke test:** `python3.13 hooks/health_report.py` → `[devflow:health] Overall: HEALTHY | Skills: ...` ✓
**Regressions:** 0
```

Replace `N` with actual tests added and `M` with new total before committing.

- [ ] **Step 4.4: Commit audit doc**

```bash
git add docs/audit-20260331.md
git commit -m "docs: document Prompt 5 harness health tracker in audit log"
```

---

## Verification Checklist

- [ ] `python3.13 -m pytest hooks/tests/test_harness_health.py -q` — all tests pass
- [ ] `python3.13 -m pytest hooks/tests/ -q` — no regressions from 435 baseline
- [ ] `python3.13 hooks/health_report.py` — outputs `[devflow:health] Overall: HEALTHY | Skills: ...`
- [ ] `python3.13 hooks/health_report.py --json | python3.13 -c "import sys,json; d=json.load(sys.stdin); print(d['overall_verdict'])"` — outputs `healthy`
- [ ] `python3.13 hooks/health_report.py --critical; echo "exit: $?"` — exits 0
