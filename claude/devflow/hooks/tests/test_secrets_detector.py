"""Tests for secrets_detector.py — PreToolUse hook that blocks credential leaks."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from secrets_detector import (
    _classify,
    _extract_content,
    Severity,
    main,
)


# ---------------------------------------------------------------------------
# _classify — pattern matching and severity
# ---------------------------------------------------------------------------

class TestClassify:
    def test_openai_key_is_high(self):
        sev, desc = _classify("sk-aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890abcdef")
        assert sev == Severity.HIGH
        assert "openai" in desc.lower() or "api key" in desc.lower()

    def test_github_pat_is_high(self):
        sev, _ = _classify("ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890abcd")
        assert sev == Severity.HIGH

    def test_aws_access_key_is_high(self):
        sev, _ = _classify("AKIAIOSFODNN7EXAMPLE")
        assert sev == Severity.HIGH

    def test_anthropic_key_is_high(self):
        key = "sk-ant-api03-" + "x" * 90
        sev, _ = _classify(key)
        assert sev == Severity.HIGH

    def test_private_key_header_is_high(self):
        sev, _ = _classify("-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAK...")
        assert sev == Severity.HIGH

    def test_password_assignment_is_medium(self):
        sev, _ = _classify('password = "supersecret123"')
        assert sev == Severity.MEDIUM

    def test_secret_assignment_is_medium(self):
        sev, _ = _classify('DB_SECRET = "my_db_pass_9x"')
        assert sev == Severity.MEDIUM

    def test_clean_content_is_none(self):
        sev, _ = _classify("def hello_world():\n    print('hello')\n")
        assert sev is None

    def test_placeholder_not_flagged(self):
        sev, _ = _classify('password = "YOUR_PASSWORD_HERE"')
        assert sev is None

    def test_example_value_not_flagged(self):
        sev, _ = _classify('password = "example_password"')
        assert sev is None


# ---------------------------------------------------------------------------
# _extract_content — pull text from different tool inputs
# ---------------------------------------------------------------------------

class TestExtractContent:
    def test_write_returns_content_field(self):
        inp = {"file_path": "src/config.py", "content": "SECRET=abc123"}
        texts = _extract_content("Write", inp)
        assert "SECRET=abc123" in texts

    def test_edit_returns_new_string(self):
        inp = {"file_path": "src/config.py", "old_string": "x=1", "new_string": "TOKEN=ghp_abc"}
        texts = _extract_content("Edit", inp)
        assert "TOKEN=ghp_abc" in texts

    def test_multiedit_returns_all_new_strings(self):
        inp = {
            "file_path": "src/config.py",
            "edits": [
                {"old_string": "a", "new_string": "TOKEN=sk-abc123"},
                {"old_string": "b", "new_string": "print('hello')"},
            ],
        }
        texts = _extract_content("MultiEdit", inp)
        assert any("TOKEN=sk-abc123" in t for t in texts)
        assert any("print('hello')" in t for t in texts)

    def test_unknown_tool_returns_empty(self):
        texts = _extract_content("Bash", {"command": "echo hi"})
        assert texts == []


# ---------------------------------------------------------------------------
# main() — exit codes and output
# ---------------------------------------------------------------------------

def _hook_input(tool: str, file_path: str, content: str) -> dict:
    inp: dict = {"file_path": file_path}
    if tool == "Write":
        inp["content"] = content
    elif tool == "Edit":
        inp["old_string"] = ""
        inp["new_string"] = content
    return {"tool": tool, "tool_input": inp}


class TestMain:
    def test_clean_file_exits_zero(self):
        hook = _hook_input("Write", "src/app.py", "def hello(): pass")
        with patch("secrets_detector.read_hook_stdin", return_value=hook):
            rc = main()
        assert rc == 0

    def test_high_severity_exits_two(self):
        hook = _hook_input("Write", "src/config.py",
                           "API_KEY = 'ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890abcd'")
        with patch("secrets_detector.read_hook_stdin", return_value=hook):
            rc = main()
        assert rc == 2

    def test_high_severity_prints_block_message(self, capsys):
        hook = _hook_input("Write", "src/config.py",
                           "API_KEY = 'ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890abcd'")
        with patch("secrets_detector.read_hook_stdin", return_value=hook):
            main()
        out = capsys.readouterr().out
        assert "SECRET" in out.upper() or "credential" in out.lower() or "blocked" in out.lower()

    def test_medium_severity_exits_zero(self, capsys):
        hook = _hook_input("Write", "src/config.py", 'password = "supersecret123"')
        with patch("secrets_detector.read_hook_stdin", return_value=hook):
            rc = main()
        assert rc == 0

    def test_medium_severity_prints_warning(self, capsys):
        hook = _hook_input("Write", "src/config.py", 'password = "supersecret123"')
        with patch("secrets_detector.read_hook_stdin", return_value=hook):
            main()
        out = capsys.readouterr().out
        assert "warn" in out.lower() or "credential" in out.lower() or "password" in out.lower()

    def test_example_file_skipped(self):
        hook = _hook_input("Write", ".env.example",
                           "API_KEY=ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890abcd")
        with patch("secrets_detector.read_hook_stdin", return_value=hook):
            rc = main()
        assert rc == 0

    def test_edit_tool_high_severity_exits_two(self):
        hook = {
            "tool": "Edit",
            "tool_input": {
                "file_path": "src/db.py",
                "old_string": "pass",
                "new_string": "AKIAIOSFODNN7EXAMPLE = secret",
            },
        }
        with patch("secrets_detector.read_hook_stdin", return_value=hook):
            rc = main()
        assert rc == 2

    def test_missing_tool_input_exits_zero(self):
        with patch("secrets_detector.read_hook_stdin", return_value={}):
            rc = main()
        assert rc == 0


def test_anthropic_key_labeled_correctly():
    """Anthropic key must NOT be labelled as OpenAI API key."""
    key = "sk-ant-api03-" + "x" * 80
    sev, desc = _classify(key)
    assert sev == Severity.HIGH
    assert "anthropic" in desc.lower()


def test_anthropic_key_various_formats_labeled_correctly():
    """All sk-ant- key variants must be labelled Anthropic, not OpenAI."""
    for key in [
        "sk-ant-api03-" + "x" * 90,
        "sk-ant-admin01-" + "A" * 80,
    ]:
        sev, desc = _classify(key)
        assert sev == Severity.HIGH, f"Expected HIGH for {key[:20]}..."
        assert "anthropic" in desc.lower(), f"Expected 'anthropic' label, got: {desc}"
