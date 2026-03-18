---
name: devflow-agent-orchestration
description: >
  Reference guide for agent orchestration patterns.
  Use when structuring multi-agent work or deciding how to parallelize tasks.
---

# Agent Orchestration Patterns

## Critical Architectural Rule

> **Subagents do NOT spawn other subagents.**
> All delegation flows exclusively through the Main Agent.
> This prevents infinite loops and opaque hierarchies.

## Patterns (in increasing order of complexity)

### 0. Baseline
**When:** Simple task, 1 step, no orchestration needed.
**Example:** "What's in config.json?"

### 1. Prompt Chaining
**When:** Sequential steps where the output of one feeds the next.
**Gate:** Checkpoint between steps that validates output before proceeding.
**Example:** Analyze code -> generate tests -> review tests -> report

### 2. Routing
**When:** Input needs to be classified before being processed in different ways.
**Example:** Detect bug/feature/question -> route to correct flow

### 3. Parallelization
**When:** Independent subtasks with no shared state.
**Use:** `superpowers:dispatching-parallel-agents`
**Variants:**
- **Sectioning:** divides data among identical agents
- **Voting:** same task on multiple agents, select best result
- **Master-Clone:** isolated instances for independent domains

### 4. Orchestrator-Workers
**When:** Complex task requires specialist agents with different contexts.
**Agents are DIFFERENT** from each other (vs Parallelization where they are identical).
**Example:** Architect agent delegates to implementer agents per module

### 5. Evaluator-Optimizer
**When:** Needs to iterate until a minimum quality criterion is met.
**Caution:** Always define a clear exit criterion to avoid infinite loops.
**Example:** Generate -> evaluate quality -> regenerate if poor -> repeat

## Workflows vs Autonomous Agents

| | Workflow | Autonomous Agent |
|---|---|---|
| **Control** | Code determines the flow | LLM decides next step |
| **Predictability** | High | Low |
| **When to use** | Known, repeatable process | Exploratory task |

**Rule:** Prefer workflows. Use autonomous agents only when the trajectory cannot be predefined.

## Decision Flowchart

```
Task received
    |
    +-> Simple 1-step task?                    -> Baseline
    +-> Sequential steps with dependencies?    -> Prompt Chaining
    +-> Need to classify the input?            -> Routing
    +-> Independent parts in parallel?         -> Parallelization
    +-> Requires different specialists?        -> Orchestrator-Workers
    +-> Iterate until minimum quality?         -> Evaluator-Optimizer
```
