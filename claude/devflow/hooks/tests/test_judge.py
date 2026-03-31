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
