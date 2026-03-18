# Plan: Convert Header/FAB Buttons to Form Dialogs

## Context
All header "Novo X" buttons and the edit icons currently navigate to separate pages (`context.go(newPath)`). The user wants these to open dialogs instead, following the same pattern as `showCheckinDialog`. This applies to: Clientes, Pets, Tipos de Serviço, Tosadores, Raças, Usuários, and the edit buttons on `/clients/:id` and `/pets/:id` detail screens. Mobile FABs must also use dialogs.

## Architecture Decision
**DRY via form body extraction**: Each form screen is refactored into:
1. A reusable `XxxFormBody extends ConsumerStatefulWidget` (the actual logic)
2. A thin `XxxFormScreen` Scaffold wrapper (unchanged externally)
3. A `showXxxFormDialog(context, {...})` top-level function

A new shared `form_dialog_shell.dart` provides the responsive dialog container, matching the checkin dialog's visual pattern (navy header, white body, bottom sheet on mobile).

All routes remain intact for direct URL access — only the button behavior changes.

---

## Files to Create

### `lib/core/widgets/form_dialog_shell.dart`
Shared responsive dialog shell used by all form dialogs:
- **Desktop**: centered `Material` widget, border radius 16, constrained (maxWidth: 520, maxHeight: 600)
- **Mobile**: bottom-anchored panel, drag handle, 92% height
- **Header**: 52px, navy `#0F1B4C`, title (white, 15px medium) + close `×` IconButton (44×44 WCAG)
- **Content**: `Expanded` scroll area below header
- API: `showFormDialog<T>({ required BuildContext context, required String title, required WidgetBuilder builder, double maxWidth = 520, double maxHeight = 600, String barrierLabel = 'Fechar' })`

---

## Files to Modify

### 1. `lib/features/clients/presentation/client_form_screen.dart`
**Refactor:**
- Extract `_ClientFormScreenState` into `ClientFormBody extends ConsumerStatefulWidget`:
  - Params: `int? clientId`, `void Function(Map<String, dynamic>) onSuccess`
  - On success in `_submit`: call `onSuccess(result)` — no navigation, no snackbar
  - On error: `showErrorSnackBar(context, ...)` directly (unchanged)
  - `build`: same form fields but WITHOUT the outer Card/padding (those stay in the screen wrapper)
- `ClientFormScreen` becomes a thin `ConsumerWidget` → `Scaffold(body: SingleChildScrollView(padding: ..., child: Card(child: ClientFormBody(clientId: ..., onSuccess: (r) { showSuccessSnackBar; context.go; }))))`
- Add `showClientFormDialog(BuildContext context, {int? clientId})`:
  - Captures `ScaffoldMessenger` + `GoRouter` before dialog
  - `result = await showFormDialog<Map>(context: ctx, title: clientId != null ? 'Editar Cliente' : 'Novo Cliente', builder: (dCtx) => ClientFormBody(clientId: clientId, onSuccess: (r) => Navigator.of(dCtx).pop(r)))`
  - If result != null: snackbar + `router.go('/clients/${result['id']}')`

### 2. `lib/features/pets/presentation/pet_form_screen.dart`
Same pattern as clients:
- Extract `PetFormBody(petId, initialClientId, onSuccess)` — includes the client autocomplete + breed filtering logic
- `PetFormScreen` wraps in Scaffold + Card
- `showPetFormDialog(context, {int? petId, int? initialClientId})` → on success navigate to `/pets/${result['id']}`

### 3. `lib/features/admin/service_types/presentation/service_type_form_screen.dart`
- Extract `ServiceTypeFormBody(serviceTypeId, onSuccess)`
- `ServiceTypeFormScreen` wraps in Scaffold + Card
- `showServiceTypeFormDialog(context, {int? serviceTypeId})` → on success: snackbar only (already on list screen, SSE handles refresh)

### 4. `lib/features/admin/groomers/presentation/groomer_form_screen.dart`
- Extract `GroomerFormBody(groomerId, onSuccess)`
- `GroomerFormScreen` wraps in Scaffold + Card
- `showGroomerFormDialog(context, {int? groomerId})` → on success: snackbar only

### 5. `lib/features/admin/breeds/presentation/breed_form_screen.dart`
- Extract `BreedFormBody(breedId, onSuccess)`
- `BreedFormScreen` wraps in Scaffold + Card
- `showBreedFormDialog(context, {int? breedId})` → on success: snackbar only

### 6. `lib/features/admin/users/presentation/user_form_screen.dart`
- Extract `UserFormBody(onSuccess)` (no edit mode)
- `UserFormScreen` wraps in Scaffold + Card
- `showUserFormDialog(BuildContext context)` → on success: snackbar only

