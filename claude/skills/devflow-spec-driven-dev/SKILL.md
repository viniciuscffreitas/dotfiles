---
name: devflow-spec-driven-dev
description: >
  Use for any non-trivial development task. Drives the complete
  Plan->Approve->TDD->Verify flow. Auto-detects feature vs bugfix.
  TRIGGER: /spec command, user says "implement", "add", "fix" for non-trivial tasks.
---

# Spec-Driven Development

## Type Detection

**Feature** = new functionality that doesn't exist
**Bugfix** = existing behavior that is broken

If ambiguous: "Does this add something new or fix something that should already work?"

## Feature Mode (<=3 tasks)

```
1. PLAN          — describe architecture + tasks in natural language
2. APPROVE       — present to user, wait for explicit confirmation
3. FRONTEND GATE — if task involves UI, invoke frontend-design:frontend-design
4. TDD           — RED -> GREEN -> REFACTOR per task
5. VERIFY        — lint + build + full test suite
6. REVIEW GATE   — run pr-review-toolkit:review-pr for logic validation
7. DONE          — commit with descriptive message
```

## Feature Mode (>3 tasks)

1. Use `superpowers:writing-plans` to create a detailed plan in `docs/plans/`
2. Use `superpowers:executing-plans` to execute with review checkpoints

## Bugfix Mode

```
1. BEHAVIOR CONTRACT — invoke devflow:behavior-contract
2. APPROVE           — user approves the contract (mandatory)
3. TDD               — write tests that prove CHANGES and MUST NOT CHANGE
4. IMPLEMENT         — minimal code to pass the tests
5. VERIFY            — all tests + no regressions
6. REVIEW GATE       — run pr-review-toolkit:review-pr for logic validation
7. DONE              — commit with contract reference
```

## Frontend Gate

Before coding ANY UI (component, page, layout, interaction):

1. Invoke `frontend-design:frontend-design`
2. The skill ensures: low cognitive load, zero visual noise, WCAG compliance
3. Use custom states instead of default browser focus rings
4. Prioritize visual silence — every element must justify its presence
5. Micro-interactions with love and care: smooth transitions, tactile feedback, purposeful animations

**When to skip:** configs, scripts, APIs, infra — backend-only work.

## Review Gate

Before declaring DONE in any flow (feature or bugfix):

1. Run `pr-review-toolkit:review-pr` for logic and quality validation
2. If the review flags issues: fix them before proceeding
3. Only declare DONE after a clean review

### Tech Debt Drafts

When the review identifies pre-existing issues (not caused by the current task):

1. Read the project profile `[devflow:project-profile]` from the session context
2. Based on `ISSUE_TRACKER_TYPE`, generate drafts in the native format:

| Tracker | Draft Format |
|---|---|
| `linear` | Draft via Linear MCP tool (do NOT create — present for user approval) |
| `github_issues` | Ready-to-run `gh issue create --title "..." --body "..." --label "tech-debt"` command |
| `jira` | JIRA description with Summary, Description, Labels fields |
| `todo_file` | Markdown bullet point to append to TODO.md |
| `none` | Plain text summary on stdout |

**NEVER create issues automatically. Always present drafts for manual review.**

If no tracker is detected (`none`), generate drafts as plain text — the system works without dependency on external tools.

## TDD Cycle

```
RED:     write the test -> run -> MUST FAIL (if it passes, the test is wrong)
GREEN:   implement minimum -> run -> MUST PASS
REFACTOR: improve without breaking -> run -> MUST PASS
COMMIT:  atomic commit per behavior
```

## Final Verification (mandatory)

1. Lint / static analysis available in the project
2. Full build (if applicable)
3. Complete test suite

If any fails: fix before declaring done.

## Rules

- NEVER declare done without full verification
- NEVER declare done without review gate
- NEVER implement before having tests (except configs/docs/infra)
- NEVER code UI without frontend gate (except backend-only work)
- Atomic commits — one behavior per commit
- For destructive operations: use devflow:wizard
