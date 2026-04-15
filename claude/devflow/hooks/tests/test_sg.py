"""Tests for hooks/_sg.py — ast-grep integration primitives."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import _sg  # noqa: E402


# ---------------------------------------------------------------------------
# detect_binary
# ---------------------------------------------------------------------------

def test_detect_binary_returns_path_when_present(monkeypatch):
    _sg._binary_cache = None
    monkeypatch.setattr(_sg.shutil, "which", lambda name: "/usr/local/bin/sg" if name == "sg" else None)
    assert _sg.detect_binary() == "/usr/local/bin/sg"


def test_detect_binary_returns_none_when_missing(monkeypatch):
    _sg._binary_cache = None
    monkeypatch.setattr(_sg.shutil, "which", lambda name: None)
    assert _sg.detect_binary() is None


def test_detect_binary_caches(monkeypatch):
    _sg._binary_cache = None
    calls = {"n": 0}

    def fake_which(name):
        calls["n"] += 1
        return "/usr/local/bin/sg"

    monkeypatch.setattr(_sg.shutil, "which", fake_which)
    _sg.detect_binary()
    _sg.detect_binary()
    _sg.detect_binary()
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# load_rules
# ---------------------------------------------------------------------------

def _write_rule(dir_: Path, filename: str, rule_id: str, language: str = "dart", message: str = "msg") -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / filename
    path.write_text(
        f"id: {rule_id}\n"
        f"language: {language}\n"
        f"message: {message}\n"
        f"severity: warning\n"
        f"rule:\n"
        f"  pattern: print($_)\n"
    )
    return path


def test_load_rules_from_global_only(tmp_path, monkeypatch):
    global_dir = tmp_path / "global"
    _write_rule(global_dir, "a.yml", "rule-a")
    _write_rule(global_dir, "b.yml", "rule-b")
    monkeypatch.setattr(_sg, "GLOBAL_RULES_DIR", global_dir)

    rules = _sg.load_rules(project_root=None)
    ids = sorted(r.id for r in rules)
    assert ids == ["rule-a", "rule-b"]


def test_load_rules_project_override_wins(tmp_path, monkeypatch):
    global_dir = tmp_path / "global"
    project_root = tmp_path / "proj"
    _write_rule(global_dir, "a.yml", "rule-a", message="global message")
    _write_rule(project_root / ".claude" / "sg-rules", "a.yml", "rule-a", message="project message")
    monkeypatch.setattr(_sg, "GLOBAL_RULES_DIR", global_dir)

    rules = _sg.load_rules(project_root=project_root)
    assert len(rules) == 1
    assert rules[0].id == "rule-a"
    assert rules[0].message == "project message"


def test_load_rules_skips_broken_yaml(tmp_path, monkeypatch, capsys):
    global_dir = tmp_path / "global"
    _write_rule(global_dir, "ok.yml", "rule-ok")
    global_dir.mkdir(exist_ok=True)
    (global_dir / "broken.yml").write_text("::: not: valid: yaml: [")
    monkeypatch.setattr(_sg, "GLOBAL_RULES_DIR", global_dir)

    rules = _sg.load_rules(project_root=None)
    ids = [r.id for r in rules]
    assert ids == ["rule-ok"]


def test_load_rules_skips_rule_missing_id(tmp_path, monkeypatch):
    global_dir = tmp_path / "global"
    global_dir.mkdir()
    (global_dir / "bad.yml").write_text("language: dart\nrule:\n  pattern: print($_)\n")
    _write_rule(global_dir, "good.yml", "good-rule")
    monkeypatch.setattr(_sg, "GLOBAL_RULES_DIR", global_dir)

    rules = _sg.load_rules(project_root=None)
    ids = [r.id for r in rules]
    assert ids == ["good-rule"]


def test_load_rules_empty_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(_sg, "GLOBAL_RULES_DIR", tmp_path / "nonexistent")
    assert _sg.load_rules(project_root=None) == []


# ---------------------------------------------------------------------------
# run_for_file — mocked (no real sg binary needed)
# ---------------------------------------------------------------------------

def test_run_for_file_returns_empty_when_no_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(_sg, "detect_binary", lambda: None)
    target = tmp_path / "foo.dart"
    target.write_text('void main() { print("hi"); }')
    rule = _sg.LoadedRule(
        id="no-print-dart", language="dart", path=tmp_path / "r.yml",
        severity="warning", message="no print",
    )
    assert _sg.run_for_file(target, [rule]) == []


def test_run_for_file_returns_empty_when_no_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(_sg, "detect_binary", lambda: "/fake/sg")
    target = tmp_path / "foo.dart"
    target.write_text('print("hi");')
    assert _sg.run_for_file(target, []) == []


def test_run_for_file_parses_sg_json_output(tmp_path, monkeypatch):
    monkeypatch.setattr(_sg, "detect_binary", lambda: "/fake/sg")

    fake_json = (
        '[{"text":"print(\\"hi\\")","range":{"start":{"line":2,"column":4}},'
        '"file":"foo.dart","ruleId":"no-print-dart"}]'
    )

    class FakeResult:
        returncode = 0
        stdout = fake_json
        stderr = ""

    monkeypatch.setattr(_sg.subprocess, "run", lambda *a, **kw: FakeResult())

    target = tmp_path / "foo.dart"
    target.write_text('void main() {\n  print("hi");\n}')
    rule = _sg.LoadedRule(
        id="no-print-dart", language="dart",
        path=tmp_path / "no-print-dart.yml",
        severity="warning", message="use SecureLogger instead of print()",
    )
    findings = _sg.run_for_file(target, [rule])
    assert len(findings) == 1
    f = findings[0]
    assert f.rule_id == "no-print-dart"
    assert f.line == 3  # sg reports 0-indexed; we normalize to 1-indexed
    assert f.severity == "warning"
    assert "SecureLogger" in f.message


def test_run_for_file_filters_by_language(tmp_path, monkeypatch):
    monkeypatch.setattr(_sg, "detect_binary", lambda: "/fake/sg")
    called = {"n": 0}

    def fake_run(*a, **kw):
        called["n"] += 1

        class R:
            returncode = 0
            stdout = "[]"
            stderr = ""
        return R()

    monkeypatch.setattr(_sg.subprocess, "run", fake_run)

    ts_target = tmp_path / "foo.ts"
    ts_target.write_text("const x = 1;")
    dart_rule = _sg.LoadedRule(
        id="no-print-dart", language="dart", path=tmp_path / "r.yml",
        severity="warning", message="m",
    )
    _sg.run_for_file(ts_target, [dart_rule])
    assert called["n"] == 0  # rule skipped — language mismatch


def test_run_for_file_handles_sg_crash(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(_sg, "detect_binary", lambda: "/fake/sg")

    def fake_run(*a, **kw):
        raise FileNotFoundError("sg missing")

    monkeypatch.setattr(_sg.subprocess, "run", fake_run)

    target = tmp_path / "foo.dart"
    target.write_text('print("hi");')
    rule = _sg.LoadedRule(
        id="no-print-dart", language="dart", path=tmp_path / "r.yml",
        severity="warning", message="m",
    )
    assert _sg.run_for_file(target, [rule]) == []
