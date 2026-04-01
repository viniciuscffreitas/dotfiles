"""Tests for TaskRiskProfiler and pre_task_profiler hook."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from risk.profiler import OversightLevel, RiskProfile, TaskRiskProfiler

# ---------------------------------------------------------------------------
# score_probability
# ---------------------------------------------------------------------------


class TestScoreProbability:
    def setup_method(self):
        self.p = TaskRiskProfiler()

    def test_low_risk_profile(self):
        ctx = {
            "stack": "typescript",
            "context_coverage": "full",
            "task_complexity": "trivial",
            "codebase_health": "clean",
        }
        assert self.p.score_probability(ctx) < 0.25

    def test_high_risk_profile(self):
        ctx = {
            "stack": "other",
            "context_coverage": "sparse",
            "task_complexity": "complex",
            "codebase_health": "legacy",
        }
        assert self.p.score_probability(ctx) > 0.60

    def test_medium_risk_profile(self):
        ctx = {
            "stack": "dart",
            "context_coverage": "partial",
            "task_complexity": "simple",
            "codebase_health": "mixed",
        }
        score = self.p.score_probability(ctx)
        assert 0.30 < score < 0.55

    def test_missing_keys_no_key_error(self):
        score = self.p.score_probability({})
        assert 0.0 <= score <= 1.0

    def test_unknown_values_no_key_error(self):
        ctx = {
            "stack": "cobol",
            "context_coverage": "unknown",
            "task_complexity": "???",
            "codebase_health": "disaster",
        }
        score = self.p.score_probability(ctx)
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# score_impact
# ---------------------------------------------------------------------------


class TestScoreImpact:
    def setup_method(self):
        self.p = TaskRiskProfiler()

    def test_production_dominates(self):
        ctx = {
            "is_production": True,
            "files_to_modify": ["a.py"],  # isolated
            "has_external_dependency": False,
        }
        assert self.p.score_impact(ctx) == pytest.approx(0.80)

    def test_wide_radius_dominates(self):
        ctx = {
            "is_production": False,
            "files_to_modify": ["a", "b", "c", "d", "e", "f"],  # 6 = wide
            "has_external_dependency": False,
        }
        assert self.p.score_impact(ctx) == pytest.approx(0.80)

    def test_low_impact_all_safe(self):
        ctx = {
            "is_production": False,
            "files_to_modify": ["a.py"],  # isolated
            "has_external_dependency": False,
        }
        assert self.p.score_impact(ctx) < 0.25

    def test_external_dependency_with_moderate_radius(self):
        ctx = {
            "is_production": False,
            "files_to_modify": ["a.py", "b.py", "c.py"],  # moderate (3)
            "has_external_dependency": True,
        }
        # moderate=0.40, external=0.30, production=False=0.20 → max = 0.40
        assert self.p.score_impact(ctx) == pytest.approx(0.40)

    def test_missing_keys_no_key_error(self):
        score = self.p.score_impact({})
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# score_detectability
# ---------------------------------------------------------------------------


class TestScoreDetectability:
    def setup_method(self):
        self.p = TaskRiskProfiler()

    def test_high_coverage_typed_e2e(self):
        ctx = {
            "test_coverage": "high",
            "typed_language": True,
            "has_e2e": True,
        }
        assert self.p.score_detectability(ctx) < 0.20

    def test_low_coverage_untyped_no_e2e(self):
        ctx = {
            "test_coverage": "low",
            "typed_language": False,
            "has_e2e": False,
        }
        # weights (0.50,0.30,0.20) × values (0.80,0.40,0.30) = 0.58 — higher than medium
        assert self.p.score_detectability(ctx) > 0.50

    def test_medium_coverage_typed_no_e2e(self):
        ctx = {
            "test_coverage": "medium",
            "typed_language": True,
            "has_e2e": False,
        }
        # weights (0.50,0.30,0.20) × values (0.40,0.10,0.30) = 0.29 — between high and low
        score = self.p.score_detectability(ctx)
        assert 0.20 < score < 0.45

    def test_missing_keys_no_key_error(self):
        score = self.p.score_detectability({})
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# determine_oversight_level
# ---------------------------------------------------------------------------


class TestDetermineOversightLevel:
    def setup_method(self):
        self.p = TaskRiskProfiler()

    def test_all_zeros_is_vibe(self):
        assert self.p.determine_oversight_level(0.0, 0.0, 0.0) == OversightLevel.VIBE

    def test_low_values_is_vibe(self):
        assert self.p.determine_oversight_level(0.20, 0.20, 0.20) == OversightLevel.VIBE

    def test_mid_values_is_standard(self):
        assert self.p.determine_oversight_level(0.40, 0.40, 0.40) == OversightLevel.STANDARD

    def test_high_impact_is_strict(self):
        # i=0.70 > 0.60 → strict
        assert self.p.determine_oversight_level(0.20, 0.70, 0.30) == OversightLevel.STRICT

    def test_high_prob_and_detectability_is_strict(self):
        # p=0.55 > 0.50 and d=0.50 > 0.40 → strict
        assert self.p.determine_oversight_level(0.55, 0.30, 0.50) == OversightLevel.STRICT

    def test_human_review_threshold(self):
        # i=0.80 > 0.75 and d=0.70 > 0.60 → human_review
        assert self.p.determine_oversight_level(0.20, 0.80, 0.70) == OversightLevel.HUMAN_REVIEW

    def test_human_review_takes_precedence_over_strict(self):
        # Both strict (i > 0.60) AND human_review (i > 0.75, d > 0.60) conditions met
        assert self.p.determine_oversight_level(0.60, 0.80, 0.70) == OversightLevel.HUMAN_REVIEW


# ---------------------------------------------------------------------------
# profile()
# ---------------------------------------------------------------------------


class TestProfile:
    def setup_method(self):
        self.p = TaskRiskProfiler()

    def _full_ctx(self):
        return {
            "stack": "python",
            "context_coverage": "partial",
            "task_complexity": "simple",
            "codebase_health": "clean",
            "is_production": False,
            "files_to_modify": ["a.py", "b.py"],
            "has_external_dependency": False,
            "test_coverage": "high",
            "typed_language": True,
            "has_e2e": False,
        }

    def test_returns_risk_profile_dataclass(self):
        result = self.p.profile(self._full_ctx())
        assert isinstance(result, RiskProfile)

    def test_result_has_all_fields(self):
        result = self.p.profile(self._full_ctx())
        assert hasattr(result, "probability")
        assert hasattr(result, "impact")
        assert hasattr(result, "detectability")
        assert hasattr(result, "oversight_level")
        assert hasattr(result, "factors")

    def test_factors_dict_contains_inputs(self):
        ctx = self._full_ctx()
        result = self.p.profile(ctx)
        assert isinstance(result.factors, dict)
        assert len(result.factors) > 0

    def test_never_raises_on_empty_context(self):
        result = self.p.profile({})
        assert isinstance(result, RiskProfile)

    def test_never_raises_on_malformed_context(self):
        result = self.p.profile({"stack": 123, "files_to_modify": "not-a-list", "typed_language": "yes"})
        assert isinstance(result, RiskProfile)

    def test_scores_are_floats_in_range(self):
        result = self.p.profile(self._full_ctx())
        for score in (result.probability, result.impact, result.detectability):
            assert isinstance(score, float)
            assert 0.0 <= score <= 1.0

    def test_oversight_level_is_enum(self):
        result = self.p.profile(self._full_ctx())
        assert isinstance(result.oversight_level, OversightLevel)


# ---------------------------------------------------------------------------
# pre_task_profiler hook
# ---------------------------------------------------------------------------


class TestPreTaskProfilerHook:
    """Tests for hooks/pre_task_profiler.py. Imported after profiler exists."""

    def _import_hook(self):
        import importlib
        hook_dir = Path(__file__).parent.parent
        sys.path.insert(0, str(hook_dir))
        import pre_task_profiler
        importlib.reload(pre_task_profiler)
        return pre_task_profiler

    def test_writes_risk_profile_json(self, tmp_path, monkeypatch):
        hook = self._import_hook()
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        monkeypatch.setattr(hook, "_get_state_dir", lambda: state_dir)
        monkeypatch.setattr(hook, "_load_context", lambda sd: {})
        with patch("pre_task_profiler.TelemetryStore"):
            hook.run(state_dir)
        profile_file = state_dir / "risk-profile.json"
        assert profile_file.exists()
        data = json.loads(profile_file.read_text())
        assert "oversight_level" in data
        assert "probability" in data
        assert "impact" in data
        assert "detectability" in data

    def test_prints_correct_format(self, tmp_path, monkeypatch, capsys):
        hook = self._import_hook()
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        monkeypatch.setattr(hook, "_get_state_dir", lambda: state_dir)
        monkeypatch.setattr(hook, "_load_context", lambda sd: {})
        with patch("pre_task_profiler.TelemetryStore"):
            hook.run(state_dir)
        captured = capsys.readouterr()
        assert "[devflow:risk]" in captured.out
        assert "oversight=" in captured.out
        assert "probability=" in captured.out
        assert "detectability=" in captured.out

    def test_calls_telemetry_store_record(self, tmp_path, monkeypatch):
        hook = self._import_hook()
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        monkeypatch.setattr(hook, "_get_state_dir", lambda: state_dir)
        monkeypatch.setattr(hook, "_load_context", lambda sd: {})
        mock_store = MagicMock()
        with patch("pre_task_profiler.TelemetryStore", return_value=mock_store):
            hook.run(state_dir)
        mock_store.record.assert_called_once()
        call_kwargs = mock_store.record.call_args[0][0]
        assert "probability_score" in call_kwargs
        assert "impact_score" in call_kwargs
        assert "detectability_score" in call_kwargs
        assert "oversight_level" in call_kwargs

    def test_handles_missing_project_profile_gracefully(self, tmp_path, monkeypatch):
        hook = self._import_hook()
        state_dir = tmp_path / "state_empty"
        state_dir.mkdir()
        monkeypatch.setattr(hook, "_get_state_dir", lambda: state_dir)
        # no project-profile.json present — _load_context reads real files
        with patch("pre_task_profiler.TelemetryStore"):
            hook.run(state_dir)  # must not raise
