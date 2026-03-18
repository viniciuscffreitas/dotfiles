# Plan: Native T&C Screen (MOM-20)

## Context
The Terms of Use screen currently loads a remote Webflow page via `MEWebView`. To achieve the Figma design (native layout with Decline/Agree buttons, app logo, and scrollable content), the screen needs to be rewritten in Flutter with hardcoded T&C content. This also allows full styling control and avoids WebView quirks. Trade-off: content changes require an app update.

## Critical Files
- **Modify:** `packages/me_profile/lib/src/presentation/screens/terms_of_use_screen.dart`
- **No routing changes needed** — same routes, same `showAcceptButton` param

## Design (from Figma node 11766:13825)
- App logo (MELogo or existing asset) centered at top
- Title: "Agree on our Terms and Conditions & Privacy Policy" (GFS Didot / `context.meTextTheme?.h3`)
- Scrollable T&C content (Work Sans Light / `context.meTextTheme?.bodyMedium`)
- Bottom: two buttons side by side — `OutlinedButton("Decline")` + `FilledButton("Agree")`
- Background: `#F9F3F0` (Sand Light = `context.meColorScheme?.sandLight`)

## Implementation

### Layout structure
```
Scaffold(
  backgroundColor: sandLight,
  body: SafeArea(
    Column(
      children: [
        // Logo centered
        Padding(top: 20) → MELogo (48px)

        // Scrollable content
        Expanded(
          ListView(
            padding: horizontal 24, vertical 16,
            children: [
              Text(title, style: h3 or h4),
              SizedBox(16),
              _TermsContent(),  // all T&C sections as Text widgets
            ]
          )
        )

        // Buttons (only when showAcceptButton=true)
        Padding(16) → Row(
          children: [
            Expanded(OutlinedButton("Decline")),
            SizedBox(12),
            Expanded(FilledButton("Agree")),
          ]
        )
      ]
    )
  )
)
```

### Profile/settings mode (showAcceptButton=false)
- Same layout but no buttons row
- Add `MEBrandAppBar` (back button)

### Decline behavior
- Show `showDialog` with `AlertDialog`:
  - Title: "Are you sure?"
  - Content: "You need to accept the Terms to use Mom Ease."
  - Actions: `TextButton("Cancel")` + `TextButton("Decline anyway")` → `context.go('/login')` on confirm

### T&C Content
Hardcode the content in a private `_TermsContent` widget (or const list of sections) within the same file. Content = existing T&C clauses + the new "Behavior Tracking & Analytics" clause (MOM-20) + the lawyer's clause (Section 19) from Jenna.

Each section:
```dart
Text(sectionTitle, style: bodyMediumBold),
SizedBox(8),
Text(sectionBody, style: bodyMedium),
SizedBox(16),
```

### Analytics
Preserve existing `time_to_terms_view` tracking (already in the screen, keep as-is).

## Verification
1. Run `flutter analyze` — must have 0 warnings
2. Run app on staging with `--flavor staging --dart-define-from-file=.env.staging`
3. Test signup flow: email verified → T&C screen loads natively → Decline shows dialog → Agree goes to onboarding
4. Test profile route: Settings → Terms of Use → read-only native screen with back button
