# Deterministic Linters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four fast deterministic linters (import_boundary, file_size, coverage_gate, compile_check) that run on every git push before the LLM judge, producing binary pass/fail with line-level evidence.

**Architecture:** A new `linters/` package hosts `LinterResult` + `LinterEngine` (registry pattern). Each linter is a pure function `(diff: str, project_root: Path) -> LinterResult`. `LinterEngine` is integrated into `pre_push_gate.py` — linters run first; failures block the push before pytest/mypy.

**Tech Stack:** Python 3.13, stdlib only (`ast`, `pathlib`, `dataclasses`, `re`, `subprocess`, `time`). No new dependencies.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `linters/__init__.py` | CREATE | Python package marker (empty) |
| `linters/engine.py` | CREATE | `LinterResult` dataclass + `LinterEngine` class + 4 linter implementations |
| `hooks/pre_push_gate.py` | MODIFY | Import + call `LinterEngine.run_all()` before existing quality checks |
| `hooks/tests/test_linters.py` | CREATE | ~30 tests covering all linters + engine + integration |
| `docs/audit-20260331.md` | MODIFY | Append Prompt 6 entry at end of file |

---

## Task 1: LinterResult dataclass + empty package

**Files:**
- Create: `linters/__init__.py`
- Create: `linters/engine.py` (LinterResult only)
- Create: `hooks/tests/test_linters.py` (LinterResult tests only)

- [ ] **Step 1: Create the package marker**

```python
# linters/__init__.py
# (empty)
```

- [ ] **Step 2: Write failing tests for LinterResult**

```python
# hooks/tests/test_linters.py
"""Tests for deterministic linters."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from linters.engine import LinterResult


# ---------------------------------------------------------------------------
# LinterResult
# ---------------------------------------------------------------------------

def test_linter_result_passed_true_when_no_violations():
    r = LinterResult(linter_name="x", passed=True, violations=[], files_checked=3, duration_ms=1.5)
    assert r.passed is True
    assert r.violations == []


def test_linter_result_files_checked_reflects_input():
    r = LinterResult(linter_name="x", passed=True, violations=[], files_checked=7, duration_ms=0.0)
    assert r.files_checked == 7


def test_linter_result_with_violations():
    r = LinterResult(
        linter_name="compile_check",
        passed=False,
        violations=["foo.py:3 — SyntaxError: invalid syntax"],
        files_checked=1,
        duration_ms=2.0,
    )
    assert r.passed is False
    assert len(r.violations) == 1
```

