"""Tests for HarnessJudge, JudgeRouter, and post_task_judge hook."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from judge.evaluator import JudgePayload, JudgeResult, HarnessJudge
from judge.router import JudgeRouter


# ---------------------------------------------------------------------------
# JudgePayload and JudgeResult
# ---------------------------------------------------------------------------

class TestDataClasses:
    def test_judge_payload_fields(self):
        p = JudgePayload(
            diff="diff --git a/foo.py",
            spec="add feature X",
            harness_rules=["no mocks", "TDD"],
            existing_code="def foo(): pass",
            feature_path="lib/features/user/",
            task_id="abc-123",
        )
        assert p.diff == "diff --git a/foo.py"
        assert p.task_id == "abc-123"
        assert p.harness_rules == ["no mocks", "TDD"]

    def test_judge_result_default_fields(self):
        r = JudgeResult(
            task_id="t1",
            verdict="pass",
            lob_violation=False,
            lob_evidence=None,
            duplication=False,
            duplication_evidence=None,
            type_contract_violation=False,
            type_contract_evidence=None,
            unjustified_complexity=False,
            complexity_evidence=None,
            naming_consistency_score=1.0,
            naming_evidence=None,
            edge_case_coverage="adequate",
            spec_fulfilled="yes",
            spec_evidence=None,
            fail_reasons=[],
            raw_response=None,
        )
        assert r.verdict == "pass"
        assert r.lob_violation is False
        assert r.fail_reasons == []


# ---------------------------------------------------------------------------
# HarnessJudge._build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def setup_method(self):
        self.judge = HarnessJudge()

    def test_prompt_includes_diff(self):
        payload = JudgePayload(
            diff="diff --git a/foo.py\n+def bar(): pass",
            spec="add bar function",
            harness_rules=["no mocks"],
            existing_code="def foo(): pass",
            feature_path="lib/",
            task_id="t1",
        )
        prompt = self.judge._build_prompt(payload)
        assert "diff --git a/foo.py" in prompt

    def test_prompt_includes_spec(self):
        payload = JudgePayload(
            diff="some diff",
            spec="implement feature ZETA",
            harness_rules=[],
            existing_code="",
            feature_path=".",
            task_id="t2",
        )
        prompt = self.judge._build_prompt(payload)
        assert "implement feature ZETA" in prompt

    def test_prompt_includes_harness_rules(self):
        payload = JudgePayload(
            diff="d", spec="s", harness_rules=["rule one", "rule two"],
            existing_code="", feature_path=".", task_id="t3",
        )
        prompt = self.judge._build_prompt(payload)
        assert "rule one" in prompt
        assert "rule two" in prompt

    def test_prompt_system_instruction_no_prose(self):
        payload = JudgePayload(
            diff="d", spec="s", harness_rules=[], existing_code="", feature_path=".", task_id="t4",
        )
        prompt = self.judge._build_prompt(payload)
        assert "Respond ONLY with valid JSON" in prompt

    def test_prompt_includes_feature_path(self):
        payload = JudgePayload(
            diff="d", spec="s", harness_rules=[], existing_code="",
            feature_path="lib/features/user/", task_id="t5",
        )
        prompt = self.judge._build_prompt(payload)
        assert "lib/features/user/" in prompt


# ---------------------------------------------------------------------------
# HarnessJudge._parse_result
# ---------------------------------------------------------------------------

VALID_JUDGE_JSON = {
    "lob_violation": {"result": "no", "evidence": None},
    "duplication": {"result": "no", "evidence": None},
    "type_contract_violation": {"result": "na", "evidence": None},
    "unjustified_complexity": {"result": "no", "evidence": None},
    "naming_consistency": {"score": 0.9, "evidence": None},
    "edge_case_coverage": {"level": "adequate", "missing": []},
    "spec_fulfilled": {"result": "yes", "evidence": None},
    "overall_verdict": "pass",
    "fail_reasons": [],
}

FAIL_JUDGE_JSON = {
    "lob_violation": {"result": "yes", "evidence": "imports from auth feature"},
    "duplication": {"result": "no", "evidence": None},
    "type_contract_violation": {"result": "no", "evidence": None},
    "unjustified_complexity": {"result": "no", "evidence": None},
    "naming_consistency": {"score": 0.8, "evidence": None},
    "edge_case_coverage": {"level": "thorough", "missing": []},
    "spec_fulfilled": {"result": "yes", "evidence": None},
    "overall_verdict": "fail",
    "fail_reasons": ["lob_violation"],
}


class TestParseResult:
    def setup_method(self):
        self.judge = HarnessJudge()

    def test_parses_valid_json(self):
        raw = json.dumps(VALID_JUDGE_JSON)
        result = self.judge._parse_result(raw, task_id="t1")
        assert result.verdict == "pass"
        assert result.lob_violation is False
        assert result.naming_consistency_score == pytest.approx(0.9)
        assert result.edge_case_coverage == "adequate"
        assert result.spec_fulfilled == "yes"

    def test_strips_json_fences(self):
        raw = "```json\n" + json.dumps(VALID_JUDGE_JSON) + "\n```"
        result = self.judge._parse_result(raw, task_id="t2")
        assert result.verdict == "pass"

    def test_strips_json_fence_no_language(self):
        raw = "```\n" + json.dumps(VALID_JUDGE_JSON) + "\n```"
        result = self.judge._parse_result(raw, task_id="t3")
        assert result.verdict == "pass"

    def test_invalid_json_returns_skipped(self):
        result = self.judge._parse_result("not json at all", task_id="t4")
        assert result.verdict == "skipped"
        assert result.task_id == "t4"

    def test_empty_string_returns_skipped(self):
        result = self.judge._parse_result("", task_id="t5")
        assert result.verdict == "skipped"

    def test_parses_fail_verdict(self):
        raw = json.dumps(FAIL_JUDGE_JSON)
        result = self.judge._parse_result(raw, task_id="t6")
        assert result.verdict == "fail"
        assert result.lob_violation is True
        assert result.lob_evidence == "imports from auth feature"
        assert "lob_violation" in result.fail_reasons

    def test_raw_response_preserved(self):
        raw = json.dumps(VALID_JUDGE_JSON)
        result = self.judge._parse_result(raw, task_id="t7")
        assert result.raw_response == raw


# ---------------------------------------------------------------------------
# HarnessJudge.evaluate()
# ---------------------------------------------------------------------------

class TestEvaluate:
    def setup_method(self):
        self.judge = HarnessJudge()
        self.payload = JudgePayload(
            diff="diff --git a/foo.py\n+def bar(): pass",
            spec="add bar function",
            harness_rules=["TDD required"],
            existing_code="def foo(): pass",
            feature_path="lib/features/",
            task_id="eval-001",
        )

    def _mock_ok(self):
        return MagicMock(returncode=0, stdout=json.dumps(VALID_JUDGE_JSON), stderr="")

    def test_returns_judge_result_on_valid_response(self):
        with patch("judge.evaluator.subprocess.run") as mock_run:
            mock_run.return_value = self._mock_ok()
            result = self.judge.evaluate(self.payload)
        assert isinstance(result, JudgeResult)
        assert result.verdict == "pass"
        assert result.task_id == "eval-001"

    def test_returns_skipped_on_timeout(self):
        with patch("judge.evaluator.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["claude"], timeout=30)
            result = self.judge.evaluate(self.payload)
        assert result.verdict == "skipped"
        assert result.task_id == "eval-001"

    def test_never_raises_on_any_input(self):
        with patch("judge.evaluator.subprocess.run") as mock_run:
            mock_run.side_effect = Exception("unexpected failure")
            result = self.judge.evaluate(self.payload)
        assert isinstance(result, JudgeResult)
        assert result.verdict == "skipped"

    def test_never_raises_on_empty_payload(self):
        empty_payload = JudgePayload(
            diff="", spec="", harness_rules=[], existing_code="", feature_path="", task_id="empty",
        )
        with patch("judge.evaluator.subprocess.run") as mock_run:
            mock_run.side_effect = Exception("fail")
            result = self.judge.evaluate(empty_payload)
        assert isinstance(result, JudgeResult)

    def test_subprocess_called_with_model(self):
        with patch("judge.evaluator.subprocess.run") as mock_run:
            mock_run.return_value = self._mock_ok()
            self.judge.evaluate(self.payload)
        cmd = mock_run.call_args[0][0]
        assert "claude" in cmd[0]
        assert any("haiku" in str(a) for a in cmd)

    def test_nonzero_exit_returns_skipped(self):
        with patch("judge.evaluator.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="API error")
            result = self.judge.evaluate(self.payload)
        assert result.verdict == "skipped"


# ---------------------------------------------------------------------------
# Verdict mapping from JSON flags
# ---------------------------------------------------------------------------

class TestVerdictMapping:
    def setup_method(self):
        self.judge = HarnessJudge()

    def _result(self, overrides: dict) -> JudgeResult:
        data = dict(VALID_JUDGE_JSON)
        data.update(overrides)
        return self.judge._parse_result(json.dumps(data), task_id="vm")

    def test_verdict_fail_when_lob_violation(self):
        r = self._result({
            "lob_violation": {"result": "yes", "evidence": "bad import"},
            "overall_verdict": "fail",
            "fail_reasons": ["lob_violation"],
        })
        assert r.verdict == "fail"
        assert r.lob_violation is True

    def test_verdict_warn_when_duplication_only(self):
        r = self._result({
            "duplication": {"result": "yes", "evidence": "copy-paste"},
            "overall_verdict": "warn",
            "fail_reasons": [],
        })
        assert r.verdict == "warn"
        assert r.duplication is True

    def test_verdict_pass_when_all_clean(self):
        r = self._result({})
        assert r.verdict == "pass"
        assert r.lob_violation is False
        assert r.duplication is False
