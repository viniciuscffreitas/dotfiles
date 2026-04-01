<div align="center">

# devflow

**Claude Code is brilliant. It has no guardrails.**

*Automatic quality hooks, TDD enforcement, spec-driven workflows, risk-aware execution, and self-evaluating telemetry — for every project, without configuration.*

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-793-brightgreen.svg)](#running-tests)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/powered%20by-Claude%20Code-orange.svg)](https://claude.ai/code)

</div>

---

## The thing nobody warns you about

You give Claude Code a task. It reads the files, understands the context, and writes genuinely good code.

Then it submits the implementation without a single test. No one stopped it.

You ask it to fix a bug. It fixes the bug and breaks three other things. No one warned it.

You're 90 minutes into a complex refactor. The context window fills up and auto-compacts. Claude comes back with no memory of what it was doing.

You're working on something sensitive. The agent spends 40k tokens just orienting itself before writing a line of code — and you don't find out until the session ends and the bill arrives.

**Claude Code doesn't have standards. It has yours — but only when you're watching.**

---

## The blind spots

Five things Claude Code can't do on its own:

- **No automatic quality checks** — you have to manually ask for linting, formatting, and file length awareness on every task
- **No TDD enforcement** — nothing prevents writing implementation before tests; it will do it every time if you don't stop it
- **Context evaporates on compaction** — when the window fills and auto-compacts, you lose track of what you were doing and so does Claude
- **No protection against accidental exit** — you can close a session mid-spec with no warning and no way to resume cleanly
- **No repeatable workflow** — every feature starts from scratch; every bugfix is handled differently; there's no process

But there are five more that only become visible at scale:

- **No risk awareness** — destructive or high-impact tasks get the same treatment as trivial ones; no oversight calibration
- **No quality evaluation** — Claude decides when it's done; there's no LLM evaluating whether the output actually meets the spec
- **No over-investigation detection** — the agent can burn 80% of its context just reading files before writing a single line of code
- **No harness visibility** — the hooks themselves can become stale, slow, or broken; nothing tells you when they stop working
- **No longitudinal signal** — every session is an island; there's no accumulation of evidence about what's actually working

These aren't complaints. They're the gaps that make working with Claude Code feel inconsistent — brilliant when you're present, fragile when you're not, and invisible as a system.

---

## What it looks like with devflow

```
[editing src/payments/processor.py]

PostToolUse → file_checker
  ↳ ruff check --fix: 2 issues auto-fixed
  ↳ ⚠ file length: 423 lines (warn threshold: 400)

PostToolUse → tdd_enforcer
  ↳ No test found for src/payments/processor.py
  ↳ Suggested: tests/test_processor.py

[context at 81% of window]

PostToolUse → context_monitor
  ↳ Context at 81%. Consider /learn to capture key discoveries before compaction.

[PreToolUse → pre_task_profiler]
  ↳ [devflow:risk] oversight=STRICT probability=0.33 impact=0.80 detectability=0.58

[git push attempted]

PreToolUse → pre_push_gate
  ↳ [devflow:lint] import_boundary: PASS | file_size: PASS | coverage_gate: PASS | compile_check: PASS
  ↳ Running pytest --tb=short -q...
  ↳ ✓ All checks passed. Push allowed.

[session ends after /spec feat-auth]

Stop → task_telemetry
  ↳ Recorded: feat-auth | understand: 8.2k tokens | build: 44.3k tokens | ratio: 0.19

Stop → post_task_judge
  ↳ [devflow:judge] verdict=PASS oversight=STRICT
```

You didn't configure any of that. It runs on every project, every session, automatically.

---

## The hidden variable

After months of watching agents succeed and fail, a pattern became undeniable.

Same model. Same prompts. Completely different results.

When the agent gets a self-contained slice — domain entity, use case, interface, and test all colocated — it gets it right on the first attempt. When it enters a layered codebase where the same concern is scattered across folders, it burns tokens reconstructing context before it can act. And the more tokens it burns before acting, the higher the error rate.

The context window is nominally 200k tokens. Effective limit is ~167k. Research shows model accuracy drops around 32k tokens regardless of window size — instructions buried in the middle get less attention than those at the start and end. This isn't a model limitation to wait out. It's a constraint to design for.

**The architectural implication nobody states clearly:**

It's not enough to manage what you feed the AI session by session. The codebase itself needs to be designed with context boundaries from the first commit. Not layer boundaries. Context boundaries.

```
Self-contained slice → agent sees everything it needs in one pass → first-attempt success
Scattered concern    → agent traverses the graph to reconstruct domain → token burn → errors
```

Your `CLAUDE.md` doesn't document the project. The file structure *is* the context structure. The question you're optimizing for stops being "how do humans navigate this?" and becomes "what does the AI need to see to act here without making mistakes?"

Martin Fowler named this field [context engineering](https://martinfowler.com/articles/exploring-gen-ai/context-engineering-coding-agents.html). Anthropic's 2026 Agentic Coding Trends Report puts it as the primary variable in output quality. The field is converging on a single finding: **the token cost before first action is the most reliable proxy for codebase quality in an agentic world.**

devflow measures exactly that — and now it evaluates its own outputs too.

---

## What's inside

### Automatic hooks

These fire on every relevant Claude Code event. You never invoke them — they just work.

#### Quality gates

| Hook | Event | What it does |
|------|-------|-------------|
| **discovery_scan** | SessionStart | Detects project structure: toolchain (Node.js, Flutter, Go, Rust, Maven, Python), issue tracker (Linear, GitHub Issues, Jira, TODO.md), design system, test framework. Manages learned skill symlinks. Outputs `[devflow:project-profile]` to context |
| **file_checker** | PostToolUse (Write\|Edit\|MultiEdit) | Runs the right formatter + linter for your toolchain. Warns at 400 lines, alerts at 600. Skips test files, config files, and generated code (`.g.dart`, `.freezed.dart`, `.pb.go`, etc.) |
| **tdd_enforcer** | PostToolUse (Write\|Edit\|MultiEdit) | Detects implementation without a corresponding test. Suggests the exact test path using language-aware directory mirroring. Non-blocking — advises, never blocks |
| **context_monitor** | PostToolUse (broad) | Tracks context usage against the compaction threshold (~167k tokens). Warns at 80%, cautions at 90% |
| **pre_push_gate** | PreToolUse (Bash) | Intercepts `git push`, runs 4 deterministic linters + language-specific quality gate (pytest/mypy for Python, flutter analyze, go vet, etc.). Blocks the push if any check fails |

#### Session continuity

| Hook | Event | What it does |
|------|-------|-------------|
| **pre_compact** | PreCompact | Saves active spec, working directory, and session state before auto-compaction |
| **post_compact_restore** | SessionStart (compact) | Reads saved state after compaction and injects it into context. You come back knowing exactly what you were working on |
| **spec_stop_guard** | Stop | Blocks session exit if a spec is in progress. Suggests `/pause` to explicitly pause. 24-hour expiry for stale specs |
| **spec_phase_tracker** | UserPromptSubmit | Detects `/spec` in the user prompt and writes `PENDING` state deterministically — before Claude responds, no LLM instruction-following required |

#### Intelligence layer

| Hook / CLI | Event | What it does |
|------|-------|-------------|
| **pre_task_profiler** | PreToolUse | Scores every task on three axes: `probability` (how likely something breaks), `impact` (blast radius), `detectability` (how easy to catch). Determines oversight level: `vibe → standard → strict → human_review`. Writes `risk-profile.json`, feeds TelemetryStore |
| **post_task_judge** | Stop | Reads the risk profile, builds a structured payload (diff + spec + harness rules + context), calls `claude-haiku` as evaluator. Routes verdict: `PASS → exit 0`, `WARN → advisory`, `FAIL + strict → block`. Never raises — timeout and parse errors degrade to `SKIPPED` |
| **task_telemetry** | Stop | Scans the session JSONL and records token cost per phase into a SQLite store (39-column schema). Infers phase transitions passively — no LLM writes required |
| **anxiety_report** | CLI | Scores sessions by over-investigation: `depth` (reads before first write) × `ratio` (understand/build token ratio). Classifies LOW/MEDIUM/HIGH. Use `python3 hooks/anxiety_report.py` |
| **health_report** | CLI | Scans every skill and hook against usage data. Flags stale, unused, broken, or slow components. Use `python3 hooks/health_report.py --critical` to gate on health |
| **weekly_intelligence** | CLI | 8-rule recommendation engine over the last N sessions. Closes the flywheel: what's working, what's slowing you down, what to build next. Use `python3 hooks/weekly_intelligence.py` |
| **instinct_capture** | Stop | Auto-captures qualitative knowledge from sessions as JSONL per project. Writes to `~/.claude/devflow/instincts/{project}.jsonl`. Review and promote with: `python3.13 hooks/instinct_review.py` |
| **secrets_gate** | PreToolUse (Write\|Edit) | Scans content for credentials, API keys, and tokens before writing to disk. Blocks if secrets detected |
| **cost_tracker** | Stop | Records USD cost per session including cache_read and cache_creation tokens with correct per-token pricing. Feeds TelemetryStore |
| **subagent_tracker** | SubagentStart + SubagentStop | Tracks every AgentTool spawn — records subagent type, duration, and cost to `state/{session}/subagents.jsonl` |
| **cwd_changed** | CWDChanged | Detects toolchain when working directory changes — warns when switching between project stacks |
| **config_reload** | ConfigChange | Notifies which devflow hooks/skills are affected when `settings.json` or `devflow-config.json` changes |

---

### Context telemetry

Every `/spec` cycle passes through two phases:

- **Understand/Plan** (PENDING → IMPLEMENTING) — tokens the agent burns before writing the first line of code
- **Build/Verify** (IMPLEMENTING → COMPLETED) — tokens spent on the actual implementation

`task_telemetry` records both phases at session end by scanning the JSONL Claude Code already writes. Phase transitions are inferred automatically — no LLM writes required, no workflow changes:

| Phase | How it's detected |
|-------|------------------|
| `PENDING` | `/spec` in the user prompt (deterministic, UserPromptSubmit hook) |
| `IMPLEMENTING` | First `Write`/`Edit` to a source file after PENDING |
| `COMPLETED` | Last successful test-runner result after IMPLEMENTING |

All data lands in a SQLite store (`~/.claude/devflow/telemetry/devflow.db`) with 39 columns including risk scores, judge verdicts, anxiety scores, skills loaded, and hook execution data — alongside the legacy `sessions.jsonl` for backwards compatibility.

```bash
python3 ~/.claude/devflow/telemetry/cli.py stats
python3 ~/.claude/devflow/telemetry/cli.py recent --n 10
python3 ~/.claude/devflow/telemetry/cli.py anxiety
```

```
PROJECT: agents
  feat-add-memory-layer       understand:   8.2k | build:  44.3k | ratio: 0.19
  feat-pipeline-retry         understand:  38.4k | build:  51.2k | ratio: 0.75 ⚠

PROJECT: momease
  feat-auth-refresh           understand:  12.1k | build:  39.8k | ratio: 0.30
  feat-notification-center    understand:  41.9k | build:  48.6k | ratio: 0.86 ⚠
```

**Reading the ratio:** `understand tokens / build tokens`. Low ratio → agent entered the task with sufficient context. High ratio (>0.5) → agent spent more reconstructing than building. Consistent high ratios on a project are a signal that the codebase architecture is working against the agent.

---

### Deterministic linters

`pre_push_gate` runs four linters before any language-specific quality checks:

| Linter | Rule | Block level |
|--------|------|-------------|
| `import_boundary` | Dart files under `lib/features/X/` must not import `lib/features/Y/` | FAIL — blocks push |
| `file_size` | Warn at 400 lines, block at 600 lines | WARN at 400, FAIL at 600 |
| `coverage_gate` | Modified `lib/features/X/y.dart` requires `test/**/*y*_test.dart` | FAIL — blocks push |
| `compile_check` | Modified `.py` files must parse with `ast.parse()` | FAIL — blocks push |

```
[devflow:lint] import_boundary: PASS | file_size: PASS | coverage_gate: PASS | compile_check: PASS
```

---

### Context Firewall

For high-risk or isolated tasks, devflow can delegate to a subprocess agent via `pre_task_firewall.py`. The firewall:

- Determines whether a task is safe to run in isolation (`_is_delegatable`: read-only tools only, no writes/destructive ops)
- Spawns `claude -p` with restricted `--allowedTools` (Grep, Glob, Read, Bash for read commands)
- Records the outcome in TelemetryStore with firewall-specific columns
- Blocks the main agent from proceeding if the sub-agent fails

This creates hard context boundaries between investigation and implementation — the sub-agent can read, the main agent acts.

---

### Commands

#### `/spec "description"`

Starts the spec-driven development workflow. Auto-detects feature vs bugfix.

**Feature flow:**
```
Plan → Approve → TDD (RED→GREEN→REFACTOR) → Verify → Review Gate → Done
```

**Bugfix flow:**
```
Behavior Contract (CHANGES / MUST NOT CHANGE / PROOF) → Approve → TDD → Verify → Review Gate → Done
```

#### `/sync`

Scans the project and discovers its conventions: stack, naming patterns, test framework, key dependencies.

#### `/learn`

Captures non-obvious solutions from the current session as reusable skills. Saves to `~/.claude/skills/devflow-learned-<slug>/SKILL.md` and auto-injects in future sessions.

#### `/pause`

Pauses the active spec, unblocking session exit. Changes spec status to `PAUSED` so the stop guard lets you close without losing progress.

---

### Skills

Skills are reference documents Claude invokes automatically when relevant.

| Skill | Auto-invoked when |
|-------|------------------|
| **devflow-spec-driven-dev** | `/spec` command; "implement", "add", "fix" for non-trivial tasks |
| **devflow-behavior-contract** | Bugfix detected; "broken", "regression" |
| **devflow-wizard** | Destructive ops: delete, reset, migration, force push |
| **devflow-agent-orchestration** | Structuring multi-agent work; parallelization decisions |
| **devflow-model-routing** | Deciding which Claude model to use for a task or subagent |

#### devflow-behavior-contract

Formal contract for bugfixes. Three sections required before touching any code:

```markdown
## Behavior Contract: /api/user/:id returns 500 instead of 404

### CHANGES
- [ ] GET /api/user/999 → HTTP 404 with {"error": "not found"}

### MUST NOT CHANGE
- [ ] GET /api/user/1 (existing) → HTTP 200 with user data
- [ ] POST /api/user → continues creating users

### PROOF
- [ ] test_user_not_found_returns_404
- [ ] test_existing_user_returns_200
```

#### devflow-wizard

Four-phase confirmation flow for destructive operations: **Analyze → Present → Detailed Plan → Execute** (two confirmations required).

**Triggers:** `git reset --hard`, `DROP TABLE`, `rm -rf`, schema migrations, force push, overwriting uncommitted changes.

#### devflow-model-routing

| Model | Use when |
|-------|---------|
| **Opus** | Architectural planning, system design, complex trade-offs, debugging without hypothesis |
| **Sonnet** | Implementation, refactoring, code review, debugging with hypothesis — **default for 90% of tasks** |
| **Haiku** | Simple search, formatting, trivial transformations, tasks under 2 minutes |

---

## Supported toolchains

| Toolchain | Detection | Formatter | Linter |
|-----------|-----------|-----------|--------|
| **Node.js** | `package.json` | Prettier | ESLint |
| **Flutter/Dart** | `pubspec.yaml` | `dart format` | `dart analyze` |
| **Go** | `go.mod` | `gofmt -w` | `go vet` |
| **Rust** | `Cargo.toml` | — | `cargo check` |
| **Maven/Java** | `pom.xml` or `mvnw` | — | `mvn compile` |
| **Python** | `pyproject.toml` or `setup.py` | `ruff format` | `ruff check --fix` |

pre_push_gate adds language-specific test runners: `pytest --tb=short -q` + optional `mypy` for Python; `flutter analyze` for Dart; `go test ./...` for Go.

### TDD path suggestions by language

| Language | Implementation | Suggested test |
|----------|---------------|----------------|
| Python | `src/user.py` | `tests/test_user.py` |
| Dart | `lib/widget.dart` | `test/widget_test.dart` |
| TypeScript | `src/api.ts` | `tests/api.test.ts` |
| Go | `internal/handler.go` | `tests/handler_test.go` |
| Kotlin | `src/UserService.kt` | `tests/UserServiceTest.kt` |
| Swift | `app/Auth.swift` | `tests/AuthTests.swift` |
| JavaScript | `src/util.js` | `tests/util.test.js` |

---

## Quickstart

### Prerequisites

- [Claude Code](https://claude.com/claude-code) CLI installed and authenticated
- Python 3.10+
- pytest: `pip3 install pytest`
- Claude API access: `instinct_capture.py` and `post_task_judge.py` call `claude -p` (Haiku) for LLM evaluation. These hooks exit 0 gracefully if the call fails, but without API access they produce no output.
- git: required for `pre_push_gate.py` and `parallel_launch.sh`
- macOS: `desktop_notify.py` uses `osascript` for notifications. On Linux/WSL, the hook silently skips notification and exits 0.

### Install

```bash
git clone https://github.com/viniciuscffreitas/devflow ~/.claude/devflow
chmod +x ~/.claude/devflow/install.sh && ~/.claude/devflow/install.sh
```

The installer handles everything: copies skills and commands, registers hooks in `~/.claude/settings.json`, and merges with your existing configuration without overwriting anything.

### Optional: copy CLAUDE.md

```bash
cp ~/.claude/devflow/CLAUDE.md ~/.claude/CLAUDE.md
```

> If you already have a `~/.claude/CLAUDE.md`, merge the devflow sections manually.

### Verify

```bash
cd ~/.claude/devflow && python3.13 -m pytest hooks/tests/ -q
# 793 tests should pass
```

### Uninstall

```bash
chmod +x ~/.claude/devflow/uninstall.sh && ~/.claude/devflow/uninstall.sh
```

---

## Architecture

```
~/.claude/
├── commands/
│   ├── spec.md
│   ├── sync.md
│   ├── learn.md
│   └── pause.md
├── skills/
│   ├── devflow-spec-driven-dev/SKILL.md
│   ├── devflow-behavior-contract/SKILL.md
│   ├── devflow-wizard/SKILL.md
│   ├── devflow-agent-orchestration/SKILL.md
│   └── devflow-model-routing/SKILL.md
└── devflow/
    ├── hooks/
    │   ├── _util.py                   ← shared helpers, toolchain detection
    │   ├── discovery_scan.py          ← project profiling, symlink management
    │   ├── file_checker.py            ← formatter + linter per toolchain
    │   ├── tdd_enforcer.py            ← test path suggestions
    │   ├── context_monitor.py         ← context window warnings
    │   ├── pre_compact.py             ← save state before compaction
    │   ├── post_compact_restore.py    ← restore state after compaction
    │   ├── spec_stop_guard.py         ← block exit mid-spec
    │   ├── spec_phase_tracker.py      ← deterministic PENDING detection
    │   ├── pre_push_gate.py           ← 4 linters + quality gate
    │   ├── pre_task_profiler.py       ← risk scoring before each task
    │   ├── pre_task_firewall.py       ← subprocess isolation for read-only tasks
    │   ├── task_telemetry.py          ← token cost per phase → SQLite
    │   ├── post_task_judge.py         ← LLM evaluation of task output
    │   ├── anxiety_report.py          ← CLI: over-investigation detector
    │   ├── health_report.py           ← CLI: harness health monitor
    │   ├── weekly_intelligence.py     ← CLI: weekly recommendations
    │   ├── instinct_capture.py        ← auto-captures qualitative knowledge as skills
    │   ├── instinct_review.py         ← CLI: review and promote captured instincts
    │   ├── secrets_gate.py            ← blocks credentials before disk write
    │   ├── cost_tracker.py            ← USD cost per session → TelemetryStore
    │   ├── subagent_tracker.py        ← SubagentStart/Stop — cost + duration per spawned agent
    │   ├── cwd_changed.py             ← CWDChanged — toolchain detection on directory switch
    │   ├── config_reload.py           ← ConfigChange — notify on settings.json changes
    │   ├── telemetry_report.py        ← CLI: token cost per phase per project
    │   └── tests/                     ← 793 tests
    ├── telemetry/
    │   ├── store.py                   ← TelemetryStore: SQLite, 39 columns
    │   ├── migrate_sessions.py        ← one-time migration from sessions.jsonl
    │   ├── cli.py                     ← stats / recent / anxiety commands
    │   └── devflow.db                 ← persistent telemetry (gitignored)
    ├── analysis/
    │   ├── context_anxiety.py         ← AnxietyScore, AnxietyReport, detector
    │   ├── harness_health.py          ← SkillHealth, HookHealth, HarnessHealthChecker
    │   └── weekly_report.py           ← WeeklyIntelligenceReport, 8-rule engine
    ├── risk/
    │   └── profiler.py                ← TaskRiskProfiler: probability × impact × detectability
    ├── judge/
    │   ├── evaluator.py               ← HarnessJudge: claude-haiku subprocess evaluation
    │   ├── router.py                  ← JudgeRouter: oversight-level blocking
    │   └── calibration/               ← 5 ground truth examples
    ├── linters/
    │   └── engine.py                  ← LinterEngine: import_boundary, file_size, coverage_gate, compile_check
    ├── agents/
    │   ├── firewall.py                ← ContextFirewall: subprocess isolation
    │   └── task_registry.py           ← file-locked TaskRegistry, WAL SQLite for parallel sessions
    ├── skills/                        ← devflow skill files
    ├── commands/                      ← devflow command files
    ├── docs/
    │   ├── audit-20260331.md          ← full build history (prompts 0-11)
    │   └── plans/                     ← implementation plans
    ├── install.sh
    ├── uninstall.sh
    ├── pyproject.toml
    ├── AGENTS.md                      ← contract for any agent operating in this repo
    └── state/
        └── <session-id>/
            ├── active-spec.json
            ├── risk-profile.json
            └── pre-compact.json
```

### Hook communication protocol

```python
# Inject context (non-blocking advisory)
{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "..."}}

# Block an action
{"decision": "block", "reason": "..."}
```

Hooks receive input via stdin. Errors go to stderr. Hooks never crash — fail-open for quality hooks, fail-safe for safety hooks.

---

## Customization

### Adjusting thresholds

```json
{
  "file_length_warn": 400,
  "file_length_critical": 600,
  "learned_skills_auto_inject": true,
  "issue_tracker_override": null
}
```

Two levels: `~/.claude/devflow/devflow-config.json` (global) or `.devflow-config.json` in the project root (overrides global).

### Disabling a specific hook

Remove or comment out the hook entry in `~/.claude/settings.json`. Every hook is independent.

---

## Weekly workflow

Every Friday, run:

```bash
python3.13 hooks/weekly_intelligence.py   # what happened this week
python3.13 hooks/instinct_review.py       # review captured knowledge
python3.13 hooks/health_report.py         # is the harness healthy?
```

---

## Parallel sessions

Run multiple Claude Code sessions simultaneously on the same codebase:

```bash
# Launch 3 sessions in parallel, each on a different issue
~/.claude/devflow/scripts/parallel_launch.sh ISSUE-123 ISSUE-124 ISSUE-125

# Dry run — preview without creating worktrees
~/.claude/devflow/scripts/parallel_launch.sh --dry-run ISSUE-123 ISSUE-124

# Clean up all parallel worktrees when done
~/.claude/devflow/scripts/parallel_launch.sh --cleanup
```

Each session gets:
- Its own git worktree on a dedicated branch
- Unique session ID (no state collisions)
- File-locked task registry (no two sessions grab the same issue)
- WAL-mode SQLite (concurrent writes without "database is locked")

---

## Running tests

```bash
cd ~/.claude/devflow

# All 793 tests
python3.13 -m pytest hooks/tests/ -q

# Specific module
python3.13 -m pytest hooks/tests/test_risk_profiler.py -v

# With coverage
python3.13 -m pytest hooks/tests/ --cov=hooks --cov-report=term-missing
```

---

## The 5 levels of Claude Code maturity

Where are you, and where do you want to be?

| Level | State | Description |
|-------|-------|-------------|
| L1 | **Raw** | Claude Code with no config, no workflow. Brilliant when you're watching. Unreliable when you're not. |
| L2 | **Configured** | Custom `CLAUDE.md`, some commands. Claude knows your preferences — when you remind it. |
| L3 | **Structured** | Spec-driven development, TDD discipline. You enforce the process manually in every session. |
| **L4** | **Automated** | **devflow: hooks enforce quality automatically. Process runs whether you remember or not. The harness evaluates itself.** |
| L5 | **Autonomous** | devflow + paperweight: background agents with guardrails. Your backlog resolves itself. |

devflow is the step from L3 to **L4** — where Claude Code stops needing you to hold its standards, starts holding them itself, and starts telling you when *it* needs improvement.

---

## Compatibility

| Plugin | Conflict? | Notes |
|--------|-----------|-------|
| **superpowers** | Partial overlap | superpowers handles brainstorming, worktrees, finishing branches. devflow adds hooks, behavior contracts, wizard, model routing. **Recommended: keep both** |
| **pr-review-toolkit** | None | Complementary — devflow doesn't do PR review |
| **frontend-design** | None | Complementary — devflow doesn't do UI |
| **paperweight** | None | Complementary — see pairing section below |
| **linear** | None | Complementary — devflow doesn't do project management |

---

## Pairing with paperweight

devflow handles the foreground. [paperweight](https://github.com/viniciuscffreitas/paperweight) handles the background.

```
Interactive session (you + Claude Code)
  └── devflow: TDD enforcement, spec-driven dev, context preservation,
               risk scoring, LLM evaluation, quality gates, context telemetry

Background session (no one watching)
  └── paperweight: Slack trigger, understand → plan → build → verify → review → merge
```

devflow is the guardrails. paperweight is the engine. Together they form a complete autonomous coding stack — L4 interactive, L5 autonomous.

The telemetry devflow collects feeds the long-term question: do the projects paperweight operates on have the context architecture that lets it act on the first attempt? The ratio is the signal.

---

## Origins

devflow synthesizes patterns from two sources:

### From [agentic-ai-systems](https://github.com/ThibautMelen/agentic-ai-systems) (Anthropic patterns)
- Agent orchestration patterns — Baseline, Prompt Chaining, Routing, Parallelization, Orchestrator-Workers, Evaluator-Optimizer
- Subagent flat hierarchy rule — subagents never spawn subagents
- Model routing — Opus for planning, Sonnet for implementation, Haiku for trivial tasks

### From [pilot-shell](https://github.com/maxritter/pilot-shell) (professional dev environment)
- Spec-driven development — structured Plan→TDD→Verify flow
- Behavior contracts — CHANGES/MUST NOT CHANGE/PROOF for bugfixes
- Automatic quality hooks, TDD enforcement, context preservation
- Session exit protection, convention discovery, skill extraction

### What devflow adds beyond both
- Language-agnostic toolchain detection (Node.js, Flutter, Go, Rust, Maven, Python) without configuration
- Smart test path suggestion with language-aware directory mirroring
- Generated file detection — skips codegen artifacts across ecosystems
- Fail-safe with expiry — stop guard uses 24-hour expiry instead of blocking indefinitely
- **Context telemetry** — fully passive measurement of token cost per spec phase, with zero-friction phase inference from JSONL signals
- **Risk profiler** — probability × impact × detectability scoring per task, determining oversight level before any code is written
- **LLM-as-judge** — haiku evaluates every task output against the spec and harness rules; routing logic blocks on FAIL+strict or FAIL+human_review
- **Context anxiety detector** — identifies sessions with pathological read-before-write patterns, surfaces the root cause
- **Harness health monitor** — the harness observes itself; stale skills and slow hooks are flagged before they become invisible debt
- **Weekly intelligence** — 8-rule recommendation engine closes the flywheel: what the data says to build next
- **Context firewall** — subprocess isolation for read-only investigation tasks, creating hard context boundaries

---

## License

MIT

---

<div align="center">

*The guardrails Claude Code never shipped with.*

**[⭐ Star if you're building with Claude Code](https://github.com/viniciuscffreitas/devflow)**

</div>
