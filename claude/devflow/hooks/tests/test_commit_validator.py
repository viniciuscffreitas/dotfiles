"""Tests for commit_validator.py — PreToolUse hook for Conventional Commits validation."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from commit_validator import (
    _extract_message,
    _is_conventional,
    main,
)


# ---------------------------------------------------------------------------
# _is_conventional
# ---------------------------------------------------------------------------

class TestIsConventional:
    def test_feat_valid(self):
        assert _is_conventional("feat: add user authentication")

    def test_fix_valid(self):
        assert _is_conventional("fix: resolve null pointer in login")

    def test_feat_with_scope(self):
        assert _is_conventional("feat(auth): add OAuth2 support")

    def test_breaking_change_bang(self):
        assert _is_conventional("feat!: drop support for Python 3.8")

    def test_breaking_with_scope(self):
        assert _is_conventional("refactor(api)!: rename all endpoints")

    def test_docs_valid(self):
        assert _is_conventional("docs: update README with new commands")

    def test_chore_valid(self):
        assert _is_conventional("chore: bump dependencies")

    def test_multiline_uses_first_line(self):
        assert _is_conventional("feat: short summary\n\nMore detailed body here.")

    def test_no_type_is_invalid(self):
        assert not _is_conventional("add user authentication")

    def test_missing_colon_is_invalid(self):
        assert not _is_conventional("feat add something")

    def test_unknown_type_is_invalid(self):
        assert not _is_conventional("update: add user authentication")

    def test_empty_description_is_invalid(self):
        assert not _is_conventional("feat: ")

    def test_empty_string_is_invalid(self):
        assert not _is_conventional("")


# ---------------------------------------------------------------------------
# _extract_message
# ---------------------------------------------------------------------------

class TestExtractMessage:
    def test_short_m_double_quotes(self):
        cmd = 'git commit -m "feat: add login"'
        assert _extract_message(cmd) == "feat: add login"

    def test_short_m_single_quotes(self):
        cmd = "git commit -m 'fix: null pointer'"
        assert _extract_message(cmd) == "fix: null pointer"

    def test_long_message_flag(self):
        cmd = 'git commit --message "docs: update README"'
        assert _extract_message(cmd) == "docs: update README"

    def test_no_message_flag_returns_none(self):
        assert _extract_message("git commit") is None

    def test_interactive_returns_none(self):
        assert _extract_message("git commit --amend") is None

    def test_not_a_commit_returns_none(self):
        assert _extract_message("git push origin main") is None

    def test_heredoc_extracts_first_real_line(self):
        cmd = "git commit -m \"$(cat <<'EOF'\nfeat: heredoc message\n\nBody here.\nEOF\n)\""
        msg = _extract_message(cmd)
        assert msg is not None
        assert "feat" in msg


# ---------------------------------------------------------------------------
# main() — non-blocking warn
# ---------------------------------------------------------------------------

class TestMain:
    def test_valid_commit_exits_zero_no_output(self, capsys):
        hook = {"tool": "Bash", "tool_input": {"command": 'git commit -m "feat: add login"'}}
        with patch("commit_validator.read_hook_stdin", return_value=hook):
            rc = main()
        assert rc == 0
        assert capsys.readouterr().out == ""

    def test_invalid_commit_exits_zero_with_warning(self, capsys):
        hook = {"tool": "Bash", "tool_input": {"command": 'git commit -m "add login"'}}
        with patch("commit_validator.read_hook_stdin", return_value=hook):
            rc = main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "conventional" in out.lower() or "commit" in out.lower()

    def test_non_commit_command_is_ignored(self, capsys):
        hook = {"tool": "Bash", "tool_input": {"command": "git push origin main"}}
        with patch("commit_validator.read_hook_stdin", return_value=hook):
            rc = main()
        assert rc == 0
        assert capsys.readouterr().out == ""

    def test_interactive_commit_is_ignored(self, capsys):
        hook = {"tool": "Bash", "tool_input": {"command": "git commit"}}
        with patch("commit_validator.read_hook_stdin", return_value=hook):
            rc = main()
        assert rc == 0
        assert capsys.readouterr().out == ""

    def test_missing_tool_input_exits_zero(self):
        with patch("commit_validator.read_hook_stdin", return_value={}):
            rc = main()
        assert rc == 0


# ---------------------------------------------------------------------------
# Review gate fixes: --amend, --no-edit, merge commits
# ---------------------------------------------------------------------------

def test_extract_message_amend_returns_none():
    assert _extract_message("git commit --amend") is None


def test_extract_message_amend_with_message_returns_none():
    """--amend with -m should still be skipped to avoid false warnings on rewrites."""
    assert _extract_message('git commit --amend -m "fix: update message"') is None


def test_extract_message_no_edit_returns_none():
    assert _extract_message("git commit --no-edit") is None


def test_is_conventional_merge_commit_passes():
    assert _is_conventional("Merge branch 'feat/auth' into main")


def test_is_conventional_revert_commit_passes():
    assert _is_conventional("Revert \"feat: add OAuth2 support\"")
