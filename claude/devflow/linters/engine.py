"""Deterministic linters for the devflow harness."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LinterResult:
    linter_name: str
    passed: bool
    violations: list[str]
    files_checked: int
    duration_ms: float
