# Run Full CI Locally Before Push

## When to use

**Always** before running `git push` on PRs with branch protection + mandatory CI.
Especially after: merging branches, resolving conflicts, changes across multiple packages.

## Why it matters

Remote CI costs time (execution) and money (CI minutes). Each push with broken CI
wastes ~5 min of runner time. Running locally takes ~2 min and gives confidence before
exposing to the remote.

## What this project's CI does (code_quality.yaml)

1. `dart format --output=none --set-exit-if-changed .` — formats the entire project
2. `flutter analyze` — analyzes the entire project (exit 1 for any error/warning/info)
3. `flutter test test/` — tests for each package group

## Local script equivalent to CI

```bash
# 1. Install deps for all packages (as CI does)
flutter pub get &
for package in packages/*/; do
  if [ -f "$package/pubspec.yaml" ]; then
    (cd "$package" && flutter pub get) &
  fi
done
wait

# 2. Check formatting (CI uses --set-exit-if-changed)
dart format --output=none --set-exit-if-changed .

# 3. Analyze the entire project (not just one package!)
flutter analyze

# 4. Run tests for all packages that have tests
for pkg in . packages/*/; do
  if [ -d "$pkg/test" ] && [ "$(find $pkg/test -name '*_test.dart' -type f | wc -l)" -gt 0 ]; then
    echo "=== $pkg ==="
    (cd "$pkg" && flutter test test/)
  fi
done
```

## Common pitfalls

### flutter analyze analyzes the ENTIRE PROJECT
- Running `flutter analyze packages/me_job` alone is not enough — CI runs without arguments
- Errors in other packages (even unmodified ones) break CI
- After merging develop, packages beyond your target may have new errors

### flutter analyze fails on info (not just errors)
- `lines_longer_than_80_chars`, `avoid_redundant_argument_values`, `unnecessary_async` etc.
- These are `info` level but cause exit code 1
- Verify: `flutter analyze; echo $?`

### flutter pub get after merge
- New deps added in develop may not be installed locally
- Symptom: `uri_does_not_exist` for packages like `bloc_test`, `fake_cloud_firestore`
- Fix: run pub get for all packages before analyze

### dart format on the ENTIRE PROJECT
- See skill `devflow-learned-dart-format-after-merge`

## Golden Rule

> Before `git push`, run the full sequence: pub get -> format check -> analyze -> tests.
> If any step fails locally, it will fail on CI.

## Zero tolerance for "pre-existing" warnings

**NEVER** dismiss a `flutter analyze` warning as "pre-existing" without verifying.
After any method signature change (e.g., `void` -> `Future<void>`), new
`discarded_futures` appear at call sites — they look pre-existing but they are NOT.

Mandatory verification before push:
```bash
flutter analyze; echo "Exit: $?"
# MUST print "No issues found!" and "Exit: 0"
# Any other result = DO NOT PUSH
```

If analyze shows issues at call sites after changing a cubit/BLoC signature,
see skill `devflow-learned-bloc-future-callsites`.
