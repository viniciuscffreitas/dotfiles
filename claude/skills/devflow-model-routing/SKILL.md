---
name: devflow-model-routing
description: >
  Guide for selecting the right Claude model per task type.
  Use when deciding which model to use for a specific task or subagent.
---

# Model Routing

## Decision Table

| Model | ID | Best for |
|---|---|---|
| **Opus 4.6** | `claude-opus-4-6` | Architectural planning, system design, complex trade-off analysis, very hard debugging without a hypothesis |
| **Sonnet 4.6** | `claude-sonnet-4-6` | Implementation, refactoring, code review, debugging with a formed hypothesis — **default for 90% of tasks** |
| **Haiku 4.5** | `claude-haiku-4-5-20251001` | Simple search, formatting, trivial transformations, tasks under 2 min |

## Principle

> **Start with Sonnet. Scale to Opus only if stuck.**

Opus is ~5x more expensive. Use it with intention.

## Where Model Selection Matters

Model routing applies in three practical scenarios:

1. **`/model` command between tasks** — switch the active model when the next task has different demands (e.g., switch to Opus before a complex architectural discussion, back to Sonnet for implementation)
2. **Subagent dispatching** — when using `superpowers:dispatching-parallel-agents`, choose the model that fits each subagent's job (Haiku for search, Sonnet for implementation, Opus for review)
3. **Starting a session** — pick the right model upfront based on what the session will primarily involve

Model selection does NOT happen automatically mid-conversation. You choose the model; the model does not switch itself.

## When Each Model Shines

### Opus 4.6
- Designing a new system from scratch with multiple interacting components
- Evaluating architectural trade-offs (e.g., "monolith vs microservices for this use case")
- Debugging a subtle issue where you have no hypothesis and need deep reasoning
- Writing a spec for a complex feature with many edge cases

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
