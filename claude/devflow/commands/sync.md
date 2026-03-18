# /sync

Scans the current codebase, discovers conventions, and updates the project context.

## Usage

```
/sync
```

## What it does

1. **Stack detection** — identifies languages, frameworks, package managers
2. **Convention discovery** — naming patterns, directory structure, import style
3. **Test discovery** — test frameworks, existing test patterns, current coverage
4. **Dependency audit** — key dependencies and their versions
5. **Context update** — Claude uses discovered conventions for the rest of the session

## When to use

- First session in an unfamiliar project
- After significant structural changes to the project
- When Claude is making decisions inconsistent with the project

## Output

Summary of discovered conventions available as session context.
