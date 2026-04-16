---
name: devflow-model-routing
description: >
  Guide for selecting the right Claude model per task type.
  Use when deciding which model to use for a specific task or subagent.
---

# Model Routing

## Decision Table

| Model | ID | USD / MTok (in / out) | Best for |
|---|---|---|---|
| **Opus 4.7** | `claude-opus-4-7` | $5 / $25 | Architectural planning, system design, complex trade-off analysis, hard debugging without a hypothesis. Adaptive thinking (no fixed budget). **Default Opus tier.** |
| **Opus 4.6** | `claude-opus-4-6` | $5 / $25 | Legacy. Use only when Fast mode latency ($30 / $150) is required — 4.7 does not support Fast mode. |
| **Sonnet 4.6** | `claude-sonnet-4-6` | $3 / $15 | Implementation, refactoring, code review, debugging with a formed hypothesis — **default for 90% of tasks** |
| **Haiku 4.5** | `claude-haiku-4-5-20251001` | $1 / $5 | Simple search, formatting, trivial transformations, tasks under 2 min |

Pricing source: https://platform.claude.com/docs/en/about-claude/pricing (last revised 2026-04-16).

## Principle

> **Start with Sonnet. Scale to Opus only if stuck.**

Opus is ~**1.67x** more expensive than Sonnet per output token ($25 vs $15). For **Opus 4.7** specifically, Anthropic notes the new tokenizer can produce up to ~**1.35x more tokens** for the same content, so the realistic effective cost vs Sonnet can land around **1.67 × 1.35 ≈ 2.25x** in the worst case. Measure before generalising.

## Opus 4.6 vs 4.7

Both versions are priced identically ($5 / $25) but have different trade-offs:

| Axis | Opus 4.6 | Opus 4.7 |
|---|---|---|
| Tokenizer | Known, stable | **New** — up to 1.35x more tokens for the same content |
| Fast mode | **Yes** — $30 / $150 for lower latency | No |
| Benchmarks | Baseline | Higher on coding / vision tasks |
| Cache behavior | Known | Needs measurement |

**Default stance:** **Opus 4.7** is the default Opus tier for planning, design, and hard debugging. It uses adaptive thinking (no fixed thinking budget) and with `effortLevel: xhigh` is tuned for strong autonomy without token runaway. Opus 4.6 is legacy — only fall back when Fast mode latency is required (4.7 does not support Fast mode). Measure effective cost per task via `telemetry/cli.py stats --by-model` if tokenizer inflation becomes a concern.

**Per-task override:** invoke Claude Code with `--model claude-opus-4-6` for legacy sessions when Fast mode is needed.

## Where Model Selection Matters

Model routing applies in three practical scenarios:

1. **`/model` command between tasks** — switch the active model when the next task has different demands (e.g., switch to Opus before a complex architectural discussion, back to Sonnet for implementation)
2. **Subagent dispatching** — when using `superpowers:dispatching-parallel-agents`, choose the model that fits each subagent's job (Haiku for search, Sonnet for implementation, Opus for review)
3. **Starting a session** — pick the right model upfront based on what the session will primarily involve

Model selection does NOT happen automatically mid-conversation. You choose the model; the model does not switch itself.

## When Each Model Shines

### Opus 4.7 (default Opus tier)
- Designing a new system from scratch with multiple interacting components
- Evaluating architectural trade-offs (e.g., "monolith vs microservices for this use case")
- Debugging a subtle issue where you have no hypothesis and need deep reasoning
- Writing a spec for a complex feature with many edge cases
- Long-running agentic tasks with full upfront context (favor `effortLevel: xhigh` + Auto Mode)

### Sonnet 4.6
- Implementing features from a spec or plan
- Refactoring code with a clear goal
- Code review and debugging when you know roughly where the problem is
- Writing and fixing tests
- Day-to-day development work (this is the workhorse)

### Haiku 4.5
- Searching codebases for patterns or references
- Formatting, renaming, and simple transformations
- Generating boilerplate from a template
- Quick lookups and summaries

## For Subagents

| Subagent type | Recommended model |
|---|---|
| Planning / architectural review | Opus |
| Implementation | Sonnet |
| Verification / code review | Sonnet |
| Search / simple analysis | Haiku |
