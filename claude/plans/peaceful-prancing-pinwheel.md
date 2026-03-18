# Track B: Remover checkIfBlocked redundante em ProfileDetailsCubit.startChat()

## Context

Como parte do MOM-125 (eliminar cold start nas funções críticas), identificamos que `ProfileDetailsCubit.startChat()` chama `checkIfBlocked` uma segunda vez desnecessariamente. Quando `startChat()` é chamado, o cubit já está em `ProfileDetailsLoadedState` — estado que só é emitido após `loadProfile()` completar com sucesso, o que inclui rodar `checkIfBlocked` (linha 146). A segunda chamada é código morto que gera uma invocação extra à Cloud Function sem nenhum benefício.

**O backend (Track A) já foi implementado e deployado no staging (PR #92).**

## Arquivo a modificar

`packages/me_profile/lib/src/presentation/cubits/details/profile_details_cubit.dart`

## Mudança exata

Remover o bloco abaixo de dentro de `startChat()` (linhas ~244-258):

```dart
// Check if the user is blocked before starting chat
try {
  final bool isBlocked =
      await _checkBlockStatusUseCase(currentState.profile.id);

  if (isBlocked) {
    const String errorMessage =
        'Cannot start a chat. You and this user have blocked each other '
        'or one of you has blocked the other.';
    emit(currentState.copyWith(chatError: errorMessage));
    return;
  }
} on BlockingException catch (e) {
  emit(currentState.copyWith(chatError: e.message));
  return;
}
```

Verificar se `BlockingException` é usada em outro lugar do arquivo. Se não for, verificar se o import de `me_blocking` fica com warning de unused.

## Execução

1. Criar worktree em `../mom-ease-mom-125` a partir de `origin/develop`
   - Branch: `viniciusfreitas/mom-125-perf-eliminate-cloud-function-cold-start-on-critical-user`
2. Remover o bloco try/catch
3. Verificar imports órfãos
4. `dart format . --set-exit-if-changed` no package
5. `flutter analyze` no package — 0 warnings
6. `flutter test` no package — todos passam
7. Commit + rebase em `origin/develop`
8. Push + abrir PR para `develop`

## Verificação

- `flutter analyze` → 0 warnings
- `flutter test` em `packages/me_profile` → todos passam
- Revisar o diff: apenas o bloco try/catch removido, nada mais
