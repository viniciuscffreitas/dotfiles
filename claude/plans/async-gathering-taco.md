# Plano: Transformação Mobile-First do Cisne Branco Flutter App

## Contexto

O aplicativo Flutter web do Cisne Branco foi desenvolvido com foco em desktop (único breakpoint em 1200px), mas será usado **majoritariamente em tablets e celulares** pela equipe do pet shop. Apenas a recepção/admin usará em desktop. O objetivo é **inverter essa prioridade para mobile-first**, reduzir ruído visual, diminuir carga cognitiva, e implementar **CRUD completo** nas telas (atualmente apenas ~12 dos 64 endpoints do backend são usados).

### Problemas Atuais
1. **Navegação não-responsiva:** NavigationRail sempre visível (desperdiça 72-220px em mobile)
2. **Listas não-otimizadas:** DataTable requer scroll horizontal em mobile
3. **Layouts fixos:** Detalhes/forms usam Row que quebra em telas pequenas
4. **CRUD incompleto:** Faltam telas de criar/editar/deletar para Clientes, Pets, Payments, e recursos admin (Service Types, Groomers, Breeds, Users)
5. **Recursos avançados não-implementados:** Fotos de inspeção, checklist de saúde, relatórios, agendamentos

### Estado Atual da Aplicação
- **Stack:** Flutter 3.x, Riverpod 2.6.1 (code generation), GoRouter, Material 3, Google Fonts (Inter)
- **Cor primária:** #1A237E (navy blue)
- **Padrões de estado:** `AsyncValue.when()`, `StateProvider`, `setState()` local em forms
- **Backend:** 64 endpoints REST disponíveis (Spring Boot), apenas 12 usados atualmente

---

## Estratégia de Breakpoints (Mobile-First)

Adotar padrão Material Design com 3 breakpoints:

```dart
// Novo arquivo: /lib/core/theme/breakpoints.dart
- Mobile: 0-600px (phones)
- Tablet: 600-1024px (tablets, iPad)
- Desktop: 1024px+ (desktop, iPad Pro landscape)
```

### Navegação por Dispositivo
- **Mobile (< 600px):** BottomNavigationBar (3 itens primários) + Drawer (secundários/admin)
- **Tablet (600-1024px):** NavigationRail colapsado + Drawer (admin)
- **Desktop (≥ 1024px):** NavigationRail expandido (como atual)

**Itens de navegação:**
- Primários (sempre visíveis): Dashboard, Ordens, Check-in
- Secundários (drawer em mobile/tablet, rail em desktop): Clientes, Pets, Admin (Tosadores, Serviços, Usuários), Logout

---

## Fases de Implementação

### **Fase 1: Fundação Responsiva** (Semana 1, 25-30h) - CRÍTICO

**Objetivo:** Estabelecer infraestrutura responsiva sem quebrar funcionalidade existente.

#### 1.1 Criar Utilitários Responsivos
**Arquivos novos:**
- `/lib/core/theme/breakpoints.dart` - Constants, helpers (isMobile, isTablet, isDesktop), extension no BuildContext
- `/lib/core/widgets/responsive_layout.dart` - Builder que recebe mobile/tablet/desktop builders
- `/lib/core/widgets/adaptive_list.dart` - Widget para listas adaptativas (Card em mobile, ListTile em tablet, DataTable em desktop)
- `/lib/core/widgets/responsive_form.dart` - Layout automático de formulários (Column em mobile, Wrap em tablet/desktop)

#### 1.2 Refatorar AppShell (Crítico)
**Arquivo modificado:** `/lib/core/widgets/app_shell.dart`

**Mudanças:**
1. Substituir `MediaQuery.of(context).size.width > 1200` por `context.isDesktop` (do novo breakpoints.dart)
2. Criar 3 métodos de scaffold:
   - `_buildMobileScaffold()` - BottomNavigationBar + Drawer
   - `_buildTabletScaffold()` - NavigationRail colapsado + Drawer
   - `_buildDesktopScaffold()` - NavigationRail expandido (código atual)
3. Extrair configuração de destinos para lista compartilhada
4. Implementar Drawer widget com itens secundários
5. Implementar BottomNavigationBar para mobile

#### 1.3 Atualizar Tema
**Arquivo modificado:** `/lib/core/theme/app_theme.dart`

