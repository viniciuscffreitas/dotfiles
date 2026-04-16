"""RED phase tests for vibe-level bypass in tdd_enforcer.

The bypass exists so Opus 4.7 can move fast on genuinely trivial tasks
(low probability/impact/detectability per risk-profile.json) without the
hook adding cognitive noise. For any other oversight_level, missing file,
malformed JSON, or missing key, the bypass is OFF (fail-safe).
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from tdd_enforcer import _should_bypass, main


def _write_risk_profile(state_dir: Path, oversight_level: str | None) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    payload: dict = {"probability": 0.1, "impact": 0.1, "detectability": 0.1}
    if oversight_level is not None:
        payload["oversight_level"] = oversight_level
    (state_dir / "risk-profile.json").write_text(json.dumps(payload))


def test_bypass_true_when_oversight_is_vibe(tmp_path):
    _write_risk_profile(tmp_path, "vibe")
    assert _should_bypass(tmp_path) is True


def test_bypass_false_when_oversight_is_standard(tmp_path):
    _write_risk_profile(tmp_path, "standard")
    assert _should_bypass(tmp_path) is False


def test_bypass_false_when_oversight_is_strict(tmp_path):
    _write_risk_profile(tmp_path, "strict")
    assert _should_bypass(tmp_path) is False


def test_bypass_false_when_oversight_is_human_review(tmp_path):
    _write_risk_profile(tmp_path, "human_review")
    assert _should_bypass(tmp_path) is False


def test_bypass_false_when_risk_profile_missing(tmp_path):
    assert _should_bypass(tmp_path) is False


def test_bypass_false_when_json_malformed(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "risk-profile.json").write_text("{not valid json")
    assert _should_bypass(tmp_path) is False


def test_bypass_false_when_oversight_key_missing(tmp_path):
    _write_risk_profile(tmp_path, None)
    assert _should_bypass(tmp_path) is False


def test_main_exits_silently_when_bypass_true(tmp_path, capsys):
    """Integration: main() must produce no stdout when bypass is active.

    is_test_file/is_impl_file/find_test_file are mocked because pytest's tmp_path
    contains 'test_' in its name, which spuriously triggers is_test_file. This test
    is about the bypass branch only — file classification is covered by test_tdd_enforcer.py.
    """
    impl_file = tmp_path / "src" / "user.py"
    impl_file.parent.mkdir(parents=True)
    impl_file.write_text("class User: pass")

    state_dir = tmp_path / "state"
    _write_risk_profile(state_dir, "vibe")

    hook_payload = {"tool_input": {"file_path": str(impl_file)}}

    with patch("tdd_enforcer.get_state_dir", return_value=state_dir), \
         patch("tdd_enforcer.read_hook_stdin", return_value=hook_payload), \
         patch("tdd_enforcer.is_test_file", return_value=False), \
         patch("tdd_enforcer.is_impl_file", return_value=True), \
         patch("tdd_enforcer.find_test_file", return_value=False):
        rc = main()

    captured = capsys.readouterr()
    assert rc == 0
    assert captured.out == ""


def test_main_warns_when_bypass_false_and_no_test(tmp_path, capsys):
    """Integration: main() warns normally when oversight is standard."""
    impl_file = tmp_path / "src" / "user.py"
    impl_file.parent.mkdir(parents=True)
    impl_file.write_text("class User: pass")

    state_dir = tmp_path / "state"
    _write_risk_profile(state_dir, "standard")

    hook_payload = {"tool_input": {"file_path": str(impl_file)}}

    with patch("tdd_enforcer.get_state_dir", return_value=state_dir), \
         patch("tdd_enforcer.read_hook_stdin", return_value=hook_payload), \
         patch("tdd_enforcer.is_test_file", return_value=False), \
         patch("tdd_enforcer.is_impl_file", return_value=True), \
         patch("tdd_enforcer.find_test_file", return_value=False):
        rc = main()

    captured = capsys.readouterr()
    assert rc == 0
    assert "[devflow TDD]" in captured.out
