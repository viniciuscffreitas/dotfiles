# Plano: Interface Dedicada para Tosadora (Groomer Mobile Experience)

## Contexto

A tosadora (Ana Cristina) usa o sistema pelo tablet/celular. Hoje ela vê o mesmo kanban do admin, com todas as OS misturadas, sem filtro, sem fluxo de inspeção. Precisamos de uma interface dedicada, focada em produtividade e segurança jurídica, com fluxo linear: **Ver fila → Inspecionar → Trabalhar → Finalizar**.

## Descobertas Importantes

O **backend já está quase completo**:
- `POST /os/{id}/photos` (upload multipart) + `GET /os/{id}/photos`
- `POST /os/{id}/checklist` + `GET /os/{id}/checklist`
- `PATCH /os/{id}/status` (valida: READY exige 3+ fotos + checklist)
- `GET /os` retorna `TechnicalOsGroomerViewResponse` para GROOMER (filtrado por groomerId automaticamente)
- `GET /os/{id}` retorna view filtrada para GROOMER
- SSE `/sse/notifications` com eventos `os-status-changed`

**2 lacunas no backend:**
1. `PetGroomerViewResponse` NÃO tem `clientFirstName` (precisa adicionar)
2. Fotos são salvas em disco (`./uploads/photos/{osId}/`) mas não há endpoint/config para servir os arquivos

**Frontend:** Nenhuma tela groomer-específica existe. Precisa criar tudo.

## Fluxo da Tosadora

```
WAITING OS (fila) → [Toca no card]
  → Tela de Inspeção:
    1. Capturar 3+ fotos (geral, pele, patas/orelhas)
    2. Preencher health checklist (pulgas, carrapatos, feridas, etc.)
    3. Confirmar → status vira IN_PROGRESS
  → Tela de Execução:
    - Timer contando desde startedAt
    - Serviços sendo executados
    - Campo de observações
    - Botão "Finalizar" → status vira READY → pet some da lista
```

---

## Parte 1: Backend (repo cisnebranco-bt, branch `feature/groomer-mobile-support`)

### 1a. Adicionar `clientFirstName` ao `PetGroomerViewResponse`

**Arquivo:** `src/main/java/com/cisnebranco/dto/response/PetGroomerViewResponse.java`
- Adicionar campo `String clientFirstName`

**Arquivo:** `src/main/java/com/cisnebranco/mapper/PetMapper.java`
- Adicionar mapping: `@Mapping(target = "clientFirstName", expression = "java(pet.getClient() != null ? pet.getClient().getName().split(\" \")[0] : null)")`

### 1b. Endpoint para servir fotos

**Novo arquivo:** `src/main/java/com/cisnebranco/controller/PhotoController.java`
- `GET /photos/{osId}/{filename}` - serve o arquivo de `{photoDir}/{osId}/{filename}`
- Valida que o path não escapa do diretório (path traversal protection)
- Retorna `Content-Type` baseado na extensão (jpeg/png/webp)
- Acesso público (fotos não contêm dados sensíveis, e o UUID no filename previne adivinhação)

### 1c. Alterar `InspectionPhotoResponse` para retornar URL em vez de path absoluto

**Arquivo:** `src/main/java/com/cisnebranco/service/InspectionPhotoService.java`
- No `toResponse()`, converter `filePath` de path absoluto para URL relativa: `/photos/{osId}/{filename}`
- Exemplo: `/app/uploads/photos/42/uuid_pic.jpg` → `/api/photos/42/uuid_pic.jpg`

### 1d. Remover dados de comissão da view do groomer

**Novo arquivo:** `src/main/java/com/cisnebranco/dto/response/OsServiceItemGroomerResponse.java`
- Campos: `Long id`, `String serviceTypeName`, `BigDecimal lockedPrice`
- (sem `lockedCommissionRate`, sem `commissionValue`)

