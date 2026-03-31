"""Deterministic linters for the devflow harness."""
from __future__ import annotations

import ast
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_DIFF_FILE_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")
_DART_IMPORT_RE = re.compile(r"""import\s+['"]package:[^/]+/features/([^/]+)/""")
_FEATURES_PATH_RE = re.compile(r"lib/features/([^/]+)/")

_WARN_LINES = 400
_BLOCK_LINES = 600


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
    t0 = time.monotonic()
    violations: list[str] = []
    files_checked = 0
    current_file: str | None = None
    line_num = 0

    for raw_line in diff.splitlines():
        m = _DIFF_FILE_RE.match(raw_line)
        if m:
            current_file = m.group(2)
            line_num = 0
            continue

        if raw_line.startswith("@@"):
            hm = re.search(r"\+(\d+)", raw_line)
            line_num = int(hm.group(1)) - 1 if hm else 0
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            line_num += 1
            if current_file and current_file.endswith(".dart"):
                files_checked += 1
                src_m = _FEATURES_PATH_RE.search(current_file)
                imp_m = _DART_IMPORT_RE.search(raw_line[1:])
                if src_m and imp_m:
                    source_feat = src_m.group(1)
                    target_feat = imp_m.group(1)
                    if source_feat != target_feat:
                        violations.append(
                            f"{current_file}:{line_num} — cross-feature import: {source_feat} → {target_feat}"
                        )
        elif not raw_line.startswith("-"):
            line_num += 1

    duration_ms = (time.monotonic() - t0) * 1000
    return LinterResult("import_boundary", not violations, violations, files_checked, duration_ms)


def _lint_file_size(diff: str, project_root: Path) -> LinterResult:
    t0 = time.monotonic()
    violations: list[str] = []
    blocked = False
    modified_files: set[str] = set()

    for line in diff.splitlines():
        m = _DIFF_FILE_RE.match(line)
        if m:
            modified_files.add(m.group(2))

    files_checked = len(modified_files)
    for rel_path in modified_files:
        abs_path = project_root / rel_path
        if abs_path.exists():
            try:
                line_count = len(abs_path.read_text(encoding="utf-8", errors="ignore").splitlines())
            except OSError:
                continue
        else:
            try:
                result = subprocess.run(
                    ["git", "show", f"HEAD:{rel_path}"],
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    continue
                line_count = len(result.stdout.splitlines())
            except Exception:  # noqa: BLE001
                continue

        if line_count > _BLOCK_LINES:
            violations.append(f"{rel_path} — {line_count} lines (limit: {_BLOCK_LINES})")
            blocked = True
        elif line_count > _WARN_LINES:
            violations.append(f"{rel_path} — {line_count} lines (limit: {_WARN_LINES})")

    duration_ms = (time.monotonic() - t0) * 1000
    return LinterResult("file_size", not blocked, violations, files_checked, duration_ms)


def _lint_coverage_gate(diff: str, project_root: Path) -> LinterResult:
    return LinterResult("coverage_gate", True, [], 0, 0.0)


def _lint_compile_check(diff: str, project_root: Path) -> LinterResult:
    return LinterResult("compile_check", True, [], 0, 0.0)
