"""
Tests for install_config.py — verifies DEVFLOW_HOOKS matcher correctness.

Bug fix: pre_task_profiler was registered with ".*" matcher (fired git diff
on every tool call including Read/Glob/Grep). Fix restricts it to
Write|Edit|MultiEdit|Bash. pre_task_firewall must remain ".*" (it intercepts
Read operations in strict oversight mode).
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_DEVFLOW_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_DEVFLOW_ROOT))


def _load_hooks() -> dict:
    import install_config
    importlib.reload(install_config)
    return install_config.build_hooks("/fake/devflow")


class TestProfilerMatcher:
    """Contract: pre_task_profiler must NOT use '.*' — restricted to mutations + Bash."""

    def test_profiler_not_registered_with_wildcard_matcher(self):
        hooks = _load_hooks()
        for entry in hooks["PreToolUse"]:
            cmds = [h["command"] for h in entry["hooks"]]
            if any("pre_task_profiler" in c for c in cmds):
                assert entry["matcher"] != ".*", (
                    "pre_task_profiler must not use '.*' — it runs git diff and must "
                    "be restricted to avoid overhead on every Read/Glob/Grep call"
                )
                return
        pytest.fail("pre_task_profiler not found in PreToolUse hooks")

    def test_profiler_matches_bash_and_write_operations(self):
        hooks = _load_hooks()
        for entry in hooks["PreToolUse"]:
            cmds = [h["command"] for h in entry["hooks"]]
            if any("pre_task_profiler" in c for c in cmds):
                matcher = entry["matcher"]
                assert "Bash" in matcher or "Write" in matcher, (
                    f"pre_task_profiler must match Bash|Write|Edit|MultiEdit — got '{matcher}'"
                )
                return
        pytest.fail("pre_task_profiler not found in PreToolUse hooks")


class TestFirewallMatcher:
    """Contract: pre_task_firewall must use '.*' — it needs to intercept Read calls."""

    def test_firewall_uses_wildcard_matcher(self):
        hooks = _load_hooks()
        for entry in hooks["PreToolUse"]:
            cmds = [h["command"] for h in entry["hooks"]]
            if any("pre_task_firewall" in c for c in cmds):
                assert entry["matcher"] == ".*", (
                    f"pre_task_firewall must use '.*' to intercept Read ops in strict mode "
                    f"— got '{entry['matcher']}'"
                )
                return
        pytest.fail("pre_task_firewall not found in PreToolUse hooks")


class TestProfilerFirewallSeparation:
    """Contract: profiler and firewall must be in separate PreToolUse entries."""

    def test_profiler_and_firewall_in_separate_entries(self):
        hooks = _load_hooks()
        profiler_entry = None
        firewall_entry = None
        for entry in hooks["PreToolUse"]:
            cmds = [h["command"] for h in entry["hooks"]]
            if any("pre_task_profiler" in c for c in cmds):
                profiler_entry = entry
            if any("pre_task_firewall" in c for c in cmds):
                firewall_entry = entry
        assert profiler_entry is not None, "pre_task_profiler not found in PreToolUse"
        assert firewall_entry is not None, "pre_task_firewall not found in PreToolUse"
        assert profiler_entry is not firewall_entry, (
            "profiler and firewall must be in SEPARATE PreToolUse entries with different matchers"
        )


class TestStopHooksDispatcher:
    """Contract: Stop hooks must use only stop_dispatcher — no individual hooks."""

    def _individual_hooks(self):
        return [
            "spec_stop_guard", "post_task_judge", "task_telemetry",
            "desktop_notify", "instinct_capture", "cost_tracker",
        ]

    def test_stop_uses_dispatcher(self):
        hooks = _load_hooks()
        all_cmds = [
            h["command"]
            for entry in hooks.get("Stop", [])
            for h in entry["hooks"]
        ]
        assert any("stop_dispatcher" in c for c in all_cmds), (
            "stop_dispatcher.py must be in Stop hooks"
        )

    def test_stop_has_no_individual_hooks(self):
        hooks = _load_hooks()
        all_cmds = [
            h["command"]
            for entry in hooks.get("Stop", [])
            for h in entry["hooks"]
        ]
        for individual in self._individual_hooks():
            for cmd in all_cmds:
                assert individual not in cmd, (
                    f"{individual} must not be directly in Stop — "
                    "it is handled internally by stop_dispatcher"
                )
