#!/usr/bin/env python3
"""
Stop hook — computes USD cost for the session and persists to TelemetryStore.

Reads model + token counts from hook stdin, looks up pricing, prints a summary
line, and writes cost_usd to the telemetry DB.

Always exits 0 — never blocks session exit.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _util import read_hook_stdin

try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from telemetry.store import TelemetryStore
except ImportError:
    TelemetryStore = None  # type: ignore[assignment,misc]

# Pricing in USD per million tokens (last revised 2026-04-16).
# Source: https://platform.claude.com/docs/en/about-claude/pricing
# Convention: cache_read = 10% of input; cache_creation = 125% of input.
# Note: Opus 4.7 shares pricing with 4.6 but uses a new tokenizer that can
# produce up to ~1.35x more tokens for the same content — see
# docs/opus-4-7-policy.md for migration guidance.
CLAUDE_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-7": {
        "input": 5.00, "output": 25.00,
        "cache_read": 0.50, "cache_creation": 6.25,
    },
    "claude-opus-4-6": {
        "input": 5.00, "output": 25.00,
        "cache_read": 0.50, "cache_creation": 6.25,
    },
    "claude-sonnet-4-6": {
        "input": 3.00, "output": 15.00,
        "cache_read": 0.30, "cache_creation": 3.75,
    },
    "claude-haiku-4-5-20251001": {
        "input": 1.00, "output": 5.00,
        "cache_read": 0.10, "cache_creation": 1.25,
    },
}

_FALLBACK_MODEL = "claude-sonnet-4-6"


def _format_k(n: int) -> str:
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _compute_cost(model: str, usage: dict) -> float:
    pricing = CLAUDE_PRICING.get(model)
    if pricing is None:
        print(
            f"[devflow:cost] WARN unknown model '{model}' — falling back to "
            f"{_FALLBACK_MODEL} pricing. Update CLAUDE_PRICING in "
            f"hooks/cost_tracker.py.",
            file=sys.stderr,
        )
        pricing = CLAUDE_PRICING[_FALLBACK_MODEL]
    input_tok = int(usage.get("input_tokens") or 0)
    output_tok = int(usage.get("output_tokens") or 0)
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    cache_create = int(usage.get("cache_creation_input_tokens") or 0)
    return (
        input_tok * pricing["input"]
        + output_tok * pricing["output"]
        + cache_read * pricing["cache_read"]
        + cache_create * pricing["cache_creation"]
    ) / 1_000_000


def _model_short(model: str) -> str:
    """Strip 'claude-' prefix for compact display."""
    return model.removeprefix("claude-")


def main() -> int:
    try:
        hook_data = read_hook_stdin()
        model = hook_data.get("model") or ""
        usage = hook_data.get("usage") or {}
        if not model or not isinstance(usage, dict):
            return 0

        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
        cache_read = int(usage.get("cache_read_input_tokens") or 0)
        cache_create = int(usage.get("cache_creation_input_tokens") or 0)
        session_id = hook_data.get("session_id") or ""

        cost_usd = _compute_cost(model, usage)

        cache_part = ""
        if cache_read or cache_create:
            cache_part = f" cr={_format_k(cache_read)} cc={_format_k(cache_create)} |"

        print(
            f"[devflow:cost] model={_model_short(model)} | "
            f"in={_format_k(input_tokens)} out={_format_k(output_tokens)}"
            f"{cache_part} | "
            f"${cost_usd:.3f}"
        )

        if TelemetryStore is not None and session_id:
            try:
                from datetime import datetime, timezone
                TelemetryStore().record({
                    "task_id": session_id,
                    "session_id": session_id,
                    "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                    "cost_usd": cost_usd,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_read_tokens": cache_read,
                    "cache_creation_tokens": cache_create,
                })
            except Exception:
                pass

    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
