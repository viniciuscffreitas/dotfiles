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
