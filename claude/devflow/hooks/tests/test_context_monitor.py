import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from context_monitor import tokens_to_pct, _get_window, main
from _util import AUTOCOMPACT_BUFFER_TOKENS, CONTEXT_WINDOW_TOKENS


def test_tokens_to_pct_zero():
    assert tokens_to_pct(0) == 0.0


def test_tokens_to_pct_at_warn_boundary():
    threshold = CONTEXT_WINDOW_TOKENS - AUTOCOMPACT_BUFFER_TOKENS  # 167000
    pct = tokens_to_pct(int(threshold * 0.80))
    assert 79.9 <= pct <= 80.1


def test_tokens_to_pct_at_caution_boundary():
    threshold = CONTEXT_WINDOW_TOKENS - AUTOCOMPACT_BUFFER_TOKENS
    pct = tokens_to_pct(int(threshold * 0.90))
    assert 89.9 <= pct <= 90.1


def test_tokens_to_pct_caps_at_100():
    assert tokens_to_pct(999_999) == 100.0


def test_tokens_to_pct_custom_window():
    pct = tokens_to_pct(100_000, window=100_000 + AUTOCOMPACT_BUFFER_TOKENS)
    assert pct == 100.0


def test_tokens_to_pct_zero_threshold():
    """If window <= buffer, should return 100 instead of dividing by zero."""
    pct = tokens_to_pct(1000, window=AUTOCOMPACT_BUFFER_TOKENS)
    assert pct == 100.0


def test_tokens_to_pct_negative_threshold():
    pct = tokens_to_pct(1000, window=0)
    assert pct == 100.0


# --- Dynamic window from payload ---

def test_get_window_uses_payload_field():
    """_get_window() should return context_window_tokens from hook data."""
    hook_data = {"context_window_tokens": 1_000_000}
    assert _get_window(hook_data) == 1_000_000


def test_get_window_falls_back_to_constant():
    """_get_window() should fall back to CONTEXT_WINDOW_TOKENS when field absent."""
    assert _get_window({}) == CONTEXT_WINDOW_TOKENS


def test_get_window_ignores_zero():
    """A zero payload window is invalid — fall back to constant."""
    assert _get_window({"context_window_tokens": 0}) == CONTEXT_WINDOW_TOKENS


def test_tokens_to_pct_with_1m_window_is_low():
    """200K tokens on a 1M window = ~20%, well below warn threshold."""
    window_1m = 1_000_000
    pct = tokens_to_pct(200_000, window=window_1m)
    assert pct < 25.0


def test_main_uses_payload_window_1m_no_warn(capsys):
    """With 1M window in payload, 200K tokens should NOT trigger a warning."""
    hook_data = {
        "context_tokens_used": 200_000,
        "context_window_tokens": 1_000_000,
    }
    with patch("context_monitor.read_hook_stdin", return_value=hook_data):
        rc = main()
    captured = capsys.readouterr()
    assert rc == 0
    assert "Context at" not in captured.out


def test_main_uses_payload_window_1m_warns_at_900k(capsys):
    """With 1M window, 900K tokens (~94%) should trigger caution warning."""
    hook_data = {
        "context_tokens_used": 900_000,
        "context_window_tokens": 1_000_000,
    }
    with patch("context_monitor.read_hook_stdin", return_value=hook_data):
        rc = main()
    captured = capsys.readouterr()
    assert rc == 0
    assert "Context at" in captured.out


def test_main_fallback_constant_warns_at_170k(capsys):
    """Without window in payload, 170K tokens (~102% of 167K threshold) → caution."""
    hook_data = {"context_tokens_used": 170_000}
    with patch("context_monitor.read_hook_stdin", return_value=hook_data):
        rc = main()
    captured = capsys.readouterr()
    assert rc == 0
    assert "Context at" in captured.out
