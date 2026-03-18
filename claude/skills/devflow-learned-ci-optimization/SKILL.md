# Flutter CI Optimization — Cost and Speed

## When to use

When configuring or reviewing CI/CD for a Flutter monorepo with GitHub Actions.
When detecting CI breaking frequently or high runner costs.

## Pattern: Pre-push hook as the first line of defense

### The Problem
Remote CI is the first line of defense -> expensive and slow.
Each dart format or flutter analyze failure consumes ~3 min of ubuntu runner.

### The Solution
Local pre-push hook that mirrors CI exactly:

```bash
# .githooks/pre-push
#!/bin/bash
set -e
cd "$(git rev-parse --show-toplevel)"

flutter pub get
for package in packages/*/; do
  if [ -f "$package/pubspec.yaml" ]; then
    (cd "$package" && flutter pub get) &
  fi
done
wait

dart format --output=none --set-exit-if-changed .
flutter analyze

if [ -d "test" ]; then
  flutter test test/ --concurrency=4
fi
for d in packages/*/; do
  if [ -d "${d}test" ] && find "${d}test" -name '*_test.dart' | head -1 | grep -q .; then
    (cd "$d" && flutter test test/ --concurrency=4)
  fi
done
```

### Setup for the team
```bash
git config core.hooksPath .githooks
```
Add to README under "Getting Started". One command per dev, once.

### Hook pitfalls
- Do NOT use `flutter pub get --quiet` — the --quiet flag does not exist in this version
- Do NOT use `|| true` on tests — it silences failures, defeating the purpose
- Validate bash syntax before committing: `bash -n .githooks/pre-push`
- Using `replace_all` on shell files can merge lines — prefer full Write instead

## Pattern: Path filter per package group in test matrix

### The Problem
A matrix of 5 groups runs all of them, even when only 1 package changed.

### The Solution
Expand the `changes` job with per-group outputs. NOTE: `matrix` context is NOT available in job-level `if:`. Per-group filtering must go inside the test step.

```yaml
changes:
  outputs:
    dart:     ${{ steps.filter.outputs.dart }}
    core:     ${{ steps.filter.outputs.core }}
    features: ${{ steps.filter.outputs.features }}
    # ... other groups
  steps:
    - uses: dorny/paths-filter@v3
      with:
        filters: |
          core:
            - 'lib/**'
            - 'packages/me_core/**'
            - 'analysis_options.yaml'
          features:
            - 'packages/me_job/**'
            - 'analysis_options.yaml'

test:
  # CORRECT: only dart in job-level if (matrix not available here)
  if: needs.changes.outputs.dart == 'true'
  strategy:
    matrix:
      include:
        - group: core
          packages: ". packages/me_core"
          filter: core   # extra field for the case in the step
        - group: features
          packages: "packages/me_job"
          filter: features
  steps:
    - name: Run tests
      run: |
        # Per-group filtering INSIDE the step (only valid place)
        case "${{ matrix.filter }}" in
          core)     CHANGED="${{ needs.changes.outputs.core }}" ;;
          features) CHANGED="${{ needs.changes.outputs.features }}" ;;
        esac
        if [ "$CHANGED" != "true" ]; then
          echo "No changes in ${{ matrix.group }} — skipping"
          exit 0
        fi
        # ... run tests
```

### Critical pitfall: matrix context in job-level if
`matrix.group` in a job-level `if:` causes "workflow file issue" — GitHub Actions
does not expose the matrix context at that evaluation point. Neither `if: |` nor `if: >-`
solve this. Per-group filtering MUST be done inside the step.

### Update the test-gate
When all groups are skipped, the result is `skipped` not `success`:
```yaml
if [ "${{ needs.test.result }}" = "success" ] || [ "${{ needs.test.result }}" = "skipped" ]
```

### Include analysis_options.yaml in all groups
A change to analysis_options.yaml affects all packages — include it as a trigger in every group.

## Cost reduction: macOS runners

| Runner | Relative cost | Xcode 26 support |
|---|---|---|
| macos-13 (Intel) | ~50% of macos-latest | NO (max Xcode 15) |
| macos-14 (Apple Silicon) | ~same as macos-latest | Yes |
| macos-15 (Apple Silicon) | ~same as macos-latest | Yes |
| macos-latest | baseline | Yes (but changes!) |

**Recommendation:** use `macos-15` instead of `macos-latest` for iOS builds.
- Same cost, but predictable (does not change silently)
- Supports Xcode 26+

## Speed gains

- `--concurrency=4` on `flutter test` -> -30% time per package
- Parallel pub get with `&` and `wait` -> -40% dependency setup time
- Path filter per group -> skips 4 of 5 groups on focused PRs -> -80% test cost

## Golden Rule

> Remote CI = last line of defense.
> Local hook = first line. Free and instant.
> Never let CI be the only barrier.
