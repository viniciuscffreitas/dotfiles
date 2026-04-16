# Opus 4.6 → 4.7 Migration Policy

**Last revised:** 2026-04-16

## Default stance

`claude-opus-4-6` remains the default Opus tier for all devflow components that route to Opus:

- `judge/evaluator.py` and `hooks/post_task_judge.py`
- `agents/firewall.py`
- `hooks/instinct_capture.py`
- User-facing recommendation from `skills/devflow-model-routing/SKILL.md`

**Rationale:** Opus 4.7 is priced identically to 4.6 ($5 / $25 per MTok), but its new tokenizer can produce up to ~1.35x more tokens for the same content. That inflation is **per-workload** — it depends on the shape of the prompts and tool schemas. Until we measure it on real devflow traffic, flipping the default is premature.

4.7 also loses **Fast mode** (the $30 / $150 6x-priced variant of 4.6), which matters for interactive latency in some hooks.

## Criterion for flipping the default to 4.7

We flip `claude-opus-4-6` → `claude-opus-4-7` as the default **only** when both hold:

1. **Measured token inflation ≤ 15%** over a representative week of mixed devflow traffic.
2. **Judge verdict does not degrade** on a stable fixture set (no statistically significant drop in `pass` rate when the judge runs on 4.7 vs 4.6 for the same inputs).

Both checks use telemetry shipped in the same workstream as this doc.

## How to measure

1. Opt a non-default workload in to 4.7 for ≥7 days by passing `--model claude-opus-4-7` on those invocations.
2. Run `python3.13 ~/.claude/devflow/telemetry/cli.py stats --by-model` to get per-model run count and total cost.
3. Compute **effective cost per run** = `total_cost_usd / runs`. Since pricing per token is identical between 4.6 and 4.7, the delta comes entirely from tokens consumed — which is the inflation signal.
4. For the judge-quality check: run `test_judge.py` fixture suite twice (once on 4.6, once on 4.7) and compare pass rates.

If inflation < 15% **and** judge quality holds → flip the default in this doc + in `skills/devflow-model-routing/SKILL.md` + in the hooks that hardcode model names.

## Per-task override

Users can always opt in to 4.7 for a single session without changing any defaults:

```bash
claude --model claude-opus-4-7 ...
```

This is the recommended way to experiment with 4.7 today.

## Checkpoint cadence

Revisit this policy:

- Every **90 days** from the last-revised date above, or
- Whenever Anthropic ships a newer Opus generation (4.8+), or
- When `stats --by-model` shows >1000 runs on 4.7 (enough signal to make a call).

## References

- Pricing (official): https://platform.claude.com/docs/en/about-claude/pricing
- `hooks/cost_tracker.py` — pricing table and fallback model
- `skills/devflow-model-routing/SKILL.md` — user-facing routing guidance
- `telemetry/store.py::cost_by_model` — per-model aggregation
- `telemetry/cli.py stats --by-model` — CLI entry point for the measurement
