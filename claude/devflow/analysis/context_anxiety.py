"""
Context Anxiety detector for devflow telemetry.

Measures investigation depth vs. action ratio from session data to detect
the pattern where the agent over-investigates before acting.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telemetry.store import TelemetryStore


@dataclass
class AnxietyScore:
    session_id: str
    task_category: str | None
    raw_score: float           # 0.0–1.0 composite
    read_write_ratio: float    # reads before first write / total reads
    investigation_depth: int   # Read/Bash count before first Write
    first_write_index: int     # index of first write-type op (999 if none)
    verdict: str               # "low" | "medium" | "high"
    evidence: list[str]        # human-readable signals


@dataclass
class AnxietyReport:
    generated_at: str          # ISO timestamp
    sessions_analyzed: int
    high_anxiety_count: int
    medium_anxiety_count: int
    low_anxiety_count: int
    mean_score: float
    top_anxious_categories: list[tuple[str, float]]  # [(category, mean_score)]
    scores: list[AnxietyScore]
    recommendation: str        # one-line action item


class ContextAnxietyDetector:
    ANXIETY_THRESHOLD = 0.7

    def score_session(self, session: dict) -> AnxietyScore:
        """
        Score a session dict from TelemetryStore.

        Resolution order:
          1. context_anxiety_score column (pre-computed)
          2. explicit investigation_depth / read_write_ratio / first_write_index fields
          3. context_tokens_at_first_action proxy
          4. insufficient data → raw_score=0.0, evidence=["insufficient data"]

        Never raises.
        """
        try:
            session_id = str(session.get("task_id") or session.get("session_id") or "")
            task_category = session.get("task_category")
            judge_verdict = session.get("judge_verdict")

            # Path 1: pre-computed score
            if session.get("context_anxiety_score") is not None:
                raw_score = float(session["context_anxiety_score"])
                depth = int(session.get("investigation_depth") or 0)
                ratio = float(session.get("read_write_ratio") or 0.0)
                first_write = self._safe_first_write(session.get("first_write_index"))
                evidence = self._build_evidence(depth, ratio, first_write, raw_score, judge_verdict)
                return AnxietyScore(
                    session_id=session_id,
                    task_category=task_category,
                    raw_score=raw_score,
                    read_write_ratio=ratio,
                    investigation_depth=depth,
                    first_write_index=first_write,
                    verdict=self._classify_verdict(raw_score),
                    evidence=evidence,
                )

            # Path 2: explicit investigation fields
            if session.get("investigation_depth") is not None:
                depth = int(session["investigation_depth"])
                ratio = float(session.get("read_write_ratio") or 0.0)
                first_write = self._safe_first_write(session.get("first_write_index"))
                raw_score = self._compute_composite(depth, ratio)
                evidence = self._build_evidence(depth, ratio, first_write, raw_score, judge_verdict)
                return AnxietyScore(
                    session_id=session_id,
                    task_category=task_category,
                    raw_score=raw_score,
                    read_write_ratio=ratio,
                    investigation_depth=depth,
                    first_write_index=first_write,
                    verdict=self._classify_verdict(raw_score),
                    evidence=evidence,
                )

            # Path 3: proxy from context_tokens_at_first_action
            tokens_at_first = session.get("context_tokens_at_first_action")
            if tokens_at_first is not None and tokens_at_first > 0:
                tokens_total = session.get("context_tokens_consumed") or tokens_at_first
                depth = min(int(tokens_at_first / 5_000), 15)
                ratio = min(tokens_at_first / tokens_total, 1.0) if tokens_total > 0 else 0.5
                raw_score = self._compute_composite(depth, ratio)
                evidence = self._build_evidence(depth, ratio, 999, raw_score, judge_verdict)
                return AnxietyScore(
                    session_id=session_id,
                    task_category=task_category,
                    raw_score=raw_score,
                    read_write_ratio=ratio,
                    investigation_depth=depth,
                    first_write_index=999,
                    verdict=self._classify_verdict(raw_score),
                    evidence=evidence,
                )

        except Exception:
            pass

        # Insufficient data (or exception path)
        session_id_safe = ""
        task_category_safe = None
        try:
            session_id_safe = str(session.get("task_id") or session.get("session_id") or "")  # type: ignore[union-attr]
            task_category_safe = session.get("task_category")  # type: ignore[union-attr]
        except Exception:
            pass

        return AnxietyScore(
            session_id=session_id_safe,
            task_category=task_category_safe,
            raw_score=0.0,
            read_write_ratio=0.0,
            investigation_depth=0,
            first_write_index=999,
            verdict="low",
            evidence=["insufficient data"],
        )

    def analyze_store(self, store: "TelemetryStore", n: int = 50) -> AnxietyReport:
        """Run score_session on up to n sessions from store.get_context_anxiety_cases()."""
        sessions = store.get_context_anxiety_cases()[:n]
        scores = [self.score_session(s) for s in sessions]

        high = sum(1 for s in scores if s.verdict == "high")
        medium = sum(1 for s in scores if s.verdict == "medium")
        low = sum(1 for s in scores if s.verdict == "low")
        mean_score = sum(s.raw_score for s in scores) / len(scores) if scores else 0.0

        category_scores: dict[str, list[float]] = {}
        for s in scores:
            cat = s.task_category or "unknown"
            category_scores.setdefault(cat, []).append(s.raw_score)

        top_anxious = sorted(
            [(cat, sum(vals) / len(vals)) for cat, vals in category_scores.items()],
            key=lambda x: x[1],
            reverse=True,
        )[:5]

        return AnxietyReport(
            generated_at=datetime.now(tz=timezone.utc).isoformat(),
            sessions_analyzed=len(scores),
            high_anxiety_count=high,
            medium_anxiety_count=medium,
            low_anxiety_count=low,
            mean_score=round(mean_score, 4),
            top_anxious_categories=top_anxious,
            scores=scores,
            recommendation=self._generate_recommendation(scores),
        )

    def _classify_verdict(self, score: float) -> str:
        if score < 0.4:
            return "low"
        if score < 0.7:
            return "medium"
        return "high"

    def _compute_composite(self, depth: int, ratio: float) -> float:
        """
        Signal 1 — investigation_depth (weight 0.6):
          depth_normalized = min(depth / 15.0, 1.0)
        Signal 2 — read_write_ratio (weight 0.4):
          Already 0.0–1.0
        composite = (depth_normalized * 0.6) + (ratio * 0.4)
        """
        depth_normalized = min(depth / 15.0, 1.0)
        return (depth_normalized * 0.6) + (ratio * 0.4)

    def _build_evidence(
        self,
        depth: int,
        ratio: float,
        first_write: int,
        raw_score: float,
        judge_verdict: str | None,
    ) -> list[str]:
        evidence = []
        if depth > 10:
            evidence.append(f"Investigated {depth} operations before first write")
        if first_write == 999:
            evidence.append("Session completed no write operations")
        if ratio > 0.8:
            evidence.append("80%+ of reads happened before any write")
        if judge_verdict == "fail" and raw_score > 0.5:
            evidence.append("High anxiety correlated with failed judge verdict")
        return evidence

    def _generate_recommendation(self, scores: list[AnxietyScore]) -> str:
        if not scores:
            return "Collect more session data to generate recommendations."
        high_ratio = sum(1 for s in scores if s.verdict == "high") / len(scores)
        if high_ratio > 0.3:
            return "Add specific file paths to task specs to reduce upfront investigation."
        if high_ratio > 0.1:
            return "Consider breaking large tasks into smaller, more targeted specs."
        return "Context anxiety levels are within acceptable range."

    @staticmethod
    def _safe_first_write(value: object) -> int:
        """Convert first_write_index to int, defaulting to 999 if None."""
        if value is None:
            return 999
        return int(value)  # type: ignore[arg-type]
