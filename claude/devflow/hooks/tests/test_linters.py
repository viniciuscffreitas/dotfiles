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
