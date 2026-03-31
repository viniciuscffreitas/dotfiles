"""
ContextFirewall — spawns isolated sub-agents via `claude -p`.

A sub-agent is a context firewall, not a specialist. Each sub-agent
receives a clean context window with only the files it needs.
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


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


class ContextFirewall:
    """Spawns an isolated sub-agent via `claude -p` as a context firewall.

    The main agent decides WHAT to do. The sub-agent executes in isolation
    with a minimal, purpose-built context — preventing cross-task contamination.
    """

    def run(self, task: FirewallTask) -> FirewallResult:
        """Spawn sub-agent. Never raises — returns success=False on any error."""
        start = time.monotonic()
        try:
            context = self._build_context(task)
            cmd = self._build_command(task, context)
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=task.timeout_seconds,
            )
            duration_ms = (time.monotonic() - start) * 1000
            return self._parse_result(task.task_id, proc, duration_ms)
        except subprocess.TimeoutExpired:
            return FirewallResult(
                task_id=task.task_id,
                success=False,
                output="",
                tokens_used=None,
                duration_ms=(time.monotonic() - start) * 1000,
                exit_code=1,
                error="timeout",
            )
        except Exception as exc:
            return FirewallResult(
                task_id=task.task_id,
                success=False,
                output="",
                tokens_used=None,
                duration_ms=(time.monotonic() - start) * 1000,
                exit_code=1,
                error=str(exc),
            )

    def _build_context(self, task: FirewallTask) -> str:
        """Reads allowed_paths, assembles context string, truncates to budget."""
        char_budget = task.context_budget * 4
        parts: list[str] = []
        used = 0
        for path in task.allowed_paths:
            try:
                content = Path(path).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            entry = f"=== {path} ===\n{content}"
            remaining = char_budget - used
            if remaining <= 0:
                break
            if len(entry) > remaining:
                entry = entry[:remaining]
            parts.append(entry)
            used += len(entry)
        return "\n\n".join(parts)

    def _build_command(self, task: FirewallTask, context: str) -> list[str]:
        """Returns subprocess command list for `claude -p`."""
        prompt = f"{task.instruction}\n\n{context}" if context else task.instruction
        return [
            "claude", "-p", prompt,
            "--model", "claude-haiku-4-5-20251001",
            "--output-format", "text",
            "--allowedTools", ",".join(task.allowed_tools),
        ]

    def _parse_result(
        self, task_id: str, proc: subprocess.CompletedProcess, duration_ms: float
    ) -> FirewallResult:
        """Parses subprocess result into FirewallResult."""
        success = proc.returncode == 0
        return FirewallResult(
            task_id=task_id,
            success=success,
            output=proc.stdout or "",
            tokens_used=None,
            duration_ms=duration_ms,
            exit_code=proc.returncode,
            error=proc.stderr if not success else None,
        )
