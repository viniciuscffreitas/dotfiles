# Plano: Web Panel 100% Real-Time

## Contexto

O web panel atual escreve no banco mas o plugin Java usa cache em memória agressivo (PlayerData, ClanManager, PunishmentManager). Mudanças feitas pelo painel **não refletem em tempo real** para jogadores online, e muitas features do plugin **não estão expostas** no painel. O objetivo é: (1) comunicação bidirecional Web↔Jogo via Redis Streams, (2) cobrir 100% das features do plugin.

## Arquitetura

```
Web Panel (Vercel)
    │
    ├── DB write (Prisma) ──→ PostgreSQL
    │
    └── XADD "admin-commands" ──→ Upstash Redis ──→ Plugin CommandDispatcher
                                                         │
                                                         ├── RELOAD_PLAYER → PlayerManager.reload(uuid)
                                                         ├── KICK_PLAYER → player.kickPlayer()
                                                         ├── FREEZE/UNFREEZE → PunishmentListener
                                                         ├── RELOAD_CLAN → ClanManager.reloadClan()
                                                         ├── RELOAD_PUNISHMENTS → PunishmentManager.loadPlayer()
                                                         ├── FORCE_MINE_RESET → MineManager.resetAll()
                                                         ├── START/STOP_EVENT → EventManager
                                                         ├── RELOAD_CONFIG → ConfigManager.applyOverride()
                                                         ├── RELOAD_SEASON → SeasonManager.reload()
                                                         ├── UPDATE_SUBSCRIPTION → PlayerData.reloadSub()
                                                         └── BROADCAST → Bukkit.broadcastMessage()
```

---

## Phase 1 — CommandDispatcher (Plugin) [5 files]

Infraestrutura bidirecional. Prerequisito para tudo.

### Novos arquivos
- `module-bridge/.../bridge/dispatch/CommandDispatcher.java` — daemon thread, `XREAD` no stream `admin-commands`, dispatch para handlers registrados, execução no main thread via `runTask()`
- `module-bridge/.../bridge/dispatch/CommandHandler.java` — interface funcional `void execute(String jsonPayload)`

### Modificações
- `module-bridge/.../bridge/BridgeModule.java` — instanciar CommandDispatcher, iniciar thread, parar no onDisable
- `module-bridge/.../bridge/UpstashClient.java` — aumentar thread pool de 2 para 3 (acomodar 2 leitores + escritor)

### Teste
- `module-bridge/src/test/.../dispatch/CommandDispatcherTest.java`

---

## Phase 2 — Command Handlers (Plugin) [~15 files]

Handlers para cada comando. Todos em `module-bridge/.../bridge/dispatch/handlers/`.

| Handler | Comando | Ação no plugin |
|---------|---------|----------------|
| `ReloadPlayerHandler` | `RELOAD_PLAYER` | Re-query DB, atualizar PlayerData em cache |
| `KickPlayerHandler` | `KICK_PLAYER` | `player.kickPlayer(reason)` |
| `FreezePlayerHandler` | `FREEZE_PLAYER` | `punishmentListener.freezePlayer(uuid)` |
| `UnfreezePlayerHandler` | `UNFREEZE_PLAYER` | `punishmentListener.unfreezePlayer(uuid)` |
| `ReloadClanHandler` | `RELOAD_CLAN` | Re-query clan do DB, atualizar maps |
| `ReloadAllClansHandler` | `RELOAD_ALL_CLANS` | `clanManager.loadAll()` |
| `ReloadPunishmentsHandler` | `RELOAD_PUNISHMENTS` | `punishmentManager.loadPlayer(uuid)` |
| `ForceMineResetHandler` | `FORCE_MINE_RESET` | `mineManager.resetAllMines()` |
| `StartEventHandler` | `START_EVENT` | `eventManager.startEvent(type)` |
| `StopEventHandler` | `STOP_EVENT` | `eventManager.stopEvent()` |
| `ReloadConfigHandler` | `RELOAD_CONFIG` | Load all config_overrides do DB, aplicar overrides |
| `BroadcastHandler` | `BROADCAST` | `Bukkit.broadcastMessage()` |
| `ReloadSeasonHandler` | `RELOAD_SEASON` | `seasonManager.loadActiveSeason()` |
| `UpdateSubscriptionHandler` | `UPDATE_SUBSCRIPTION` | Re-query subscription do DB, atualizar PlayerData |

### Modificações necessárias em módulos existentes
- `PunishmentModule.java` — adicionar getter `getPunishmentListener()`
- `ClanManager.java` — adicionar `reloadClan(int clanId)` que re-query e atualiza maps
- `BridgeModule.java` — registrar todos handlers

---

## Phase 3 — Fix Config Overrides (Plugin) [1 file]

**Arquivo:** `core/.../config/ConfigManager.java`

Converter ~35 getters estáticos para usar `getIntOverridable()`/`getDoubleOverridable()`:

```java
// Antes:
public int getCombatTagSeconds() { return combatTagSeconds; }
// Depois:
public int getCombatTagSeconds() { return getIntOverridable("combat.combat-tag-seconds", combatTagSeconds); }
```

Getters a converter: combat (8), economy (3), factions (10), season (4), mine (1), ranking (5), events (4) = **35 getters**.

---

## Phase 4 — Web Panel: Command Publishing [8 files]

### Novo arquivo
- `web/src/lib/admin-commands.ts` — helper `publishCommand(command, payload)` que faz `redis.xadd("admin-commands", ...)`