Adicionar utilitários de spacing responsivo e ajustar touch targets para mobile (min 48x48px).

#### 1.4 Refatorar Telas Existentes (Responsivas)
**Arquivos modificados:**
- `/lib/features/os/presentation/os_list_screen.dart` - Usar AdaptiveList (Cards em mobile, DataTable em desktop)
- `/lib/features/os/presentation/os_detail_screen.dart` - Column em mobile, Row em desktop
- `/lib/features/clients/presentation/clients_screen.dart` - Usar AdaptiveList
- `/lib/features/dashboard/presentation/dashboard_screen.dart` - Grid responsivo com Wrap
- `/lib/features/checkin/presentation/checkin_screen.dart` - Stepper full-screen em mobile

**Padrão Mobile para Listas (ex: OS List):**
```dart
Card(
  child: InkWell(
    onTap: () => context.go('/os/$id'),
    child: Padding(
      padding: EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(children: [StatusChip(status), Spacer(), Text('#$id')]),
          SizedBox(height: 8),
          Text(petName, style: titleMedium.bold),
          Text(clientName, style: bodyMedium.grey),
          Row(children: [
            Icon(Icons.person_outline),
            Text(groomerName ?? 'Não atribuído'),
            Spacer(),
            Text('R\$ $price', style: titleSmall.bold),
          ]),
        ],
      ),
    ),
  ),
)
```

**Deliverables:**
- App funciona em mobile/tablet/desktop sem quebras
- Navegação adapta-se ao dispositivo
- Listas otimizadas para touch
- Zero breaking changes

---

### **Fase 2: CRUD de Clientes** (Semana 2, 20-25h) - ALTA PRIORIDADE

**Objetivo:** Implementar gestão completa de clientes (usada diariamente pela recepção).

#### Arquivos Novos
1. `/lib/features/clients/presentation/client_detail_screen.dart`
   - Exibe: nome, telefone, email, endereço, lista de pets
   - Ações: Editar, Deletar, Adicionar Pet

2. `/lib/features/clients/presentation/client_form_screen.dart`
   - Modo create/edit (reutilizável)
   - Campos: nome* (required), telefone* (mask), email, endereço
   - Validação: nome não-vazio, telefone formato brasileiro (DDD + número)
   - Layout responsivo (ResponsiveForm widget)

3. `/lib/features/clients/presentation/widgets/client_card.dart`
   - Card mobile-friendly para lista de clientes

#### Modificações em Arquivos Existentes
- `/lib/features/clients/data/clients_repository.dart`
  - Adicionar: `createClient(ClientRequest)`, `updateClient(id, ClientRequest)`, `deleteClient(id)`

- `/lib/features/clients/presentation/clients_screen.dart`
  - Adicionar FAB "Novo Cliente" (mobile) ou botão em AppBar (desktop)
  - Card tap → navegar para `/clients/:id`
  - Long-press (mobile) ou menu (desktop) → Editar/Deletar

- `/lib/core/router/app_router.dart`
  - Adicionar rotas: `/clients/:id` (detail), `/clients/new` (create), `/clients/:id/edit` (edit)

#### Backend Endpoints Usados
- `POST /clients` (create)
- `PUT /clients/{id}` (update)
- `DELETE /clients/{id}` (delete)
- `GET /clients/{id}` (detail - já existe parcialmente)

**Deliverables:**
- Clientes totalmente gerenciáveis
- Formulário responsivo
- Validação de campos
- Feedback de sucesso/erro via SnackBar

---

### **Fase 3: CRUD de Pets** (Semana 3, 20-25h) - ALTA PRIORIDADE

**Objetivo:** Implementar gestão completa de pets (essencial para check-in).

#### Arquivos Novos
1. `/lib/features/pets/data/pets_repository.dart`
   - Métodos: `findAll()`, `findById()`, `findByClient()`, `create()`, `update()`, `delete()`

2. `/lib/features/pets/presentation/pet_list_screen.dart`
   - Lista paginada com filtro por cliente
   - Busca por nome
   - AdaptiveList (cards em mobile)

3. `/lib/features/pets/presentation/pet_detail_screen.dart`
   - Exibe: nome, espécie, raça, porte, cliente, histórico de OS
   - Ações: Editar, Deletar

