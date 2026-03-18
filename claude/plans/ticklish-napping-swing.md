# Plano: SSE Real-Time para Telas Admin

## Contexto
O SSE já funciona para mudanças de status de OS. A meta é estender o mesmo padrão para 6 entidades admin (clientes, pets, tosadores, tipos de serviço, raças, usuários) para que as listas se atualizem automaticamente em tempo real sem botão de refresh.

## Abordagem
- **Backend**: Adicionar `sseEmitterService.sendToAll()` via `TransactionSynchronizationManager.afterCommit()` em cada service (mesmo padrão do `TechnicalOsService`)
- **Frontend**: Adicionar listeners no `SseService` e roteamento centralizado no `AppShell` via `ref.listen → ref.invalidate`

---

## Fase 1 — Backend (`cisnebranco-bt`)

**Branch**: `feature/sse-entity-broadcasts` from develop

### Helper privado a adicionar em cada service:
```java
private void broadcastEvent(String eventName, String action, Long id) {
    TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
        @Override
        public void afterCommit() {
            try {
                sseEmitterService.sendToAll(eventName, Map.of("action", action, "id", id));
            } catch (Exception e) {
                log.warn("Failed to broadcast SSE event '{}' for id {}", eventName, id, e);
            }
        }
    });
}
```

### Imports a adicionar em cada service:
```java
import lombok.extern.slf4j.Slf4j;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import java.util.Map;
```

### Mudanças por service:

| Service | Adicionar campo | Adicionar @Slf4j | Eventos |
|---|---|---|---|
| `ClientService` | `private final SseEmitterService sseEmitterService;` | Sim | `client-changed` em create/update/delete |
| `PetService` | idem | Sim | `pet-changed` em create/update/deactivate |
| `GroomerService` | idem | Sim | `groomer-changed` em create/update/deactivate |
| `ServiceTypeService` | idem | Sim | `service-type-changed` em create/update/deactivate |
| `BreedService` | idem | Sim | `breed-changed` em create/update/delete |
| `UserService` | idem | Sim | `user-changed` em create/deactivate |

### Gotchas importantes:
1. **`create()` que usa resultado do save inline** (`return mapper.toResponse(repo.save(entity))`): separar em 2 linhas para capturar o id gerado antes do broadcast
2. **`delete()`**: capturar `Long entityId = entity.getId()` antes de `repo.delete(entity)`
3. **`deactivate()`**: capturar id antes de `setActive(false)`

### Arquivos a modificar:
- `src/main/java/com/cisnebranco/service/ClientService.java`
- `src/main/java/com/cisnebranco/service/PetService.java`
- `src/main/java/com/cisnebranco/service/GroomerService.java`
- `src/main/java/com/cisnebranco/service/ServiceTypeService.java`
- `src/main/java/com/cisnebranco/service/BreedService.java`
- `src/main/java/com/cisnebranco/service/UserService.java`

**Referência canônica**: `TechnicalOsService.java` linhas 150-165

---

## Fase 2 — Frontend (`cisnebranco_web`)

**Branch**: `feature/sse-admin-invalidation` from develop

### 2.1 `lib/core/sse/sse_service.dart`
Adicionar 6 listeners (mesmo padrão do `os-status-changed`), cada um emitindo ao `_controller` com campo `type`:

```dart
_eventSource!.addEventListener(
  'client-changed',
  ((web.MessageEvent event) {
    final eventData = event.data;
    if (eventData != null) {
      try {
        final jsonStr = (eventData as JSString).toDart;
        final data = jsonDecode(jsonStr) as Map<String, dynamic>;
        _controller.add({'type': 'client-changed', 'action': data['action'], 'id': data['id']});
      } catch (e) {}
    }
  }).toJS,
);
```
Repetir para: `pet-changed`, `groomer-changed`, `service-type-changed`, `breed-changed`, `user-changed`.

### 2.2 `lib/core/widgets/app_shell.dart`
**a)** Adicionar `ref.listen` no início do método `build` (após `currentPath`):

```dart
ref.listen(osNotificationsProvider, (_, next) {
  next.whenData((event) {
    final type = event['type'] as String?;
    switch (type) {
      case 'client-changed':
        ref.invalidate(clientsListProvider);
      case 'pet-changed':
        ref.invalidate(petsListProvider);
      case 'groomer-changed':
        ref.invalidate(groomersListProvider);
      case 'service-type-changed':
        ref.invalidate(serviceTypesListProvider);
      case 'breed-changed':
        ref.invalidate(breedsListProvider);
      case 'user-changed':
        ref.invalidate(usersListProvider);
      case 'reconnect':
        final config = _listScreenConfigs[currentPath];
        if (config != null) ref.invalidate(config.provider);
    }
  });
});
```

**b)** Remover `onRefresh` de `_listActions` + remover `IconButton(Icons.refresh)` do retorno + atualizar o call site em `_actionsForPath`.

**c)** Adicionar imports que faltarem para os providers.

### Arquivos a modificar:
- `lib/core/sse/sse_service.dart`
- `lib/core/widgets/app_shell.dart`

---

## Ordem de deploy
1. Backend primeiro (eventos emitidos, frontend ignora os novos — sem regressão)
2. Frontend depois (passa a ouvir os novos eventos)

## Verificação
- Criar um cliente em tab A → lista em tab B atualiza automaticamente sem refresh
- Criar um pet → lista de pets atualiza
- Desativar tosador → lista de tosadores atualiza
- Derrubar rede 5s e reconectar → lista da tela atual re-fetcha
- `flutter analyze` sem warnings/errors antes de cada PR
