<div align="center">

# devflow

**Claude Code is brilliant. It has no guardrails.**

*Automatic quality hooks, TDD enforcement, spec-driven workflows, and context telemetry — for every project, without configuration.*

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![Tests](https://img.shields.io/badge/tests-316-brightgreen.svg)](#running-tests)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/powered%20by-Claude%20Code-orange.svg)](https://claude.ai/code)

</div>

---

## The thing nobody warns you about

You give Claude Code a task. It reads the files, understands the context, and writes genuinely good code.

Then it submits the implementation without a single test. No one stopped it.

You ask it to fix a bug. It fixes the bug and breaks three other things. No one warned it.

You're 90 minutes into a complex refactor. The context window fills up and auto-compacts. Claude comes back with no memory of what it was doing.

**Claude Code doesn't have standards. It has yours — but only when you're watching.**

---

## The blind spots

Five things Claude Code can't do on its own:

- **No automatic quality checks** — you have to manually ask for linting, formatting, and file length awareness on every task
- **No TDD enforcement** — nothing prevents writing implementation before tests; it will do it every time if you don't stop it
- **Context evaporates on compaction** — when the window fills and auto-compacts, you lose track of what you were doing and so does Claude
- **No protection against accidental exit** — you can close a session mid-spec with no warning and no way to resume cleanly
- **No repeatable workflow** — every feature starts from scratch; every bugfix is handled differently; there's no process

These aren't complaints. They're the gaps that make working with Claude Code feel inconsistent — brilliant when you're present, fragile when you're not.

---

## What it looks like with devflow

```
[editing src/payments/processor.py]

PostToolUse → file_checker
  ↳ dart analyze: no issues
  ↳ ⚠ file length: 423 lines (warn threshold: 400)

PostToolUse → tdd_enforcer
  ↳ No test found for src/payments/processor.py
  ↳ Suggested: test/payments/processor_test.dart

[context at 81% of window]

PostToolUse → context_monitor
  ↳ Context at 81%. Consider /learn to capture key discoveries before compaction.

[git push attempted]

PreToolUse → pre_push_gate
  ↳ Running dart format --output=none --set-exit-if-changed...
  ↳ Running flutter analyze...
  ↳ ✓ All checks passed. Push allowed.

[session ends after /spec feat-auth]

Stop → task_telemetry
  ↳ Recorded: feat-auth | understand: 8.2k tokens | build: 44.3k tokens | ratio: 0.19
```

You didn't configure any of that. It runs on every project, every session, automatically.

---

## The hidden variable

After two months of watching agents succeed and fail, a pattern became undeniable.

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

devflow's `task_telemetry` hook measures exactly that.

---

## What's inside

### Automatic hooks

These fire on every relevant Claude Code event. You never invoke them — they just work.

| Hook | Event | What it does |
|------|-------|-------------|
| **discovery_scan** | SessionStart | Detects project structure: toolchain (Node.js, Flutter, Go, Rust, Maven), issue tracker (Linear, GitHub Issues, Jira, TODO.md), design system, test framework. Manages learned skill symlinks. Outputs `[devflow:project-profile]` to context |
| **file_checker** | PostToolUse (Write\|Edit\|MultiEdit) | Runs the right formatter + linter for your toolchain. Warns at 400 lines, alerts at 600. Skips test files, config files, and generated code (`.g.dart`, `.freezed.dart`, `.pb.go`, etc.) |
| **tdd_enforcer** | PostToolUse (Write\|Edit\|MultiEdit) | Detects implementation without a corresponding test. Suggests the exact test path using language-aware directory mirroring. Non-blocking — advises, never blocks |
| **context_monitor** | PostToolUse (broad) | Tracks context usage against the compaction threshold (~167k tokens). Warns at 80%, cautions at 90% |
| **pre_compact** | PreCompact | Saves active spec, working directory, and session state before auto-compaction |
| **post_compact_restore** | SessionStart (compact) | Reads saved state after compaction and injects it into context. You come back knowing exactly what you were working on |
| **spec_stop_guard** | Stop | Blocks session exit if a spec is in progress. Suggests `/pause` to explicitly pause. 24-hour expiry for stale specs — corrupt state older than 24h is treated as abandoned, not a permanent block |
| **pre_push_gate** | PreToolUse (Bash) | Intercepts `git push` and runs quality checks for your toolchain. Blocks the push if any check fails |
| **spec_phase_tracker** | UserPromptSubmit | Detects `/spec` in the user prompt and writes `PENDING` state deterministically — before Claude responds, no LLM instruction-following required |
| **task_telemetry** | Stop | Scans the session JSONL and records token cost per phase. Infers `IMPLEMENTING` from the first source-file write after `PENDING`; infers `COMPLETED` from the last successful test-runner result. No LLM writes required — purely passive. Output: `~/.claude/devflow/telemetry/sessions.jsonl` |

---

### Context telemetry

Every `/spec` cycle passes through two phases:

- **Understand/Plan** (PENDING → IMPLEMENTING) — tokens the agent burns before writing the first line of code
- **Build/Verify** (IMPLEMENTING → COMPLETED) — tokens spent on the actual implementation

`task_telemetry` records both phases at session end by scanning the JSONL Claude Code already writes. Phase transitions are inferred automatically — no LLM writes required, no workflow changes:

| Phase | How it's detected |
|-------|------------------|
| `PENDING` | `/spec` in the user prompt (deterministic, UserPromptSubmit hook) |
| `IMPLEMENTING` | First `Write`/`Edit` to a source file (`.py`, `.dart`, `.java`, `.ts`, ...) after PENDING |
| `COMPLETED` | Last successful test-runner result (`pytest`, `flutter test`, `mvn test`, ...) after IMPLEMENTING |

Explicit `active-spec.json` writes (if present) take priority over inferred phases.

```bash
python3 ~/.claude/devflow/hooks/telemetry_report.py
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

**Filtering:**
```bash
python3 ~/.claude/devflow/hooks/telemetry_report.py --project agents
python3 ~/.claude/devflow/hooks/telemetry_report.py --last 10
```

Two weeks of data across projects with different architectures gives you the empirical ground truth for the Context-Native Architecture thesis — not anecdote, not intuition, actual numbers.

---

### Commands

#### `/spec "description"`

Starts the spec-driven development workflow. Auto-detects feature vs bugfix.

**Feature flow:**
```
Plan → Approve → TDD (RED→GREEN→REFACTOR) → Verify → Done
```

**Bugfix flow:**
```
Behavior Contract (CHANGES / MUST NOT CHANGE / PROOF) → Approve → TDD → Verify → Done
```

**Examples:**
```
/spec "add pagination to user list endpoint"
/spec "fix: profile photo not loading on iOS"
/spec "refactor auth middleware to support OAuth"
```

The `fix:` prefix triggers bugfix mode with a formal behavior contract. Ambiguous cases are clarified via question.

#### `/sync`

Scans the project and discovers its conventions: stack, naming patterns, test framework, key dependencies. Claude uses the discovered conventions for the rest of the session.

**When to use:** first session on an unfamiliar project, after structural changes, or when Claude is making inconsistent decisions.

#### `/learn`

Captures non-obvious solutions from the current session as reusable skills. Saves to `~/.claude/skills/devflow-learned-<slug>/SKILL.md` and auto-injects in future sessions when the same project type is detected.

**Good candidates:** recurring bug solutions, undocumented project patterns, non-obvious tool workarounds.

#### `/pause`

Pauses the active spec, unblocking session exit. Changes spec status to `PAUSED` so the stop guard lets you close without losing progress. Resume with `/spec` referencing the existing plan.

---

### Skills

Skills are reference documents Claude invokes automatically when relevant. You don't call them directly.

#### devflow-spec-driven-dev

The core workflow orchestrator. Defines the complete flow for features and bugfixes with explicit verification gates.

**Key rules:**
- Never declare done without full verification (lint + build + tests)
- Never implement before having tests (except configs/docs/infra)
- Atomic commits — one behavior per commit
- For destructive operations: invoke devflow-wizard

#### devflow-behavior-contract

Formal contract for bugfixes. Three sections that must be defined before touching any code:

- **CHANGES** — what WILL change (specific, testable)
- **MUST NOT CHANGE** — what MUST NOT change (all callers and dependents)
- **PROOF** — tests that prove both sections hold

The contract requires user approval before implementation. If any MUST NOT CHANGE item breaks: stop, revise, re-present.

**Example:**
```markdown
## Behavior Contract: /api/user/:id returns 500 instead of 404

### CHANGES
- [ ] GET /api/user/999 → HTTP 404 with {"error": "not found"}

### MUST NOT CHANGE
- [ ] GET /api/user/1 (existing) → HTTP 200 with user data
- [ ] POST /api/user → continues creating users
- [ ] JWT auth → continues being validated

### PROOF
- [ ] test_user_not_found_returns_404
- [ ] test_existing_user_returns_200
```

#### devflow-wizard

Four-phase confirmation flow for destructive operations:

1. **ANALYZE** — read full scope, list what's affected and what's irreversible
2. **PRESENT** — show the user what will happen and offer less destructive alternatives
3. **DETAILED PLAN** — list each step with rollback points, confirm again
4. **EXECUTE** — only after second confirmation

**Triggers:** `git reset --hard`, `DROP TABLE`, `rm -rf`, schema migrations, force push, overwriting uncommitted changes.

#### devflow-agent-orchestration

Reference guide for structuring multi-agent work. Six patterns in increasing complexity:

| Pattern | When to use |
|---------|------------|
| **Baseline** | Single-step task |
| **Prompt Chaining** | Sequential steps where output feeds the next |
| **Routing** | Input needs classification before different processing |
| **Parallelization** | Independent subtasks with no shared state |
| **Orchestrator-Workers** | Complex task requiring specialist agents with different contexts |
| **Evaluator-Optimizer** | Need to iterate until minimum quality criteria is met |

**Critical rule:** Subagents NEVER spawn other subagents. All delegation flows exclusively through the Main Agent.

#### devflow-model-routing

Guide for selecting the right Claude model per task type:

| Model | Use when |
|-------|---------|
| **Opus** | Architectural planning, system design, complex trade-offs, debugging without hypothesis |
| **Sonnet** | Implementation, refactoring, code review, debugging with hypothesis — **default for 90% of tasks** |
| **Haiku** | Simple search, formatting, trivial transformations, tasks under 2 minutes |

**Principle:** Start with Sonnet. Scale to Opus only if stuck. Opus is ~5x more expensive — use with intention.

---

## Supported toolchains

file_checker auto-detects your project and runs the right tools:

| Toolchain | Detection | Formatter | Linter |
|-----------|-----------|-----------|--------|
| **Node.js** | `package.json` | Prettier (global or local `node_modules/.bin/`) | ESLint |
| **Flutter/Dart** | `pubspec.yaml` | `dart format` | `dart analyze` |
| **Go** | `go.mod` | `gofmt -w` | `go vet` |
| **Rust** | `Cargo.toml` | — | `cargo check` |
| **Maven/Java** | `pom.xml` or `mvnw` | — | `mvn compile` |

If a tool isn't installed, the hook skips it silently. No errors, no noise.

### TDD path suggestions by language

tdd_enforcer knows the naming convention for each language:

| Language | Implementation | Suggested test |
|----------|---------------|----------------|
| Python | `src/user.py` | `tests/test_user.py` |
| Dart | `lib/widget.dart` | `test/widget_test.dart` |
| TypeScript | `src/api.ts` | `tests/api.test.ts` |
| Go | `internal/handler.go` | `tests/handler_test.go` |
| Kotlin | `src/UserService.kt` | `tests/UserServiceTest.kt` |
| Swift | `app/Auth.swift` | `tests/AuthTests.swift` |
| JavaScript | `src/util.js` | `tests/util.test.js` |

Directory mirroring: `src/features/auth/login.py` → `tests/features/auth/test_login.py`

---

## Quickstart

### Prerequisites

- [Claude Code](https://claude.com/claude-code) CLI installed and authenticated
- Python 3.10+
- pytest: `pip3 install pytest`

### Install

```bash
git clone https://github.com/viniciuscffreitas/dotfiles ~/.claude/devflow
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
cd ~/.claude/devflow && python3 -m pytest hooks/tests/ -v
# 197 tests should pass
```

### Uninstall

```bash
chmod +x ~/.claude/devflow/uninstall.sh && ~/.claude/devflow/uninstall.sh
```

Removes skills, commands, and hook registrations from `~/.claude/settings.json` without affecting other plugins.

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
├── devflow/
│   ├── hooks/
│   │   ├── _util.py
│   │   ├── file_checker.py
│   │   ├── tdd_enforcer.py
│   │   ├── context_monitor.py
│   │   ├── pre_compact.py
│   │   ├── post_compact_restore.py
│   │   ├── spec_stop_guard.py
│   │   ├── pre_push_gate.py
│   │   ├── task_telemetry.py       ← records tokens per spec phase
│   │   ├── telemetry_report.py     ← CLI: tokens per phase per project
│   │   └── tests/
│   │       ├── test_util.py               # 22 tests
│   │       ├── test_file_checker.py       # 10 tests
│   │       ├── test_tdd_enforcer.py       # 14 tests
│   │       ├── test_spec_stop_guard.py    #  9 tests
│   │       ├── test_context_monitor.py    #  7 tests
│   │       ├── test_compact_hooks.py      #  9 tests
│   │       ├── test_pre_push_gate.py      # 11 tests
│   │       ├── test_spec_phase_tracker.py # 15 tests
│   │       ├── test_task_telemetry.py     # 67 tests
│   │       └── test_telemetry_report.py   # 16 tests  (197 total)
│   ├── telemetry/
│   │   └── sessions.jsonl          ← append-only telemetry log
│   ├── skills/
│   ├── commands/
│   ├── install.sh
│   ├── uninstall.sh
│   └── state/
│       └── <session-id>/
│           ├── active-spec.json
│           └── pre-compact.json
└── settings.json
```

### Hook communication protocol

Hooks communicate with Claude Code via JSON on stdout:

```python
# Inject context (non-blocking advisory)
{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "..."}}

# Block an action
{"decision": "block", "reason": "..."}
```

Hooks receive input via stdin (JSON with tool_input, context_tokens_used, etc.). Errors go to stderr — no interference with the stdout protocol.

### Error handling philosophy

- **Hooks must never crash** — a crashing hook disrupts Claude Code's workflow
- **Silent exit when nothing to report** — no noise, no unnecessary output
- **Log errors to stderr** — diagnostic trail without breaking the protocol
- **Fail-safe for safety hooks** — spec_stop_guard has a 24-hour expiry; corrupt state older than 24h is treated as abandoned
- **Fail-open for quality hooks** — file_checker and tdd_enforcer skip gracefully on errors
- **Silent on irrelevant sessions** — task_telemetry writes nothing if no `/spec` phases are detected

---

## Customization

### Adjusting thresholds

Two levels of config:

- **Global:** `~/.claude/devflow/devflow-config.json`
- **Per-project:** `.devflow-config.json` in the project root (overrides global)

```json
{
  "file_length_warn": 400,
  "file_length_critical": 600,
  "learned_skills_auto_inject": true,
  "issue_tracker_override": null
}
```

### Adding a new toolchain

1. Add to `ToolchainKind` enum in `_util.py`
2. Add fingerprint to `_TOOLCHAIN_FINGERPRINTS` list
3. Add entry to `TOOLCHAIN_FINGERPRINT_MAP`
4. Create `_check_<toolchain>` function in `file_checker.py`
5. Register in `_CHECKERS` dict

### Disabling a specific hook

Remove or comment out the hook entry in `~/.claude/settings.json`. Every hook is independent.

---

## Running tests

```bash
cd ~/.claude/devflow

# All 197 tests
python3 -m pytest hooks/tests/ -v

# Specific file
python3 -m pytest hooks/tests/test_tdd_enforcer.py -v

# With coverage
python3 -m pytest hooks/tests/ --cov=hooks --cov-report=term-missing
```

---

## The 5 levels of Claude Code maturity

Where are you, and where do you want to be?

| Level | State | Description |
|-------|-------|-------------|
| L1 | **Raw** | Claude Code with no config, no workflow. Brilliant when you're watching. Unreliable when you're not. |
| L2 | **Configured** | Custom `CLAUDE.md`, some commands. Claude knows your preferences — when you remind it. |
| L3 | **Structured** | Spec-driven development, TDD discipline. You enforce the process manually in every session. |
| **L4** | **Automated** | **devflow: hooks enforce quality automatically. Process runs whether you remember or not.** |
| L5 | **Autonomous** | devflow + paperweight: background agents with guardrails. Your backlog resolves itself. |

devflow is the step from L3 to **L4** — where Claude Code stops needing you to hold its standards and starts holding them itself.

---

## Compatibility

devflow coexists cleanly with other Claude Code plugins:

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
  └── devflow: TDD enforcement, spec-driven dev, context preservation, quality gates, context telemetry

Background session (no one watching)
  └── paperweight: Slack trigger, understand → plan → build → verify → review → merge
```

devflow is the guardrails. paperweight is the engine. Together they form a complete autonomous coding stack — L4 interactive, L5 autonomous.

The telemetry data devflow collects feeds the long-term question: do the projects paperweight operates on have the context architecture that lets it act on the first attempt? The ratio is the signal.

Install paperweight:

```bash
git clone https://github.com/viniciuscffreitas/paperweight
cd paperweight && uv run agents
```

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
- Language-agnostic toolchain detection across Node.js, Flutter, Go, Rust, Maven without configuration
- Smart test path suggestion with language-aware directory mirroring
- Generated file detection — skips codegen artifacts across ecosystems
- Fail-safe with expiry — stop guard uses 24-hour expiry instead of blocking indefinitely
- Stderr error logging — diagnostic trail without breaking the hook protocol
- **Context telemetry** — fully passive measurement of token cost per spec phase, with zero-friction phase inference from JSONL signals (no LLM writes required)
- **Deterministic spec tracking** — `PENDING` state written before Claude even responds, via UserPromptSubmit hook; `IMPLEMENTING` and `COMPLETED` inferred from coding actions

---

## License

MIT

---

<div align="center">

*The guardrails Claude Code never shipped with.*

**[⭐ Star if you're building with Claude Code](https://github.com/viniciuscffreitas/devflow)**

</div>
