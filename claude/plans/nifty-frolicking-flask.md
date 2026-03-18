# Chat Action: Aplicar Orçamento FAT FIRE via Chat (com Preview)

## Context
O usuário quer dizer "aplica o orçamento FAT FIRE" no chat e ver uma **preview** das alocações antes de confirmar. Deve poder editar valores e só então aplicar. Segue o mesmo padrão de preview que já existe para transações (card com "Editar" e "Confirmar").

## Padrão Existente (Transações)
1. IA gera `---action--- {type: "create_transaction", ...} ---end_action---`
2. Backend envia SSE `{type: "action_preview", action: {...}}`
3. iOS mostra `TransactionPreviewCard` com botões "Editar" / "Confirmar"
4. "Editar" abre `EditTransactionPreviewSheet` (form com campos editáveis)
5. "Confirmar" → iOS chama `POST /api/transactions/manual` direto
6. Sucesso → marca como confirmado + posta notification

**Importante:** A confirmação é feita pelo iOS (não pelo backend). O backend só envia o preview.

---

## Mudanças

### 1. Backend: Extrair lógica FAT FIRE (`backend/src/routes/budgets.ts`)
Extrair o corpo do handler `GET /budgets/fire-recommendations` para função exportável:
```typescript
export async function calculateFireRecommendations(): Promise<FireRecommendations>
```
O handler GET passa a chamar essa função. O chat action também vai chamá-la.

### 2. Backend: Novo action no chat (`backend/src/routes/chat.ts`)

**Schema** (~linha 150):
```typescript
const applyFireBudgetsSchema = z.object({
  type: z.literal("apply_fire_budgets"),
});
```
Adicionar ao `actionSchema` union.

**Routing** (~linha 318): Adicionar `"apply_fire_budgets"` à condição de preview.
Mas em vez de enviar o schema da ação, calcular as recomendações e enviar dados ricos:
```typescript
if (actionType === "apply_fire_budgets") {
  const recs = await calculateFireRecommendations();
  reply.raw.write(`data: ${JSON.stringify({
    type: "action_preview",
    action: { type: "apply_fire_budgets", ...recs }
  })}\n\n`);
}
```

### 3. Backend: Prompt da IA (`backend/src/services/ai.ts`)
Adicionar na seção "Ações disponíveis":
```
- **apply_fire_budgets**: {"type": "apply_fire_budgets"}
  Aplica orçamento FAT FIRE baseado no salário. Use quando o usuário pedir para configurar/aplicar orçamento, sugestões de budget, ou organizar gastos por renda.
```

### 4. iOS: Modelo de dados (`ios/Fintech/Models/ChatMessage.swift`)

Novo struct `FireBudgetPreviewData`:
```swift
struct FireBudgetPreviewData: Codable {
    let type: String  // "apply_fire_budgets"
    var income: Int
    var allocations: [FirePreviewAllocation]
}
struct FirePreviewAllocation: Codable, Identifiable {
    let name: String
    let percentage: Int
    var amount: Int
    var categories: [FirePreviewCategory]
    var id: String { name }
}
struct FirePreviewCategory: Codable, Identifiable {
    let id: String
    let name: String
    let icon: String
    var suggestedLimit: Int
}
```

Adicionar ao `SSEEvent`:
```swift
let fireBudgetAction: FireBudgetPreviewData?  // decoded from action when type matches
```

Adicionar ao `ChatMessage`:
```swift
var fireBudgetPreview: FireBudgetPreviewData?
var firePreviewConfirmed: Bool = false
var firePreviewError: String?
```

### 5. iOS: Preview Card (`ios/Fintech/Views/Chat/FireBudgetPreviewCard.swift`) — NOVO

Card visual mostrando:
- Header: "Orçamento FAT FIRE" + renda total
- 3 linhas macro: Necessidades 50% · R$ X | Estilo de Vida 30% · R$ X | Investimentos 20% · R$ X
- Total
- Botões: "Editar" (cinza) + "Confirmar" (verde/primary)
- Estado confirmado: badge "✓ Aplicado"

Estilo: seguir `TransactionPreviewCard` — compacto, dentro do bubble do chat.

### 6. iOS: Edit Sheet (`ios/Fintech/Views/Chat/EditFireBudgetSheet.swift`) — NOVO

Sheet com:
- Seções por macro-categoria
- Cada categoria: nome + campo editável de valor (R$)
- Total dinâmico recalculado conforme edita
- Botão "Salvar" que retorna o `FireBudgetPreviewData` editado

### 7. iOS: Integração no Chat (`ios/Fintech/Views/Chat/`)

**ChatViewModel.swift:**
- No handler de SSE `action_preview`: detectar `type == "apply_fire_budgets"` e chamar `attachFirePreviewToLastAssistant(data)`
- Novo método `confirmFireBudgets(messageId)`:
  - Marca `firePreviewConfirmed = true`
  - Para cada category em cada allocation: `PUT /api/budgets` com `{categoryId, month, limitAmount}`
  - Sucesso → posta `chatActionCompleted` com `actionType: "apply_fire_budgets"`
  - Erro → reverte confirmed, seta error
- Novo método `confirmEditedFireBudgets(messageId, editedData)`:
  - Atualiza o preview com dados editados e confirma

**MessageBubble.swift:**
- Se `message.fireBudgetPreview != nil`: renderizar `FireBudgetPreviewCard`
- Passar callbacks `onConfirm` e `onEdit`

**ChatView.swift:**
- Adicionar estado `@State private var editingFireBudget: FireBudgetPreviewData?`
- Sheet para `EditFireBudgetSheet`
- Conectar callbacks do MessageBubble

### 8. iOS: BudgetViewModel observer
Linha 62: Expandir condição para incluir `"apply_fire_budgets"`:
```swift
actionType == "create_budget" || actionType == "apply_fire_budgets"
```

---

## Arquivos Afetados
1. `backend/src/routes/budgets.ts` — extrair `calculateFireRecommendations()`
2. `backend/src/routes/chat.ts` — schema + routing para preview
3. `backend/src/services/ai.ts` — documentar ação no prompt
4. `ios/Fintech/Models/ChatMessage.swift` — `FireBudgetPreviewData` + campos no `ChatMessage`/`SSEEvent`
5. `ios/Fintech/Views/Chat/FireBudgetPreviewCard.swift` — **NOVO** preview card
6. `ios/Fintech/Views/Chat/EditFireBudgetSheet.swift` — **NOVO** edit sheet
7. `ios/Fintech/Views/Chat/MessageBubble.swift` — render fire preview
8. `ios/Fintech/Views/Chat/ChatView.swift` — sheet + callbacks
9. `ios/Fintech/Views/Chat/ChatViewModel.swift` — confirm/edit logic
10. `ios/Fintech/ViewModels/BudgetViewModel.swift` — expandir observer

## Verificação
1. `npm run build` no backend
2. `xcodebuild -scheme Fintech` no iOS
3. Deploy backend
4. No chat: "aplica o orçamento FAT FIRE" → card preview aparece com 3 macro-categorias
5. Clicar "Editar" → sheet com valores editáveis
6. Clicar "Confirmar" → budgets criados, badge "✓ Aplicado"
7. Navegar para Orçamento Mensal → valores atualizados
8. Instalar no iPhone
