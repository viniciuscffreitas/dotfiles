"""PostToolUse hook (broad matcher) — monitors context window usage.
Warns at ~80% and ~90%. Non-blocking.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import (
    AUTOCOMPACT_BUFFER_TOKENS,
    CONTEXT_CAUTION_PCT,
    CONTEXT_WARN_PCT,
    CONTEXT_WINDOW_TOKENS,
    hook_context,
    read_hook_stdin,
)


def _get_window(hook_data: dict) -> int:
    """Return the context window size from hook payload, falling back to constant.

    Reads context_window_tokens from the hook data so Opus 4.6 / Sonnet 4.6
    (1M token context) don't trigger premature warnings from a hardcoded value.
    """
    payload_window = hook_data.get("context_window_tokens", 0)
    if payload_window and payload_window > 0:
        return int(payload_window)
    return CONTEXT_WINDOW_TOKENS


def tokens_to_pct(tokens_used: int, window: int = CONTEXT_WINDOW_TOKENS) -> float:
    compaction_threshold = window - AUTOCOMPACT_BUFFER_TOKENS
    if compaction_threshold <= 0:
        return 100.0
    return min(100.0, (tokens_used / compaction_threshold) * 100)


def main() -> int:
    try:
        hook_data = read_hook_stdin()
        tokens_used = hook_data.get("context_tokens_used", 0)
        if not tokens_used:
            return 0

        window = _get_window(hook_data)
        pct = tokens_to_pct(tokens_used, window=window)

        if pct >= CONTEXT_CAUTION_PCT:
            msg = (
                f"[devflow] Context at {pct:.0f}% — "
                f"Wrap up your current task. Auto-compaction will trigger soon."
            )
            print(hook_context(msg))
        elif pct >= CONTEXT_WARN_PCT:
            msg = (
                f"[devflow] Context at {pct:.0f}% — "
                f"Consider using /learn to capture important discoveries."
            )
            print(hook_context(msg))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
