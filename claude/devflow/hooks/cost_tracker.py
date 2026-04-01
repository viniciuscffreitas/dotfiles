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

# Pricing in USD per million tokens (as of 2026-03)
# cache_read is ~10% of input; cache_creation is ~125% of input
CLAUDE_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-6": {
        "input": 15.00, "output": 75.00,
        "cache_read": 1.50, "cache_creation": 18.75,
    },
    "claude-sonnet-4-6": {
        "input": 3.00, "output": 15.00,
        "cache_read": 0.30, "cache_creation": 3.75,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80, "output": 4.00,
        "cache_read": 0.08, "cache_creation": 1.00,
    },
}

_FALLBACK_MODEL = "claude-sonnet-4-6"


def _format_k(n: int) -> str:
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def _compute_cost(model: str, usage: dict) -> float:
    pricing = CLAUDE_PRICING.get(model, CLAUDE_PRICING[_FALLBACK_MODEL])
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
                TelemetryStore().record({"task_id": session_id, "cost_usd": cost_usd})
            except Exception:
                pass

    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
