"""
Hook registration configuration for devflow.

Single source of truth for DEVFLOW_HOOKS — used by install.sh and unit tests.
Separating this from install.sh enables direct import in tests without
executing file I/O or requiring sys.argv.
"""
from __future__ import annotations


def build_hooks(devflow_dir: str) -> dict:
    """Return the DEVFLOW_HOOKS dict for the given devflow directory.

    Args:
        devflow_dir: Absolute path to the devflow root directory.
    """
    d = devflow_dir
    return {
        "PreToolUse": [
            # pre_task_profiler: runs git diff + risk scoring — restrict to mutations
            # and Bash only (NOT Read/Glob/Grep — would run git diff on every tool call).
            {
                "matcher": "Write|Edit|MultiEdit|Bash",
                "hooks": [
                    {"type": "command", "command": f"python3 {d}/hooks/pre_task_profiler.py"},
                ],
            },
            # pre_task_firewall: intercepts Read calls in strict oversight mode —
            # must remain ".*" so it fires on Read tool use.
            {
                "matcher": ".*",
                "hooks": [
                    {"type": "command", "command": f"python3 {d}/hooks/pre_task_firewall.py"},
                ],
            },
            {
                "matcher": "Write|Edit|MultiEdit",
                "hooks": [
                    {"type": "command", "command": f"python3 {d}/hooks/secrets_gate.py"},
                ],
            },
            {
                "matcher": "Bash",
                "hooks": [
                    {"type": "command", "command": f"python3 {d}/hooks/pre_push_gate.py"},
                    {"type": "command", "command": f"python3 {d}/hooks/commit_validator.py"},
                ],
            },
        ],
        "PostToolUse": [
            {
                "matcher": "Write|Edit|MultiEdit",
                "hooks": [
                    {"type": "command", "command": f"python3 {d}/hooks/file_checker.py"},
                    {"type": "command", "command": f"python3 {d}/hooks/tdd_enforcer.py"},
                ],
            },
            {
                "matcher": ".*",
                "hooks": [
                    {"type": "command", "command": f"python3 {d}/hooks/context_monitor.py"},
                ],
            },
        ],
        "UserPromptSubmit": [
            {
                "matcher": "",
                "hooks": [
                    {"type": "command", "command": f"python3 {d}/hooks/spec_phase_tracker.py"},
                ],
            },
        ],
        # Stop: single stop_dispatcher.py entry — it internally runs all stop-time
        # hooks (spec_stop_guard, cost_tracker, task_telemetry, desktop_notify,
        # post_task_judge, instinct_capture) using importlib to avoid 6 separate
        # Python interpreter startups per turn end.
        "Stop": [
            {
                "matcher": "",
                "hooks": [
                    {"type": "command", "command": f"python3 {d}/hooks/stop_dispatcher.py", "async": False},
                ],
            },
        ],
        "SessionStart": [
            {
                "matcher": "",
                "hooks": [
                    {"type": "command", "command": f"python3 {d}/hooks/discovery_scan.py"},
                ],
            },
            {
                "matcher": "compact",
                "hooks": [
                    {"type": "command", "command": f"python3 {d}/hooks/post_compact_restore.py"},
                ],
            },
        ],
        "PreCompact": [
            {
                "matcher": "",
                "hooks": [
                    {"type": "command", "command": f"python3 {d}/hooks/pre_compact.py"},
                ],
            },
        ],
        "SubagentStart": [
            {
                "matcher": "",
                "hooks": [
                    {"type": "command", "command": f"python3 {d}/hooks/subagent_tracker.py", "async": True},
                ],
            },
        ],
        "SubagentStop": [
            {
                "matcher": "",
                "hooks": [
                    {"type": "command", "command": f"python3 {d}/hooks/subagent_tracker.py", "async": True},
                ],
            },
        ],
        "CwdChanged": [
            {
                "matcher": "",
                "hooks": [
                    {"type": "command", "command": f"python3 {d}/hooks/cwd_changed.py"},
                ],
            },
        ],
        "ConfigChange": [
            {
                "matcher": "",
                "hooks": [
                    {"type": "command", "command": f"python3 {d}/hooks/config_reload.py", "async": True},
                ],
            },
        ],
    }
