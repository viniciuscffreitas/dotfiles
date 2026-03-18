# /learn

Captures discoveries from the current session as reusable skills.

## Usage

```
/learn
```

## What it does

1. **Identifies** non-obvious solutions found in this session
2. **Extracts** the reusable pattern (the "how" independent of the "what")
3. **Proposes** title, trigger, and content for the new skill
4. **Saves** to `~/.claude/skills/devflow-learned-<slug>/SKILL.md`

## Good candidates for /learn

- Solution for a recurring or hard-to-debug bug
- Code pattern the project uses but isn't documented
- Non-obvious sequence of steps for a common operation
- Workaround for a tool or framework limitation

## Bad candidates for /learn

- Obvious or well-documented things
- Solutions too specific to the current context (no reuse)
- Subjective preferences without technical justification

## Output

New skill created at `~/.claude/skills/devflow-learned-<slug>/SKILL.md`
