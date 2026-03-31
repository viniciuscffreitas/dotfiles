"""Tests for ContextFirewall and pre_task_firewall hook."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from agents.firewall import FirewallResult, FirewallTask


# ---------------------------------------------------------------------------
# FirewallTask
# ---------------------------------------------------------------------------

class TestFirewallTask:
    def test_instantiates_with_required_fields(self):
        task = FirewallTask(
            task_id="t1",
            instruction="summarize this file",
            allowed_paths=["/tmp/foo.py"],
            allowed_tools=["Read"],
        )
        assert task.task_id == "t1"
        assert task.instruction == "summarize this file"
        assert task.allowed_paths == ["/tmp/foo.py"]
        assert task.allowed_tools == ["Read"]

    def test_timeout_seconds_defaults_to_120(self):
        task = FirewallTask(
            task_id="t2",
            instruction="analyze",
            allowed_paths=[],
            allowed_tools=[],
        )
        assert task.timeout_seconds == 120

    def test_context_budget_defaults_to_4000(self):
        task = FirewallTask(
            task_id="t3",
            instruction="analyze",
            allowed_paths=[],
            allowed_tools=[],
        )
        assert task.context_budget == 4000


# ---------------------------------------------------------------------------
# FirewallResult
# ---------------------------------------------------------------------------

class TestFirewallResult:
    def test_instantiates_with_all_fields(self):
        r = FirewallResult(
            task_id="r1",
            success=True,
            output="some output",
            tokens_used=None,
            duration_ms=42.5,
            exit_code=0,
            error=None,
        )
        assert r.task_id == "r1"
        assert r.success is True
        assert r.output == "some output"
        assert r.tokens_used is None
        assert r.duration_ms == pytest.approx(42.5)
        assert r.exit_code == 0
        assert r.error is None
