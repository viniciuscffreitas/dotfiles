"""
Task Risk Profiler — three-dimension framework: Probability × Impact × Detectability.

Determines the oversight_level that gates verification depth for each task.
Pure module: no I/O, no side effects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class OversightLevel(str, Enum):
    VIBE = "vibe"
    STANDARD = "standard"
    STRICT = "strict"
    HUMAN_REVIEW = "human_review"


@dataclass
class RiskProfile:
    probability: float
    impact: float
    detectability: float
    oversight_level: OversightLevel
    factors: dict = field(default_factory=dict)


_STACK_SCORES: dict[str, float] = {
    "typescript": 0.10,
    "python": 0.20,
    "dart": 0.30,
    "other": 0.50,
}

_COVERAGE_SCORES: dict[str, float] = {
    "full": 0.10,
    "partial": 0.40,
    "sparse": 0.80,
}

_COMPLEXITY_SCORES: dict[str, float] = {
    "trivial": 0.10,
    "simple": 0.30,
    "complex": 0.70,
}

_HEALTH_SCORES: dict[str, float] = {
    "clean": 0.10,
    "mixed": 0.40,
    "legacy": 0.80,
}

_TEST_COVERAGE_SCORES: dict[str, float] = {
    "high": 0.10,
    "medium": 0.40,
    "low": 0.80,
}


class TaskRiskProfiler:

    def score_probability(self, context: dict) -> float:
        """
        Weighted average of four factors:
          stack=0.20, context_coverage=0.35, task_complexity=0.30, codebase_health=0.15
        Missing or unknown keys default to the medium/other value.
        """
        try:
            stack = _STACK_SCORES.get(str(context.get("stack", "")), 0.50)
            coverage = _COVERAGE_SCORES.get(str(context.get("context_coverage", "")), 0.40)
            complexity = _COMPLEXITY_SCORES.get(str(context.get("task_complexity", "")), 0.30)
            health = _HEALTH_SCORES.get(str(context.get("codebase_health", "")), 0.40)

            return (
                stack * 0.20
                + coverage * 0.35
                + complexity * 0.30
                + health * 0.15
            )
        except Exception:
            return 0.0

    def score_impact(self, context: dict) -> float:
        """
        Max of three factors (one high-impact factor dominates):
          is_production: True=0.80, False=0.20
          impact_radius: isolated(1)=0.10, moderate(2-5)=0.40, wide(6+)=0.80
          has_external_dependency: True=0.30, False=0.00
        """
        try:
            is_prod = context.get("is_production", False)
            prod_score = 0.80 if bool(is_prod) else 0.20

            files = context.get("files_to_modify", [])
            if not isinstance(files, (list, tuple)):
                files = []
            n = len(files)
            if n <= 1:
                radius_score = 0.10
            elif n <= 5:
                radius_score = 0.40
            else:
                radius_score = 0.80

            has_ext = context.get("has_external_dependency", False)
            ext_score = 0.30 if bool(has_ext) else 0.00

            return max(prod_score, radius_score, ext_score)
        except Exception:
            return 0.0

    def score_detectability(self, context: dict) -> float:
        """
        Weighted average (higher = harder to detect = more risk):
          test_coverage=0.50, typed_language=0.30, has_e2e=0.20
        """
        try:
            coverage = _TEST_COVERAGE_SCORES.get(str(context.get("test_coverage", "")), 0.40)

            typed = context.get("typed_language", False)
            typed_score = 0.10 if bool(typed) else 0.40

            e2e = context.get("has_e2e", False)
            e2e_score = 0.10 if bool(e2e) else 0.30

            return (
                coverage * 0.50
                + typed_score * 0.30
                + e2e_score * 0.20
            )
        except Exception:
            return 0.0

    def determine_oversight_level(
        self, p: float, i: float, d: float
    ) -> OversightLevel:
        """
        Precedence: human_review > strict > standard > vibe

        human_review: i > 0.75 and d > 0.60
        strict:       i > 0.60 or (p > 0.50 and d > 0.40)
        standard:     max(p, i) < 0.50
        vibe:         max(p, i) < 0.30 and d < 0.30
        """
        if i > 0.75 and d > 0.60:
            return OversightLevel.HUMAN_REVIEW
        if i > 0.60 or (p > 0.50 and d > 0.40):
            return OversightLevel.STRICT
        if max(p, i) < 0.30 and d < 0.30:
            return OversightLevel.VIBE
        return OversightLevel.STANDARD

    def profile(self, context: dict) -> RiskProfile:
        """
        Run all three scorers and determine oversight_level.
        Stores input values in RiskProfile.factors for telemetry.
        Never raises — returns RiskProfile with all zeros on any error.
        """
        try:
            p = self.score_probability(context)
            i = self.score_impact(context)
            d = self.score_detectability(context)
            level = self.determine_oversight_level(p, i, d)
            factors = {
                "stack": context.get("stack"),
                "context_coverage": context.get("context_coverage"),
                "task_complexity": context.get("task_complexity"),
                "codebase_health": context.get("codebase_health"),
                "is_production": context.get("is_production"),
                "files_to_modify_count": len(context.get("files_to_modify", []))
                if isinstance(context.get("files_to_modify"), (list, tuple))
                else 0,
                "has_external_dependency": context.get("has_external_dependency"),
                "test_coverage": context.get("test_coverage"),
                "typed_language": context.get("typed_language"),
                "has_e2e": context.get("has_e2e"),
            }
            return RiskProfile(
                probability=p,
                impact=i,
                detectability=d,
                oversight_level=level,
                factors=factors,
            )
        except Exception:
            return RiskProfile(
                probability=0.0,
                impact=0.0,
                detectability=0.0,
                oversight_level=OversightLevel.VIBE,
                factors={},
            )
