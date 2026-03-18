# Plano: Offline-First ADR-002 — Cisne Branco Flutter Web

## Contexto
ADR-002 exige Drift (SQLite) + padrão Outbox para operação 100% offline.
Atualmente: zero pacotes de persistência local — `drift` ausente do `pubspec.yaml`.
Plataforma confirmada: **Flutter Web** (browser no tablet). Usar `drift_flutter` que gerencia
IndexedDB/WASM automaticamente sem configuração manual do WASM.

---

## 1. Pacotes a Adicionar (`pubspec.yaml`)

```yaml
dependencies:
  drift: ^2.22.0
  drift_flutter: ^0.2.0          # Web + native automático via driftDatabase()
  connectivity_plus: ^6.1.0      # Detecção de rede (browser Network API)
  sqlite3: ^2.4.6                # Bindings Dart para SQLite

dev_dependencies:
  drift_dev: ^2.22.0             # Gerador de código Drift
  # build_runner já existe
```

---

## 2. Arquitetura Geral

```
Screens/Widgets (sem mudança)
         │ ref.watch/read
Riverpod Providers (atualizados para apontar para camada offline)
         │
OfflineFirstOsRepository  ←────────────────────────────────┐
  │ reads: Drift DB first → fallback API se vazio           │
  │ writes: Drift DB + OutboxQueue                          │
  │                                                         │
  ├── AppDatabase (Drift)      OutboxSyncService ───────────┘
  │     • OsCacheTable               │ dispara quando:
  │     • OutboxQueueTable           │  - SSE reconnect event
  │     • ReferenceTable(s)          │  - connectivity_plus: online
  │                                  │
  └── OsRepository (Dio)    ←── processa fila → DELETE item ao confirmar
       (existente, sem mudança)
```

---

## 3. Schema Drift — Tabelas

### 3a. `OsCacheTable` — Cache das Ordens de Serviço
```dart
// lib/core/database/tables/os_cache_table.dart
class OsCacheTable extends Table {
  IntColumn  get id            => integer()();
  TextColumn get status        => text()();           // 'WAITING' | 'IN_PROGRESS' | ...
  IntColumn  get groomerId     => integer().nullable()();
  TextColumn get petJson       => text()();           // JSON: {id, name, breedName, size, clientFirstName}
  TextColumn get serviceItemsJson => text()();        // JSON array: [{id, serviceTypeName, lockedPrice}]
  RealColumn get totalPrice    => real().nullable()();
  RealColumn get totalCommission => real().nullable()();
  TextColumn get notes         => text().nullable()();
  DateTimeColumn get createdAt   => dateTime()();
  DateTimeColumn get startedAt   => dateTime().nullable()();
  DateTimeColumn get finishedAt  => dateTime().nullable()();
  DateTimeColumn get deliveredAt => dateTime().nullable()();
  DateTimeColumn get cachedAt    => dateTime()();     // Quando foi salvo localmente
  BoolColumn get isDirty         => boolean().withDefault(const Constant(false))();

  @override Set<Column> get primaryKey => {id};
}
```

### 3b. `OutboxQueueTable` — Fila de Mutações Pendentes
```dart
// lib/core/database/tables/outbox_queue_table.dart
class OutboxQueueTable extends Table {
  IntColumn  get id            => integer().autoIncrement()();
  TextColumn get operation     => text()();   // enum OutboxOp (ver seção 4)
  IntColumn  get osId          => integer().nullable()();
  IntColumn  get serviceItemId => integer().nullable()(); // adjustPrice
  IntColumn  get paymentEventId => integer().nullable()(); // refund
  TextColumn get payloadJson   => text()();               // JSON do body HTTP
  BlobColumn get binaryData    => blob().nullable()();    // bytes foto
  TextColumn get filename      => text().nullable()();
  TextColumn get caption       => text().nullable()();
  DateTimeColumn get createdAt => dateTime()();           // timestamp do tablet
  IntColumn  get attempts      => integer().withDefault(const Constant(0))();
  TextColumn get lastError     => text().nullable()();
  // Itens são deletados após sucesso — sem coluna status
}
```

