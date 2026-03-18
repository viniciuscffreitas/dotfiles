---
name: devflow-learned-golden-test-ci
description: Golden test setup for CI — tag exclusion and required imports
trigger: When creating golden tests (Alchemist or similar) or adding @Tags annotation to Dart test files
---

# Golden Tests in CI — Two Required Steps

## Problem 1: @Tags needs flutter_test import

`@Tags(['golden'])` is defined in the `test` package (re-exported by `flutter_test`). When used as a library-level annotation before `library;`, the file MUST import `flutter_test`:

```dart
@Tags(<String>['golden'])
library;

import 'package:flutter_test/flutter_test.dart'; // REQUIRED for @Tags
import 'package:alchemist/alchemist.dart';
```

Without this import, `flutter analyze` fails with:
```
error • Undefined name 'Tags' used as an annotation • undefined_annotation
```

This is non-obvious because `alchemist` uses `goldenTest()` which internally uses flutter_test, but doesn't re-export `Tags`.

## Problem 2: Exclude golden tests from CI

Golden tests (Alchemist, golden_toolkit) produce platform-specific pixel rendering. Images generated on macOS won't match Ubuntu CI runners, even with the Ahem font.

**Solution:** Tag + exclude pattern:

1. Tag every golden test file with `@Tags(<String>['golden'])`
2. Register the tag in `dart_test.yaml` at the package root:
   ```yaml
   tags:
     golden:
       description: "Golden image tests — run locally only (platform-dependent rendering)"
   ```
3. CI test command uses `--exclude-tags=golden`:
   ```bash
   flutter test test/ --exclude-tags=golden
   ```

## Checklist for new golden tests

- [ ] `@Tags(<String>['golden'])` + `library;` at top of file
- [ ] `import 'package:flutter_test/flutter_test.dart';`
- [ ] `dart_test.yaml` exists in the package with `golden` tag registered
- [ ] CI workflow passes `--exclude-tags=golden` to `flutter test`