4. `/lib/features/pets/presentation/pet_form_screen.dart`
   - Campos: nome*, cliente* (autocomplete), espécie* (dropdown), raça* (filtrada por espécie), porte* (dropdown), observações
   - Validação inline
   - ResponsiveForm layout

5. `/lib/features/pets/presentation/widgets/pet_card.dart`

#### Modificações
- `/lib/core/router/app_router.dart`
  - Rotas: `/pets`, `/pets/:id`, `/pets/new`, `/pets/:id/edit`

- AppShell: Adicionar item "Pets" na navegação (todos os usuários, não só ADMIN)

#### Backend Endpoints
- `GET /pets` (list)
- `GET /pets/{id}` (detail)
- `GET /pets/by-client/{clientId}` (filter)
- `POST /pets` (create)
- `PUT /pets/{id}` (update)
- `DELETE /pets/{id}` (delete)

**Deliverables:**
- Pets gerenciáveis de forma independente
- Integração com clientes (autocomplete)
- Raças filtradas por espécie selecionada
- Check-in pode linkar para detalhe do pet

---

### **Fase 4: Gestão de Pagamentos** (Semana 4, 15-20h) - ALTA PRIORIDADE

**Objetivo:** Completar workflow de OS com registro de pagamentos (crítico para fechar OS).

#### Arquivos Novos
1. `/lib/features/os/presentation/widgets/payment_form.dart`
   - Modal (desktop) ou BottomSheet (mobile)
   - Campos: valor* (numeric), método* (PIX, Dinheiro, Cartão, Débito), referência (opcional), observações
   - Validação: valor > 0

2. `/lib/features/os/presentation/widgets/payment_list.dart`
   - Lista de eventos de pagamento na OS detail
   - Exibe: data, valor, método, referência, usuário que registrou
   - Ação ADMIN: Estornar pagamento (confirmation dialog)

#### Modificações
- `/lib/features/os/data/os_repository.dart`
  - Adicionar: `addPayment(osId, PaymentRequest)`, `getPayments(osId)`, `refundPayment(osId, eventId)`

- `/lib/features/os/presentation/os_detail_screen.dart`
  - Nova seção: "Pagamentos" (expandable card)
  - Exibir saldo devedor (totalPrice - payments.sum)
  - Botão: "Registrar Pagamento" (abre modal/bottom sheet)
  - Badge de status de pagamento: Pendente/Pago Parcial/Pago

- `/lib/features/os/presentation/os_list_screen.dart`
  - Adicionar filtro por paymentStatus (opcional)

#### Backend Endpoints
- `POST /os/{osId}/payments` (ADMIN)
- `GET /os/{osId}/payments` (ADMIN)
- `POST /os/{osId}/payments/{eventId}/refund` (ADMIN)

**Deliverables:**
- Pagamentos registrados diretamente na OS
- Saldo calculado automaticamente
- Histórico de pagamentos visível
- Estorno disponível para ADMIN

---

### **Fase 5: Melhorias em OS** (Semana 5, 15-20h) - MÉDIA PRIORIDADE

**Objetivo:** Adicionar recursos avançados de OS (fotos, checklist, edição).

#### Arquivos Novos
1. `/lib/features/os/presentation/widgets/photo_upload.dart`
   - Captura de câmera (mobile) ou upload (desktop)
   - Usar `image_picker` (mobile) e `image_picker_web` (web)
   - Exibir preview antes de enviar

2. `/lib/features/os/presentation/widgets/photo_gallery.dart`
   - Grid de fotos em OS detail
   - Lightbox ao clicar (fullscreen)
   - Caption display

3. `/lib/features/os/presentation/widgets/health_checklist.dart`
   - ExpansionPanel em OS detail
   - Campos: condição da pele, pelagem, pulgas, carrapatos, feridas, orelhas, unhas, observações
   - Salvar ao mudar (auto-save)

4. `/lib/features/os/presentation/os_form_screen.dart`
   - Editar OS: alterar tosador, adicionar/remover serviços, notas
   - Validação

#### Modificações
- `/lib/features/os/data/os_repository.dart`
  - Adicionar: `uploadPhoto(osId, file, caption)`, `getPhotos(osId)`, `updateChecklist(osId, checklist)`, `getChecklist(osId)`, `updateOs(osId, request)`

