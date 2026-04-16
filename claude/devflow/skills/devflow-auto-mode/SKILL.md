---
name: devflow-auto-mode
description: >
  Guide for using Claude Code's Auto Mode (Shift+Tab) within devflow.
  Decides when to cede check-in control to Opus 4.7 versus keeping manual gates.
  Use when starting a long-running task, after /spec APPROVE, or when deciding
  whether to interrupt an autonomous run.
---

# Auto Mode in devflow

Auto Mode (toggled with **Shift+Tab** in Claude Code) lets Opus 4.7 progress through
multi-step work without asking for confirmation between steps. It is one of the
features that makes 4.7's "long-running task" sweet spot practical — but it is also
the place where ceded control is hardest to take back mid-run.

devflow's position: **Auto Mode is a tool, not a default.** Use it when the upfront
context is genuinely complete and the trajectory is bounded. Skip it when the task
is exploratory, when blast radius is wide, or when intermediate decisions need a human.

## When to enable

| Situation | Why Auto Mode helps |
|---|---|
| Multi-file refactor with clear scope (rename, extract, move) | The plan is mechanical; check-ins between identical edits add latency without signal |
| Full-service review or audit pass | The work is read-heavy and the conclusions are batched — interrupting fragments the analysis |
| `/spec` execution **after** APPROVE on a Feature Mode (≤3 tasks) plan | The plan is locked; ceding control to the implementer is the whole point |
| Migrating between known patterns (e.g., `setState` → signals across many components) | Repetitive transformations benefit from uninterrupted flow |
| Long agentic loops (writing-plans → executing-plans on a >3-task plan) | Auto Mode pairs naturally with `superpowers:executing-plans` review checkpoints |

## When to keep manual control

| Situation | Why check-ins still matter |
|---|---|
| Exploratory work — "let's see if X is feasible" | The trajectory is the question, not the destination |
| Bugfix without a Behavior Contract | Without a contract, "minimal change" is a judgment call best made together |
| Destructive operations (delete, reset, migration, force push) | `devflow-wizard` exists precisely because these need explicit confirmation |
| Tasks with `oversight_level: human_review` per `risk-profile.json` | The risk profiler already flagged this as needing human eyes |
| First-time work in an unfamiliar area of the codebase | Cheaper to course-correct early than to undo a long autonomous run |

## Interaction with other devflow gates

Auto Mode does **not** override devflow gates. It only removes the manual confirmation
*between* steps. The following are unaffected:

- **Frontend Gate** — `frontend-design:frontend-design` still runs before any UI code
- **Review Gate** — `pr-review-toolkit:review-pr` still runs before DONE
- **TDD cycle** — the RED→GREEN→REFACTOR discipline still applies. `tdd_enforcer` only silences the *reminder* when oversight is `vibe`; the cycle itself remains your default for non-trivial work.
- **Behavior Contract** — bugfixes still require contract approval before implementation
- **Destructive operations** — `devflow-wizard` confirmation is mandatory

The mental model: Auto Mode is the *cadence* of execution; gates are the *checkpoints*.
You can run a fast cadence between gates and still hit every gate.

## Recommended pattern with /spec

```
1. /spec "..."                  ← manual: state intent
2. PLAN presented               ← manual: review architecture
3. APPROVE                      ← manual: explicit confirmation (gate)
4. [enable Auto Mode here]      ← Shift+Tab once the plan is locked
5. TDD per task (RED→GREEN→REFACTOR)  ← autonomous between tasks
6. VERIFY (lint + build + tests)      ← autonomous; failures still surface
7. [disable Auto Mode]          ← Shift+Tab before the review gate
8. REVIEW GATE                  ← manual: read the review, decide on follow-ups
9. DONE                         ← manual: commit, push
```

The asymmetry is deliberate: enabling Auto Mode after APPROVE is safe because the
plan is the contract. Disabling before REVIEW is safer because the review may
surface issues that change the next step entirely.

## When to interrupt a running Auto Mode

Don't hesitate to break in if you notice:

- The model started a path that contradicts the original plan
- A failing test or build error is being worked around instead of fixed at the root
- The model is editing files outside the scope of the approved plan
- Token spend is escalating without visible progress (run `python3 ~/.claude/devflow/telemetry/cli.py stats --by-model` to inspect)

Interrupting is cheap. Letting a divergent run continue is expensive.

## Effort level interaction

Auto Mode is calibrated for `effortLevel: xhigh` (devflow's default for Opus 4.7). At
`max`, the model may overthink each step and Auto Mode amplifies the cost. At `high`
or below, the model may be too quick to declare done without thorough verification —
Auto Mode amplifies that too. Stay at `xhigh` unless you have a specific reason.

## Anti-patterns

- **Auto Mode + ambiguous prompt** — the model fills ambiguity with its own assumptions; you lose the chance to correct early
- **Auto Mode + no plan** — without a target, every step is exploratory
- **Auto Mode + skipping Review Gate** — Auto Mode is not "skip all gates," it's "skip per-step confirmation"
- **Auto Mode + destructive operations** — `devflow-wizard` exists for a reason; bypassing it via Auto Mode defeats the safety mechanism