### 3c. Tabelas de Referência (dados que mudam raramente)
```dart
// lib/core/database/tables/reference_tables.dart

class BreedCacheTable extends Table {
  IntColumn  get id      => integer()();
  TextColumn get name    => text()();
  TextColumn get species => text()(); // 'DOG' | 'CAT'
  @override Set<Column> get primaryKey => {id};
}

class ServiceTypeCacheTable extends Table {
  IntColumn  get id          => integer()();
  TextColumn get name        => text()();
  TextColumn get code        => text().nullable()();
  TextColumn get description => text().nullable()();
  @override Set<Column> get primaryKey => {id};
}

class GroomerCacheTable extends Table {
  IntColumn  get id   => integer()();
  TextColumn get name => text()();
  @override Set<Column> get primaryKey => {id};
}

class PetCacheTable extends Table {
  IntColumn  get id       => integer()();
  IntColumn  get clientId => integer()();
  TextColumn get name     => text()();
  TextColumn get dataJson => text()(); // JSON completo do pet
  @override Set<Column> get primaryKey => {id};
}

class ClientCacheTable extends Table {
  IntColumn  get id      => integer()();
  TextColumn get name    => text()();
  TextColumn get phone   => text().nullable()();
  DateTimeColumn get cachedAt => dateTime()();
  @override Set<Column> get primaryKey => {id};
}

class BreedPricingCacheTable extends Table {
  IntColumn  get breedId       => integer()();
  IntColumn  get serviceTypeId => integer()();
  RealColumn get price         => real()();
  IntColumn  get durationMinutes => integer().nullable()();
  TextColumn get serviceTypeName => text()();
  TextColumn get serviceTypeCode => text().nullable()();
  @override Set<Column> get primaryKey => {breedId, serviceTypeId};
}
```

---

## 4. OutboxOp — Enum de Operações

```dart
// lib/core/sync/outbox_op.dart
enum OutboxOp {
  updateStatus,       // PATCH /os/{id}/status         payload: {status}
  uploadPhoto,        // POST  /os/{id}/photos          binary + filename + caption
  saveChecklist,      // POST  /os/{id}/checklist       payload: checklist JSON
  adjustPrice,        // PATCH /os/{osId}/services/{itemId}/price  payload: {adjustedPrice}
  checkIn,            // POST  /os/check-in             payload: check-in body
  addPayment,         // POST  /os/{id}/payments        payload: payment body
  refundPayment,      // POST  /os/{id}/payments/{eventId}/refund
  assignGroomer,      // PATCH /os/{id}/groomer         payload: {groomerId}
  createClient,       // POST  /clients
  updateClient,       // PUT   /clients/{id}
  deleteClient,       // DELETE /clients/{id}
  createPet,          // POST  /pets
  updatePet,          // PUT   /pets/{id}
  deletePet,          // DELETE /pets/{id}
}
```

---

## 5. Arquivos a Criar (novos)

```
lib/core/database/
  app_database.dart                  ← @DriftDatabase + conexão web
  tables/
    os_cache_table.dart
    outbox_queue_table.dart
    reference_tables.dart
  dao/
    os_dao.dart                      ← upsertOs, getOsByStatus, getOsById
    outbox_dao.dart                  ← enqueue, peek, delete, incrementAttempts
    reference_dao.dart               ← upsert/get breeds, services, groomers, pets, clients

lib/core/sync/
  outbox_op.dart                     ← enum OutboxOp
  outbox_sync_service.dart           ← processQueue(), _dispatch(item)
  connectivity_notifier.dart         ← StreamProvider<bool> via connectivity_plus

lib/features/os/data/
  offline_first_os_repository.dart   ← wraps OsRepository + AppDatabase
```

---

## 6. Arquivos a Modificar (existentes)

