# /sync

Re-scan the current project and refresh the devflow context.

## Instructions

Run the following steps **in order** using the Bash tool:

**Step 1 — Re-run discovery scan:**
```bash
python3 ~/.claude/devflow/hooks/discovery_scan.py
```

**Step 2 — Display the updated project profile:**
```bash
python3 ~/.claude/devflow/hooks/sync_report.py
```

Report the output of both commands to the user verbatim. The discovery scan
updates `project-profile.json` and re-injects learned skill symlinks.
The sync report confirms the current toolchain, test framework, issue tracker,
and any active learned skills.

## When to use

- First session in an unfamiliar project
- After significant structural changes (new framework, renamed dirs)
- When Claude is making conventions inconsistent with the project
- After manually editing `.devflow-config.json`
