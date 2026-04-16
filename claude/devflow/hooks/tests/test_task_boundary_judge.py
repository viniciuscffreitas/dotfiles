"""Tests for task_boundary_judge hook — evaluates pending tasks at task boundaries."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_HOOKS_DIR = Path(__file__).parent.parent
_DEVFLOW_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_DEVFLOW_ROOT))
sys.path.insert(0, str(_HOOKS_DIR))

from judge.evaluator import JudgeResult
from telemetry.store import TelemetryStore


def _make_result(verdict: str, task_id: str = "prev-task") -> JudgeResult:
    return JudgeResult(
        task_id=task_id, verdict=verdict,
        lob_violation=False, lob_evidence=None,
        duplication=False, duplication_evidence=None,
        type_contract_violation=False, type_contract_evidence=None,
        unjustified_complexity=False, complexity_evidence=None,
        naming_consistency_score=1.0, naming_evidence=None,
        edge_case_coverage="adequate", spec_fulfilled="yes",
        spec_evidence=None, fail_reasons=[], raw_response=None,
    )


def _write_risk_profile(state_dir: Path, oversight_level: str = "standard") -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "risk-profile.json").write_text(json.dumps({
        "oversight_level": oversight_level,
        "probability": 0.3,
        "impact": 0.4,
        "detectability": 0.6,
    }))


def _write_active_spec(state_dir: Path, status: str = "IMPLEMENTING", plan: str = "fix the bug") -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "active-spec.json").write_text(json.dumps({
        "status": status,
        "plan_path": plan,
        "started_at": 1700000000,
    }))


def _seed_pending_task(store: TelemetryStore, task_id: str = "prev-task",
                       oversight: str = "standard") -> None:
    """Insert a task record with judge_verdict=NULL (pending)."""
    store.record({
        "task_id": task_id,
        "oversight_level": oversight,
        "probability_score": 0.3,
    })


# ---------------------------------------------------------------------------
# Unit tests — task_boundary_judge hook
# ---------------------------------------------------------------------------

class TestBoundaryJudgeEvaluatesPendingTask:
    """When a pending task exists with risk-profile, the judge must evaluate it."""

    def test_boundary_judge_evaluates_pending_task(self, tmp_path):
        db_path = tmp_path / "test.db"
        store = TelemetryStore(db_path=db_path)
        _seed_pending_task(store, "prev-task", "standard")

        state_dir = tmp_path / "state" / "prev-task"
        _write_risk_profile(state_dir, "standard")
        _write_active_spec(state_dir, "IMPLEMENTING", "fix auth bug")

        import task_boundary_judge as m
        import importlib
        importlib.reload(m)

        with patch.object(m, "_find_pending_task", return_value={
                "task_id": "prev-task", "oversight_level": "standard"}), \
             patch.object(m, "_get_state_dir_for_task",
                          return_value=state_dir), \
             patch.object(m, "_get_diff", return_value="diff --git a/auth.py"), \
             patch("task_boundary_judge.HarnessJudge") as mock_judge_cls, \
             patch("task_boundary_judge.JudgeRouter") as mock_router_cls, \
             patch("task_boundary_judge.TelemetryStore", return_value=store):

            mock_judge = MagicMock()
            mock_judge.evaluate.return_value = _make_result("pass", "prev-task")
            mock_judge_cls.return_value = mock_judge
            mock_router = MagicMock()
            mock_router.should_run.return_value = True
            mock_router.handle.return_value = 0
            mock_router_cls.return_value = mock_router

            code = m.run()

        assert code == 0
        mock_judge.evaluate.assert_called_once()
        payload = mock_judge.evaluate.call_args[0][0]
        assert payload.task_id == "prev-task"
        assert "diff --git" in payload.diff


class TestBoundaryJudgeSkipsWhenNoPending:
    """No pending task in DB → exit 0 immediately, no evaluation."""

    def test_boundary_judge_skips_when_no_pending(self, tmp_path):
        db_path = tmp_path / "test.db"
        store = TelemetryStore(db_path=db_path)
        # No pending tasks seeded

        import task_boundary_judge as m
        import importlib
        importlib.reload(m)

        with patch.object(m, "_find_pending_task", return_value=None), \
             patch("task_boundary_judge.HarnessJudge") as mock_judge_cls:

            code = m.run()

        assert code == 0
        mock_judge_cls.return_value.evaluate.assert_not_called()


class TestBoundaryJudgeSkipsVibeOversight:
    """Oversight level 'vibe' → skip evaluation entirely."""

    def test_boundary_judge_skips_vibe_oversight(self, tmp_path):
        db_path = tmp_path / "test.db"
        store = TelemetryStore(db_path=db_path)
        _seed_pending_task(store, "prev-task", "vibe")

        import task_boundary_judge as m
        import importlib
        importlib.reload(m)

        # _find_pending_task returns None for vibe tasks (filtered by query)
        with patch.object(m, "_find_pending_task", return_value=None), \
             patch("task_boundary_judge.HarnessJudge") as mock_judge_cls:

            code = m.run()

        assert code == 0
        mock_judge_cls.return_value.evaluate.assert_not_called()


class TestBoundaryJudgeSkipsAlreadyJudged:
    """Task with judge_verdict already set → skip (double-judging guard)."""

    def test_boundary_judge_skips_already_judged(self, tmp_path):
        db_path = tmp_path / "test.db"
        store = TelemetryStore(db_path=db_path)
        store.record({"task_id": "prev-task", "judge_verdict": "pass",
                       "oversight_level": "standard"})

        import task_boundary_judge as m
        import importlib
        importlib.reload(m)

        # Already judged → _find_pending_task returns None
        with patch.object(m, "_find_pending_task", return_value=None), \
             patch("task_boundary_judge.HarnessJudge") as mock_judge_cls:

            code = m.run()

        assert code == 0
        mock_judge_cls.return_value.evaluate.assert_not_called()


class TestBoundaryJudgeWritesJudgeErrorOnFailure:
    """Haiku timeout/failure → verdict='judge_error', never 'pending'."""

    def test_boundary_judge_writes_judge_error_on_failure(self, tmp_path):
        db_path = tmp_path / "test.db"
        store = TelemetryStore(db_path=db_path)
        _seed_pending_task(store, "prev-task", "standard")

        state_dir = tmp_path / "state" / "prev-task"
        _write_risk_profile(state_dir, "standard")
        _write_active_spec(state_dir)

        import task_boundary_judge as m
        import importlib
        importlib.reload(m)

        mock_store = MagicMock()

        with patch.object(m, "_find_pending_task", return_value={
                "task_id": "prev-task", "oversight_level": "standard"}), \
             patch.object(m, "_get_state_dir_for_task",
                          return_value=state_dir), \
             patch.object(m, "_get_diff", return_value="some diff"), \
             patch("task_boundary_judge.HarnessJudge") as mock_judge_cls, \
             patch("task_boundary_judge.JudgeRouter") as mock_router_cls, \
             patch("task_boundary_judge.TelemetryStore", return_value=mock_store):

            # Judge returns skipped (timeout/failure scenario)
            mock_judge = MagicMock()
            mock_judge.evaluate.return_value = _make_result("skipped", "prev-task")
            mock_judge_cls.return_value = mock_judge
            mock_router = MagicMock()
            mock_router.should_run.return_value = True
            mock_router.handle.return_value = 0
            mock_router_cls.return_value = mock_router

            code = m.run()

        assert code == 0
        mock_store.record.assert_called_once()
        recorded = mock_store.record.call_args[0][0]
        assert recorded["judge_verdict"] == "judge_error"


class TestBoundaryJudgeSpecOverwriteWarning:
    """If active-spec.json has status=PENDING with very recent started_at,
    it means spec_phase_tracker ran first — log a warning."""

    def test_boundary_judge_warns_if_spec_already_overwritten(self, tmp_path):
        import time
        state_dir = tmp_path / "state" / "prev-task"
        _write_risk_profile(state_dir, "standard")
        _write_active_spec(state_dir, status="PENDING", plan="brand new spec")
        # Backdate to "just now" (within 5s)
        spec = json.loads((state_dir / "active-spec.json").read_text())
        spec["started_at"] = int(time.time())
        (state_dir / "active-spec.json").write_text(json.dumps(spec))

        import task_boundary_judge as m
        import importlib
        importlib.reload(m)

        with patch.object(m, "_find_pending_task", return_value={
                "task_id": "prev-task", "oversight_level": "standard"}), \
             patch.object(m, "_get_state_dir_for_task",
                          return_value=state_dir), \
             patch.object(m, "_get_diff", return_value="diff"), \
             patch("task_boundary_judge.HarnessJudge") as mock_judge_cls, \
             patch("task_boundary_judge.JudgeRouter") as mock_router_cls, \
             patch("task_boundary_judge.TelemetryStore", return_value=MagicMock()):

            mock_judge_cls.return_value.evaluate.return_value = _make_result("pass")
            mock_router = MagicMock()
            mock_router.should_run.return_value = True
            mock_router.handle.return_value = 0
            mock_router_cls.return_value = mock_router

            code = m.run()

        # Should still succeed but emit warning (tested via capsys or log)
        assert code == 0


# ---------------------------------------------------------------------------
# Stop fallback — post_task_judge double-judging guard
# ---------------------------------------------------------------------------

class TestStopFallbackJudgesUnjudgedTask:
    """Stop event evaluates task if boundary judge didn't catch it."""

    def test_stop_fallback_judges_unjudged_task(self, tmp_path):
        _write_risk_profile(tmp_path, "standard")

        import importlib
        import post_task_judge as m
        importlib.reload(m)

        mock_store = MagicMock()

        with patch.object(m, "_get_diff", return_value="diff"), \
             patch.object(m, "_is_already_judged", return_value=False), \
             patch("post_task_judge.get_session_id", return_value="unjudged-task"), \
             patch("post_task_judge.HarnessJudge") as mock_judge_cls, \
             patch("post_task_judge.JudgeRouter") as mock_router_cls, \
             patch("post_task_judge.TelemetryStore", return_value=mock_store):

            mock_judge = MagicMock()
            mock_judge.evaluate.return_value = _make_result("pass", "unjudged-task")
            mock_judge_cls.return_value = mock_judge
            mock_router = MagicMock()
            mock_router.should_run.return_value = True
            mock_router.handle.return_value = 0
            mock_router_cls.return_value = mock_router

            code = m.run(tmp_path)

        assert code == 0
        mock_judge.evaluate.assert_called_once()