**Arquivo:** `src/main/java/com/cisnebranco/dto/response/TechnicalOsGroomerViewResponse.java`
- Remover campo `totalCommission`
- Mudar tipo de `serviceItems` de `List<OsServiceItemResponse>` para `List<OsServiceItemGroomerResponse>`

**Arquivo:** `src/main/java/com/cisnebranco/mapper/TechnicalOsMapper.java`
- Adicionar mapping para `OsServiceItemGroomerResponse`

---

## Parte 2: Frontend (repo cisnebranco_web, branch `feature/groomer-mobile-ui`)

### 2a. Dependência

**Arquivo:** `pubspec.yaml`
- Adicionar `image_picker: ^1.1.2` (para captura de fotos via browser/câmera)

### 2b. Repository Layer - Novos Métodos

**Arquivo:** `lib/features/os/data/os_repository.dart`

Adicionar ao `OsRepository`:
```dart
Future<Map<String, dynamic>> uploadPhoto(int osId, Uint8List bytes, String filename, {String? caption})
Future<List<dynamic>> getPhotos(int osId)
Future<Map<String, dynamic>> saveChecklist(int osId, Map<String, dynamic> data)
Future<Map<String, dynamic>?> getChecklist(int osId)
```

Adicionar providers:
```dart
@riverpod osPhotos(Ref ref, int osId)
@riverpod osChecklist(Ref ref, int osId)
```

Rodar `dart run build_runner build` para regenerar `.g.dart`.

### 2c. Tela Home: "Meus Atendimentos"

**Novo arquivo:** `lib/features/groomer/presentation/groomer_home_screen.dart`

- `ConsumerStatefulWidget` com SSE listener para auto-refresh
- Busca OS do groomer via `osListProvider(groomerId: myGroomerId)` (backend já filtra)
- Divide em 2 seções: "Em Andamento" (IN_PROGRESS, destacado no topo) + "Fila de Espera" (WAITING)
- `RefreshIndicator` para pull-to-refresh
- Cards grandes com touch target 55x55px mínimo

**Novo arquivo:** `lib/features/groomer/presentation/widgets/groomer_os_card.dart`

Card mostra:
- Nome do pet (grande, bold)
- Raça + Porte
- Primeiro nome do cliente
- Serviços (ex: "Banho + Tosa")
- Tempo na fila (relativo: "15min", "1h")
- Botão de ação: "Inspecionar" (WAITING) ou "Continuar" (IN_PROGRESS)

### 2d. Tela de Inspeção (3 passos)

**Novo arquivo:** `lib/features/groomer/presentation/groomer_inspection_screen.dart`

`ConsumerStatefulWidget` com `PageView` + indicador de 3 passos:

**Passo 1 - Fotos:**
- 3 slots grandes (Geral, Pele/Pelagem, Patas/Orelhas)
- Cada slot: toque → `ImagePicker.pickImage(source: ImageSource.camera)` (no web: abre câmera ou file chooser)
- Upload imediato via `osRepository.uploadPhoto()`
- Mostra thumbnail local (bytes) + indicador de upload
- Botão "Próximo" habilitado quando 3+ fotos capturadas

**Passo 2 - Health Checklist:**
- Toggles grandes (SwitchListTile): Pulgas, Carrapatos, Feridas
- Campos de texto: Condição da Pele, Pelagem, Orelhas, Unhas, Observações
- Salva via `osRepository.saveChecklist()`
- Botão "Próximo"

**Passo 3 - Confirmação:**
- Resumo: info do pet, thumbnails das fotos, checklist preenchido
- Botão grande: "Iniciar Atendimento"
- Ao tocar: `osRepository.updateStatus(osId, 'IN_PROGRESS')` → navega para execução

### 2e. Tela de Execução (IN_PROGRESS)

**Novo arquivo:** `lib/features/groomer/presentation/groomer_execution_screen.dart`

