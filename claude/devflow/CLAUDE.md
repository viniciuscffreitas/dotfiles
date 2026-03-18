## devflow v2.2 — Workflow & Quality

### When to use /spec
Use `/spec "description"` for any non-trivial task:
- Features that add new behavior
- Bugfixes (auto-detects -> Behavior Contract)
- Refactoring with non-trivial scope

Skip /spec only for trivial 1-2 line changes.

### TDD
- RED: write the test describing behavior -> run -> MUST FAIL
- GREEN: implement minimum to pass -> run -> MUST PASS
- REFACTOR: improve without breaking -> run -> MUST PASS
- COMMIT: atomic commit per behavior

### Verification (mandatory before "done")
1. Lint / static analysis for the project
2. Full build (if applicable)
3. Complete test suite

### Model Routing
- `claude-opus-4-6` -> planning, design, complex trade-offs
- `claude-sonnet-4-6` -> implementation, refactoring, debugging (default)
- `claude-haiku-4-5-20251001` -> search, formatting, simple transformations

### Code Quality
- File length limits configurable via `devflow-config.json` (global: `~/.claude/devflow/`, project: `.devflow-config.json`)
- Default: >400 lines warning, >600 lines mandatory split
- No TODO without associated issue
- Atomic, descriptive commits

### Issue Tracker (agnostic)
- Discovery scan auto-detects the project tracker (Linear, GitHub Issues, Jira, TODO.md)
- `[devflow:project-profile]` is injected each session with `ISSUE_TRACKER_TYPE`
- Review Gate generates tech debt drafts in the tracker's native format
- NEVER create issues automatically — always present drafts for manual approval
- If no tracker detected: plaintext drafts to stdout

### Destructive Operations
Any delete, reset, migration, or irreversible overwrite:
-> Use `devflow:wizard` (explicit confirmation mandatory)

### Frontend & UX
- **Design System first**: always consult existing tokens, components, and patterns before creating new ones
- **Visual silence**: every element on screen must justify its presence — remove noise, don't add it
- **Low cognitive load**: clear hierarchy, one primary action per screen, progressive disclosure
- **WCAG**: minimum AA contrast, don't rely on color alone, keyboard navigation must work
- **Custom states**: replace default browser focus rings with design system visual states
- **Crafted with care**: polished micro-interactions (smooth transitions, tactile feedback, purposeful animations — not decorative)
- **Frontend Gate mandatory**: before coding UI, invoke `frontend-design:frontend-design`

### Review Gate
- Before declaring DONE on any non-trivial task, run `pr-review-toolkit:review-pr`
- Review validates logic, quality, regressions, and design system adherence
- Issues found in review: fix before proceeding

### Learned Skills (single-session focus)
- devflow is single-session: learned skills are injected via global symlinks in `~/.claude/skills/`
- Two simultaneous sessions on different projects cause race conditions on symlinks
- For parallel sessions: set `"learned_skills_auto_inject": false` in `devflow-config.json` or project `.devflow-config.json`
- Skills loaded at session start survive symlink removal — the real risk is only during concurrent compaction

### Subagents
- Subagents DO NOT spawn other subagents
- All delegation flows through the Main Agent
- For independent parallel tasks: `superpowers:dispatching-parallel-agents`