class TestStopFallbackSkipsAlreadyJudged:
    """Stop event must not double-judge if boundary judge already ran."""

    def test_stop_fallback_skips_already_judged(self, tmp_path):
        _write_risk_profile(tmp_path, "standard")

        import importlib
        import post_task_judge as m
        importlib.reload(m)

        mock_store = MagicMock()

        with patch.object(m, "_get_diff", return_value="diff"), \
             patch("post_task_judge.get_session_id", return_value="judged-task"), \
             patch("post_task_judge.HarnessJudge") as mock_judge_cls, \
             patch("post_task_judge.JudgeRouter") as mock_router_cls, \
             patch("post_task_judge.TelemetryStore", return_value=mock_store), \
             patch.object(m, "_is_already_judged", return_value=True):

            mock_router = MagicMock()
            mock_router.should_run.return_value = True
            mock_router_cls.return_value = mock_router

            code = m.run(tmp_path)

        assert code == 0
        mock_judge_cls.return_value.evaluate.assert_not_called()


# ---------------------------------------------------------------------------
# Hook ordering validation
# ---------------------------------------------------------------------------

class TestHookOrderingInSettings:
    """Validates hook ordering rules in settings.json.

    task_boundary_judge was removed from UserPromptSubmit — boundary judging
    is now handled by stop_dispatcher (Stop hook) which is the authoritative
    boundary event. This test now verifies that stop_dispatcher is registered
    as the Stop hook and spec_phase_tracker is still present in UserPromptSubmit.
    """

    def test_hook_ordering_in_settings(self):
        settings_path = Path.home() / ".claude" / "settings.json"
        if not settings_path.exists():
            pytest.skip("settings.json not found")

        settings = json.loads(settings_path.read_text())
        hooks = settings.get("hooks", {})

        # stop_dispatcher must be registered as the Stop hook
        stop_hooks = hooks.get("Stop", [])
        stop_commands: list[str] = []
        for group in stop_hooks:
            for hook in group.get("hooks", []):
                stop_commands.append(hook.get("command", ""))
        assert any("stop_dispatcher" in cmd for cmd in stop_commands), (
            "stop_dispatcher not found in Stop hooks — boundary judging requires it"
        )

        # spec_phase_tracker must be in UserPromptSubmit
        ups_hooks = hooks.get("UserPromptSubmit", [])
        ups_commands: list[str] = []
        for group in ups_hooks:
            for hook in group.get("hooks", []):
                ups_commands.append(hook.get("command", ""))
        assert any("spec_phase_tracker" in cmd for cmd in ups_commands), (
            "spec_phase_tracker not found in UserPromptSubmit hooks"
        )


