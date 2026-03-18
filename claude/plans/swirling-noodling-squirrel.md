# Perfil com Salário + Redução de Fricção

## Contexto

O usuário quer: (1) guardar histórico de salário no perfil para uso no app inteiro, (2) ver evolução salarial, (3) reduzir fricção — tudo que é manual deveria ser automatizado ou simplificado com IA/voz.

Problemas atuais: não existe tabela de perfil/usuário, greeting hardcoded "Olá 👋", settings não persistem, cash flow não conhece salário, chat não sabe o salário.

Bug fix incluso: RecurringListView tinha NavigationStack aninhado causando loading infinito (já corrigido pelo agent na sessão).

---

## Task 1: Schema — `user_profile` + `salary_history`

**Arquivos:**
- Modificar: `backend/src/db/schema.ts` (ao final, antes de investments)

```typescript
export const userProfile = pgTable("user_profile", {
  id: uuid().primaryKey().defaultRandom(),
  name: varchar({ length: 100 }),
  primaryCurrency: varchar("primary_currency", { length: 3 }).notNull().default("BRL"),
  settings: jsonb().notNull().default("{}"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

export const salaryHistory = pgTable("salary_history", {
  id: uuid().primaryKey().defaultRandom(),
  amount: decimal({ precision: 15, scale: 2 }).notNull(),
  currency: varchar({ length: 3 }).notNull().default("BRL"),
  effectiveDate: date("effective_date").notNull(),
  notes: text(),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});
```

---

## Task 2: Backend — Rotas de perfil e salário

**Arquivos:**
- Criar: `backend/src/routes/profile.ts`
- Modificar: `backend/src/index.ts` — registrar `profileRoutes`

Endpoints:
- `GET /profile` — retorna perfil (auto-cria se não existe, single-user)
- `PUT /profile` — atualiza name, settings (upsert)
- `GET /salary-history` — lista por effectiveDate DESC
- `POST /salary-history` — adiciona (amount, currency, effectiveDate, notes)
- `DELETE /salary-history/:id` — remove entrada

---

## Task 3: Backend — Salário no chat, insights e cash flow

**Arquivos:**
- Modificar: `backend/src/routes/chat.ts` — adicionar salary ao `buildChatContext()`
- Modificar: `backend/src/routes/insights.ts` — incluir salário no prompt
- Modificar: `backend/src/routes/cash-flow.ts` — salário como income garantido na projeção

**chat.ts:** No Promise.all do `buildChatContext()`, adicionar:
```typescript
db.query.userProfile.findFirst(),
db.query.salaryHistory.findMany({ orderBy: [desc(salaryHistory.effectiveDate)] }),
```
Incluir no `financialContext`: `userProfile`, `currentSalary`, `salaryHistory`.

**insights.ts:** Adicionar `currentSalary` para gerar insights tipo "Você gastou 45% do salário em moradia".

**cash-flow.ts:** Se salário existe, adicionar como income fixo em cada mês projetado (linhas 122-147, dentro do loop `for (let i = 1; i <= 3; i++)`).

---

## Task 4: iOS — Models + ProfileViewModel expandido

**Arquivos:**
- Criar: `ios/Fintech/Models/Profile.swift`
- Modificar: `ios/Fintech/ViewModels/ProfileViewModel.swift`

**Profile.swift:**
```swift
struct UserProfile: Codable {
    var name: String?
    var primaryCurrency: String
    var settings: ProfileSettings
}

struct ProfileSettings: Codable {
    var notificationsEnabled: Bool?
    var faceIdEnabled: Bool?
}

struct SalaryEntry: Codable, Identifiable {
    let id: String
    let amount: String
    let currency: String
    let effectiveDate: String
    let notes: String?
    var amountDouble: Double { Double(amount) ?? 0 }
}
```

**ProfileViewModel:** Expandir para:
- Carregar `profile` + `salaryHistory` em paralelo com accounts/goals/budgets
- `updateProfile(name:settings:)` → PUT /profile
- `addSalary(amount:currency:effectiveDate:notes:)` → POST /salary-history
- `deleteSalary(id:)` → DELETE /salary-history/:id
- Computed: `currentSalary` (primeiro da lista), `userName`

---

## Task 5: iOS — ProfileView redesign com salário

**Arquivos:**
- Modificar: `ios/Fintech/Views/Profile/ProfileView.swift`
- Criar: `ios/Fintech/Views/Profile/AddSalarySheet.swift`

Seções da ProfileView (em ordem):
1. **Header** — nome editável (tap inline), salvar via PUT /profile
2. **Salário atual** — card com valor, moeda, data efetiva
3. **Histórico de salário** — mini chart (Swift Charts `LineMark` por effectiveDate) + lista com swipe-delete
4. **Botão "Adicionar salário"** → sheet `AddSalarySheet`
5. Contas Conectadas (existente)
6. Orçamento (existente)
7. Metas (existente)
8. Configurações (existente, mas agora persistido via PUT /profile)

**AddSalarySheet:** Form com valor (numeric), moeda picker (BRL/USD/EUR), date picker, notes.

---

## Task 6: iOS — Greeting personalizado + settings persistidos

**Arquivos:**
- Modificar: `ios/Fintech/Views/Dashboard/DashboardView.swift` — linha 84: trocar `"Olá 👋"` por `"Olá, \(viewModel.userName) 👋"`
- Modificar: `ios/Fintech/Views/Dashboard/DashboardViewModel.swift` — adicionar `userName` carregado do GET /profile

Settings em ProfileView: trocar `@State` por bindings ao `viewModel.profile.settings`, auto-salvar via `.onChange(of:)` → `viewModel.updateProfile()`.

---

## Task 7: Commit, deploy, install, seed

1. `npm run build` — verificar compilação
2. Build iOS — verificar compilação
3. Commit tudo
4. Deploy VPS: rsync + `drizzle-kit push` (cria tabelas novas) + `pm2 restart fintech-api`
5. Seed salários via curl:
   - `POST /api/salary-history` — R$4.200, 2025-04-07 (7 de abril 2025)
   - `POST /api/salary-history` — R$5.200, 2025-07-01 (1 de julho 2025)
   - `POST /api/salary-history` — US$3.000, 2026-02-06 (6 de fevereiro 2026)
6. `PUT /api/profile` — name: "Vinícius"
7. Build iOS com code signing + install no iPhone

---

## Verificação

1. `GET /api/profile` → `{ name: "Vinícius", primaryCurrency: "BRL", settings: {...} }`
2. `GET /api/salary-history` → 3 entradas ordenadas por data DESC
3. Dashboard: "Olá, Vinícius 👋"
4. Chat: "qual meu salário?" → responde US$3.000
5. Cash flow: projeção inclui salário como income
6. Perfil: gráfico de evolução + lista de salários
7. Settings toggles persistem entre reinícios
8. RecurringListView carrega normalmente (fix NavigationStack)
