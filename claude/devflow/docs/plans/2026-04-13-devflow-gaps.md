# devflow — Gap Resolution Plan
**Date:** 2026-04-13
**Scope:** 11 gaps from audit + 1 new April 2026 gap
**Total tasks:** 7
**Test baseline:** 500 (482 hooks/ + 18 telemetry/)
**README badge:** claims 586 — will be corrected

---

## Context: The 5-hour window

Max 20x plan ($200/mo) operates on rolling 5-hour windows of ~880K tokens. Since March 2026,
Opus 4.6 and Sonnet 4.6 have a 1M context window (GA, no surcharge). The `context_monitor`
hook uses `CONTEXT_WINDOW_TOKENS = 200_000` — a constant that is now wrong for both models.
This is Task 1 (P0).

---

## Task 1 — Fix `context_monitor`: dynamic window from hook payload [P0]

**Problem:** `CONTEXT_WINDOW_TOKENS = 200_000` is hardcoded in `_util.py`. Since March 2026,
Opus 4.6 and Sonnet 4.6 have 1M context. The hook warns "80%" when the session is actually at
16% of real capacity — or never warns at all if over 200K.

**Fix:** Read `context_window_tokens` from the hook event payload (Claude Code sends this field
in PostToolUse events). Fall back to `200_000` only if the field is absent.

**Files changed:**
- `hooks/_util.py` — make `CONTEXT_WINDOW_TOKENS` a fallback constant, not the source of truth
- `hooks/context_monitor.py` — read `context_window_tokens` from `hook_data`, pass to `tokens_to_pct()`
- `hooks/tests/test_context_monitor.py` — update tests to use dynamic window; add test for 1M window

**TDD approach:**
```
RED:   test_tokens_to_pct_uses_payload_window → fails (function ignores payload)
GREEN: read hook_data["context_window_tokens"] with fallback to CONTEXT_WINDOW_TOKENS
REFACTOR: extract _get_window(hook_data) helper
```

**Commit:** `fix(context_monitor): read context window from hook payload — fixes 1M Opus/Sonnet`

---

## Task 2 — Telemetry: populate existing schema columns [Batch B-1]

**Problem:** TelemetryStore already has columns for `tool_calls_total`, `compaction_events`,
and `context_tokens_at_first_action` — but `task_telemetry.py` never populates them. They've
been 0 since the SQLite store was built.

**Fix:** Populate these three columns by enhancing the JSONL scanner in `task_telemetry.py`.

**Columns to populate:**
- `tool_calls_total` — count all tool call events in the JSONL per session
- `compaction_events` — count PreCompact events from the JSONL
- `context_tokens_at_first_action` — tokens_used at the turn of the first Write/Edit

**Files changed:**
- `hooks/task_telemetry.py` — enhance `parse_session()` to extract these three signals
- `hooks/tests/test_task_telemetry.py` — add tests for each new signal

**TDD approach:**
```
RED:   test_parse_session_counts_tool_calls → fails (returns 0)
RED:   test_parse_session_counts_compaction_events → fails
RED:   test_parse_session_records_tokens_at_first_action → fails
GREEN: add extraction logic to parse_session()
REFACTOR: extract _count_tool_calls(events), _count_compaction(events), _tokens_at_first_action(events)
```

**Commit:** `feat(telemetry): populate tool_calls_total, compaction_events, context_tokens_at_first_action`

---

## Task 3 — Telemetry: new signals (USD cost, retry rate, TDD follow-through) [Batch B-2]

**Problem:** Three valuable signals are missing from the schema entirely.

**New columns to add to TelemetryStore:**
- `estimated_usd` REAL — dollar cost estimate from token counts + model detection
- `test_retry_count` INTEGER — failed test runs before first success in the session
- `tdd_followthrough_rate` REAL — ratio of tdd_enforcer warnings that got a test created in the same session

**Pricing table (hardcoded, versioned in code):**
```python
# Per 1M tokens (input/output blended estimate using 3:1 ratio approximation)
PRICING = {
    "claude-opus-4-6":    {"input": 5.0,  "output": 25.0},
    "claude-sonnet-4-6":  {"input": 3.0,  "output": 15.0},
    "claude-haiku-4-5":   {"input": 1.0,  "output": 5.0},
    "default":            {"input": 3.0,  "output": 15.0},  # Sonnet as default
}
```

