"""Tests for desktop_notify.py — covers testable logic only.

Side-effecting functions (_notify, main's osascript call) are mocked.
_last_assistant_text and _read_input are pure logic and tested directly.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))
import desktop_notify


def _make_transcript(entries: list, tmp_path: Path) -> str:
    p = tmp_path / "transcript.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries))
    return str(p)


class TestLastAssistantText(unittest.TestCase):
    def test_returns_last_assistant_text_block(self, tmp_path=None):
        import tempfile, os
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            entries = [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": [{"type": "text", "text": "I did the thing"}]},
            ]
            p.write_text("\n".join(json.dumps(e) for e in entries))
            result = desktop_notify._last_assistant_text(str(p))
            self.assertEqual(result, "I did the thing")

    def test_returns_string_content_directly(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            entries = [{"role": "assistant", "content": "Plain string response"}]
            p.write_text(json.dumps(entries[0]))
            result = desktop_notify._last_assistant_text(str(p))
            self.assertEqual(result, "Plain string response")

    def test_truncates_at_60_chars(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            long_text = "A" * 80
            entries = [{"role": "assistant", "content": [{"type": "text", "text": long_text}]}]
            p.write_text(json.dumps(entries[0]))
            result = desktop_notify._last_assistant_text(str(p))
            self.assertEqual(result, "A" * 60 + "…")

    def test_exactly_60_chars_no_ellipsis(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            text = "B" * 60
            entries = [{"role": "assistant", "content": [{"type": "text", "text": text}]}]
            p.write_text(json.dumps(entries[0]))
            result = desktop_notify._last_assistant_text(str(p))
            self.assertEqual(result, text)
            self.assertNotIn("…", result)

    def test_skips_user_entries_returns_last_assistant(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            entries = [
                {"role": "assistant", "content": [{"type": "text", "text": "first response"}]},
                {"role": "user", "content": "follow-up"},
                {"role": "assistant", "content": [{"type": "text", "text": "second response"}]},
                {"role": "user", "content": "last user msg"},
            ]
            p.write_text("\n".join(json.dumps(e) for e in entries))
            result = desktop_notify._last_assistant_text(str(p))
            self.assertEqual(result, "second response")

    def test_returns_empty_string_when_no_assistant_entry(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            entries = [{"role": "user", "content": "just a user message"}]
            p.write_text(json.dumps(entries[0]))
            result = desktop_notify._last_assistant_text(str(p))
            self.assertEqual(result, "")

    def test_returns_empty_string_for_missing_file(self):
        result = desktop_notify._last_assistant_text("/nonexistent/path/transcript.jsonl")
        self.assertEqual(result, "")

    def test_returns_empty_string_for_empty_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            p.write_text("")
            result = desktop_notify._last_assistant_text(str(p))
            self.assertEqual(result, "")

    def test_skips_invalid_json_lines(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            p.write_text("not-json\n" + json.dumps({"role": "assistant", "content": "valid"}))
            result = desktop_notify._last_assistant_text(str(p))
            self.assertEqual(result, "valid")

    def test_skips_text_blocks_with_empty_text(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            entries = [
                {"role": "assistant", "content": [{"type": "text", "text": ""}]},
                {"role": "assistant", "content": [{"type": "text", "text": "real content"}]},
            ]
            p.write_text("\n".join(json.dumps(e) for e in entries))
            result = desktop_notify._last_assistant_text(str(p))
            self.assertEqual(result, "real content")

    def test_ignores_non_text_content_blocks(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            entries = [
                {"role": "assistant", "content": [
                    {"type": "tool_use", "name": "Bash", "input": {}},
                    {"type": "text", "text": "after tool use"},
                ]},
            ]
            p.write_text(json.dumps(entries[0]))
            result = desktop_notify._last_assistant_text(str(p))
            self.assertEqual(result, "after tool use")


class TestReadInput(unittest.TestCase):
    def test_parses_valid_json(self):
        payload = {"session_id": "abc", "transcript_path": "/tmp/t.jsonl"}
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = json.dumps(payload)
            result = desktop_notify._read_input()
        self.assertEqual(result, payload)

    def test_returns_empty_dict_on_invalid_json(self):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = "not-json"
            result = desktop_notify._read_input()
        self.assertEqual(result, {})

    def test_returns_empty_dict_on_empty_input(self):
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read.return_value = ""
            result = desktop_notify._read_input()
        self.assertEqual(result, {})


class TestMain(unittest.TestCase):
    def test_calls_notify_with_transcript_subtitle(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "t.jsonl"
            p.write_text(json.dumps({"role": "assistant", "content": "Done!"}))
            payload = {"session_id": "s1", "transcript_path": str(p)}

            with patch("sys.stdin") as mock_stdin, \
                 patch("desktop_notify._notify") as mock_notify, \
                 patch("sys.stdout") as mock_stdout:
                mock_stdin.read.return_value = json.dumps(payload)
                mock_stdout.write = MagicMock()
                exit_code = desktop_notify.main()

            mock_notify.assert_called_once_with("Claude", "Done!")
            self.assertEqual(exit_code, 0)

    def test_calls_notify_with_fallback_when_no_transcript(self):
        payload = {"session_id": "s1"}
        with patch("sys.stdin") as mock_stdin, \
             patch("desktop_notify._notify") as mock_notify, \
             patch("sys.stdout") as mock_stdout:
            mock_stdin.read.return_value = json.dumps(payload)
            mock_stdout.write = MagicMock()
            exit_code = desktop_notify.main()

        mock_notify.assert_called_once_with("Claude", "Resposta pronta")
        self.assertEqual(exit_code, 0)

    def test_returns_0_always(self):
        payload = {}
        with patch("sys.stdin") as mock_stdin, \
             patch("desktop_notify._notify"), \
             patch("sys.stdout") as mock_stdout:
            mock_stdin.read.return_value = json.dumps(payload)
            mock_stdout.write = MagicMock()
            result = desktop_notify.main()
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