- `/lib/features/os/presentation/os_detail_screen.dart`
  - Seção "Fotos de Inspeção" (expandable)
  - Seção "Checklist de Saúde" (expandable)
  - Botão "Editar OS" (AppBar action)

#### Backend Endpoints
- `POST /os/{id}/photos` (upload)
- `GET /os/{id}/photos` (list)
- `POST /os/{id}/checklist` (create/update)
- `GET /os/{id}/checklist` (get)
- `PUT /os/{id}` (update OS - se existir, ou usar PATCH status/groomer)

#### Dependências Novas
```yaml
dependencies:
  image_picker: ^1.0.7
  image_picker_web: ^3.1.2
```

**Deliverables:**
- Fotos anexadas à OS
- Checklist preenchido antes de finalizar
- OS editável (tosador, serviços, notas)

---

### **Fase 6: Admin CRUD** (Semana 6, 20-25h) - MÉDIA PRIORIDADE

**Objetivo:** Painel admin completo (Service Types, Groomers, Breeds, Users).

#### Estrutura de Diretórios
```
/lib/features/admin/
├── service_types/
│   ├── data/service_types_repository.dart
│   └── presentation/
│       ├── service_types_screen.dart
│       └── service_type_form_screen.dart
├── groomers/
│   ├── data/groomers_repository.dart
│   └── presentation/
│       ├── groomers_screen.dart
│       └── groomer_form_screen.dart
├── breeds/
│   ├── data/breeds_repository.dart
│   └── presentation/
│       ├── breeds_screen.dart
│       └── breed_form_screen.dart
└── users/
    ├── data/users_repository.dart
    └── presentation/
        ├── users_screen.dart
        └── user_form_screen.dart
```

#### Funcionalidades por Entidade
1. **Service Types (Tipos de Serviço):**
   - List, Create, Edit, Deactivate
   - Campos: código, nome, taxa de comissão, duração padrão (minutos)
   - Validação: taxa 0-100%, duração > 0

2. **Groomers (Tosadores):**
   - List, Create, Edit, Deactivate
   - Campos: nome, telefone
   - Status ativo/inativo

3. **Breeds (Raças):**
   - List, Create, Edit, Delete
   - Campos: nome, espécie (Dog/Cat)
   - Filtro por espécie

4. **Users (Usuários):**
   - List, Create, Deactivate
   - Campos: username, password (apenas create), role (ADMIN/GROOMER), groomerId (se GROOMER)
   - **Sem edição de senha** (por segurança)

#### Modificações
- AppShell: Adicionar seção "Admin" (expandable) com 4 sub-itens (Service Types, Groomers, Breeds, Users)
- Router: 12 novas rotas (list + form para cada entidade)
- **Role guard:** Todas as rotas admin requerem `role == ADMIN`

#### Backend Endpoints (todos ADMIN)
- Service Types: GET, POST, PUT, DELETE `/service-types`
- Groomers: GET, POST, PUT, DELETE `/groomers`
- Breeds: GET, POST, PUT, DELETE `/breeds`
- Users: GET, POST, DELETE `/users`

**Deliverables:**
- Painel admin funcional
- CRUD completo para todas as entidades administrativas
- Guards de role implementados

---

### **Fase 7: Recursos Avançados** (Semana 7+, 30-40h) - BAIXA PRIORIDADE (Futuro)

**Objetivo:** Agendamentos, relatórios, comissões (nice-to-have).

#### Funcionalidades
1. **Appointments (Agendamentos):**
   - Tela de calendário (usar `table_calendar` package)
   - Create, Edit, Cancel appointments
   - Converter appointment → OS (check-in direto)
   - Slots disponíveis por tosador

2. **Reports (Relatórios):**
   - Dashboard com gráficos (revenue, performance)
   - Exportar CSV/PDF
   - Filtros por data, tosador, serviço

3. **Commissions (Comissões):**
   - Visualizar comissões por tosador
   - Filtro semanal/mensal
   - GROOMER vê apenas próprias comissões, ADMIN vê todas

**Nota:** Esta fase fica fora do escopo inicial (foco em mobile + CRUD essencial).

---

## Widgets Reutilizáveis a Criar

