# Task Risk Profiler Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a three-dimension risk profiler (Probability × Impact × Detectability) that runs before every task execution and determines the `oversight_level` gating verification depth. Integrates with TelemetryStore via upsert.

**Architecture:** `risk/profiler.py` is a pure module (no I/O). `hooks/pre_task_profiler.py` is the Claude Code PreToolUse hook that reads context, calls the profiler, writes `state/{session_id}/risk-profile.json`, and emits `[devflow:risk]` to stdout. TelemetryStore integration uses the existing `record()` upsert.

**Tech Stack:** Python 3.13, stdlib only in profiler, pytest, unittest.mock

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `risk/__init__.py` | Makes `risk/` a Python package |
| Create | `risk/profiler.py` | TaskRiskProfiler: 4 scorers + profile() |
| Create | `hooks/pre_task_profiler.py` | PreToolUse hook: reads context, calls profiler, writes state, logs telemetry |
| Create | `hooks/tests/test_risk_profiler.py` | All tests (RED then GREEN) |
| Modify | `docs/audit-20260331.md` | Document Prompt 2 |

All paths relative to `~/.claude/devflow/`.

---

## Task 1: risk/profiler.py — pure scoring engine

**Files:** `risk/__init__.py`, `risk/profiler.py`, `hooks/tests/test_risk_profiler.py` (RED only)

- [ ] **Step 1: Write failing tests for all four scorer methods and profile()**

Create `hooks/tests/test_risk_profiler.py` with the full test suite for:
- `score_probability()`: 4 cases (low/high/medium/missing keys)
- `score_impact()`: 4 cases (production dominates, wide radius, no risk, external+moderate)
- `score_detectability()`: 3 cases (high coverage, low coverage, medium)
- `determine_oversight_level()`: 6 cases (vibe ×2, standard, strict, human_review, precedence)
- `profile()`: 4 cases (dataclass shape, factors dict, empty context no raise, malformed no raise)

Run `python3.13 -m pytest hooks/tests/test_risk_profiler.py -q` → **MUST FAIL** (ImportError).

- [ ] **Step 2: Create risk/__init__.py and risk/profiler.py**

Implement `TaskRiskProfiler` with all four methods per the spec. Run tests → **MUST PASS**.

---

## Task 2: hooks/pre_task_profiler.py — Claude Code hook

**Files:** `hooks/pre_task_profiler.py`, add hook tests to `hooks/tests/test_risk_profiler.py`

- [ ] **Step 3: Write failing tests for the hook**

Add to `hooks/tests/test_risk_profiler.py`:
- `test_hook_writes_risk_profile_json`: hook writes `state/{session_id}/risk-profile.json` with correct fields
- `test_hook_prints_correct_format`: stdout contains `[devflow:risk] oversight=... probability=... impact=... detectability=...`
- `test_hook_calls_telemetry_store`: `TelemetryStore.record()` called with correct columns (mock the store)
- `test_hook_handles_missing_project_profile`: no crash when `project-profile.json` absent

Run → **MUST FAIL**.

- [ ] **Step 4: Implement hooks/pre_task_profiler.py**

Hook reads context from:
1. `state/{session_id}/project-profile.json` → `stack`
2. `state/{session_id}/active-spec.json` → `task_complexity` (from `plan_path` length heuristic: len > 200 = complex, > 50 = simple, else trivial)
3. `git diff --stat HEAD` → count files for `files_to_modify`
4. Coverage report if available

Runs `TaskRiskProfiler().profile(context)`, writes `risk-profile.json`, logs via `TelemetryStore`, prints `[devflow:risk] oversight=... probability=... impact=... detectability=...`.

Run → **MUST PASS**.

---

## Task 3: Verify + Document

- [ ] **Step 5: Full test suite run**

```bash
cd ~/.claude/devflow && python3.13 -m pytest hooks/tests/ -q
```
Baseline: 334. New total must be ≥ 334 + N (where N = tests written).

- [ ] **Step 6: Manual smoke test**

```bash
cd ~/.claude/devflow && python3.13 hooks/pre_task_profiler.py
```
Should print `[devflow:risk] oversight=... probability=... impact=... detectability=...` without error.

- [ ] **Step 7: Update audit-20260331.md**

Add "Prompt 2: task risk profiler — N tests added, 334 → M total" section with file list and test breakdown.

---

## Scoring Reference

### score_probability (weighted average)
- stack: typescript=0.10, python=0.20, dart=0.30, other=0.50 (weight 0.20)
- context_coverage: full=0.10, partial=0.40, sparse=0.80 (weight 0.35)
- task_complexity: trivial=0.10, simple=0.30, complex=0.70 (weight 0.30)
- codebase_health: clean=0.10, mixed=0.40, legacy=0.80 (weight 0.15)

### score_impact (max of all factors)
- is_production: True=0.80, False=0.20
- impact_radius: isolated(1 file)=0.10, moderate(2-5)=0.40, wide(6+)=0.80
- has_external_dependency: True=0.30, False=0.00

### score_detectability (weighted average)
- test_coverage: high=0.10, medium=0.40, low=0.80 (weight 0.50)
- typed_language: True=0.10, False=0.40 (weight 0.30)
- has_e2e: True=0.10, False=0.30 (weight 0.20)

### determine_oversight_level (precedence: human_review > strict > standard > vibe)
- vibe: max(p, i) < 0.30 AND d < 0.30
- standard: max(p, i) < 0.50
- strict: i > 0.60 OR (p > 0.50 AND d > 0.40)
- human_review: i > 0.75 AND d > 0.60