### Modificações — adicionar `publishCommand()` após cada mutação:

| Arquivo | Ação | Comando publicado |
|---------|------|-------------------|
| `players/actions.ts` | `updatePlayer` | `RELOAD_PLAYER {uuid}` |
| `punishments/actions.ts` | `createPunishment(BAN)` | `KICK_PLAYER` + `RELOAD_PUNISHMENTS` |
| `punishments/actions.ts` | `createPunishment(KICK)` | `KICK_PLAYER {uuid, reason}` |
| `punishments/actions.ts` | `pardonPunishment` | `RELOAD_PUNISHMENTS {uuid}` |
| `clans/actions.ts` | `updateClan` | `RELOAD_CLAN {clanId}` |
| `clans/actions.ts` | `removeClanMember` | `RELOAD_CLAN {clanId}` |
| `clans/actions.ts` | `deleteClan` | `RELOAD_ALL_CLANS` |
| `events/actions.ts` | `startEvent` | `START_EVENT {type}` |
| `events/actions.ts` | `endEvent` | `STOP_EVENT` |
| `seasons/actions.ts` | `startSeason/endSeason` | `RELOAD_SEASON` |
| `subscriptions/actions.ts` | `create/extend/cancel/reactivate` | `UPDATE_SUBSCRIPTION {uuid}` |
| `config/actions.ts` | `updateConfig` | `RELOAD_CONFIG` (além do stream existente) |

---

## Phase 5 — Novas Features do Web Panel [~25 files]

### 5a. Economy — Operações de escrita [4 files]
- `economy/actions.ts` — **NOVO**: `creditPlayer()`, `debitPlayer()`, `cancelAuctionListing()`
- `economy/credit-debit-dialog.tsx` — **NOVO**: dialog para creditar/debitar com motivo
- `economy/auction-listings.tsx` — **NOVO**: tabela de listings com botão cancelar
- `economy/page.tsx` — **MODIFICAR**: adicionar dialog e listings

### 5b. Clans — Gestão avançada [5 files]
- `clans/create-clan-dialog.tsx` — **NOVO**: criar clan (name, tag, leader uuid)
- `clans/actions.ts` — **MODIFICAR**: `createClan()`, `promoteMember()`, `demoteMember()`, `transferLeadership()`
- `clans/[id]/clan-member-actions.tsx` — **MODIFICAR**: botões promover/demover
- `clans/[id]/page.tsx` — **MODIFICAR**: seção de claims expandida
- `clans/page.tsx` — **MODIFICAR**: botão criar clan

### 5c. Players — Ações em tempo real [4 files]
- `players/[uuid]/player-actions.tsx` — **NOVO**: kick, freeze/unfreeze buttons
- `players/[uuid]/inventory-snapshots.tsx` — **NOVO**: listar snapshots do `inventory_snapshots` table
- `players/[uuid]/page.tsx` — **MODIFICAR**: adicionar ações e snapshots
- `players/actions.ts` — **MODIFICAR**: `kickPlayer()`, `freezePlayer()`, `unfreezePlayer()`

### 5d. Mine [3 files]
- `mine/page.tsx` — **NOVO**: botão force reset, info de regiões
- `mine/actions.ts` — **NOVO**: `forceMineReset()`
- Nav item no sidebar

### 5e. Anticheat [2 files]
- `anticheat/page.tsx` — **NOVO**: query staff_log para flags AC, agrupar por player
- Nav item no sidebar

### 5f. Broadcast [3 files]
- `broadcast/page.tsx` — **NOVO**: form para enviar mensagem global
- `broadcast/actions.ts` — **NOVO**: `broadcast(message)`
- Nav item no sidebar

### 5g. Config expandido [2 files]
- `config/actions.ts` — **MODIFICAR**: adicionar ~20 chaves faltantes (ranking, events, season, combat extras)
- `config/page.tsx` — **MODIFICAR**: novas seções (Ranking, Events, Season)

### 5h. Season & Events enhancements [3 files]
- `seasons/actions.ts` — **MODIFICAR**: `toggleSOTW()`, `manageNovice()`
- `seasons/page.tsx` — **MODIFICAR**: SOTW toggle, novice management
- `events/page.tsx` — **MODIFICAR**: section de missões

### 5i. Nav items [1 file]
- `components/admin/nav-items.ts` — **MODIFICAR**: adicionar Mine, Anticheat, Broadcast

---

## Ordem de Deploy

1. **Phases 1-3** (Plugin): Build e deploy juntos → restart servidor
2. **Phase 4** (Web): Deploy após plugin estar rodando com CommandDispatcher
3. **Phases 5a-5i** (Web): Independentes entre si, deploy incrementalmente

---

## Verificação

### Plugin (Phases 1-3)
1. `./gradlew build` — compilar sem erros
2. Deploy no servidor, verificar logs: `[Bridge] CommandDispatcher started`
3. Testar manualmente: inserir comando no Redis Stream via web, verificar execução in-game

### Web (Phases 4-5)
1. `npx next build` — compilar sem erros
2. Testar cada ação no painel:
   - Editar stats de jogador online → verificar que reflete in-game imediatamente
   - Criar ban → jogador kickado automaticamente
   - Alterar config → verificar que novo valor é usado pelo plugin
   - Force mine reset → mine reseta in-game
3. Verificar staff_log para audit trail de todas as ações