### Core Widgets
1. **StatusChip** (extrair de `os_list_screen.dart:175`) - `/lib/core/widgets/status_chip.dart`
2. **EmptyState** - `/lib/core/widgets/empty_state.dart` (ícone + mensagem + botão ação)
3. **ErrorCard** - `/lib/core/widgets/error_card.dart` (card vermelho com retry)
4. **LoadingIndicator** - `/lib/core/widgets/loading_indicator.dart` (centralizado ou inline)
5. **ConfirmationDialog** - `/lib/core/widgets/confirmation_dialog.dart` (delete, cancel ações)
6. **InfoRow** (extrair de `os_detail_screen.dart`) - `/lib/core/widgets/info_row.dart`
7. **StatCard** (extrair de `dashboard_screen.dart`) - `/lib/core/widgets/stat_card.dart`
8. **ActionCard** (extrair de `dashboard_screen.dart`) - `/lib/core/widgets/action_card.dart`

---

## Redução de Carga Cognitiva

### Princípios Aplicados
1. **Navegação simplificada:** 3 itens primários visíveis, secundários no drawer
2. **Progressive disclosure:** Campos opcionais em ExpansionPanel, seções colapsáveis
3. **Hierarquia visual clara:**
   - Títulos grandes (headlineMedium)
   - Conteúdo médio (bodyMedium)
   - Captions pequenos (labelSmall)
4. **Ações consistentes:**
   - FAB para ação primária (mobile)
   - AppBar actions para secundárias
   - Long-press para menu contextual
5. **Feedback imediato:**
   - SnackBar para sucesso (verde, 3s auto-dismiss)
   - SnackBar para erro (vermelho, persiste com retry)
   - Confirmation dialogs para ações destrutivas

### Touch Targets
- Minimum 48x48px em mobile
- Padding generoso (16-20px em cards)
- Espaçamento entre elementos (mín 8px)

---

## Arquivos Críticos (Ordem de Modificação)

1. **`/lib/core/theme/breakpoints.dart`** (NOVO) - Fundação responsiva, usado em todo codebase
2. **`/lib/core/widgets/app_shell.dart`** - Hub de navegação, afeta todas as telas
3. **`/lib/core/widgets/adaptive_list.dart`** (NOVO) - Padrão de lista usado em OS, Clientes, Pets, Admin
4. **`/lib/features/os/presentation/os_list_screen.dart`** - Referência de implementação para listas adaptativas
5. **`/lib/core/router/app_router.dart`** - Adicionar rotas de CRUD (12+ novas rotas)
6. **`/lib/features/clients/presentation/client_form_screen.dart`** (NOVO) - Estabelece padrão de form responsivo
7. **`/lib/features/clients/data/clients_repository.dart`** - Primeiro repositório com CRUD completo

---

## Estratégia de Testes

### Manual Testing (cada fase)
**Dispositivos:**
- Mobile: Chrome DevTools (390px iPhone), dispositivo físico
- Tablet: Chrome DevTools (768px iPad)
- Desktop: 1920x1080

**Checklist por tela:**
- [ ] Navegação funciona em todos os dispositivos
- [ ] Formulários são utilizáveis (campos visíveis, botões alcançáveis)
- [ ] Listas scrollam e permitem seleção
- [ ] Ações estão acessíveis (não cortadas)
- [ ] Loading/error states exibem corretamente
- [ ] Feedback de sucesso/erro aparece

### CRUD Testing (Fases 2-6)
Para cada entidade:
- [ ] **Create:** Form valida, salva, redireciona para detail, mostra success
- [ ] **Read:** List carrega com paginação, detail exibe todos os campos
- [ ] **Update:** Form pré-popula, salva alterações, mostra success
- [ ] **Delete:** Confirmation dialog, deleta, atualiza lista, mostra success

### Role-Based Testing (Fase 6)
- [ ] ADMIN vê todas as features
- [ ] GROOMER vê apenas OS atribuídas
- [ ] Não-admin não vê seção Admin

### Error Handling
- [ ] Network offline → error card com retry
- [ ] 401 → redirect para login
- [ ] 403 → "Sem permissão" message
- [ ] 500 → error com retry

---

## Verificação End-to-End (Pós-Implementação)