### 7. `lib/core/widgets/app_shell.dart`
**Changes:**
1. Import all 6 new dialog functions
2. Add `void Function(BuildContext)? showNew` field to `_ListScreenConfig` (remove `const` from constructor)
3. Populate `_listScreenConfigs` with `showNew` callbacks:
   - `'/clients'` → `showNew: showClientFormDialog`
   - `'/pets'` → `showNew: showPetFormDialog`
   - `'/admin/service-types'` → `showNew: showServiceTypeFormDialog`
   - `'/admin/groomers'` → `showNew: showGroomerFormDialog`
   - `'/admin/breeds'` → `showNew: showBreedFormDialog`
   - `'/admin/users'` → `showNew: showUserFormDialog`
4. Update `_listActions`: `onPressed: () => listConfig.showNew?.call(context) ?? context.go(listConfig.newPath)`
5. Update `_fabForPath` signature to `(VoidCallback, String)? _fabForPath(BuildContext context, String path)` returning a callback
6. Update `_buildMobileLayout`: pass `context` to `_fabForPath(context, currentPath)`, use `fabConfig.$1` as `onPressed` directly
7. Update `_actionsForPath` for edit buttons (detail screens):
   - `/clients/:id` → `showClientFormDialog(context, clientId: int.parse(id))`
   - `/pets/:id` → `showPetFormDialog(context, petId: int.parse(id))`

---

## Dialog Shell Design System Details

Following `checkin_dialog.dart` exactly:
```dart
// Desktop shell
Center(
  child: Material(
    color: Colors.white,
    borderRadius: BorderRadius.circular(16),
    clipBehavior: Clip.antiAlias,
    child: ConstrainedBox(
      constraints: BoxConstraints(maxWidth: maxWidth, maxHeight: maxHeight),
      child: Column(children: [_header, Expanded(child: child)]),
    ),
  ),
)

// Mobile shell
SafeArea(
  child: Align(
    alignment: Alignment.bottomCenter,
    child: Material(
      color: Colors.white,
      borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      child: SizedBox(
        width: double.infinity, height: screenHeight * 0.92,
        child: Column(children: [dragHandle, _header, Expanded(child: child)]),
      ),
    ),
  ),
)
```

Header widget:
```dart
Container(
  height: 52,
  color: const Color(0xFF0F1B4C),  // AppTheme.primaryColor
  padding: const EdgeInsets.symmetric(horizontal: 8),
  child: Row(children: [
    SizedBox(width: 44), // balance the close button
    Expanded(child: Text(title, style: white 15sp medium, textAlign: center)),
    IconButton(
      icon: Icon(Icons.close, color: white, size: 20),
      onPressed: () => Navigator.of(context).pop(),
      tooltip: 'Fechar',
      constraints: BoxConstraints(minWidth: 44, minHeight: 44),
    ),
  ]),
)
```

WCAG compliance: white on navy = ~13:1 contrast ratio ✓, 44×44 touch targets ✓, Semantics labels ✓

---

## Form Body Layout (inside dialog)

The `XxxFormBody` renders without Card wrapper (the dialog IS the container):
```dart
SingleChildScrollView(
  padding: const EdgeInsets.fromLTRB(20, 20, 20, 0),
  child: Form(
    child: Column(children: [
      // form fields via ResponsiveForm
      const SizedBox(height: 24),
    ]),
  ),
)
```

Submit button rendered in a sticky footer:
```dart
Padding(
  padding: const EdgeInsets.all(20),
  child: SizedBox(
    width: double.infinity,
    child: ElevatedButton(onPressed: _submit, child: Text(...)),
  ),
)
```

The `XxxFormBody.build` returns a Column with `[Expanded(scroll area), footer]`.

---

## Key Routes Preserved (unchanged)
- `/clients/new` → `ClientFormScreen(clientId: null)`
- `/clients/:id/edit` → `ClientFormScreen(clientId: id)`
- `/pets/new`, `/pets/:id/edit`
- `/admin/*/new`, `/admin/*/:id`

Routes still work for direct URL access. Only button triggers change.

---

## Verification
1. Click "Novo Cliente" on `/clients` header → dialog opens, fill form, submit → dialog closes, snackbar, navigate to client detail
2. Click edit pencil on `/clients/:id` → dialog with pre-filled data → update → dialog closes, snackbar, stay on detail
3. Mobile FAB on `/clients` → same dialog as step 1
4. Admin forms (`/admin/service-types`) → dialog, submit, snackbar, no navigation
5. Existing routes `/clients/new` still render as full-page form (not broken)
