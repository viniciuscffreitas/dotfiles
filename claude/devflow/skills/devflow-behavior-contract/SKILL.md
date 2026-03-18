---
name: devflow-behavior-contract
description: >
  Use before any bugfix. Formally defines what WILL change and what MUST NOT change.
  TRIGGER: bugfix detected in /spec, or user says "fix bug", "broken", "regression".
---

# Behavior Contract

## Purpose

Before any bugfix: formally define the behavior contract.
Makes explicit what must not break -> prevents regressions.

## Contract Format

Produce exactly this structure:

```
## Behavior Contract: [short bug description]

**Context:** [which component, which endpoint, which function]

### CHANGES (expected behavior after fix)
- [ ] [specific, testable behavior that will be fixed]

### MUST NOT CHANGE (behaviors that MUST be preserved)
- [ ] [existing behavior that continues working]

### PROOF (tests that validate the contract)
- [ ] test_[name]: proves CHANGES works
- [ ] test_[name]: proves MUST NOT CHANGE still works
- [ ] test_[name]: tests the edge case that caused the bug
```

## Process

1. Read the code of the affected component
2. Identify current behavior (broken) vs expected behavior (correct)
3. List all callers/dependents of the component
4. Build the CHANGES + MUST NOT CHANGE contract
5. **Present to user for approval** (AskUserQuestion if needed)
6. Write the tests that prove each item
7. Only then implement the fix

## Critical Rules

- CHANGES must be specific and testable (not "fixes the bug", but "returns 404 when ID does not exist")
- MUST NOT CHANGE must cover all callers of the modified component
- If a MUST NOT CHANGE item breaks during implementation: STOP, revise contract, re-present
- Contract should appear as a comment in the commit or PR description

## Example

```
## Behavior Contract: /api/user/:id returns 500 instead of 404

**Context:** UserController.getById() — line 42

### CHANGES
- [ ] GET /api/user/999 -> HTTP 404 with body {"error": "not found"}
- [ ] Error log is NOT emitted for non-existent IDs

### MUST NOT CHANGE
- [ ] GET /api/user/1 (existing) -> HTTP 200 with data
- [ ] POST /api/user -> continues creating users
- [ ] JWT authentication -> continues being validated

### PROOF
- [ ] test_user_not_found_returns_404
- [ ] test_existing_user_returns_200
- [ ] test_no_error_log_on_missing_user
```
