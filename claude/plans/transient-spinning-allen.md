# MOM-36: Force Update Dialog on App Launch

## Context

Agora que estamos publicando na App Store e Play Store, usuários em versões antigas podem continuar usando o app indefinidamente. Precisamos de um mecanismo para forçar atualização quando uma versão mínima é definida no Firebase Remote Config.

## Abordagem

**Pragmática** — sem repository/use-case layers. A lógica é simples: `currentVersion < minVersion` → mostra dialog. O fluxo:

```
RemoteConfigService (me_firebase) → ForceUpdateCubit (me_core) → BlocListener (app.dart)
```

## Arquivos

### Novos (4 arquivos)
1. `packages/me_firebase/lib/src/core/remote_config_service.dart` — Singleton, mesmo padrão do `FirebaseService`/`MixpanelService`
2. `packages/me_core/lib/src/presentation/cubits/force_update/force_update_state.dart` — State com `isUpdateRequired`
3. `packages/me_core/lib/src/presentation/cubits/force_update/force_update_cubit.dart` — Cubit com `checkForUpdate()` + semver comparison
4. `packages/me_core/test/src/presentation/cubits/force_update/force_update_cubit_test.dart` — Testes unitários

### Modificados (7 arquivos)
5. `packages/me_firebase/pubspec.yaml` — adicionar `firebase_remote_config`
6. `packages/me_firebase/lib/src/core/core.dart` — export do novo service
7. `packages/me_core/pubspec.yaml` — adicionar `package_info_plus`
8. `packages/me_core/lib/src/presentation/cubits/cubits.dart` — export do cubit
9. `packages/me_core/lib/src/di/core_injection.dart` — registrar `ForceUpdateCubit`
10. `lib/main.dart` — init RemoteConfig + provide cubit + trigger check
11. `lib/app.dart` — BlocListener + ForceUpdateDialog inline

## Implementação passo a passo

### 1. Dependency: `firebase_remote_config` em me_firebase
```yaml
# packages/me_firebase/pubspec.yaml
firebase_remote_config: ^5.3.0
```

### 2. `RemoteConfigService` — singleton igual ao FirebaseService
- `initialize()`: setDefaults (`min_app_version: '0.0.0'`), fetchAndActivate
- `minAppVersion` getter: retorna string ou `'0.0.0'` se não inicializado
- Erros reportados via `reportNonFatalError()`, nunca crasha

### 3. Dependency: `package_info_plus` em me_core
```yaml
# packages/me_core/pubspec.yaml
package_info_plus: ^8.0.0
```

### 4. `ForceUpdateState` — simples
```dart
class ForceUpdateState extends Equatable {
  const ForceUpdateState({this.isUpdateRequired = false});
  final bool isUpdateRequired;
  // copyWith, props
}
```

### 5. `ForceUpdateCubit`
- `checkForUpdate()`: pega versão via `PackageInfo.fromPlatform()`, compara com `RemoteConfigService().minAppVersion`
- `isVersionBelow(current, minimum)`: comparação semver estática, `@visibleForTesting`
- Erros silenciosos (nunca bloqueia o user)

### 6. DI: registrar em `core_injection.dart`
```dart
..registerLazySingleton<ForceUpdateCubit>(ForceUpdateCubit.new)
```

### 7. `main.dart` — 3 mudanças
- Após `MixpanelService.registerMixpanelServices()`: `await RemoteConfigService().initialize()`
- No `MultiBlocProvider`: adicionar `BlocProvider<ForceUpdateCubit>.value(...)`
- No `addPostFrameCallback`: `CoreInjection.getIt<ForceUpdateCubit>().checkForUpdate()`

### 8. `app.dart` — BlocListener + dialog inline
Adicionar na lista de `MultiBlocListener.listeners`:
```dart
BlocListener<ForceUpdateCubit, ForceUpdateState>(
  listener: (context, state) {
    if (state.isUpdateRequired) {
      SchedulerBinding.instance.addPostFrameCallback(
        (_) => _showForceUpdateDialog(),
      );
    }
  },
),
```

Dialog method direto no `MainApp` (sem criar arquivo separado — é um dialog simples):
- `barrierDismissible: false`
- `PopScope(canPop: false)` para bloquear botão voltar no Android
- Botão "Update Now" abre store URL via `url_launcher`
- Store URLs hardcoded: iOS App Store + Play Store (package `com.momeasenow.app`)

### 9. Testes unitários
- `isVersionBelow('0.0.18', '0.0.19')` → true
- `isVersionBelow('0.0.19', '0.0.19')` → false
- `isVersionBelow('0.1.0', '0.0.99')` → false
- `isVersionBelow('1.0.0', '0.99.99')` → false
- Cubit emits `isUpdateRequired: true` quando abaixo do mínimo
- Cubit não emite quando igual ou acima

### 10. Firebase Console (manual)
- Staging + Production: adicionar parâmetro `min_app_version` = `"0.0.0"`
- Para testar: setar `"99.0.0"` e ver dialog aparecer

## Verificação
1. `flutter analyze` — 0 warnings
2. `flutter test packages/me_core/test/` — testes passam
3. Build staging: `flutter run --flavor staging --dart-define-from-file=.env.staging`
4. Setar `min_app_version=99.0.0` no Firebase Console → dialog deve aparecer
5. Setar `min_app_version=0.0.0` → dialog não deve aparecer