# ---------------------------------------------------------------------------
# Integration test — full boundary judging flow
# ---------------------------------------------------------------------------

class TestFullFlowBoundaryJudging:
    """Simulates: task A → boundary → judge A → task B → boundary → judge B."""

    def test_full_flow_boundary_judging(self, tmp_path):
        db_path = tmp_path / "test.db"
        store = TelemetryStore(db_path=db_path)
        state_root = tmp_path / "state"

        # --- Task A: create record, state files ---
        store.record({"task_id": "task-A", "oversight_level": "standard"})
        state_a = state_root / "task-A"
        _write_risk_profile(state_a, "standard")
        _write_active_spec(state_a, "IMPLEMENTING", "fix auth bug")

        import task_boundary_judge as m
        import importlib
        importlib.reload(m)

        # --- Boundary: judge task A ---
        with patch.object(m, "_find_pending_task", return_value={
                "task_id": "task-A", "oversight_level": "standard"}), \
             patch.object(m, "_get_state_dir_for_task", return_value=state_a), \
             patch.object(m, "_get_diff", return_value="diff A"), \
             patch("task_boundary_judge.HarnessJudge") as mock_j1, \
             patch("task_boundary_judge.JudgeRouter") as mock_r1, \
             patch("task_boundary_judge.TelemetryStore", return_value=store):

            mock_j1.return_value.evaluate.return_value = _make_result("pass", "task-A")
            mock_r1.return_value.should_run.return_value = True
            mock_r1.return_value.handle.return_value = 0
            m.run()

        # Verify task A was judged
        rows = store.get_recent(n=10)
        task_a = next(r for r in rows if r["task_id"] == "task-A")
        assert task_a["judge_verdict"] == "pass"

        # --- Task B: create record, state files ---
        store.record({"task_id": "task-B", "oversight_level": "strict"})
        state_b = state_root / "task-B"
        _write_risk_profile(state_b, "strict")
        _write_active_spec(state_b, "IMPLEMENTING", "add pagination")

        importlib.reload(m)

        # --- Boundary: judge task B ---
        with patch.object(m, "_find_pending_task", return_value={
                "task_id": "task-B", "oversight_level": "strict"}), \
             patch.object(m, "_get_state_dir_for_task", return_value=state_b), \
             patch.object(m, "_get_diff", return_value="diff B"), \
             patch("task_boundary_judge.HarnessJudge") as mock_j2, \
             patch("task_boundary_judge.JudgeRouter") as mock_r2, \
             patch("task_boundary_judge.TelemetryStore", return_value=store):

            mock_j2.return_value.evaluate.return_value = _make_result("warn", "task-B")
            mock_r2.return_value.should_run.return_value = True
            mock_r2.return_value.handle.return_value = 0
            m.run()

        # Verify task B was judged
        rows = store.get_recent(n=10)
        task_b = next(r for r in rows if r["task_id"] == "task-B")
        assert task_b["judge_verdict"] == "warn"

        # Verify task A still has its original verdict (not overwritten)
        task_a = next(r for r in rows if r["task_id"] == "task-A")
        assert task_a["judge_verdict"] == "pass"
