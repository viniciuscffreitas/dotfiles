---
name: devflow-wizard
description: >
  Use for destructive operations: delete, reset, migration, overwrite, irreversible changes.
  TRIGGER: delete files/branches, drop tables, reset data, overwrite uncommitted changes,
  force push, schema migrations, bulk operations.
---

# Wizard — Destructive Operations

## Purpose

Destructive operations require explicit confirmation before proceeding.
The cost of pausing to confirm is low. The cost of an unwanted action is high.

## Mandatory Flow

```
PHASE 1 — ANALYZE
    Read and understand the full scope of the operation
    List: what will be affected, what will be lost, what is irreversible

PHASE 2 — PRESENT
    Present to user:
    - What will be done
    - What CANNOT be undone
    - Less destructive alternatives, if they exist
    USE AskUserQuestion for explicit confirmation

PHASE 3 — DETAILED PLAN
    If approved in Phase 2:
    - List each step in order
    - Identify rollback points (if they exist)
    - Present again for final confirmation
    USE AskUserQuestion again

PHASE 4 — EXECUTE
    Execute only after second confirmation
    Report each step as it executes
    Stop immediately if something unexpected occurs
```

## Trigger Examples

- `git reset --hard`, `git push --force`
- `DROP TABLE`, `DELETE FROM` without WHERE
- `rm -rf`, `find . -delete`
- Schema migrations that alter existing columns
- Overwriting files with uncommitted changes
- Disabling a feature with active users

## Rules

- NEVER skip confirmation even if the user seems certain
- NEVER assume a previous approval covers different cases
- If in doubt about destructiveness: treat as destructive
