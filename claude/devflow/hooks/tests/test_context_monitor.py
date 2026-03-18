import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from context_monitor import tokens_to_pct
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
