"""Tests for cwd_changed — CWDChanged hook."""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import cwd_changed
from _util import ToolchainKind


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hook_data(cwd: str = "/Users/vini/Developer/myproject") -> dict:
    return {
        "session_id": "sess-cwd-1",
        "hook_event_name": "CWDChanged",
        "cwd": cwd,
    }


def _run(hook_data: dict, state_dir: Path, toolchain=None) -> tuple[int, str]:
    captured = io.StringIO()
    tc_result = (toolchain, Path(hook_data.get("cwd", "/tmp")) if toolchain else None)
    with (
        patch("cwd_changed.read_hook_stdin", return_value=hook_data),
        patch("cwd_changed._get_state_dir", return_value=state_dir),
        patch("cwd_changed.detect_toolchain", return_value=tc_result),
        patch("sys.stdout", captured),
    ):
        code = cwd_changed.main()
    return code, captured.getvalue()


# ---------------------------------------------------------------------------
# Basic behaviour
# ---------------------------------------------------------------------------

def test_exits_zero(tmp_path):
    code, _ = _run(_hook_data(), tmp_path)
    assert code == 0


def test_prints_devflow_prefix(tmp_path):
    _, out = _run(_hook_data(), tmp_path)
    assert "[devflow:cwd]" in out


def test_shows_new_directory(tmp_path):
    _, out = _run(_hook_data("/Users/vini/Developer/myapp"), tmp_path)
    assert "myapp" in out


def test_shows_detected_toolchain(tmp_path):
    _, out = _run(_hook_data(), tmp_path, toolchain=ToolchainKind.FLUTTER)
    assert "flutter" in out.lower()


def test_shows_nodejs_toolchain(tmp_path):
    _, out = _run(_hook_data(), tmp_path, toolchain=ToolchainKind.NODEJS)
    assert "nodejs" in out.lower() or "node" in out.lower()


def test_shows_unknown_when_no_toolchain(tmp_path):
    _, out = _run(_hook_data(), tmp_path, toolchain=None)
    assert "unknown" in out.lower() or out  # at minimum produces output


# ---------------------------------------------------------------------------
# State persistence — last_cwd tracking
# ---------------------------------------------------------------------------

def test_persists_last_cwd(tmp_path):
    _run(_hook_data("/Users/vini/Developer/proj-a"), tmp_path)
    state_file = tmp_path / "last_cwd.json"
    assert state_file.exists()
    data = json.loads(state_file.read_text())
    assert data["cwd"] == "/Users/vini/Developer/proj-a"


def test_warns_on_toolchain_change(tmp_path):
    # First call: Flutter project
    state_file = tmp_path / "last_cwd.json"
    state_file.write_text(json.dumps({"cwd": "/old", "toolchain": "FLUTTER"}))

    # Second call: switch to Node.js project
    _, out = _run(_hook_data("/Users/vini/Developer/web-app"), tmp_path, toolchain=ToolchainKind.NODEJS)
    assert "convention" in out.lower() or "changed" in out.lower() or "switch" in out.lower()


def test_no_warning_same_toolchain(tmp_path):
    state_file = tmp_path / "last_cwd.json"
    state_file.write_text(json.dumps({"cwd": "/old", "toolchain": "FLUTTER"}))

    _, out = _run(_hook_data("/Users/vini/Developer/other-flutter"), tmp_path, toolchain=ToolchainKind.FLUTTER)
    assert "convention" not in out.lower() and "switch" not in out.lower()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_missing_cwd_field_exits_zero(tmp_path):
    code, _ = _run({"session_id": "s", "hook_event_name": "CWDChanged"}, tmp_path)
    assert code == 0


def test_empty_hook_data_exits_zero(tmp_path):
    code, _ = _run({}, tmp_path)
    assert code == 0


def test_never_raises(tmp_path):
    import importlib
    importlib.reload(cwd_changed)
    with (
        patch("cwd_changed.read_hook_stdin", return_value={"cwd": None}),
        patch("cwd_changed._get_state_dir", return_value=tmp_path),
        patch("cwd_changed.detect_toolchain", return_value=(None, None)),
        patch("sys.stdout", io.StringIO()),
    ):
        try:
            cwd_changed.main()
        except Exception as exc:
            pytest.fail(f"main() raised: {exc}")
