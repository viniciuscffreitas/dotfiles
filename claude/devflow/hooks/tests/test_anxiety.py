"""Tests for ContextAnxietyDetector — Context Anxiety analysis module."""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# devflow root is three levels up from hooks/tests/
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
# hooks/ dir for anxiety_report CLI import
sys.path.insert(0, str(Path(__file__).parent.parent))

from analysis.context_anxiety import (
    AnxietyReport,
    AnxietyScore,
    ContextAnxietyDetector,
)


# ---------------------------------------------------------------------------
# AnxietyScore — dataclass and verdict thresholds
# ---------------------------------------------------------------------------

class TestAnxietyScoreDataclass:
    def test_instantiates_with_correct_field_types(self):
        score = AnxietyScore(
            session_id="abc",
            task_category="feature",
            raw_score=0.5,
            read_write_ratio=0.6,
            investigation_depth=8,
            first_write_index=8,
            verdict="medium",
            evidence=["some signal"],
        )
        assert isinstance(score.session_id, str)
        assert isinstance(score.task_category, str)
        assert isinstance(score.raw_score, float)
        assert isinstance(score.read_write_ratio, float)
        assert isinstance(score.investigation_depth, int)
        assert isinstance(score.first_write_index, int)
        assert isinstance(score.verdict, str)
        assert isinstance(score.evidence, list)

    def test_verdict_low_when_raw_score_below_0_4(self):
        detector = ContextAnxietyDetector()
        assert detector._classify_verdict(0.0) == "low"
        assert detector._classify_verdict(0.39) == "low"
        assert detector._classify_verdict(0.3) == "low"

    def test_verdict_medium_when_raw_score_0_4_to_0_69(self):
        detector = ContextAnxietyDetector()
        assert detector._classify_verdict(0.4) == "medium"
        assert detector._classify_verdict(0.5) == "medium"
        assert detector._classify_verdict(0.69) == "medium"

    def test_verdict_high_when_raw_score_0_7_or_above(self):
        detector = ContextAnxietyDetector()
        assert detector._classify_verdict(0.7) == "high"
        assert detector._classify_verdict(0.95) == "high"
        assert detector._classify_verdict(1.0) == "high"


# ---------------------------------------------------------------------------
# _compute_composite
# ---------------------------------------------------------------------------

class TestComputeComposite:
    def setup_method(self):
        self.detector = ContextAnxietyDetector()

    def test_depth_0_ratio_0_gives_0(self):
        assert self.detector._compute_composite(0, 0.0) == pytest.approx(0.0)

    def test_depth_15_ratio_1_gives_1(self):
        assert self.detector._compute_composite(15, 1.0) == pytest.approx(1.0)

    def test_depth_10_ratio_0_5_gives_approx_0_6(self):
        # (min(10/15, 1.0) * 0.6) + (0.5 * 0.4) = (0.6667 * 0.6) + 0.2 ≈ 0.6
        result = self.detector._compute_composite(10, 0.5)
        assert result == pytest.approx(0.6, abs=0.01)

    def test_depth_above_15_clamped_to_1(self):
        # Without clamp: 20/15 * 0.6 = 0.8 — with clamp: 1.0 * 0.6 = 0.6
        result = self.detector._compute_composite(20, 0.0)
        assert result == pytest.approx(0.6)
        # Also verify full clamp at ratio=1
        assert self.detector._compute_composite(100, 1.0) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# score_session
# ---------------------------------------------------------------------------

class TestScoreSession:
    def setup_method(self):
        self.detector = ContextAnxietyDetector()

    def test_write_as_first_op_gives_zero_depth_and_low_score(self):
        session = {
            "task_id": "s1",
            "investigation_depth": 0,
            "first_write_index": 0,
            "read_write_ratio": 0.0,
        }
        score = self.detector.score_session(session)
        assert score.investigation_depth == 0
        assert score.raw_score == pytest.approx(0.0)
        assert score.verdict == "low"

    def test_15_reads_before_write_gives_high_score(self):
        session = {
            "task_id": "s2",
            "investigation_depth": 15,
            "first_write_index": 15,
            "read_write_ratio": 1.0,
        }
        score = self.detector.score_session(session)
        assert score.raw_score == pytest.approx(1.0)
        assert score.verdict == "high"

    def test_no_write_found_score_near_1(self):
        session = {
            "task_id": "s3",
            "investigation_depth": 15,
            "first_write_index": 999,
            "read_write_ratio": 1.0,
        }
        score = self.detector.score_session(session)
        assert score.first_write_index == 999
        assert score.raw_score >= 0.9

    def test_empty_session_gives_insufficient_data(self):
        score = self.detector.score_session({})
        assert score.raw_score == 0.0
        assert score.evidence == ["insufficient data"]

    def test_depth_above_10_adds_depth_evidence(self):
        session = {
            "investigation_depth": 12,
            "first_write_index": 12,
            "read_write_ratio": 0.5,
        }
        score = self.detector.score_session(session)
        assert any("12 operations" in e for e in score.evidence)

    def test_ratio_above_0_8_adds_ratio_evidence(self):
        session = {
            "investigation_depth": 5,
            "first_write_index": 5,
            "read_write_ratio": 0.9,
        }
        score = self.detector.score_session(session)
        assert any("80%" in e for e in score.evidence)

    def test_judge_fail_with_high_score_adds_correlation_evidence(self):
        # depth=12, ratio=0.9 → score = (12/15*0.6)+(0.9*0.4) = 0.48+0.36 = 0.84 > 0.5
        session = {
            "investigation_depth": 12,
            "first_write_index": 12,
            "read_write_ratio": 0.9,
            "judge_verdict": "fail",
        }
        score = self.detector.score_session(session)
        assert score.raw_score > 0.5
        assert any("correlated" in e for e in score.evidence)

    def test_never_raises_on_any_input(self):
        bad_inputs = [
            None,
            {},
            "not a dict",
            42,
            [],
            {"investigation_depth": "bad_value"},
            {"context_anxiety_score": "not_a_float"},
            {"investigation_depth": None, "context_tokens_at_first_action": None},
        ]
        for inp in bad_inputs:
            result = self.detector.score_session(inp)  # type: ignore[arg-type]
            assert result.raw_score == 0.0, f"Expected 0.0 for input {inp!r}"
            assert "insufficient data" in result.evidence


