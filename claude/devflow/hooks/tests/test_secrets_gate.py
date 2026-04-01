"""Tests for secrets_gate.py — PreToolUse Write|Edit|MultiEdit hook.

Design constraints verified here:
- Blocks (exit 2) on real credential patterns
- Never blocks on devflow test fixtures (the test files themselves may contain
  credential-shaped strings for calibration — see _is_test_file exclusion)
- Never blocks on placeholder values, env-var references, or comment lines
- Always exits 0 (pass-through) on non-secret content
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import secrets_gate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_input(file_path: str, content: str) -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": file_path, "content": content}}


def _edit_input(file_path: str, new_string: str) -> dict:
    return {"tool_name": "Edit", "tool_input": {"file_path": file_path, "new_string": new_string}}


def _multiedit_input(file_path: str, edits: list) -> dict:
    return {"tool_name": "MultiEdit", "tool_input": {"file_path": file_path, "edits": edits}}


def _run(data: dict) -> int:
    """Run the hook with mocked stdin/stdout; return exit code."""
    raw = json.dumps(data)
    captured_stdout = []
    with patch("sys.stdin") as mock_stdin, \
         patch("sys.stdout") as mock_stdout:
        mock_stdin.read.return_value = raw
        mock_stdout.write = lambda s: captured_stdout.append(s)
        return secrets_gate.main()


# ---------------------------------------------------------------------------
# Pattern detection — BLOCK cases
# ---------------------------------------------------------------------------

class TestBlocksOnCredentials(unittest.TestCase):
    def test_blocks_anthropic_api_key_in_write(self):
        content = 'ANTHROPIC_API_KEY = "sk-ant-api03-' + "A" * 95 + '"'
        code = _run(_write_input("config.py", content))
        self.assertEqual(code, 2)

    def test_blocks_aws_akia_key(self):
        # AKIAIOSFODNN7EXAMPLE = AKIA + 16 uppercase chars (valid AWS key format)
        content = 'aws_access_key_id = "AKIAIOSFODNN7EXAMPLE"'
        code = _run(_edit_input("settings.py", content))
        self.assertEqual(code, 2)

    def test_blocks_github_token_ghp(self):
        token = "ghp_" + "A" * 36
        content = f'GITHUB_TOKEN = "{token}"'
        code = _run(_edit_input("deploy.py", content))
        self.assertEqual(code, 2)

    def test_blocks_github_token_ghs(self):
        token = "ghs_" + "B" * 36
        content = f'token = "{token}"'
        code = _run(_write_input("auth.py", content))
        self.assertEqual(code, 2)

    def test_blocks_private_key_pem(self):
        content = "-----BEGIN RSA PRIVATE KEY-----\nMIIEo...\n-----END RSA PRIVATE KEY-----"
        code = _run(_write_input("key.pem", content))
        self.assertEqual(code, 2)

    def test_blocks_ec_private_key(self):
        content = "-----BEGIN EC PRIVATE KEY-----\nMHQC...\n-----END EC PRIVATE KEY-----"
        code = _run(_write_input("certs/server.key", content))
        self.assertEqual(code, 2)

    def test_blocks_generic_secret_assignment_single_quote(self):
        content = "secret = 'supersecretvalue123'"
        code = _run(_edit_input("config.py", content))
        self.assertEqual(code, 2)

    def test_blocks_generic_password_assignment(self):
        content = 'DB_PASSWORD = "hunter2correcthorse"'
        code = _run(_write_input("database.py", content))
        self.assertEqual(code, 2)

    def test_blocks_api_key_assignment(self):
        content = 'api_key = "realkey-abc12345xyz"'
        code = _run(_write_input("client.py", content))
        self.assertEqual(code, 2)

    def test_blocks_in_multiedit_new_string(self):
        # Verify MultiEdit new_string is scanned (not just Write/Edit)
        edits = [
            {"old_string": "api_key = None", "new_string": 'api_key = "realvalue-abc12345xyz"'},
        ]
        code = _run(_multiedit_input("config.py", edits))
        self.assertEqual(code, 2)


# ---------------------------------------------------------------------------
# Exclusions — PASS cases
# ---------------------------------------------------------------------------

class TestDoesNotBlockExclusions(unittest.TestCase):
    def test_passes_env_var_reference_os_environ(self):
        content = 'API_KEY = os.environ["ANTHROPIC_API_KEY"]'
        code = _run(_write_input("config.py", content))
        self.assertEqual(code, 0)

    def test_passes_env_var_reference_getenv(self):
        content = 'SECRET = os.getenv("SECRET_KEY", "")'
        code = _run(_write_input("settings.py", content))
        self.assertEqual(code, 0)

    def test_passes_placeholder_your_api_key(self):
        content = 'API_KEY = "your-api-key-here"'
        code = _run(_write_input("README.md", content))
        self.assertEqual(code, 0)

    def test_passes_placeholder_angle_brackets(self):
        content = 'TOKEN = "<YOUR_TOKEN_HERE>"'
        code = _run(_write_input("example.py", content))
        self.assertEqual(code, 0)

    def test_passes_comment_line_with_secret_pattern(self):
        content = "# secret = 'do not use hardcoded secrets'"
        code = _run(_write_input("notes.py", content))
        self.assertEqual(code, 0)

    def test_passes_example_env_file(self):
        content = "API_KEY=your-api-key\nSECRET=your-secret"
        code = _run(_write_input(".env.example", content))
        self.assertEqual(code, 0)

    def test_passes_test_file_with_credential_shaped_fixture(self):
        # devflow test fixtures may have credential-shaped strings for calibration
        content = 'FAKE_KEY = "sk-ant-api03-' + "T" * 95 + '"  # test fixture'
        code = _run(_write_input("/Users/vini/.claude/devflow/hooks/tests/test_judge.py", content))
        self.assertEqual(code, 0)

    def test_passes_test_file_path_with_test_prefix(self):
        content = 'token = "ghp_' + "X" * 36 + '"  # fixture'
        code = _run(_write_input("hooks/tests/test_calibration.py", content))
        self.assertEqual(code, 0)

    def test_passes_conftest_file(self):
        content = 'AWS_KEY = "AKIAIOSFODNN7EX"  # mock'
        code = _run(_write_input("conftest.py", content))
        self.assertEqual(code, 0)

    def test_passes_normal_python_code(self):
        content = "def authenticate(user, password):\n    return verify_hash(user, password)"
        code = _run(_write_input("auth.py", content))
        self.assertEqual(code, 0)

    def test_passes_multiedit_old_string_only_not_new(self):
        # old_string is not scanned — only new_string matters
        edits = [
            {"old_string": 'KEY = "AKIAIOSFODNN7EX"', "new_string": "KEY = os.environ['KEY']"},
        ]
        code = _run(_multiedit_input("config.py", edits))
        self.assertEqual(code, 0)


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

class TestInputParsing(unittest.TestCase):
    def test_passes_through_unknown_tool(self):
        data = {"tool_name": "Read", "tool_input": {"file_path": "x.py"}}
        code = _run(data)
        self.assertEqual(code, 0)

    def test_passes_on_malformed_stdin(self):
        with patch("sys.stdin") as mock_stdin, patch("sys.stdout"):
            mock_stdin.read.return_value = "not-json"
            code = secrets_gate.main()
        self.assertEqual(code, 0)

    def test_passes_on_empty_content(self):
        code = _run(_write_input("empty.py", ""))
        self.assertEqual(code, 0)
