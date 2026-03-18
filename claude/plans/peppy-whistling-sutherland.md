# Fix PR #387 & #388 Review Issues

## Context
PR review identified issues in two related PRs fixing profile photo bugs. PR #387 fixes data-layer enrichment overwriting valid `profile_photo_url` with null/empty. PR #388 fixes UI-layer empty imageUrl creating failing network requests. Both PRs are on branches off `develop` in `moonshot-partners/mom-ease`. Changes will be pushed directly to those branches.

## Files to Modify

### 1. `packages/me_firebase/lib/src/data/data_sources/enriched_care_provider_remote_data_source.dart`

**A. Replace `addAll()` with safe merge at all 3 enrichment sites (lines 127, 133, 312, 318, 382, 388)**

Instead of the field-specific save/restore pattern from the PR, use a structural fix — a private `_mergePreservingValues` helper that never overwrites non-null/non-empty values with null/empty:

```dart
/// Merges [source] into [target], skipping null or empty-string values
/// when [target] already has a non-null, non-empty value for that key.
void _mergePreservingValues(
  Map<String, dynamic> target,
  Map<String, dynamic> source,
) {
  for (final MapEntry<String, dynamic> entry in source.entries) {
    final Object? existing = target[entry.key];
    final Object? incoming = entry.value;
    if (existing != null &&
        existing is String &&
        existing.isNotEmpty &&
        (incoming == null || (incoming is String && incoming.isEmpty))) {
      continue;
    }
    target[entry.key] = incoming;
  }
}
```

Replace all 6 `enrichedProfile.addAll(...)` calls at the 3 enrichment sites with `_mergePreservingValues(enrichedProfile, ...)`.

**B. Fix silent catch blocks — add logging and return partial results (lines 792-794, 843-845, 893-895)**

```dart
// _fetchUsersByIds (line 792):
} on Exception catch (e) {
  debugPrint('[error] _fetchUsersByIds failed for ${userIds.length} users: $e');
}

// _fetchUserProfilesByIds (line 843):
} on Exception catch (e) {
  debugPrint('[error] _fetchUserProfilesByIds failed for ${userIds.length} users: $e');
  return userProfilesMap; // Return partial results, not empty map
}

// _fetchCareProviderProfilesByUserIds (line 893):
} on Exception catch (e) {
  debugPrint('[error] _fetchCareProviderProfilesByUserIds failed for ${userIds.length} users: $e');
  return careProviderMap; // Return partial results, not empty map
}
```

**C. Fix `_getCurrentUserProfile` silent catch (line 714)**

```dart
} on Exception catch (e) {
  debugPrint('[error] _getCurrentUserProfile failed for $userId: $e');
  return null;
}
```

### 2. `packages/me_design_system/lib/src/presentation/components/atoms/me_profile_picture.dart`

**Add `.trim()` to the empty check (line 54):**

```dart
if (imageUrl != null && imageUrl!.trim().isNotEmpty) {
```

### 3. `packages/me_firebase/test/data/data_sources/enriched_care_provider_remote_data_source_test.dart`

**Add test group for `_mergePreservingValues` behavior through the enrichment pipeline:**

- Test: preserves `profile_photo_url` when `users` collection has null
- Test: preserves `profile_photo_url` when `care_provider_profiles` has null
- Test: keeps null when no collection has it
- Test: allows valid URL from later collection to overwrite original
- Test: preserves value when overwritten with empty string

### 4. `packages/me_design_system/test/presentation/components/atoms/me_profile_picture_test.dart`

**Add whitespace-only test:**

- Test: shows initials when imageUrl is whitespace-only `"   "`

## Execution Plan

1. Clone both PR branches locally
2. Apply changes to PR #387 branch (`fix/preserve-profile-photo-url-in-enrichment`)
3. Apply changes to PR #388 branch (`fix/handle-empty-image-url-in-profile-picture`)
4. Run `flutter analyze` on both packages
5. Run tests on both packages
6. Push to both branches

## Verification

```bash
cd packages/me_firebase && flutter test
cd packages/me_design_system && flutter test
flutter analyze
```
