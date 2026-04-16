"""Tests for the shared read_oversight_level helper in _util.py.

Centralised because pre_task_firewall, post_task_judge and tdd_enforcer all
read risk-profile.json the same way. The helper preserves their fail-safe
behaviour: callers pick the default that matches their risk posture.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from _util import read_oversight_level


def _write_profile(state_dir: Path, payload: dict | None) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    if payload is not None:
        (state_dir / "risk-profile.json").write_text(json.dumps(payload))


def test_returns_oversight_level_when_present(tmp_path):
    _write_profile(tmp_path, {"oversight_level": "strict"})
    assert read_oversight_level(tmp_path) == "strict"


def test_returns_default_when_file_missing(tmp_path):
    assert read_oversight_level(tmp_path, default="standard") == "standard"
    assert read_oversight_level(tmp_path, default="strict") == "strict"


def test_returns_default_when_json_malformed(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "risk-profile.json").write_text("{not valid")
    assert read_oversight_level(tmp_path, default="standard") == "standard"


def test_returns_default_when_oversight_key_missing(tmp_path):
    _write_profile(tmp_path, {"probability": 0.1, "impact": 0.1})
    assert read_oversight_level(tmp_path, default="standard") == "standard"
    assert read_oversight_level(tmp_path, default="strict") == "strict"


def test_default_parameter_defaults_to_standard(tmp_path):
    """If caller omits default, falls back to "standard" (least-risky default)."""
    assert read_oversight_level(tmp_path) == "standard"


def test_returns_each_valid_oversight_level(tmp_path):
    for level in ("vibe", "standard", "strict", "human_review"):
        _write_profile(tmp_path, {"oversight_level": level})
        assert read_oversight_level(tmp_path) == level
