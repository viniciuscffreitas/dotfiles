# Flutter BLoC: void -> Future<void> in Cubits Propagates discarded_futures to Call Sites

## When to use

Whenever changing a Cubit/BLoC method signature from `void` to `Future<void>`.
Especially methods called inside `BlocListener`, `BlocConsumer`, or any
synchronous Flutter widget callback.

## The Problem

Changing `void nextStep()` to `Future<void> nextStep() async` in the cubit is correct and safe.
But all call sites in synchronous contexts (BLoC listeners, button callbacks)
now return a Future that is silently discarded, causing `discarded_futures`:

```dart
// BEFORE — void, no problem
listener: (context, state) {
  cubit.nextStep(); // ok
}

// AFTER — Future<void>, lint breaks
listener: (context, state) {
  cubit.nextStep(); // ❌ discarded_futures
}
```

## The Solution: unawaited() at UI call sites

```dart
import 'dart:async'; // required for unawaited()

listener: (context, state) {
  unawaited(cubit.nextStep()); // ✅ explicitly marks fire-and-forget intent
}
```

### Why unawaited() and not await?

- `BlocListener` and widget callbacks are **synchronous** — they cannot use `await`
- `unawaited()` signals to the analyzer that the discard is **intentional**
- The real await (the one that matters) lives **inside the cubit**, not in the UI
- The UI doesn't need to wait — it reacts to the state emitted by the cubit

### Why not `async` on the callback?

```dart
// WRONG — does not work in BlocListener
listener: (context, state) async {
  await cubit.nextStep(); // cubit emits state BEFORE listener finishes → race condition
}
```

## Checklist when changing void -> Future<void> in a cubit

- [ ] Grep all call sites: `grep -r "\.nextStep\(\)\|\.skipStep\(\)" packages/ lib/`
- [ ] For each call site, check the context:
  - **Asynchronous** context (another cubit, use case): can use `await`
  - **Synchronous** context (BlocListener, onPressed, callback): use `unawaited()`
- [ ] Add `import 'dart:async';` in every file that uses `unawaited()`
- [ ] Run `flutter analyze` on the entire project — must return **"No issues found!"**

## Pitfall: the agent sees "pre-existing warnings" and ignores them

If `flutter analyze` shows warnings in views AFTER the change, **they are NOT pre-existing**.
They are new, caused by the signature change. Verify with:

```bash
# Before committing, confirm zero issues
flutter analyze; echo "Exit: $?"
# Must print "No issues found!" and "Exit: 0"
```

## Real-world example (MOM-71, mom-ease)

Change in the cubit:
```dart
// profile_setup_coordinator_cubit.dart
Future<void> nextStep() async { // was: void nextStep()
  await _logAnalyticsEvent(...); // await ensures flush before navigating
  emit(state.copyWith(status: ProfileSetupStatus.completed));
}
```

Call sites that needed unawaited():
- `background_check_step_view.dart:43`
- `family_details_step_view.dart:26`
- `personal_info_step_view.dart:24`
- `service_offerings_step_view.dart:28`
- `service_preferences_step_view.dart:25`