| Arquivo | O que muda |
|---------|-----------|
| `pubspec.yaml` | +drift, +drift_flutter, +connectivity_plus, +sqlite3, +drift_dev |
| `lib/main.dart` | Inicializar AppDatabase; adicionar databaseProvider |
| `lib/core/widgets/app_shell.dart` | Conectar reconnect SSE → OutboxSyncService.processQueue() |
| `lib/features/os/data/os_repository.dart` | Riverpod providers apontam para OfflineFirstOsRepository |
| `lib/features/checkin/data/checkin_providers.dart` | clientSearch e breedPrices leem do cache local |

---

## 7. AppDatabase — Definição Principal

```dart
// lib/core/database/app_database.dart
import 'package:drift/drift.dart';
import 'package:drift_flutter/drift_flutter.dart';
import 'tables/os_cache_table.dart';
import 'tables/outbox_queue_table.dart';
import 'tables/reference_tables.dart';
import 'dao/os_dao.dart';
import 'dao/outbox_dao.dart';
import 'dao/reference_dao.dart';

part 'app_database.g.dart';

@DriftDatabase(
  tables: [
    OsCacheTable, OutboxQueueTable,
    BreedCacheTable, ServiceTypeCacheTable, GroomerCacheTable,
    PetCacheTable, ClientCacheTable, BreedPricingCacheTable,
  ],
  daos: [OsDao, OutboxDao, ReferenceDao],
)
class AppDatabase extends _$AppDatabase {
  AppDatabase() : super(driftDatabase(name: 'cisne_branco_db'));
  // driftDatabase() de drift_flutter: usa IndexedDB no Web, SQLite no nativo

  @override int get schemaVersion => 1;
}

// Provider Riverpod
@riverpod
AppDatabase appDatabase(Ref ref) {
  final db = AppDatabase();
  ref.onDispose(() => db.close());
  return db;
}
```

---

## 8. OfflineFirstOsRepository — Camada Central

```dart
// lib/features/os/data/offline_first_os_repository.dart
class OfflineFirstOsRepository {
  final OsRepository _remote;   // Dio (existente)
  final AppDatabase _db;

  // READ: local DB → fallback remoto se vazio
  Future<Map<String, dynamic>> findById(int id) async {
    final cached = await _db.osDao.getById(id);
    if (cached != null) return cached.toMap();
    final remote = await _remote.findById(id);
    await _db.osDao.upsert(remote); // hidrata o cache
    return remote;
  }

  // READ: local DB always (sem fallback — lista vem do cache hidratado)
  Future<Map<String, dynamic>> findAll({...}) async {
    final cached = await _db.osDao.getByStatus(status);
    if (cached.isNotEmpty) return _toPage(cached);
    final remote = await _remote.findAll(...);
    await _db.osDao.upsertAll(remote['content']);
    return remote;
  }

  // WRITE: local first + enqueue outbox
  Future<Map<String, dynamic>> updateStatus(int id, String status) async {
    await _db.osDao.updateStatus(id, status); // otimista local
    await _db.outboxDao.enqueue(OutboxQueueTableCompanion(
      operation: Value(OutboxOp.updateStatus.name),
      osId: Value(id),
      payloadJson: Value(jsonEncode({'status': status})),
      createdAt: Value(DateTime.now()),
    ));
    return {'id': id, 'status': status}; // retorno otimista
  }

  // WRITE foto: enqueue com bytes
  Future<Map<String, dynamic>> uploadPhoto(int osId, Uint8List bytes,
      String filename, {String? caption}) async {
    await _db.outboxDao.enqueue(OutboxQueueTableCompanion(
      operation: Value(OutboxOp.uploadPhoto.name),
      osId: Value(osId),
      payloadJson: Value(jsonEncode({'caption': caption})),
      binaryData: Value(bytes),
      filename: Value(filename),
      caption: Value(caption),
      createdAt: Value(DateTime.now()),
    ));
    // Retorna placeholder para UI continuar
    return {'id': -1, 'caption': caption, 'url': null, '_pending': true};
  }
  // ... saveChecklist, adjustServiceItemPrice, checkIn seguem o mesmo padrão
}
```

---

## 9. OutboxSyncService — Processamento da Fila

