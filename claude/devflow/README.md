# devflow

**Automatic development guardrails and spec-driven workflows for Claude Code.**

devflow is a language-agnostic plugin that adds automatic quality hooks, TDD enforcement, context preservation, and structured development workflows to every Claude Code session. It works globally across all your projects without per-project configuration.

Extracted and abstracted from [agentic-ai-systems](https://github.com/ThibautMelen/agentic-ai-systems) (Anthropic's agentic patterns) and [pilot-shell](https://github.com/maxritter/pilot-shell) (professional Claude Code environment).

## Why devflow exists

Claude Code is powerful but has blind spots out of the box:

- **No automatic quality checks** — you have to manually ask for linting, formatting, and file length awareness
- **No TDD enforcement** — nothing stops you from writing implementation without tests
- **Context evaporates on compaction** — when the context window fills up and auto-compacts, you lose track of what you were doing
- **No protection against accidental session exit** — you can close a session mid-task with no warning
- **No structured workflow for features vs bugfixes** — every task starts from scratch with no repeatable process

devflow solves all of these with zero friction — hooks run automatically, skills activate when relevant, and commands are available when you need them.

---

## What's inside

### Automatic hooks (run without any action from you)

These fire on every relevant Claude Code event. You never invoke them — they just work.

| Hook | Event | Matcher | What it does |
|------|-------|---------|-------------|
| **discovery_scan** | SessionStart | `*` | Detects project structure on session start: toolchain (Node.js, Flutter, Go, Rust, Maven), issue tracker (Linear, GitHub Issues, Jira, TODO.md), design system, test framework. Manages learned skill symlinks. Outputs `[devflow:project-profile]` to context |
| **file_checker** | PostToolUse | `Write\|Edit\|MultiEdit` | Detects your project's toolchain (Node.js, Flutter, Go, Rust, Maven) and runs the appropriate formatter + linter. Warns when files exceed 400 lines, alerts at 600. Skips test files, config files, and generated code (`.g.dart`, `.freezed.dart`, `.pb.go`, etc.) |
| **tdd_enforcer** | PostToolUse | `Write\|Edit\|MultiEdit` | Detects when you write implementation code without a corresponding test. Suggests the exact test file path using language-aware directory mirroring (`src/user.py` → `tests/test_user.py`, `lib/widget.dart` → `test/widget_test.dart`). Non-blocking — advises, never blocks |
| **context_monitor** | PostToolUse | `Read\|Write\|Edit\|MultiEdit\|Bash\|Glob\|Grep` | Tracks context window usage against the compaction threshold (~167k tokens). Warns at 80% ("consider using /learn"), cautions at 90% ("finish current task, compaction imminent") |
| **pre_compact** | PreCompact | `*` | Saves session state before auto-compaction: active spec, working directory, session ID. Writes to `~/.claude/devflow/state/<session>/pre-compact.json` |
| **post_compact_restore** | SessionStart | `compact` | Reads saved state after compaction and injects it into context. You come back knowing exactly what you were working on, what spec was active, and where you were |
| **spec_stop_guard** | Stop | `*` | Blocks session exit if a spec is actively in progress (status: IMPLEMENTING, PENDING, or in_progress). Suggests `/pause` to explicitly pause. Includes 24-hour expiry for stale specs. Corrupt files older than 24h are treated as abandoned (fail-safe). |

### Commands (you type these in the prompt)

#### `/spec "description"`

Starts the spec-driven development workflow. Auto-detects whether you're building a feature or fixing a bug.

**Feature flow:**
```
Plan → Approve → TDD (RED→GREEN→REFACTOR) → Verify → Done
```

**Bugfix flow:**
```
Behavior Contract (CHANGES/MUST NOT CHANGE/PROOF) → Approve → TDD → Verify → Done
```

**Examples:**
```
/spec "add pagination to user list endpoint"
/spec "fix: profile photo not loading on iOS"
/spec "refactor auth middleware to support OAuth"
```

The `fix:` prefix triggers bugfix mode with a formal behavior contract. Without it, feature mode is used. Ambiguous cases are clarified via question.

#### `/sync`

Scans the current project and discovers its conventions:

1. **Stack detection** — languages, frameworks, package managers
2. **Convention discovery** — naming patterns, directory structure, import style
3. **Test discovery** — test framework, existing test patterns, coverage
4. **Dependency audit** — key dependencies and versions
5. **Context update** — Claude uses discovered conventions for the rest of the session

**When to use:**
- First session in an unfamiliar project
- After significant structural changes
- When Claude is making decisions inconsistent with the project

#### `/learn`

Captures non-obvious solutions from the current session as reusable skills:

1. Identifies solutions that aren't well-documented or obvious
2. Extracts the reusable pattern (the "how" independent of the "what")
3. Proposes title, trigger, and content
4. Saves to `~/.claude/skills/devflow-learned-<slug>/SKILL.md`

**Good candidates:** recurring bug solutions, undocumented project patterns, non-obvious tool workarounds.

**Bad candidates:** obvious things, context-specific solutions with no reuse, subjective preferences.

#### `/pause`

Pauses the active spec, unblocking session exit:

1. Reads `~/.claude/devflow/state/<session>/active-spec.json`
2. Changes status from `IMPLEMENTING`/`PENDING` to `PAUSED`
3. The stop guard no longer blocks exit

**When to use:**
- Need to exit but stop guard is blocking
- Want to pause a spec to work on something else
- Need to close terminal urgently

**Resuming:** Next session, post_compact_restore shows there was a paused spec. Resume with `/spec` referencing the existing plan.

### Skills (Claude invokes these automatically when relevant)

Skills are reference documents that guide Claude's behavior. You don't call them directly — they activate based on context.

#### devflow-spec-driven-dev

The core workflow orchestrator. Defines the complete flow for features and bugfixes with explicit verification gates.

**Key rules:**
- Never declare done without full verification (lint + build + tests)
- Never implement before having tests (except configs/docs/infra)
- Atomic commits — one behavior per commit
- For destructive operations: invoke devflow-wizard

#### devflow-behavior-contract

Formal contract for bugfixes with three sections:

- **CHANGES** — what WILL change (specific, testable behaviors)
- **MUST NOT CHANGE** — what MUST NOT change (all callers/dependents of modified component)
- **PROOF** — tests that prove both CHANGES and MUST NOT CHANGE

The contract must be approved by the user before implementation begins. If any MUST NOT CHANGE item breaks during implementation: stop, revise contract, re-present.

**Example:**
```markdown
## Behavior Contract: /api/user/:id returns 500 instead of 404

### CHANGES
- [ ] GET /api/user/999 → HTTP 404 with {"error": "not found"}

### MUST NOT CHANGE
- [ ] GET /api/user/1 (existing) → HTTP 200 with data
- [ ] POST /api/user → continues creating users
- [ ] JWT auth → continues being validated

### PROOF
- [ ] test_user_not_found_returns_404
- [ ] test_existing_user_returns_200
```

#### devflow-wizard

Four-phase flow for destructive operations with double confirmation:

1. **ANALYZE** — read and understand full scope, list what's affected and irreversible
2. **PRESENT** — show user what will be done, what can't be undone, and less destructive alternatives
3. **DETAILED PLAN** — list each step with rollback points, confirm again
4. **EXECUTE** — only after second confirmation, report each step, stop on anything unexpected

**Triggers:** `git reset --hard`, `DROP TABLE`, `rm -rf`, schema migrations, force push, overwriting uncommitted changes, disabling features with active users.

#### devflow-agent-orchestration

Reference guide for structuring multi-agent work. Six patterns in increasing complexity:

| Pattern | When to use |
|---------|------------|
| **Baseline** | Simple single-step task |
| **Prompt Chaining** | Sequential steps where output feeds next step |
| **Routing** | Input needs classification before different processing |
| **Parallelization** | Independent subtasks with no shared state |
| **Orchestrator-Workers** | Complex task requiring specialist agents with different contexts |
| **Evaluator-Optimizer** | Need to iterate until minimum quality criteria is met |

**Critical architectural rule:** Subagents NEVER spawn other subagents. All delegation flows exclusively through the Main Agent. This prevents infinite loops and opaque hierarchies.

#### devflow-model-routing

Guide for selecting the right Claude model:

| Model | Use when |
|-------|---------|
| **Opus** | Architectural planning, system design, complex trade-off analysis, debugging without hypothesis |
| **Sonnet** | Implementation, refactoring, code review, debugging with hypothesis — **default for 90% of tasks** |
| **Haiku** | Simple search, formatting, trivial transformations, <2min tasks |

**Principle:** Start with Sonnet. Scale to Opus only if stuck.

---

## Supported toolchains

file_checker auto-detects your project and runs the right tools:

| Toolchain | Detection | Formatter | Linter |
|-----------|-----------|-----------|--------|
| **Node.js** | `package.json` | Prettier (global or local `node_modules/.bin/`) | ESLint (global or local) |
| **Flutter/Dart** | `pubspec.yaml` | — | `dart analyze` |
| **Go** | `go.mod` | `gofmt -w` | `go vet` |
| **Rust** | `Cargo.toml` | — | `cargo check` |
| **Maven/Java** | `pom.xml` or `mvnw` | — | `mvn compile` |

If a tool isn't installed, the hook silently skips it. No errors, no noise.

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

### Skipped files

These are never checked by file_checker or flagged by tdd_enforcer:

- **Test files:** anything matching `test_`, `_test.`, `.test.`, `_spec.`, `.spec.`, `conftest.`, `fixture`, `mock`
- **Config files:** `.json`, `.yaml`, `.yml`, `.toml`, `.ini`, `.cfg`, `.md`, `.txt`, `.env`, `.lock`, `.gitignore`
- **Named files:** `Dockerfile`, `Makefile`, `Procfile`
- **Generated code:** `.g.dart`, `.freezed.dart`, `.generated.ts`, `.generated.js`, `.pb.go`, `.pb.ts`, `.pb.py`, `.moc.cpp`, `.designer.cs`
- **Directories:** `node_modules`, `.git`, `__pycache__`, `.dart_tool`, `build`, `dist`, `migrations`
- **Skip names (tdd_enforcer):** `setup.py`, `conftest.py`, `manage.py`, `wsgi.py`, `asgi.py`, `main.dart`, `app.ts`, `index.ts`, `index.js`

---

## Installation

### Prerequisites

- [Claude Code](https://claude.com/claude-code) CLI installed
- Python 3.10+ (for hooks)
- pytest (for running tests): `pip3 install pytest`

### Steps

1. **Clone the repo:**
```bash
git clone https://github.com/viniciuscffreitas/devflow.git ~/.claude/devflow
```

2. **Run the installer:**
```bash
chmod +x ~/.claude/devflow/install.sh && ~/.claude/devflow/install.sh
```

This handles everything automatically: copies skills and commands to the right directories, registers hooks in `~/.claude/settings.json`, and merges with your existing configuration.

3. **Optional — copy CLAUDE.md:**
```bash
cp ~/.claude/devflow/CLAUDE.md ~/.claude/CLAUDE.md
```

> If you already have a `~/.claude/CLAUDE.md`, merge the devflow sections manually instead of overwriting.

4. **Verify installation:**
```bash
# All 81 tests should pass
cd ~/.claude/devflow && python3 -m pytest hooks/tests/ -v
```

### Uninstalling

To remove devflow cleanly:

```bash
chmod +x ~/.claude/devflow/uninstall.sh && ~/.claude/devflow/uninstall.sh
```

This removes skills, commands, and hook registrations from `~/.claude/settings.json` without affecting other plugins.

---

## Compatibility

devflow is designed to coexist with other Claude Code plugins:

| Plugin | Conflict? | Notes |
|--------|-----------|-------|
| **superpowers** | Partial overlap | superpowers handles brainstorming, worktrees, finishing branches. devflow adds automatic hooks, behavior contracts, wizard, model routing. They complement each other well. **Recommended: keep both** |
| **pr-review-toolkit** | None | Complementary — devflow doesn't do PR review |
| **frontend-design** | None | Complementary — devflow doesn't do UI |
| **swift-lsp** | None | Complementary — devflow doesn't do LSP |
| **linear** | None | Complementary — devflow doesn't do project management |
| **explanatory-output-style** | None | Style plugin, no functional overlap |
| **dippy** | None | dippy is PreToolUse/Bash, devflow hooks are PostToolUse |
| **soundsh** | None | Sound hooks use different events |

---

## Architecture

```
~/.claude/
├── commands/
│   ├── spec.md          # /spec command
│   ├── sync.md          # /sync command
│   ├── learn.md         # /learn command
│   └── pause.md         # /pause command
├── skills/
│   ├── devflow-spec-driven-dev/SKILL.md
│   ├── devflow-behavior-contract/SKILL.md
│   ├── devflow-wizard/SKILL.md
│   ├── devflow-agent-orchestration/SKILL.md
│   └── devflow-model-routing/SKILL.md
├── devflow/
│   ├── hooks/
│   │   ├── _util.py              # Shared utilities
│   │   ├── file_checker.py       # Quality hook
│   │   ├── tdd_enforcer.py       # TDD hook
│   │   ├── context_monitor.py    # Context % hook
│   │   ├── pre_compact.py        # Save state hook
│   │   ├── post_compact_restore.py  # Restore state hook
│   │   ├── spec_stop_guard.py    # Stop guard hook
│   │   └── tests/
│   │       ├── test_util.py           # 22 tests
│   │       ├── test_file_checker.py   # 10 tests
│   │       ├── test_tdd_enforcer.py   # 14 tests
│   │       ├── test_spec_stop_guard.py # 7 tests
│   │       ├── test_context_monitor.py # 7 tests
│   │       └── test_compact_hooks.py  # 9 tests (pre + post)
│   ├── skills/                    # Source skills (copied by install.sh)
│   ├── commands/                  # Source commands (copied by install.sh)
│   ├── install.sh                 # Automated installer
│   ├── uninstall.sh               # Automated uninstaller
│   └── state/
│       └── <session-id>/
│           ├── active-spec.json   # Current spec status
│           └── pre-compact.json   # Saved state before compaction
└── settings.json                  # Hook registrations
```

### Hook communication protocol

Hooks communicate with Claude Code via JSON on stdout:

```python
# Inject context (non-blocking advisory message)
{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "..."}}

# Block an action
{"decision": "block", "reason": "..."}

# Deny permission
{"permissionDecision": "deny", "reason": "..."}
```

Hooks receive input via stdin (JSON with tool_input, context_tokens_used, etc.). Errors are logged to stderr (doesn't interfere with the stdout protocol).

### Error handling philosophy

- **Hooks must never crash** — a crashing hook disrupts Claude Code's workflow
- **Silent exit when nothing to report** — no noise, no unnecessary output
- **Log errors to stderr** — provides diagnostic trail without breaking stdout protocol
- **Fail-safe for safety hooks** — spec_stop_guard includes a 24-hour expiry; corrupt state files older than 24h are treated as abandoned rather than blocking indefinitely
- **Fail-open for quality hooks** — file_checker and tdd_enforcer skip gracefully on errors (no false positives)

---

## Customization

### Adjusting thresholds

Thresholds can be configured via `devflow-config.json` at two levels:

- **Global:** `~/.claude/devflow/devflow-config.json`
- **Per-project:** `.devflow-config.json` in the project root (overrides global)

Alternatively, edit `~/.claude/devflow/hooks/_util.py` directly:

```python
FILE_LINES_WARN = 400        # Warning at this many lines
FILE_LINES_CRITICAL = 600    # Critical at this many lines

CONTEXT_WINDOW_TOKENS = 200_000     # Claude's context window
AUTOCOMPACT_BUFFER_TOKENS = 33_000  # Buffer before compaction
CONTEXT_WARN_PCT = 80.0             # Warn at this %
CONTEXT_CAUTION_PCT = 90.0          # Caution at this %
```

### Adding a new toolchain

1. Add to `ToolchainKind` enum in `_util.py`
2. Add fingerprint to `_TOOLCHAIN_FINGERPRINTS` list
3. Add entry to `TOOLCHAIN_FINGERPRINT_MAP`
4. Create `_check_<toolchain>` function in `file_checker.py`
5. Register in `_CHECKERS` dict

### Adding generated file patterns

Add to `GENERATED_PATTERNS` in `_util.py`:

```python
GENERATED_PATTERNS = frozenset({
    ".g.dart", ".freezed.dart",
    # Add your pattern here:
    ".auto.ts",
})
```

### Disabling a specific hook

Remove or comment out the hook entry in `~/.claude/settings.json`. The other hooks continue working independently.

---

## Running tests

```bash
cd ~/.claude/devflow

# Run all 81 tests
python3 -m pytest hooks/tests/ -v

# Run specific test file
python3 -m pytest hooks/tests/test_tdd_enforcer.py -v

# Run with coverage (requires pytest-cov)
python3 -m pytest hooks/tests/ --cov=hooks --cov-report=term-missing
```

---

## Concepts and origins

devflow synthesizes patterns from two sources into a language-agnostic system:

### From [agentic-ai-systems](https://github.com/ThibautMelen/agentic-ai-systems) (Anthropic patterns)
- **Agent orchestration patterns** — Baseline, Prompt Chaining, Routing, Parallelization, Orchestrator-Workers, Evaluator-Optimizer
- **Subagent flat hierarchy rule** — subagents never spawn subagents
- **Model routing** — Opus for planning, Sonnet for implementation, Haiku for trivial tasks
- **Workflow vs autonomous agent distinction** — prefer workflows, use autonomous only when trajectory can't be predefined

### From [pilot-shell](https://github.com/maxritter/pilot-shell) (professional dev environment)
- **Spec-driven development** — structured Plan→TDD→Verify flow
- **Behavior contracts** — CHANGES/MUST NOT CHANGE/PROOF for bugfixes
- **Automatic quality hooks** — lint, format, file length on every edit
- **TDD enforcement** — nudge toward test-first development
- **Context preservation** — save/restore state across compaction
- **Session exit protection** — prevent accidental loss of work-in-progress
- **Convention discovery** — `/sync` to understand project patterns
- **Skill extraction** — `/learn` to capture session discoveries
- **Wizard pattern** — multi-phase confirmation for destructive ops

### What devflow adds beyond both sources
- **Language-agnostic toolchain detection** — works across Node.js, Flutter, Go, Rust, Maven without configuration
- **Smart test path suggestion** — language-aware directory mirroring with correct naming conventions
- **Generated file detection** — skips codegen artifacts across ecosystems
- **Fail-safe with expiry** — stop guard uses 24-hour expiry for stale specs instead of blocking indefinitely on corrupt state
- **Stderr error logging** — diagnostic trail without breaking hook protocol

---

## License

MIT
