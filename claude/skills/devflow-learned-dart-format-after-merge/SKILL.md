# Mandatory dart format after merge

## Trigger

Whenever any of these actions happen in a Flutter/Dart project:
- `git merge <branch>`
- Merge conflict resolution
- `git rebase`
- `git cherry-pick`
- Accepting upstream changes (`git pull`)

**NEVER skip this step before committing the merge.**

## The Problem

CI runs `dart format --output=none --set-exit-if-changed .` on the **entire** project.

When you merge, files from the other branch may arrive without correct formatting
— even if YOU didn't touch them. If you only format the files you edited, CI will
break because of files that came from the other branch.

**Real cost:** each broken CI costs build time + developer time to diagnose.
In projects with paid runners, it costs actual money.

## Solution

After any merge (with or without conflicts), before committing:

```bash
# 1. Check which files need formatting
dart format --output=none --set-exit-if-changed .

# 2. Format everything (if there are files to fix)
dart format .

# 3. Confirm it's clean
dart format --output=none --set-exit-if-changed .
# should print: "Formatted N files (0 changed)"

# 4. Only then commit
git add -u
git commit -m "style: dart format after merge"
```

## Quick version (one-liner)

```bash
dart format . && dart format --output=none --set-exit-if-changed . && echo "FORMAT OK"
```

If it prints `FORMAT OK`, you can commit. If not, something went wrong.

## Why this happens

`dart format` can produce different outputs depending on the SDK version.
The other branch may have been committed with a different version of the formatter,
or simply without running `dart format` before committing.

## Post-merge checklist

- [ ] `dart format .` run on the entire project
- [ ] `dart format --output=none --set-exit-if-changed .` confirms 0 changed
- [ ] `flutter analyze` with no warnings
- [ ] Tests for the affected package passing
- [ ] Only then commit and push
