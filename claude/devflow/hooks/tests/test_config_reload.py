"""Tests for config_reload — ConfigChange hook."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import config_reload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hook_data(file_path: str = "/Users/vini/.claude/settings.json") -> dict:
    return {
        "session_id": "sess-cfg-1",
        "hook_event_name": "ConfigChange",
        "file": file_path,
    }


def _run(hook_data: dict) -> tuple[int, str]:
    captured = io.StringIO()
    with (
        patch("config_reload.read_hook_stdin", return_value=hook_data),
        patch("sys.stdout", captured),
    ):
        code = config_reload.main()
    return code, captured.getvalue()


# ---------------------------------------------------------------------------
# Basic behaviour
# ---------------------------------------------------------------------------

def test_exits_zero(tmp_path):
    code, _ = _run(_hook_data())
    assert code == 0


def test_settings_json_prints_devflow_prefix():
    _, out = _run(_hook_data("/Users/vini/.claude/settings.json"))
    assert "[devflow:config]" in out


def test_devflow_config_json_prints_prefix():
    _, out = _run(_hook_data("/Users/vini/.claude/devflow/devflow-config.json"))
    assert "[devflow:config]" in out


def test_settings_json_mentioned_in_output():
    _, out = _run(_hook_data("/Users/vini/.claude/settings.json"))
    assert "settings.json" in out


def test_devflow_config_mentioned_in_output():
    _, out = _run(_hook_data("/Users/vini/.claude/devflow/devflow-config.json"))
    assert "devflow-config.json" in out


def test_irrelevant_file_silent():
    """Changes to unrelated files produce no output."""
    _, out = _run(_hook_data("/Users/vini/somefile.txt"))
    assert out.strip() == ""


def test_output_indicates_reload():
    _, out = _run(_hook_data("/Users/vini/.claude/settings.json"))
    assert "reload" in out.lower() or "changed" in out.lower() or "updated" in out.lower()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_missing_file_field_exits_zero():
    code, _ = _run({"session_id": "s", "hook_event_name": "ConfigChange"})
    assert code == 0


def test_empty_hook_data_exits_zero():
    code, _ = _run({})
    assert code == 0


def test_never_raises():
    import importlib
    importlib.reload(config_reload)
    with (
        patch("config_reload.read_hook_stdin", return_value={"file": None}),
        patch("sys.stdout", io.StringIO()),
    ):
        try:
            config_reload.main()
        except Exception as exc:
            pytest.fail(f"main() raised: {exc}")