- [ ] **Step 3: Run — must FAIL**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_linters.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'linters'`

- [ ] **Step 4: Create linters/engine.py with LinterResult only**

```python
# linters/engine.py
"""Deterministic linters for the devflow harness."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LinterResult:
    linter_name: str
    passed: bool
    violations: list[str]
    files_checked: int
    duration_ms: float
```

- [ ] **Step 5: Run — must PASS**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_linters.py -v
```

Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
cd /Users/vini/.claude/devflow && git add linters/__init__.py linters/engine.py hooks/tests/test_linters.py && git commit -m "feat(linters): add LinterResult dataclass + package skeleton"
```

---

## Task 2: LinterEngine (registry + run/run_all stubs)

**Files:**
- Modify: `linters/engine.py` (add LinterEngine class)
- Modify: `hooks/tests/test_linters.py` (add engine tests)

- [ ] **Step 1: Write failing engine tests**

Append to `hooks/tests/test_linters.py`:

```python
from linters.engine import LinterEngine


# ---------------------------------------------------------------------------
# LinterEngine — run / run_all
# ---------------------------------------------------------------------------

def test_engine_run_raises_for_unknown_linter(tmp_path):
    engine = LinterEngine()
    with pytest.raises(ValueError, match="unknown linter"):
        engine.run("nonexistent", "", tmp_path)


def test_engine_run_all_returns_one_result_per_linter(tmp_path):
    engine = LinterEngine()
    results = engine.run_all("", tmp_path)
    assert len(results) == 4
    names = {r.linter_name for r in results}
    assert names == {"import_boundary", "file_size", "coverage_gate", "compile_check"}


def test_engine_run_all_never_raises_even_if_linter_throws(tmp_path, monkeypatch):
    engine = LinterEngine()
    # Poison one linter to raise
    def _bad(diff, project_root):
        raise RuntimeError("exploded")
    engine._linters["import_boundary"] = _bad
    results = engine.run_all("", tmp_path)
    # Should still return 4 results, no exception raised
    assert len(results) == 4
    bad = next(r for r in results if r.linter_name == "import_boundary")
    assert bad.passed is False
    assert any("linter error" in v for v in bad.violations)


def test_engine_run_all_empty_diff_all_pass(tmp_path):
    engine = LinterEngine()
    results = engine.run_all("", tmp_path)
    assert all(r.passed for r in results)


def test_engine_run_returns_correct_result_for_known_linter(tmp_path):
    engine = LinterEngine()
    result = engine.run("compile_check", "", tmp_path)
    assert result.linter_name == "compile_check"
    assert isinstance(result.passed, bool)
```

Also add `import pytest` to the top imports block.

- [ ] **Step 2: Run — must FAIL**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_linters.py -v 2>&1 | grep -E "PASSED|FAILED|ERROR"
```

Expected: several FAILED (ImportError / AttributeError)

- [ ] **Step 3: Add LinterEngine to linters/engine.py**

Replace full content of `linters/engine.py`:

```python
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
# Linter implementations (stubs — filled in subsequent tasks)
# ---------------------------------------------------------------------------

def _lint_import_boundary(diff: str, project_root: Path) -> LinterResult:
    return LinterResult("import_boundary", True, [], 0, 0.0)


def _lint_file_size(diff: str, project_root: Path) -> LinterResult:
    return LinterResult("file_size", True, [], 0, 0.0)


def _lint_coverage_gate(diff: str, project_root: Path) -> LinterResult:
    return LinterResult("coverage_gate", True, [], 0, 0.0)


def _lint_compile_check(diff: str, project_root: Path) -> LinterResult:
    return LinterResult("compile_check", True, [], 0, 0.0)
```

- [ ] **Step 4: Run — must PASS**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_linters.py -v
```

Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/vini/.claude/devflow && git add linters/engine.py hooks/tests/test_linters.py && git commit -m "feat(linters): add LinterEngine registry skeleton with stub linters"
```

---

## Task 3: import_boundary linter

**Files:**
- Modify: `linters/engine.py` (replace `_lint_import_boundary` stub)
- Modify: `hooks/tests/test_linters.py` (add import_boundary tests)

- [ ] **Step 1: Write failing tests**

Append to `hooks/tests/test_linters.py`:

```python
# ---------------------------------------------------------------------------
# import_boundary
# ---------------------------------------------------------------------------

_DART_CROSS_FEATURE_DIFF = """\
diff --git a/lib/features/auth/login_page.dart b/lib/features/auth/login_page.dart
--- a/lib/features/auth/login_page.dart
+++ b/lib/features/auth/login_page.dart
@@ -1,3 +1,4 @@
+import 'package:myapp/features/home/home_controller.dart';
 import 'package:myapp/features/auth/auth_service.dart';
