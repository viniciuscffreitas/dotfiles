"""
ContextFirewall — spawns isolated sub-agents via `claude -p`.

A sub-agent is a context firewall, not a specialist. Each sub-agent
receives a clean context window with only the files it needs.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FirewallTask:
    task_id: str
    instruction: str           # what the sub-agent must do
    allowed_paths: list[str]   # file paths the sub-agent may read
    allowed_tools: list[str]   # tool names the sub-agent may use
    timeout_seconds: int = 120
    context_budget: int = 4000  # max tokens to pass (approx: chars / 4)


@dataclass
class FirewallResult:
    task_id: str
    success: bool
    output: str                # sub-agent stdout
    tokens_used: int | None    # not available from subprocess
    duration_ms: float
    exit_code: int
    error: str | None          # populated if success=False
