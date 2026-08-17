# /sync

Refresh repo context for the current session.

This is not a deployment/sync command. It is a "where are we?" command.

## Instructions

Run these checks in order, then summarize the useful context in plain language.

```bash
pwd
git status --short --branch
git branch --show-current
git log --oneline --decorate -10
git diff --stat
git diff --name-only
find .. -maxdepth 2 \( -name AGENTS.md -o -name CLAUDE.md -o -name ".agentflow" \) -print
```

Then report:

- current repo and branch
- uncommitted work
- recent commits
- files changed in this session/branch
- active project policy/config files
- what you now believe the next task context is

Do not dump huge command output unless Vini asks. Compress aggressively.
