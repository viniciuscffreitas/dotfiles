# AGENTS.md — devflow Harness Contract

> This file is a **contract**, not a tutorial.
> It tells any agent — human or AI — what it MUST do, what it MUST NOT do,
> and what the harness enforces automatically.

---

## 1. Identity

**devflow** is a quality and oversight harness for Claude Code. It wraps every
agent session with risk profiling, context isolation, linting, semantic
evaluation, and telemetry so that AI-generated changes meet the same bar as
human-reviewed code. It is maintained by Vinicius Freitas and lives at
`~/.claude/devflow/`. The harness is language-agnostic: hooks fire on Claude
Code events regardless of the project stack. The central config is
`devflow-config.json`; per-project overrides live in `.devflow-config.json`
at the repo root.

---

## 2. Harness Overview

All devflow hooks registered in `~/.claude/settings.json`:

| Hook | Event | Matcher | What it enforces |
|---|---|---|---|
| `discovery_scan.py` | SessionStart | — | Detects project profile (tracker, toolchain, framework); writes `project-profile.json` |
| `post_compact_restore.py` | SessionStart | compact | Restores active-spec state after context compaction |
| `spec_phase_tracker.py` | UserPromptSubmit | — | Detects `/spec` invocations; writes `PENDING` state immediately, before Claude responds |
| `pre_push_gate.py` | PreToolUse | Bash | Intercepts `git push`; runs toolchain-specific quality checks; blocks on failure |
| `file_checker.py` | PostToolUse | Write\|Edit\|MultiEdit | Enforces file-size limits (warn ≥ 400 lines, block ≥ 600 lines) |
| `tdd_enforcer.py` | PostToolUse | Write\|Edit\|MultiEdit | Warns when source files are written without a corresponding test file |
| `context_monitor.py` | PostToolUse | Read\|Write\|Edit\|MultiEdit\|Bash\|Glob\|Grep | Monitors context window usage; warns at ~80 % and ~90 % |
| `pre_compact.py` | PreCompact | — | Persists active-spec state before compaction so it survives context reset |
| `spec_stop_guard.py` | Stop | — | Blocks session exit when a spec is in `PENDING` or `IMPLEMENTING` state |
| `task_telemetry.py` | Stop | — | Scans session JSONL; records per-phase token cost to `telemetry/sessions.jsonl` |

Additional hooks that **exist in `hooks/` but are not currently registered**
(available for activation):

| Hook | Intended Event | What it would enforce |
|---|---|---|
| `pre_task_profiler.py` | PreToolUse | Computes risk score + oversight level; writes `risk-profile.json` |
| `pre_task_firewall.py` | PreToolUse | Delegates isolated read tasks to a clean-context sub-agent |
| `post_task_judge.py` | Stop | Runs LLM-as-judge on the session diff; routes result via `JudgeRouter` |

---

## 3. Oversight Levels

When `pre_task_profiler.py` is active, every task is scored and assigned an
oversight level that controls whether the judge runs and whether a failed
evaluation blocks the session.

| Level | When triggered | Judge runs | Blocks on fail | Human required |
|---|---|---|---|---|
| `vibe` | risk prob < 0.2 | No | No | No |
| `standard` | 0.2 ≤ prob < 0.5 | Yes | No | No |
| `strict` | 0.5 ≤ prob < 0.8 | Yes | Yes (exit 1) | No |
| `human_review` | prob ≥ 0.8 **or** high-impact flag | Yes | Always | **Yes** |

The current risk profile for the session is written to
`~/.claude/devflow/state/<session-id>/risk-profile.json` and read by
`post_task_judge.py` at Stop time.

---

## 4. Rules for Agents

Any agent — human or AI — working in this repository MUST follow these rules.
Where a linter or hook is listed, it enforces the rule automatically; violations
that reach the push gate will block the push.

1. **Never cross feature boundaries.**
   Do not write to `lib/features/X/` from a file in `lib/features/Y/`.
   *(`import_boundary` linter enforces this.)*

