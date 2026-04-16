"""Tests for sync_report.py — displays project-profile.json after discovery_scan."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from sync_report import main, _format_profile


# ---------------------------------------------------------------------------
# _format_profile
# ---------------------------------------------------------------------------

def test_format_profile_contains_toolchain():
    profile = {"toolchain": "PYTHON", "issue_tracker": "linear",
                "test_framework": "pytest", "in_project": True}
    output = _format_profile(profile)
    assert "PYTHON" in output


def test_format_profile_contains_issue_tracker():
    profile = {"toolchain": "PYTHON", "issue_tracker": "linear",
                "test_framework": "pytest", "in_project": True}
    output = _format_profile(profile)
    assert "linear" in output


def test_format_profile_contains_test_framework():
    profile = {"toolchain": "NODEJS", "issue_tracker": "github_issues",
                "test_framework": "jest", "in_project": True}
    output = _format_profile(profile)
    assert "jest" in output


def test_format_profile_shows_not_in_project():
    profile = {"toolchain": None, "issue_tracker": "none",
                "test_framework": "none", "in_project": False}
    output = _format_profile(profile)
    assert "not in project" in output.lower() or "none" in output.lower()


def test_format_profile_shows_learned_skills():
    profile = {"toolchain": "PYTHON", "issue_tracker": "none",
                "test_framework": "pytest", "in_project": True,
                "injected_skills": ["devflow-learned-docker-host-networking"]}
    output = _format_profile(profile)
    assert "docker" in output.lower() or "learned" in output.lower()


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def test_main_exits_zero_with_profile(tmp_path, capsys):
    state_dir = tmp_path / "state" / "sess1"
    state_dir.mkdir(parents=True)
    profile = {"toolchain": "PYTHON", "issue_tracker": "linear",
                "test_framework": "pytest", "in_project": True,
                "injected_skills": []}
    (state_dir / "project-profile.json").write_text(json.dumps(profile))
    with patch("sync_report._get_state_dir", return_value=state_dir):
        rc = main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "PYTHON" in out


def test_main_exits_zero_with_no_profile(tmp_path, capsys):
    state_dir = tmp_path / "state" / "empty"
    state_dir.mkdir(parents=True)
    with patch("sync_report._get_state_dir", return_value=state_dir):
        rc = main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "no profile" in out.lower() or "run" in out.lower() or "discovery" in out.lower()


def test_main_shows_project_root_when_available(tmp_path, capsys):
    state_dir = tmp_path / "state" / "s"
    state_dir.mkdir(parents=True)
    profile = {"toolchain": "PYTHON", "issue_tracker": "none",
                "test_framework": "pytest", "in_project": True,
                "project_root": "/Users/vini/Developer/myapp", "injected_skills": []}
    (state_dir / "project-profile.json").write_text(json.dumps(profile))
    with patch("sync_report._get_state_dir", return_value=state_dir):
        main()
    out = capsys.readouterr().out
    assert "myapp" in out or "/Users/vini" in out
