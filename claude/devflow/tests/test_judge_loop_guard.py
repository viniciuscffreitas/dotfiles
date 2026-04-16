"""
Tests for the infinite-loop guard in post_task_judge / HarnessJudge / instinct_capture.

Contract:
  CHANGES  - claude subprocess spawned by judge/instinct does NOT re-trigger them
  MUST NOT - normal (non-subprocess) judge run continues to evaluate
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_HOOKS_DIR = Path(__file__).parent.parent / "hooks"
_JUDGE_DIR = Path(__file__).parent.parent / "judge"

sys.path.insert(0, str(_HOOKS_DIR))
sys.path.insert(0, str(_JUDGE_DIR))
sys.path.insert(0, str(Path(__file__).parent.parent))


def _load_post_task_judge():
    spec = importlib.util.spec_from_file_location(
        "post_task_judge", _HOOKS_DIR / "post_task_judge.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_instinct_capture():
    spec = importlib.util.spec_from_file_location(
        "instinct_capture", _HOOKS_DIR / "instinct_capture.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# post_task_judge — CHANGES: subprocess guard causes early exit
# ---------------------------------------------------------------------------

def test_judge_subprocess_skipped(tmp_path, monkeypatch):
    """When DEVFLOW_JUDGE_SUBPROCESS=1, main() must return 0 without calling HarnessJudge."""
    monkeypatch.setenv("DEVFLOW_JUDGE_SUBPROCESS", "1")

    mod = _load_post_task_judge()

    with patch.object(mod, "HarnessJudge") as mock_judge_cls:
        result = mod.main()

    assert result == 0, "main() must return 0 when DEVFLOW_JUDGE_SUBPROCESS=1"
    mock_judge_cls.assert_not_called()


# ---------------------------------------------------------------------------
# HarnessJudge — CHANGES: evaluate() injects guard env into subprocess
# ---------------------------------------------------------------------------

def test_judge_sets_env_on_subprocess(monkeypatch):
    """HarnessJudge.evaluate() must pass DEVFLOW_JUDGE_SUBPROCESS=1 in subprocess env."""
    monkeypatch.delenv("DEVFLOW_JUDGE_SUBPROCESS", raising=False)

    from judge.evaluator import HarnessJudge, JudgePayload

    payload = JudgePayload(
        diff="diff --git a/x.py",
        spec="fix something",
        harness_rules=[],
        existing_code="",
        feature_path=".",
        task_id="test-session",
    )

    captured_env = {}

    def fake_run(cmd, **kwargs):
        captured_env.update(kwargs.get("env") or {})
        result = MagicMock()
        result.returncode = 0
        result.stdout = (
            '{"overall_verdict":"pass","fail_reasons":[],'
            '"lob_violation":{"result":"no","evidence":null},'
            '"duplication":{"result":"no","evidence":null},'
            '"type_contract_violation":{"result":"no","evidence":null},'
            '"unjustified_complexity":{"result":"no","evidence":null},'
            '"naming_consistency":{"score":1.0,"evidence":null},'
            '"edge_case_coverage":{"level":"adequate","missing":[]},'
            '"spec_fulfilled":{"result":"yes","evidence":null}}'
        )
        return result

    import subprocess
    with patch.object(subprocess, "run", side_effect=fake_run):
        HarnessJudge().evaluate(payload)

    assert captured_env.get("DEVFLOW_JUDGE_SUBPROCESS") == "1", (
        "evaluate() must set DEVFLOW_JUDGE_SUBPROCESS=1 in subprocess env"
    )


# ---------------------------------------------------------------------------
# post_task_judge — MUST NOT CHANGE: normal run calls HarnessJudge
# ---------------------------------------------------------------------------

def test_judge_normal_run_unaffected(tmp_path, monkeypatch):
    """Without DEVFLOW_JUDGE_SUBPROCESS, main() must call HarnessJudge.evaluate()."""
    monkeypatch.delenv("DEVFLOW_JUDGE_SUBPROCESS", raising=False)

    mod = _load_post_task_judge()

    mock_result = MagicMock()
    mock_result.verdict = "pass"
    mock_result.lob_violation = False
    mock_result.lob_evidence = None
    mock_result.duplication = False
    mock_result.duplication_evidence = None
    mock_result.type_contract_violation = False
    mock_result.type_contract_evidence = None
    mock_result.unjustified_complexity = False
    mock_result.complexity_evidence = None
    mock_result.naming_consistency_score = 1.0
    mock_result.naming_evidence = None
    mock_result.edge_case_coverage = "adequate"
    mock_result.spec_fulfilled = "yes"
    mock_result.spec_evidence = None
    mock_result.fail_reasons = []

    with patch.object(mod, "HarnessJudge") as mock_judge_cls, \
         patch.object(mod, "_get_state_dir", return_value=tmp_path), \
         patch.object(mod, "JudgeRouter") as mock_router_cls:

        mock_judge_instance = MagicMock()
        mock_judge_instance.evaluate.return_value = mock_result
        mock_judge_cls.return_value = mock_judge_instance

        mock_router = MagicMock()
        mock_router.should_run.return_value = True
        mock_router.handle.return_value = 0
        mock_router_cls.return_value = mock_router

        result = mod.main()

    mock_judge_instance.evaluate.assert_called_once()
    assert result == 0


# ---------------------------------------------------------------------------
# instinct_capture — CHANGES: subprocess guard causes early exit
# ---------------------------------------------------------------------------

def test_instinct_subprocess_skipped(monkeypatch):
    """When DEVFLOW_JUDGE_SUBPROCESS=1, instinct_capture.main() must return 0
    without calling _call_haiku."""
    monkeypatch.setenv("DEVFLOW_JUDGE_SUBPROCESS", "1")

    mod = _load_instinct_capture()

    with patch.object(mod, "_call_haiku") as mock_haiku:
        result = mod.main()

    assert result == 0, "main() must return 0 when DEVFLOW_JUDGE_SUBPROCESS=1"
    mock_haiku.assert_not_called()


# ---------------------------------------------------------------------------
# instinct_capture — CHANGES: _call_haiku() injects guard env into subprocess
# ---------------------------------------------------------------------------

def test_instinct_sets_env_on_subprocess(monkeypatch):
    """instinct_capture._call_haiku() must pass DEVFLOW_JUDGE_SUBPROCESS=1 in subprocess env."""
    monkeypatch.delenv("DEVFLOW_JUDGE_SUBPROCESS", raising=False)

    mod = _load_instinct_capture()

    captured_env = {}

    def fake_run(cmd, **kwargs):
        captured_env.update(kwargs.get("env") or {})
        result = MagicMock()
        result.returncode = 0
        result.stdout = '[{"title":"t","summary":"s","confidence":0.9,"tags":[]}]'
        return result

    import subprocess
    with patch.object(subprocess, "run", side_effect=fake_run):
        mod._call_haiku("some transcript")

    assert captured_env.get("DEVFLOW_JUDGE_SUBPROCESS") == "1", (
        "_call_haiku() must set DEVFLOW_JUDGE_SUBPROCESS=1 in subprocess env"
    )