```dart
// lib/core/sync/outbox_sync_service.dart
class OutboxSyncService {
  final AppDatabase _db;
  final OsRepository _remote; // Dio direto

  Future<void> processQueue() async {
    final items = await _db.outboxDao.getPending();
    for (final item in items) {
      try {
        await _dispatch(item);
        await _db.outboxDao.delete(item.id); // sucesso → remove
      } on DioException catch (e) {
        if (e.response?.statusCode == 409) {
          // Conflito → timestamp do tablet vence: reenviar com header
          await _retryWithTimestamp(item);
        } else if (e.response?.statusCode != null &&
                   e.response!.statusCode! >= 400 &&
                   e.response!.statusCode! < 500) {
          await _db.outboxDao.delete(item.id); // 4xx → descarta (bad request)
        } else {
          await _db.outboxDao.incrementAttempts(item.id, e.message);
        }
      }
    }
  }

  Future<void> _dispatch(OutboxQueueTableData item) async {
    final op = OutboxOp.values.byName(item.operation);
    final payload = item.payloadJson.isEmpty ? {} : jsonDecode(item.payloadJson);
    // Inclui timestamp do tablet para resolução de conflito (ADR-002)
    final headers = {'X-Tablet-Timestamp': item.createdAt.toIso8601String()};

    switch (op) {
      case OutboxOp.updateStatus:
        await _remote.updateStatus(item.osId!, payload['status'],
            extraHeaders: headers);
      case OutboxOp.uploadPhoto:
        await _remote.uploadPhoto(item.osId!, item.binaryData!,
            item.filename!, caption: item.caption);
      case OutboxOp.saveChecklist:
        await _remote.saveChecklist(item.osId!, payload as Map<String, dynamic>);
      case OutboxOp.adjustPrice:
        await _remote.adjustServiceItemPrice(item.osId!, item.serviceItemId!,
            (payload['adjustedPrice'] as num).toDouble());
      case OutboxOp.checkIn:
        final result = await _remote.checkIn(payload as Map<String, dynamic>);
        await _db.osDao.upsert(result); // hidrata com ID real do servidor
      // ... demais casos
    }
  }
}

@riverpod
OutboxSyncService outboxSyncService(Ref ref) {
  return OutboxSyncService(
    db: ref.watch(appDatabaseProvider),
    remote: ref.watch(osRepositoryProvider),
  );
}
```

---

## 10. ConnectivityNotifier

```dart
// lib/core/sync/connectivity_notifier.dart
@riverpod
Stream<bool> isOnline(Ref ref) {
  return Connectivity().onConnectivityChanged.map(
    (results) => results.any((r) => r != ConnectivityResult.none),
  );
}
```

**Importante**: No Flutter Web, `connectivity_plus` usa a Network Information API do browser,
que nem sempre é precisa. Por isso, o disparo também usa o evento SSE `reconnect`.

---

## 11. Integração no app_shell.dart

```dart
// Adicionar ao listener SSE existente em app_shell.dart:
ref.listen(osNotificationsProvider, (_, next) {
  next.whenData((event) {
    // ... invalidações existentes ...
    if (event['type'] == 'reconnect') {
      // Flushar outbox ao reconectar ao servidor
      ref.read(outboxSyncServiceProvider).processQueue();
    }
  });
});

// Adicionar listener de connectivity:
ref.listen(isOnlineProvider, (previous, next) {
  if (next.valueOrNull == true && previous?.valueOrNull == false) {
    ref.read(outboxSyncServiceProvider).processQueue();
  }
});
```

---

## 12. Hidratação Inicial do Cache (Warmup)

No startup do app (após autenticação), popular o cache:

```dart
// Executar após login bem-sucedido em auth_controller.dart:
Future<void> _warmupLocalCache(Ref ref) async {
  final db = ref.read(appDatabaseProvider);
  final sync = ref.read(outboxSyncServiceProvider);

  // 1. Flush outbox pendente de sessão anterior
  await sync.processQueue();

  // 2. Hidratar referências
  await Future.wait([
    _cacheBreeds(ref, db),
    _cacheServiceTypes(ref, db),
    _cacheGroomers(ref, db),
  ]);

  // 3. OS da tosadora (se role == GROOMER)
  if (groomerId != null) {
    await _cacheOsForGroomer(ref, db, groomerId);
  }
}
```

