## Devflow hook rules — never violate

- NEVER add a hook with matcher `".*"` — spawns Python on every tool call
- NEVER add hooks to PreToolUse/PostToolUse without a specific matcher
- Allowed matchers for PreToolUse: `"Write|Edit|MultiEdit"` only
- Hooks that run per-session: SessionStart, Stop, UserPromptSubmit
- Before adding any hook, ask: "does this run on every tool call?"
  If yes → don't add it.

### Re-enable checklist (all 4 required)
1. Fires how many times per session? — 1x = ok, N× = danger
2. Matcher is specific? — `".*"` = prohibited
3. Avg execution time? — >100ms = problem
4. What if it fails? — nothing critical = make it async