**Model detection:** scan JSONL for `model` field in assistant messages. Use most frequent model seen.

**Files changed:**
- `telemetry/store.py` — add 3 new columns to `_COLUMNS` and `_CREATE_TABLE`; add migration
- `hooks/task_telemetry.py` — compute and pass new signals to TelemetryStore.record()
- `telemetry/cli.py` — show `estimated_usd` in `stats` and `recent` commands
- `hooks/tests/test_task_telemetry.py` — tests for USD computation, retry count, TDD follow-through
- `telemetry/tests/test_cli.py` — tests for USD display

**TDD approach:**
```
RED:   test_estimated_usd_opus_session → fails (column doesn't exist)
RED:   test_test_retry_count_counts_failures → fails
RED:   test_tdd_followthrough_when_test_created → fails (=1.0)
RED:   test_tdd_followthrough_when_no_test → fails (=0.0)
GREEN: schema migration + JSONL extraction + CLI display
REFACTOR: extract _estimate_usd(tokens, model) pure function
```

**Commit:** `feat(telemetry): add USD cost estimate, test retry count, TDD follow-through rate`

---

## Task 4 — Secrets detection hook [P1]

**Problem:** No PreToolUse gate scans for credentials before they're written to disk.
This is a material security gap for a tool operating across multiple projects.

**Fix:** New `hooks/secrets_detector.py` — PreToolUse on Write|Edit|MultiEdit.

**Detection patterns (heuristic, not ML):**
```python
PATTERNS = [
    # High confidence — block
    (r'(?i)(api[_-]?key|apikey)\s*=\s*["\'][A-Za-z0-9_\-]{20,}["\']', "HIGH", "API key"),
    (r'(?i)(secret|password|passwd|pwd)\s*=\s*["\'][^"\']{8,}["\']', "HIGH", "credential"),
    (r'(?i)sk-[A-Za-z0-9]{20,}', "HIGH", "OpenAI/Anthropic secret key"),
    (r'(?i)ghp_[A-Za-z0-9]{36}', "HIGH", "GitHub personal access token"),
    (r'-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----', "HIGH", "private key"),
    # Medium confidence — warn
    (r'(?i)(token|auth)\s*=\s*["\'][A-Za-z0-9_\-\.]{16,}["\']', "MEDIUM", "token"),
    (r'(?i)bearer\s+[A-Za-z0-9_\-\.]{16,}', "MEDIUM", "bearer token"),
]
```

**Behavior:**
- HIGH match → block with `{"decision": "block", "reason": "..."}`
- MEDIUM match → warn via `hookSpecificOutput` (non-blocking)
- Skip files: `*.test.*`, `*.spec.*`, `*.md`, calibration/, known dummy values

**Files changed:**
- `hooks/secrets_detector.py` — new hook
- `hooks/tests/test_secrets_detector.py` — new test file
- `install.sh` — register new hook in settings.json

**TDD approach:**
```
RED:   test_blocks_on_api_key_assignment → fails (hook doesn't exist)
RED:   test_blocks_on_openai_sk_key → fails
RED:   test_warns_on_bearer_token → fails
RED:   test_skips_test_files → fails
RED:   test_skips_dummy_values → fails (e.g. "sk-xxxx" = dummy)
GREEN: implement pattern matching + decision logic
REFACTOR: extract _classify(content) → list[Finding]
```

**Commit:** `feat(hooks): add secrets_detector — block credential writes before they land on disk`

---

## Task 5 — Commit message validation hook [P2]

**Problem:** CLAUDE.md states "atomic, descriptive commits" but nothing enforces format.

**Fix:** New `hooks/commit_validator.py` — PreToolUse on Bash, intercepts `git commit`.

**Format:** Conventional Commits (type(scope): description)
```
Valid types: feat, fix, chore, docs, test, refactor, perf, ci, build, style
Pattern: ^(feat|fix|chore|docs|test|refactor|perf|ci|build|style)(\(.+\))?: .{10,}
```

**Behavior:**
- Non-blocking warn (never blocks commits) — `hookSpecificOutput`
- Suggests corrected format if detectable
- Skips: merge commits, initial commits, `--amend`, `--no-edit`

**Files changed:**
- `hooks/commit_validator.py` — new hook
- `hooks/tests/test_commit_validator.py` — new test file
- `install.sh` — register new hook