2. **Keep files short.**
   Files with ≥ 400 lines trigger a warning; files with ≥ 600 lines are blocked.
   *(Configured in `devflow-config.json`; `file_size` linter enforces this.)*

3. **Every source file needs a test file.**
   Every file under `lib/features/` must have a corresponding test.
   The `coverage_gate` linter matches the `lib/features/` path pattern (hardcoded
   in `linters/engine.py`). For projects with a different structure, this rule
   applies to whatever directory the linter is configured to scan.
   *(`coverage_gate` linter enforces this.)*

4. **Hooks and analysis are not ordinary code.**
   Never modify `hooks/` or `analysis/` without updating the hook test suite
   under `hooks/tests/`.

5. **Never suppress or bypass harness hooks.**
   Do not patch hook output, intercept `sys.exit`, or otherwise circumvent
   hook decisions. The harness is the safety layer — disabling it removes
   the safety layer.

6. **Sub-agents receive a FirewallTask — not the full context.**
   When the firewall hook is active, sub-agents spawned by this repo get a
   `FirewallTask` with explicit `allowed_paths` and `allowed_tools`. Do not
   expand the allowed set without justification.

7. **TDD: test before implementation.**
   Write a failing test (RED) before writing the implementation (GREEN).
   If a file is being added and no test runner is available, note the exception
   explicitly in the commit message.

8. **One logical change per commit.**
   Commit after each GREEN phase. Atomic, descriptive commits only.
   No `TODO` in committed code without a linked issue.

9. **YAGNI — no speculative abstractions.**
   Do not create helpers, utilities, or abstractions for hypothetical future
   requirements. Three similar lines of code is better than a premature
   abstraction.

10. **Stop on `human_review`.**
    If a task is scored `oversight=human_review`, stop immediately and surface
    the risk profile to the human before proceeding. Do not attempt to lower
    the score by rephrasing the task.

---

## 5. Context Anxiety Warning

If you find yourself reading many files before writing a single line, stop.
This is **context anxiety** — a pattern where the agent reads broadly to feel
safe rather than acting on what it already knows. Check your spec. Identify the
**one file** you need to touch. Start there. The `context_monitor` hook will
warn you when the context window is at 80 % and 90 %; if you are still reading
at that point and have not written anything, you are in context anxiety. Use
`python3 ~/.claude/devflow/hooks/anxiety_report.py` to get an investigation-depth-to-action ratio
for the current session and redirect focus.

---

## 6. Telemetry and Observability

### What gets recorded

`task_telemetry.py` (Stop hook) scans the session JSONL and records:

- **Tokens per phase** — cost of the understand/plan phase (`PENDING → IMPLEMENTING`)
  vs. the build/verify phase (`IMPLEMENTING → COMPLETED`)
- **Phase ratio** — a high plan:build ratio is a proxy for context dispersion
  (too much reading, not enough building)
- **Project slug** — derived from the working directory
- **Session ID** and timestamp

### Where it lives

| Store | Path | Format |
|---|---|---|
| Primary log | `~/.claude/devflow/telemetry/sessions.jsonl` | JSONL, one record per session |
| SQLite analytics | `~/.claude/devflow/telemetry/devflow.db` | Dual-write partner to the JSONL |
| Active spec state | `~/.claude/devflow/state/<session-id>/active-spec.json` | JSON, phase transitions |
| Risk profile | `~/.claude/devflow/state/<session-id>/risk-profile.json` | JSON, oversight level |

### How to query

```bash
# Last 10 sessions
python3 ~/.claude/devflow/hooks/telemetry_report.py --last 10

# Filter by project
python3 ~/.claude/devflow/hooks/telemetry_report.py --project <slug>

# Context anxiety ratio for current session
python3 ~/.claude/devflow/hooks/anxiety_report.py

# Harness health check
python3 ~/.claude/devflow/hooks/health_report.py
```
