"""Tests for deterministic linters."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

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


# ---------------------------------------------------------------------------
# LinterEngine — run / run_all
# ---------------------------------------------------------------------------

from linters.engine import LinterEngine


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