---

## 13. Providers Atualizados em os_repository.dart

```dart
// Substituir os providers existentes:

@riverpod
OfflineFirstOsRepository offlineFirstOsRepository(Ref ref) {
  return OfflineFirstOsRepository(
    remote: ref.watch(osRepositoryProvider),
    db: ref.watch(appDatabaseProvider),
  );
}

// osDetail agora usa a camada offline-first:
@riverpod
Future<Map<String, dynamic>> osDetail(Ref ref, int id) {
  return ref.watch(offlineFirstOsRepositoryProvider).findById(id);
}

@riverpod
Future<Map<String, dynamic>> osList(Ref ref, {int page = 0, int size = 20,
    String? status, int? groomerId}) {
  return ref.watch(offlineFirstOsRepositoryProvider).findAll(
    page: page, size: size, status: status, groomerId: groomerId,
  );
}
```

Screens e widgets **não precisam de mudança** — lêem `osDetailProvider` e `osListProvider` igual antes.

---

## 14. Ordem de Implementação (Sprints)

### Dia 1–2: Fundação
1. `pubspec.yaml` — adicionar pacotes + rodar `flutter pub get`
2. Criar tabelas Drift (`tables/`)
3. Criar DAOs (`dao/`)
4. Criar `app_database.dart` + provider
5. Rodar `dart run build_runner build` para gerar `*.g.dart`
6. `lib/main.dart` — inicializar AppDatabase

### Dia 3–4: Repositório Offline
7. `offline_first_os_repository.dart` — reads (findAll, findById, getChecklist, getPhotos)
8. `offline_first_os_repository.dart` — writes (updateStatus, uploadPhoto, saveChecklist, adjustPrice)
9. Atualizar providers em `os_repository.dart`
10. Testar fluxo offline da tosadora

### Dia 5–6: Outbox + Sync
11. `outbox_op.dart` — enum
12. `outbox_sync_service.dart` — processQueue + _dispatch para todos OutboxOp
13. `connectivity_notifier.dart`
14. Integrar sync no `app_shell.dart` (SSE reconnect + connectivity)

### Dia 7: Referências + Check-in Offline
15. `reference_dao.dart` — breeds, serviceTypes, groomers, pets, clients
16. `checkin_providers.dart` — usar cache local em clientSearch e breedPrices
17. Hidratação no login (`auth_controller.dart`)

### Dia 8–9: Repositórios Admin + Testes
18. Repos admin (clients, pets, breeds, service-types) com outbox
19. Indicador visual de "pendências offline" no UI (badge no AppShell)
20. Testes manuais: desligar Wi-Fi, completar atendimento, religar, verificar sync

---

## 15. Verificação Pós-Implementação

```
Checklist de validação:
[ ] flutter pub get — sem conflitos de versão
[ ] dart run build_runner build — geração limpa dos *.g.dart
[ ] flutter build web --release — build sem erros
[ ] Modo offline: desligar Wi-Fi no browser, fazer inspeção completa (3 fotos + checklist + preço + iniciar)
[ ] Outbox: verificar tabela outbox_queue_table via DevTools (IndexedDB)
[ ] Reconectar Wi-Fi: OutboxSyncService processa fila e OS aparece no backend
[ ] Conflito: mudar status no tablet offline + admin muda o mesmo OS → tablet timestamp vence
[ ] Referências: breeds/serviceTypes disponíveis offline no check-in
```

---

## Arquivos Críticos de Referência

- `lib/features/os/data/os_repository.dart` — padrão base a ser envolvido
- `lib/core/api/api_client.dart` — Dio singleton compartilhado
- `lib/core/sse/sse_service.dart` — evento `reconnect` dispara sync
- `lib/core/widgets/app_shell.dart` — ponto de integração do sync listener
- `lib/features/auth/application/auth_controller.dart` — ponto de warmup do cache
- `lib/features/checkin/data/checkin_providers.dart` — usa referências offline
- `lib/main.dart` — inicialização do AppDatabase