### Workflow Completo de Recepção (Mobile/Tablet)
1. **Login** → Dashboard responsivo
2. **Criar Cliente** → Form mobile-friendly, salvar sucesso
3. **Criar Pet** para cliente → Autocomplete, raça filtrada por espécie
4. **Check-in** → Stepper full-screen, seleção touch-friendly
5. **Ver OS** na lista → Cards em mobile, tap para detail
6. **Atualizar status** → Botão grande, confirmation
7. **Registrar pagamento** → Modal/bottom sheet, salva
8. **Ver histórico** → Payment list, saldo atualizado

### Workflow Admin (Desktop)
1. **Gerenciar Service Types** → List DataTable, create/edit form, delete confirmation
2. **Gerenciar Groomers** → Activate/deactivate, atribuir a OS
3. **Ver relatórios** (Fase 7 futura)

### Responsividade
1. Resize browser de 390px → 768px → 1920px
2. Verificar transições de layout (mobile → tablet → desktop)
3. Confirmar navegação adapta (BottomNav → Rail colapsado → Rail expandido)

---

## Trade-offs e Decisões

### Breakpoints: 600/1024 vs 480/1024
**Decisão:** 600/1024 (padrão Material Design)
**Razão:** Consistência com convenções, testado em produção por Google

### Navegação: BottomNav+Rail vs Drawer-only
**Decisão:** BottomNav (mobile) + Rail (tablet/desktop)
**Razão:** Ergonomia mobile, descobribilidade

### Listas: AdaptiveList vs Responsive DataTable package
**Decisão:** AdaptiveList custom
**Razão:** Controle total, UX mobile otimizada (cards > table)

### Forms: Local setState vs Formz package
**Decisão:** Manter local setState + Riverpod
**Razão:** Simplicidade, pattern já estabelecido no codebase

### Rollout: Incremental vs Big Bang
**Decisão:** Big Bang com staging testing
**Razão:** Time pequeno, poucos usuários, coordenar treinamento é viável

---

## Estimativa de Esforço

| Fase | Horas | Prioridade |
|------|-------|-----------|
| Fase 1: Fundação Responsiva | 25-30 | ⚠️ CRÍTICO |
| Fase 2: Clientes CRUD | 20-25 | 🔴 ALTA |
| Fase 3: Pets CRUD | 20-25 | 🔴 ALTA |
| Fase 4: Pagamentos | 15-20 | 🔴 ALTA |
| Fase 5: Melhorias OS | 15-20 | 🟡 MÉDIA |
| Fase 6: Admin CRUD | 20-25 | 🟡 MÉDIA |
| **MVP (Fases 1-4)** | **80-100h** | **2-3 meses part-time** |
| Fase 7: Avançado (futuro) | 30-40 | 🟢 BAIXA |

---

## Próximos Passos Imediatos

1. **Aprovação do plano** pelo usuário
2. **Criar feature branch** `feature/mobile-first-responsive` a partir de `develop`
3. **Fase 1:** Implementar fundação responsiva (breakpoints, AppShell, AdaptiveList)
4. **Teste em staging** com dispositivos reais
5. **Fase 2-4:** CRUD essencial (Clientes, Pets, Pagamentos)
6. **UAT (User Acceptance Testing)** com equipe do pet shop
7. **Deploy para produção** via PR develop → main (CD automático)
8. **Treinamento rápido** (30min) com equipe
9. **Fases 5-6:** Recursos adicionais conforme prioridade

---

## Arquivos de Referência

**Existentes (para extrair padrões):**
- `/lib/core/widgets/app_shell.dart` - Navegação atual
- `/lib/core/theme/app_theme.dart` - Tema Material 3
- `/lib/features/os/presentation/os_list_screen.dart` - Padrão de lista
- `/lib/features/checkin/presentation/checkin_screen.dart` - Stepper multi-step
- `/lib/features/auth/presentation/login_screen.dart` - Validação de form

**Novos (críticos):**
- `/lib/core/theme/breakpoints.dart` - Fundação responsiva
- `/lib/core/widgets/adaptive_list.dart` - Padrão de lista mobile
- `/lib/core/widgets/responsive_form.dart` - Layout de forms
- `/lib/features/clients/presentation/client_form_screen.dart` - Template de CRUD form
