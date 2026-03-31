"""Deterministic linters for the devflow harness."""
from __future__ import annotations

import ast
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class LinterResult:
    linter_name: str
    passed: bool
    violations: list[str]
    files_checked: int
    duration_ms: float


# Type alias for a linter function
LinterFn = Callable[[str, Path], LinterResult]


class LinterEngine:
    def __init__(self) -> None:
        self._linters: dict[str, LinterFn] = {
            "import_boundary": _lint_import_boundary,
            "file_size": _lint_file_size,
            "coverage_gate": _lint_coverage_gate,
            "compile_check": _lint_compile_check,
        }

    def run_all(self, diff: str, project_root: Path) -> list[LinterResult]:
        results = []
        for name, fn in self._linters.items():
            try:
                results.append(fn(diff, project_root))
            except Exception as e:  # noqa: BLE001
                results.append(LinterResult(
                    linter_name=name,
                    passed=False,
                    violations=[f"linter error: {e}"],
                    files_checked=0,
                    duration_ms=0.0,
                ))
        return results

    def run(self, name: str, diff: str, project_root: Path) -> LinterResult:
        if name not in self._linters:
            raise ValueError(f"unknown linter: {name!r}")
        return self._linters[name](diff, project_root)


# ---------------------------------------------------------------------------
# Linter stubs — implementations added in subsequent tasks
# ---------------------------------------------------------------------------

def _lint_import_boundary(diff: str, project_root: Path) -> LinterResult:
    return LinterResult("import_boundary", True, [], 0, 0.0)


def _lint_file_size(diff: str, project_root: Path) -> LinterResult:
    return LinterResult("file_size", True, [], 0, 0.0)


def _lint_coverage_gate(diff: str, project_root: Path) -> LinterResult:
    return LinterResult("coverage_gate", True, [], 0, 0.0)


def _lint_compile_check(diff: str, project_root: Path) -> LinterResult:
    return LinterResult("compile_check", True, [], 0, 0.0)