- Nome do pet (grande), raça, porte
- Lista de serviços
- **Timer**: `Stream.periodic(1s)` calculando diferença desde `startedAt`
  - Formato: `MM:SS` ou `HH:MM:SS`
  - Texto sutil: "estimado: Xmin" (do `defaultDurationMinutes` se disponível nos serviceItems)
- Campo de observações técnicas
- Botão grande "Finalizar"
  - Dialog de confirmação (usa `showConfirmationDialog` existente)
  - `osRepository.updateStatus(osId, 'READY')`
  - Volta para home, pet some da lista

**Novo arquivo:** `lib/features/groomer/presentation/widgets/elapsed_timer.dart`
- Widget reutilizável de timer elapsed

### 2f. Navegação - Modificações

**Arquivo:** `lib/core/router/app_router.dart`

Novas rotas no ShellRoute:
```dart
GoRoute(path: '/groomer', ...)           // GroomerHomeScreen
GoRoute(path: '/groomer/inspect/:id', ...) // GroomerInspectionScreen
GoRoute(path: '/groomer/exec/:id', ...)    // GroomerExecutionScreen
```

Redirect: GROOMER logado vai para `/groomer` em vez de `/`.
Guard: GROOMER tentando acessar `/`, `/os`, `/checkin`, etc. → redireciona para `/groomer`.

**Arquivo:** `lib/core/widgets/app_shell.dart`

Quando `role == 'GROOMER'`:
- **Bottom nav mobile**: Apenas 1 item "Atendimentos" (ou sem bottom nav, só header)
- **Drawer**: Apenas logout (sem Clientes, Pets, Admin)
- **NavigationRail** (tablet): Apenas "Atendimentos"
- **Títulos**: `/groomer` → "Meus Atendimentos", `/groomer/inspect/*` → "Inspeção", `/groomer/exec/*` → "Atendimento"
- **Header actions**: Refresh em `/groomer`

---

## Ordem de Implementação

1. **Backend PR** (`feature/groomer-mobile-support` → develop → main)
   - 1a: clientFirstName no DTO
   - 1b: PhotoController para servir fotos
   - 1c: URL no InspectionPhotoResponse
   - 1d: Remover comissão da groomer view
   - Deploy para produção

2. **Frontend PR** (`feature/groomer-mobile-ui` → develop → main)
   - 2a: Dependência image_picker
   - 2b: Repository methods + providers
   - 2c: Groomer home screen + card widget
   - 2f: Navegação (router + app_shell) — junto com home para testar
   - 2d: Inspection flow (fotos + checklist)
   - 2e: Execution screen (timer + finalizar)
   - Deploy para produção

---

## Verificação

1. **Backend**: Subir local, testar com curl/Swagger:
   - `GET /os` como GROOMER → resposta tem `clientFirstName`, sem `totalCommission`
   - `POST /os/{id}/photos` → upload funciona
   - `GET /photos/{osId}/{filename}` → foto é servida
   - `POST /os/{id}/checklist` → salva checklist
   - `PATCH /os/{id}/status` com `IN_PROGRESS` → OK
   - `PATCH /os/{id}/status` com `READY` sem fotos → erro 400

2. **Frontend**: Testar no browser com viewport de tablet (768x1024):
   - Login como GROOMER → vai para `/groomer`
   - Vê lista de OS WAITING + IN_PROGRESS
   - Toca em WAITING OS → vai para inspeção
   - Captura 3 fotos → próximo → preenche checklist → próximo → confirma
   - Status muda para IN_PROGRESS, vai para tela de execução
   - Timer roda, toca "Finalizar" → confirma → READY
   - Pet some da lista home
   - SSE: outra aba muda status → tela do groomer atualiza

---

## Fora de Escopo (v2)

- Suporte offline (Drift + BatchSync)
- Push notifications (além do SSE que já existe)
- Confirmação de categoria de serviço na finalização
- Confirmação de preço com PricingMatrix na inspeção
- Edição de fotos/cropping
- Notas técnicas salvas automaticamente (autosave)