**TDD approach:**
```
RED:   test_warns_on_missing_type → fails
RED:   test_passes_valid_conventional_commit → fails
RED:   test_skips_merge_commits → fails
RED:   test_skips_amend → fails
GREEN: regex match + advisory output
```

**Commit:** `feat(hooks): add commit_validator — warn on non-conventional commit messages`

---

## Task 6 — /sync: real implementation [P1]

**Problem:** `commands/sync.md` describes what /sync does but has no implementation.
It's LLM instruction-following with no deterministic backing.

**Fix:** Replace the stub with a command that:
1. Runs `discovery_scan.py` via Bash subprocess
2. Reads the resulting `project-profile.json`
3. Presents structured output to Claude to act on

**New sync.md structure:**
```markdown
## Implementation

Run discovery_scan to get a fresh project profile:
```bash
python3 ~/.claude/devflow/hooks/discovery_scan.py
```
Read the profile output, then use it to update context and check for convention inconsistencies.
```

**Additional: sync_report.py** — a thin CLI that reads project-profile.json and formats a human-readable summary (toolchain, tracker, test framework, learned skills count, design system).

**Files changed:**
- `commands/sync.md` — replace stub with deterministic Bash step
- `hooks/sync_report.py` — new CLI for formatted summary
- `hooks/tests/test_sync_report.py` — new test file

**TDD approach:**
```
RED:   test_sync_report_formats_flutter_profile → fails (no sync_report.py)
RED:   test_sync_report_handles_missing_profile → fails
GREEN: read project-profile.json → format output
```

**Commit:** `fix(commands): /sync executes discovery_scan deterministically`

---

## Task 7 — Context efficiency auto-surfacing + README badge [P2 + cleanup]

**Problem 1:** When understand/build ratio > 0.5, no signal surfaces beyond the CLI output.
The audit said this should auto-generate a tech debt draft in the native tracker format.

**Problem 2:** README badge says 586 tests but 500 exist. Misleading.

**Fix 1:** In `task_telemetry.py`, after writing telemetry, check the computed ratio.
If > 0.5, print a tech debt draft formatted for the detected tracker.

**Draft templates:**

| Tracker | Output |
|---|---|
| `linear` | Print Linear-formatted description to stdout (user manually creates) |
| `github_issues` | Print ready-to-run `gh issue create ...` command |
| `none` / fallback | Plain text draft to stdout |

**Output format:**
```
[devflow:ratio-alert] understand/build ratio 0.73 on feat-auth (threshold: 0.50)
--- TECH DEBT DRAFT ---
[tracker-specific format]
--- Present this draft to user before creating ---
```

**Fix 2:** Update README badge from 586 to 500. Add a note explaining the gap.

**Files changed:**
- `hooks/task_telemetry.py` — add `_maybe_surface_ratio_alert(session, project_profile_path)` called from `main()`
- `hooks/tests/test_task_telemetry.py` — tests for alert trigger and draft format
- `README.md` — update badge from 586 → 500

**TDD approach:**
```
RED:   test_ratio_alert_fires_above_threshold → fails
RED:   test_ratio_alert_silent_below_threshold → fails
RED:   test_ratio_alert_github_format → fails
RED:   test_ratio_alert_no_tracker_format → fails
GREEN: _maybe_surface_ratio_alert() implementation
```

**Commit:** `feat(telemetry): surface high anxiety ratio as tech debt draft`
**Commit:** `docs: correct README test badge 586 → 500`

---

## Execution order

```
Task 1 (P0, standalone) → Task 2 → Task 3 → Task 4 → Task 5 → Task 6 → Task 7
                                ↑ schema deps ↑
                         Task 2 must complete before Task 3 (schema migration order)
```

Tasks 4–7 are independent of each other and of 2–3. Can be parallelized.

## Final verify

```bash
cd ~/.claude/devflow
python3.13 -m pytest --tb=short -q        # all tests must pass
python3.13 hooks/health_report.py --critical   # no critical harness issues
```

## Expected final test count

| Current | Task 1 | Task 2 | Task 3 | Task 4 | Task 5 | Task 6 | Task 7 | Total |
|---------|--------|--------|--------|--------|--------|--------|--------|-------|
| 500 | +8 | +12 | +16 | +18 | +12 | +8 | +10 | **~584** |

---

*Plan generated 2026-04-13. Baseline: 500 tests.*