# ---------------------------------------------------------------------------
# analyze_store
# ---------------------------------------------------------------------------

def _make_sessions(n: int) -> list[dict]:
    return [
        {
            "task_id": f"task_{i}",
            "investigation_depth": i * 2,
            "first_write_index": i * 2 + 1,
            "read_write_ratio": min(i * 0.1, 1.0),
            "task_category": "feature" if i % 2 == 0 else "bugfix",
        }
        for i in range(n)
    ]


class TestAnalyzeStore:
    def setup_method(self):
        self.detector = ContextAnxietyDetector()

    def _mock_store(self, sessions: list[dict]) -> MagicMock:
        store = MagicMock()
        store.get_context_anxiety_cases.return_value = sessions
        return store

    def test_returns_anxiety_report(self):
        report = self.detector.analyze_store(self._mock_store(_make_sessions(3)), n=3)
        assert isinstance(report, AnxietyReport)

    def test_sessions_analyzed_equals_n(self):
        sessions = _make_sessions(3)
        report = self.detector.analyze_store(self._mock_store(sessions), n=3)
        assert report.sessions_analyzed == 3

    def test_counts_sum_to_sessions_analyzed(self):
        report = self.detector.analyze_store(self._mock_store(_make_sessions(3)), n=3)
        total = (
            report.high_anxiety_count
            + report.medium_anxiety_count
            + report.low_anxiety_count
        )
        assert total == report.sessions_analyzed

    def test_mean_score_is_correct_average(self):
        sessions = [
            {"task_id": "a", "investigation_depth": 0, "first_write_index": 0, "read_write_ratio": 0.0, "task_category": "c"},
            {"task_id": "b", "investigation_depth": 15, "first_write_index": 15, "read_write_ratio": 1.0, "task_category": "c"},
        ]
        report = self.detector.analyze_store(self._mock_store(sessions), n=2)
        # score(a)=0.0, score(b)=1.0 → mean=0.5
        assert report.mean_score == pytest.approx(0.5, abs=0.001)

    def test_top_anxious_categories_sorted_descending(self):
        sessions = [
            {"task_id": "a", "investigation_depth": 15, "first_write_index": 15, "read_write_ratio": 1.0, "task_category": "high_cat"},
            {"task_id": "b", "investigation_depth": 0, "first_write_index": 0, "read_write_ratio": 0.0, "task_category": "low_cat"},
        ]
        report = self.detector.analyze_store(self._mock_store(sessions), n=2)
        category_scores = [s for _, s in report.top_anxious_categories]
        assert category_scores == sorted(category_scores, reverse=True)

    def test_recommendation_is_non_empty_string(self):
        report = self.detector.analyze_store(self._mock_store(_make_sessions(3)), n=3)
        assert isinstance(report.recommendation, str)
        assert len(report.recommendation) > 0

    def test_generated_at_is_valid_iso_timestamp(self):
        report = self.detector.analyze_store(self._mock_store(_make_sessions(3)), n=3)
        dt = datetime.fromisoformat(report.generated_at)
        assert dt is not None


# ---------------------------------------------------------------------------
# AnxietyReport
# ---------------------------------------------------------------------------

class TestAnxietyReport:
    def test_scores_list_has_one_entry_per_analyzed_session(self):
        detector = ContextAnxietyDetector()
        n = 5
        sessions = _make_sessions(n)
        store = MagicMock()
        store.get_context_anxiety_cases.return_value = sessions
        report = detector.analyze_store(store, n=n)
        assert len(report.scores) == n


# ---------------------------------------------------------------------------
# anxiety_report CLI
# ---------------------------------------------------------------------------

def _cli_mock_store(n: int = 3) -> MagicMock:
    store = MagicMock()
    store.get_context_anxiety_cases.return_value = [
        {
            "task_id": f"cli_{i}",
            "investigation_depth": i * 3,
            "first_write_index": i * 3 + 1,
            "read_write_ratio": min(i * 0.2, 1.0),
            "task_category": "feature",
        }
        for i in range(n)
    ]
    return store


class TestAnxietyReportCLI:
    def test_cli_runs_without_error(self, capsys):
        import anxiety_report
        with patch("anxiety_report.TelemetryStore", return_value=_cli_mock_store()):
            anxiety_report.main([])
        out = capsys.readouterr().out
        assert out  # non-empty output

    def test_json_flag_outputs_parseable_json_with_correct_keys(self, capsys):
        import anxiety_report
        with patch("anxiety_report.TelemetryStore", return_value=_cli_mock_store()):
            anxiety_report.main(["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        for key in ("sessions_analyzed", "high_anxiety_count", "mean_score", "scores", "recommendation", "generated_at"):
            assert key in data, f"Missing key: {key}"

    def test_default_output_starts_with_devflow_anxiety(self, capsys):
        import anxiety_report
        with patch("anxiety_report.TelemetryStore", return_value=_cli_mock_store()):
            anxiety_report.main([])
        out = capsys.readouterr().out
        assert out.startswith("[devflow:anxiety]")
