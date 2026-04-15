# Plan: ast-grep as a devflow primitive

**Date:** 2026-04-15
**Type:** Feature (additive — no existing behavior changes)
**Status:** PENDING approval

## Motivation

Andrés Vidal shared *The Complete Guide to Tokenmaxxing with Claude* in #ai (thread `1776070644.464989`). Core claim, which holds up:

> `grep` returns lines, not context. Claude re-reads full files to understand what it matched → context bloat, higher cost, noise from comments/strings/TODOs.
>
> `ast-grep` (`sg`) does structural AST search — returns the call, not the substring. Surgical, low-noise, cheap.

devflow today does text/regex matching in several hook points. None use AST. Concrete waste:
- `file_checker.py` relies on downstream tools (`dart analyze`, `eslint`) to catch forbidden calls — expensive and per-language
- No way to express "reject `print()` outside `test/`" declaratively
- Rule additions require Python code, not data

This plan makes ast-grep a first-class primitive so new rules are YAML files, not code changes.

## Non-goals

- Replacing the `Grep` tool globally. `Grep` stays correct for text, comments, docs, configs.
- Auto-installing ast-grep. User owns their toolchain.
- Porting `secrets_gate.py`. Secrets are textual patterns — regex is correct there.
- Touching `tdd_enforcer.py` — path logic, not content search.
- Porting `instinct_capture.py` — heavier lift, separate follow-up.

## Architecture

### Rule format — native ast-grep YAML

```yaml
# ~/.claude/devflow/sg-rules/no-print-dart.yml
id: no-print-dart
language: dart
message: "use SecureLogger instead of print()"
severity: warning
rule:
  pattern: print($_)
files:
  - "lib/**/*.dart"
not-files:
  - "**/test/**"
  - "**/*.g.dart"
  - "**/*.freezed.dart"
```

No custom DSL. Reuses ast-grep's format so rules are portable and `sg scan` understands them directly.

### Two rule sources, merged

- **Global (shipped):** `~/.claude/devflow/sg-rules/*.yml`
- **Project override:** `<project_root>/.claude/sg-rules/*.yml`

Project rules override global ones with the same `id`. Matches the existing devflow config pattern (global `devflow-config.json` + project `.devflow-config.json`).

### New module: `hooks/_sg.py`

Thin wrapper over the `sg` CLI. Responsibilities:

- `detect_binary() -> Optional[str]` — cached per-process, returns path to `sg` or `None`
- `load_rules(project_root: Optional[Path]) -> list[LoadedRule]` — merges global + project, validates YAML, caches
- `run_for_file(path: Path, rules: list[LoadedRule]) -> list[SgFinding]` — filters rules by language+files glob, invokes `sg scan --rule <file> --json=stream <target>`, parses output
- Graceful degradation: missing binary → empty findings, one warning per session
- Broken YAML → skip rule with stderr log, never raise into the caller

Dataclasses:
```python
@dataclass
class LoadedRule:
    id: str
    language: str
    path: Path
    severity: str  # "error" | "warning" | "info"

@dataclass
class SgFinding:
    rule_id: str
    file: Path
    line: int
    column: int
    message: str
    severity: str
```

### `file_checker.py` integration

After the existing toolchain check block, call `_sg.run_for_file(file_path, rules)`. Append findings to the existing `[devflow quality]` output. Non-blocking (same severity model as file-size warnings).

```python
sg_findings = _sg.run_for_file(file_path, _sg.load_rules(project_root))
if sg_findings:
    parts.append("sg: " + "; ".join(f"{f.rule_id}@L{f.line}: {f.message}" for f in sg_findings))
```

### `discovery_scan.py` integration

At session start, probe for `sg`. Inject one line into the project profile:

```
[devflow:project-profile]
...
AST_GREP=present  (or AST_GREP=missing)
```

When missing, follow with a one-line install hint (`brew install ast-grep` / `cargo install ast-grep` / `npm i -g @ast-grep/cli`). Agents see this in-context and know whether `sg` is callable via Bash.

### Global CLAUDE.md nudge

Add one bullet under "### Context Discipline":

> For code *structure* searches (function calls, definitions, usages), prefer `sg` (ast-grep) via Bash when `AST_GREP=present`. `Grep` remains the right tool for text, comments, docs, configs.

One sentence. No bloat. The nuance (code vs. text) matters — a blanket "always use sg" would break doc/comment search.

### Initial shipped rule set

Minimum viable, all structural, all validated against real fixtures:

1. `no-print-dart.yml` — Dart `print()` outside `test/`, `main`, `debugPrint`
2. `no-console-log-ts.yml` — TS/JS `console.log/warn/error` outside `test/`, `spec/`
3. `no-debugger.yml` — `debugger;` in TS/JS

Deferred from v1 because they need careful pattern work:
- `no-todo-without-ticket` — comment matching varies per language, keep as text rule in follow-up
- `no-raw-sql-in-handler` — project-specific, ships in projects not global

## Tasks