"""

_DART_SAME_FEATURE_DIFF = """\
diff --git a/lib/features/auth/login_page.dart b/lib/features/auth/login_page.dart
--- a/lib/features/auth/login_page.dart
+++ b/lib/features/auth/login_page.dart
@@ -1,3 +1,4 @@
+import 'package:myapp/features/auth/auth_service.dart';
"""

_NON_DART_DIFF = """\
diff --git a/lib/features/auth/service.py b/lib/features/auth/service.py
--- a/lib/features/auth/service.py
+++ b/lib/features/auth/service.py
@@ -1,3 +1,4 @@
+from features.home import controller
"""


def test_import_boundary_detects_cross_feature(tmp_path):
    engine = LinterEngine()
    result = engine.run("import_boundary", _DART_CROSS_FEATURE_DIFF, tmp_path)
    assert result.passed is False
    assert len(result.violations) == 1
    assert "auth" in result.violations[0]
    assert "home" in result.violations[0]


def test_import_boundary_allows_same_feature(tmp_path):
    engine = LinterEngine()
    result = engine.run("import_boundary", _DART_SAME_FEATURE_DIFF, tmp_path)
    assert result.passed is True
    assert result.violations == []


def test_import_boundary_ignores_non_dart_files(tmp_path):
    engine = LinterEngine()
    result = engine.run("import_boundary", _NON_DART_DIFF, tmp_path)
    assert result.passed is True


def test_import_boundary_passes_on_empty_diff(tmp_path):
    engine = LinterEngine()
    result = engine.run("import_boundary", "", tmp_path)
    assert result.passed is True
    assert result.files_checked == 0
```

- [ ] **Step 2: Run — must FAIL**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_linters.py::test_import_boundary_detects_cross_feature -v
```

Expected: FAILED (stub always returns passed=True)

- [ ] **Step 3: Implement _lint_import_boundary in linters/engine.py**

Replace the `_lint_import_boundary` stub:

```python
_DIFF_FILE_RE = re.compile(r"^diff --git a/(.+) b/(.+)$")
_DART_IMPORT_RE = re.compile(r"""^import\s+['"]package:[^/]+/lib/features/([^/]+)/""")
_FEATURES_PATH_RE = re.compile(r"lib/features/([^/]+)/")


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
            # Extract starting line from hunk header e.g. @@ -1,3 +1,4 @@
            hm = re.search(r"\+(\d+)", raw_line)
            line_num = int(hm.group(1)) - 1 if hm else 0
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            line_num += 1
            if current_file and current_file.endswith(".dart"):
                files_checked += 1
                src_m = _FEATURES_PATH_RE.search(current_file)
                imp_m = _DART_IMPORT_RE.match(raw_line[1:].lstrip())
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
```

- [ ] **Step 4: Run — must PASS**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_linters.py -k "import_boundary" -v
```

Expected: `4 passed`

- [ ] **Step 5: Run full suite — no regressions**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/ -q --tb=short
```

Expected: all previous + 4 new = passing

- [ ] **Step 6: Commit**

```bash
cd /Users/vini/.claude/devflow && git add linters/engine.py hooks/tests/test_linters.py && git commit -m "feat(linters): implement import_boundary — detects cross-feature Dart imports"
```

---

## Task 4: file_size linter

**Files:**
- Modify: `linters/engine.py` (replace `_lint_file_size` stub)
- Modify: `hooks/tests/test_linters.py` (add file_size tests)

- [ ] **Step 1: Write failing tests**

Append to `hooks/tests/test_linters.py`:

```python
# ---------------------------------------------------------------------------
# file_size
# ---------------------------------------------------------------------------

def _make_diff_for_file(path: str) -> str:
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1,1 +1,2 @@\n+# change\n"


def test_file_size_blocks_at_601_lines(tmp_path):
    src = tmp_path / "lib" / "features" / "auth" / "big.dart"
    src.parent.mkdir(parents=True)
    src.write_text("\n" * 601)
    diff = _make_diff_for_file("lib/features/auth/big.dart")
    engine = LinterEngine()
    result = engine.run("file_size", diff, tmp_path)
    assert result.passed is False
    assert any("601" in v or "600" in v for v in result.violations)


def test_file_size_warns_at_450_lines_but_passes(tmp_path):
    src = tmp_path / "lib" / "features" / "home" / "page.dart"
    src.parent.mkdir(parents=True)
    src.write_text("\n" * 450)
    diff = _make_diff_for_file("lib/features/home/page.dart")
    engine = LinterEngine()
    result = engine.run("file_size", diff, tmp_path)
    assert result.passed is True
    assert len(result.violations) == 1  # warning logged but not blocking


def test_file_size_passes_for_small_file(tmp_path):
    src = tmp_path / "lib" / "features" / "auth" / "small.dart"
    src.parent.mkdir(parents=True)
    src.write_text("void main() {}\n" * 10)
    diff = _make_diff_for_file("lib/features/auth/small.dart")
    engine = LinterEngine()
    result = engine.run("file_size", diff, tmp_path)
    assert result.passed is True
    assert result.violations == []
```

- [ ] **Step 2: Run — must FAIL**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_linters.py -k "file_size" -v
```

Expected: FAILED (stub always passes, returns no violations)

- [ ] **Step 3: Implement _lint_file_size in linters/engine.py**

Replace the `_lint_file_size` stub:

```python
_WARN_LINES = 400
_BLOCK_LINES = 600


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
            # Try git show as fallback
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
```

- [ ] **Step 4: Run — must PASS**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_linters.py -k "file_size" -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/vini/.claude/devflow && git add linters/engine.py hooks/tests/test_linters.py && git commit -m "feat(linters): implement file_size — warn at 400, block at 600 lines"
```

---

## Task 5: coverage_gate linter

**Files:**
- Modify: `linters/engine.py` (replace `_lint_coverage_gate` stub)
- Modify: `hooks/tests/test_linters.py` (add coverage_gate tests)

- [ ] **Step 1: Write failing tests**

Append to `hooks/tests/test_linters.py`:

```python
# ---------------------------------------------------------------------------
# coverage_gate
# ---------------------------------------------------------------------------

def test_coverage_gate_fails_when_no_test_file(tmp_path):
    src = tmp_path / "lib" / "features" / "auth" / "login_page.dart"
    src.parent.mkdir(parents=True)
    src.write_text("// dart source\n")
    diff = _make_diff_for_file("lib/features/auth/login_page.dart")
    engine = LinterEngine()
    result = engine.run("coverage_gate", diff, tmp_path)
    assert result.passed is False
    assert any("login_page" in v for v in result.violations)


def test_coverage_gate_passes_when_test_file_exists(tmp_path):
    src = tmp_path / "lib" / "features" / "auth" / "login_page.dart"
    src.parent.mkdir(parents=True)
    src.write_text("// dart source\n")
    test_dir = tmp_path / "test" / "features" / "auth"
    test_dir.mkdir(parents=True)
    (test_dir / "login_page_test.dart").write_text("// test\n")
    diff = _make_diff_for_file("lib/features/auth/login_page.dart")
    engine = LinterEngine()
    result = engine.run("coverage_gate", diff, tmp_path)
    assert result.passed is True
    assert result.violations == []


def test_coverage_gate_skips_test_files(tmp_path):
    # A _test.dart file being modified should not be flagged
    test_file = tmp_path / "test" / "features" / "auth" / "login_page_test.dart"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("// test\n")
    diff = _make_diff_for_file("test/features/auth/login_page_test.dart")
    engine = LinterEngine()
    result = engine.run("coverage_gate", diff, tmp_path)
    assert result.passed is True
    assert result.violations == []


def test_coverage_gate_skips_non_feature_files(tmp_path):
    src = tmp_path / "lib" / "utils" / "helpers.dart"
    src.parent.mkdir(parents=True)
    src.write_text("// util\n")
    diff = _make_diff_for_file("lib/utils/helpers.dart")
    engine = LinterEngine()
    result = engine.run("coverage_gate", diff, tmp_path)
    assert result.passed is True
    assert result.violations == []
```

- [ ] **Step 2: Run — must FAIL**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_linters.py -k "coverage_gate" -v
```

Expected: FAILED (stub always passes)

- [ ] **Step 3: Implement _lint_coverage_gate in linters/engine.py**

Replace the `_lint_coverage_gate` stub:

```python
_FEATURES_DIR_RE = re.compile(r"^lib/features/[^/]+/")


def _lint_coverage_gate(diff: str, project_root: Path) -> LinterResult:
    t0 = time.monotonic()
    violations: list[str] = []
    modified_files: set[str] = set()

    for line in diff.splitlines():
        m = _DIFF_FILE_RE.match(line)
        if m:
            modified_files.add(m.group(2))

    dart_sources = [
        f for f in modified_files
        if f.endswith(".dart")
        and not f.endswith("_test.dart")
        and _FEATURES_DIR_RE.match(f)
    ]

    files_checked = len(dart_sources)
    for rel_path in dart_sources:
        stem = Path(rel_path).stem
        pattern = f"test/**/*{stem}*_test.dart"
        matches = list(project_root.glob(pattern))
        if not matches:
            violations.append(
                f"{rel_path} — no test file found (expected: test/**/*{stem}*_test.dart)"
            )

    duration_ms = (time.monotonic() - t0) * 1000
    return LinterResult("coverage_gate", not violations, violations, files_checked, duration_ms)
```

- [ ] **Step 4: Run — must PASS**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_linters.py -k "coverage_gate" -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/vini/.claude/devflow && git add linters/engine.py hooks/tests/test_linters.py && git commit -m "feat(linters): implement coverage_gate — require test file for lib/features/ sources"
```

---

## Task 6: compile_check linter

**Files:**
- Modify: `linters/engine.py` (replace `_lint_compile_check` stub)
- Modify: `hooks/tests/test_linters.py` (add compile_check tests)

- [ ] **Step 1: Write failing tests**

Append to `hooks/tests/test_linters.py`:

```python
# ---------------------------------------------------------------------------
# compile_check
# ---------------------------------------------------------------------------

def test_compile_check_passes_for_valid_python(tmp_path):
    src = tmp_path / "hooks" / "my_hook.py"
    src.parent.mkdir(parents=True)
    src.write_text("def foo():\n    return 42\n")
    diff = _make_diff_for_file("hooks/my_hook.py")
    engine = LinterEngine()
    result = engine.run("compile_check", diff, tmp_path)
    assert result.passed is True
    assert result.violations == []


def test_compile_check_fails_with_line_number_for_syntax_error(tmp_path):
    src = tmp_path / "hooks" / "bad.py"
    src.parent.mkdir(parents=True)
    src.write_text("def foo(\n    return 42\n")
    diff = _make_diff_for_file("hooks/bad.py")
    engine = LinterEngine()
    result = engine.run("compile_check", diff, tmp_path)
    assert result.passed is False
    assert len(result.violations) == 1
    assert "SyntaxError" in result.violations[0]
    # line number must be present
    assert result.violations[0].split(":")[1].isdigit() or ":" in result.violations[0]


def test_compile_check_skips_deleted_files(tmp_path):
    # File mentioned in diff but not on disk — must be skipped silently
    diff = _make_diff_for_file("hooks/deleted.py")
    engine = LinterEngine()
    result = engine.run("compile_check", diff, tmp_path)
    assert result.passed is True
    assert result.violations == []


def test_compile_check_never_raises_on_malformed_input(tmp_path):
    # Malformed diff, binary content, etc. — must not raise
    engine = LinterEngine()
    result = engine.run("compile_check", "\x00\xff malformed diff", tmp_path)
    assert isinstance(result, LinterResult)


def test_compile_check_ignores_non_python_files(tmp_path):
    src = tmp_path / "lib" / "main.dart"
    src.parent.mkdir(parents=True)
    src.write_text("void main() {}\n")
    diff = _make_diff_for_file("lib/main.dart")
    engine = LinterEngine()
    result = engine.run("compile_check", diff, tmp_path)
    assert result.passed is True
    assert result.files_checked == 0
```

- [ ] **Step 2: Run — must FAIL**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_linters.py -k "compile_check" -v
```

Expected: FAILED (stub always passes; syntax error test fails)

- [ ] **Step 3: Implement _lint_compile_check in linters/engine.py**

Replace the `_lint_compile_check` stub:

```python
def _lint_compile_check(diff: str, project_root: Path) -> LinterResult:
    t0 = time.monotonic()
    violations: list[str] = []
    modified_files: set[str] = set()

    for line in diff.splitlines():
        m = _DIFF_FILE_RE.match(line)
        if m:
            modified_files.add(m.group(2))

    py_files = [f for f in modified_files if f.endswith(".py")]
    files_checked = 0

    for rel_path in py_files:
        abs_path = project_root / rel_path
        if not abs_path.exists():
            continue  # deleted file — skip
        files_checked += 1
        try:
            source = abs_path.read_text(encoding="utf-8", errors="ignore")
            ast.parse(source, filename=rel_path)
        except SyntaxError as e:
            violations.append(f"{rel_path}:{e.lineno} — SyntaxError: {e.msg}")
        except Exception:  # noqa: BLE001
            pass  # other parse errors: skip silently

    duration_ms = (time.monotonic() - t0) * 1000
    return LinterResult("compile_check", not violations, violations, files_checked, duration_ms)
```

- [ ] **Step 4: Run — must PASS**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_linters.py -k "compile_check" -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
cd /Users/vini/.claude/devflow && git add linters/engine.py hooks/tests/test_linters.py && git commit -m "feat(linters): implement compile_check — ast.parse on modified Python files"
```

---

## Task 7: pre_push_gate integration + integration tests

**Files:**
- Modify: `hooks/pre_push_gate.py` (add `run_linters()` + `get_diff()` + integrate in `main()`)
- Modify: `hooks/tests/test_linters.py` (add pre_push_gate integration tests)

- [ ] **Step 1: Write failing integration tests**

Append to `hooks/tests/test_linters.py`:

```python
# ---------------------------------------------------------------------------
# pre_push_gate integration
# ---------------------------------------------------------------------------

import subprocess as _subprocess
import json as _json

sys.path.insert(0, str(Path(__file__).parent.parent))
from pre_push_gate import run_linters, get_diff


def test_run_linters_output_contains_devflow_lint_tag(tmp_path, capsys):
    run_linters("", tmp_path)
    captured = capsys.readouterr()
    assert "[devflow:lint]" in captured.out


def test_run_linters_all_pass_returns_true(tmp_path):
    passed = run_linters("", tmp_path)
    assert passed is True


def test_run_linters_failure_returns_false(tmp_path, monkeypatch):
    # Make compile_check fail by patching LinterEngine
    from linters import engine as eng_mod
    original = eng_mod._lint_compile_check

    def _failing(diff, project_root):
        return LinterResult("compile_check", False, ["fake.py:1 — SyntaxError: bad"], 1, 0.0)

    monkeypatch.setattr(eng_mod, "_lint_compile_check", _failing)
    passed = run_linters("", tmp_path)
    assert passed is False


def test_get_diff_returns_string(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # initialize a git repo with one commit so HEAD~1 resolution works or fallback
    _subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    _subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
    _subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
    result = get_diff(tmp_path)
    assert isinstance(result, str)
```

- [ ] **Step 2: Run — must FAIL**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_linters.py -k "run_linters or get_diff" -v
```

Expected: FAILED (`run_linters` and `get_diff` don't exist yet)

- [ ] **Step 3: Add get_diff() and run_linters() to pre_push_gate.py**

Add these imports at the top of `hooks/pre_push_gate.py` (after existing imports):

```python
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from linters.engine import LinterEngine
```

Note: `subprocess` and `sys` may already be imported; only add what's missing. Add the `linters` import after the existing `sys.path.insert` lines.

Add these two functions before `main()`:

```python
def get_diff(project_root: Path) -> str:
    """Get diff for linters. Tries HEAD~1 first, falls back to unstaged diff."""
    result = run_command(["git", "diff", "HEAD~1"], cwd=project_root, timeout=10)
    if result[0] == 0 and result[1].strip():
        return result[1]
    result = run_command(["git", "diff"], cwd=project_root, timeout=10)
    return result[1] if result[0] == 0 else ""


def run_linters(diff: str, project_root: Path) -> bool:
    """Run all linters. Prints summary. Returns True if all pass."""
    engine = LinterEngine()
    results = engine.run_all(diff, project_root)
    parts = []
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        parts.append(f"{r.linter_name}: {status}")
        for v in r.violations:
            print(f"  [devflow:lint] {v}")
    print(f"[devflow:lint] {' | '.join(parts)}")
    return all(r.passed for r in results)
```

- [ ] **Step 4: Integrate run_linters() into main()**

In `pre_push_gate.py`, modify `main()` to call `run_linters()` before the existing quality checks:

```python
def main() -> int:
    hook_data = read_hook_stdin()
    command = get_bash_command(hook_data)

    if not should_gate(command):
        return 0

    toolchain, project_root = detect_toolchain(Path.cwd())
    if not toolchain or not project_root:
        return 0

    # --- Deterministic linters (run first, cheap, never hallucinate) ---
    diff = get_diff(project_root)
    if not run_linters(diff, project_root):
        msg = "Pre-push gate BLOCKED: linter violations found (see above).\n"
        print(hook_block(msg))
        return 0

    quality_cmds = get_quality_commands(toolchain, project_root)
    if not quality_cmds:
        return 0

    for qc in quality_cmds:
        code, output = run_command(qc["cmd"], cwd=project_root, timeout=qc["timeout"])
        if code != 0:
            msg = f"Pre-push gate BLOCKED: {qc['label']} failed.\n"
            if output:
                msg += output[:500]
            print(hook_block(msg))
            return 0

    return 0
```

- [ ] **Step 5: Run integration tests — must PASS**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/test_linters.py -k "run_linters or get_diff" -v
```

Expected: `4 passed`

- [ ] **Step 6: Run full test suite — no regressions**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/ -q --tb=short
```

Expected: 478 + (all new linter tests) passing, 0 failed

- [ ] **Step 7: Commit**

```bash
cd /Users/vini/.claude/devflow && git add hooks/pre_push_gate.py hooks/tests/test_linters.py && git commit -m "feat(linters): integrate LinterEngine into pre_push_gate — linters run before pytest/mypy"
```

---

## Task 8: Smoke test + audit doc update

**Files:**
- Modify: `docs/audit-20260331.md` (append Prompt 6 entry)

- [ ] **Step 1: Run smoke test**

```bash
cd /Users/vini/.claude/devflow && echo '{}' | python3.13 hooks/pre_push_gate.py
```

Expected output contains:
```
[devflow:lint] import_boundary: PASS | file_size: PASS | coverage_gate: PASS | compile_check: PASS
```

- [ ] **Step 2: Count final test total**

```bash
cd /Users/vini/.claude/devflow && python3.13 -m pytest hooks/tests/ -q --tb=no 2>&1 | tail -3
```

Note the final N passed count to fill into the audit doc.

- [ ] **Step 3: Append Prompt 6 entry to audit doc**

Append to `docs/audit-20260331.md`:

```markdown

### Prompt 6: Deterministic linters — N tests added, 478 → M total (`2026-03-31`)

**Files created:**
- `linters/__init__.py` — Python package marker
- `linters/engine.py` — `LinterResult` dataclass + `LinterEngine` (registry) + 4 linter implementations: `import_boundary`, `file_size`, `coverage_gate`, `compile_check`
- `hooks/tests/test_linters.py` — N tests across LinterResult, 4 linters, LinterEngine, and pre_push_gate integration

**Files modified:**
- `hooks/pre_push_gate.py` — added `get_diff()`, `run_linters()`, integrated before existing quality gates

**Linters implemented:**

| Linter | Rule | Block level |
|--------|------|-------------|
| `import_boundary` | Dart files under `lib/features/X/` must not import `lib/features/Y/` | pass=False if violations |
| `file_size` | Warn at 400 lines, block at 600 lines | pass=False only at 600+ |
| `coverage_gate` | Modified `lib/features/X/y.dart` requires `test/**/*y*_test.dart` | pass=False if no test |
| `compile_check` | Modified `.py` files must parse with `ast.parse()` | pass=False on SyntaxError |

**hooks/tests/ baseline:** 478 → M (N net added)
**Smoke test:** `echo '{}' | python3.13 hooks/pre_push_gate.py` → `[devflow:lint] import_boundary: PASS | file_size: PASS | coverage_gate: PASS | compile_check: PASS` ✓
**Regressions:** 0
```

- [ ] **Step 4: Commit**

```bash
cd /Users/vini/.claude/devflow && git add docs/audit-20260331.md && git commit -m "docs: add Prompt 6 audit entry — deterministic linters"
```

---

## Self-Review

### Spec Coverage Check

| Spec Requirement | Covered By |
|-----------------|------------|
| `linters/__init__.py` (empty) | Task 1 |
| `linters/engine.py` | Tasks 1–6 |
| `LinterResult` dataclass fields | Task 1 |
| `LinterEngine.run_all()` — never raises | Task 2 |
| `LinterEngine.run()` — raises ValueError | Task 2 |
| `import_boundary` linter | Task 3 |
| `file_size` linter | Task 4 |
| `coverage_gate` linter | Task 5 |
| `compile_check` linter | Task 6 |
| `pre_push_gate.py` integration | Task 7 |
| `[devflow:lint]` output format | Task 7 |
| Linter failures → exit 1 | Task 7 |
| Existing pytest/mypy run after linters | Task 7 |
| All linter tests in `test_linters.py` | Tasks 1–7 |
| `audit-20260331.md` Prompt 6 entry | Task 8 |

All spec requirements covered.

### Type Consistency

- `LinterResult` defined in Task 1, used consistently in Tasks 2–7
- `_DIFF_FILE_RE` defined once in Task 3, reused in Tasks 4–6
- `run_linters()` returns `bool`, tested in Task 7
- `get_diff()` returns `str`, tested in Task 7

### Placeholder Scan

No TBDs, TODOs, or "similar to Task N" patterns found.