| # | Task | Deliverable | Test |
|---|------|-------------|------|
| 1 | `_sg.detect_binary()` with per-process cache | `hooks/_sg.py` partial | `test_sg.py::test_detect_binary_caches` |
| 2 | `_sg.load_rules()` — merge global + project, validate, cache | `hooks/_sg.py` + fixture yamls | `test_sg.py::test_load_rules_merge_override` + `test_load_rules_skips_broken_yaml` |
| 3 | `_sg.run_for_file()` — invoke sg, parse JSON, filter by language/files | `hooks/_sg.py` complete | `test_sg.py::test_run_for_file_structural` (skipped if sg missing) |
| 4 | `file_checker.py` hook integration | patch to `file_checker.py` | `test_file_checker.py::test_sg_findings_appended` (mock `_sg`) |
| 5 | `discovery_scan.py` binary probe + profile line | patch to `discovery_scan.py` | `test_discovery_scan.py::test_ast_grep_presence` |
| 6 | Ship 3 rule yamls in `sg-rules/` | `sg-rules/no-print-dart.yml`, `no-console-log-ts.yml`, `no-debugger.yml` | manual fixture test per rule |
| 7 | CLAUDE.md one-line nudge | edit `~/.claude/CLAUDE.md` | n/a (doc change) |
| 8 | `docs/sg-rules.md` — author guide | new doc | n/a |
| 9 | Bootstrap note in README + install hint in discovery_scan | README + log string | n/a |

9 tasks, each atomic and independently committable.

## TDD order

Write test first, watch it fail, implement, watch it pass, commit.

1. `test_detect_binary_caches` (RED) → implement cache (GREEN)
2. `test_load_rules_merge_override` + `test_load_rules_skips_broken_yaml` → implement loader
3. `test_run_for_file_structural` — gated on real `sg` binary, `pytest.skip` when missing
4. `test_file_checker_sg_findings_appended` — mocks `_sg.run_for_file` to return fake findings
5. `test_discovery_scan_ast_grep_presence` — monkeypatches `shutil.which`

Tests MUST run green on machines without `sg` installed (CI). Real-binary tests gate on `_sg.detect_binary()`.

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| `sg` not installed → silent skip → users don't know rules exist | discovery_scan profile line; one-time session warning when rules exist but binary is missing |
| Broken rule YAML crashes hook → blocks Write/Edit | Per-rule try/except in loader; hook never raises; stderr log only |
| Perf: `sg scan` per file on every edit | Scope rules by language first; short-circuit when zero rules match; measured target <50ms per file |
| False positives (`print` in `fingerprint`) | Structural `pattern: print($_)` matches the call expression, not substring — this is the whole point |
| ast-grep rule syntax drift between versions | Doc minimum version (`ast-grep >= 0.25`); loader logs detected version on first use |
| YAML pattern wrong for a language → shipped rule is noise | Each shipped rule has a fixture file that triggers it and another that must not — these run in CI when binary present |
| User without brew can't install | Doc cargo + npm install paths in README and in the missing-binary warning |

## Acceptance criteria

1. With `sg` installed: editing a `lib/foo.dart` with `print("hi")` emits `[devflow quality] sg: no-print-dart@L<n>: use SecureLogger instead of print()` in the hook output.
2. With `sg` installed: editing `test/foo_test.dart` with `print("hi")` emits NO sg finding (files filter works).
3. Without `sg`: editing any file produces the exact same output as today — zero behavioral diff.
4. Broken YAML file in `sg-rules/`: hook completes successfully, broken rule is skipped with one stderr line.
5. Project rule with same `id` as global: project version wins (verified by fixture test).
6. `pytest hooks/tests/` passes on a machine without `sg`.
7. `pytest hooks/tests/` passes on a machine with `sg` installed (includes real runner tests).
8. `discovery_scan` session-start profile includes an `AST_GREP=present|missing` line.
9. `~/.claude/CLAUDE.md` contains the one-sentence code/text nudge.

## Verification before DONE

1. `ruff check ~/.claude/devflow` — clean
2. `pytest ~/.claude/devflow/hooks/tests/` — full suite green
3. Manual smoke in a dart project: add `print("smoke")` to a file under `lib/`, save via Claude Code, observe the devflow quality output

## Review gate

`pr-review-toolkit:review-pr` after all 9 tasks complete and verification passes.

## Out of scope (explicit)

- `instinct_capture.py` porting to sg (separate plan, higher risk)
- `linters/engine.py` integration (diff-based, different hook point, follow-up)
- Blocking enforcement via `pre_push_gate.py` (stays warning-only in v1)
- Community rule repo / rule sharing across machines
- Per-rule autofix (`sg scan --fix`) — v1 is detection only

## Rollback

All changes are additive. Rollback = delete `hooks/_sg.py`, delete `sg-rules/`, revert the `file_checker.py` + `discovery_scan.py` patches, revert the one-line CLAUDE.md change. No data migration, no state to unwind.
