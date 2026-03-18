# Redesign WiseConvertSheet no estilo Wise

## Context
A tela de conversão atual usa cards empilhados (input + resultado). O usuário quer redesenhar para ficar no estilo da tela de conversão da Wise (screenshot), adaptado ao nosso design system (cores warm off-white/forest green, `.cardStyle()`, etc).

## Layout alvo (inspirado na Wise)

### Form Phase — rewrite completo
```
┌──────────────────────────────────┐
│  X              1 USD = 5,17 BRL │  ← header: X button + rate pill
│                                  │
│  De                              │
│  🇺🇸 USD              2.300     │  ← flag pill + input grande
│            Disponível: 2.599 USD │  ← saldo disponível
│                                  │
│         ──── ⇅ ────              │  ← divider com ícone swap
│                                  │
│  Para                            │
│  🇧🇷 BRL           11.787,24    │  ← flag pill + valor calculado
│            Fee: US$ 20,82 (IOF)  │  ← fee inline
│                                  │
│         (spacer)                 │
│                                  │
│  ⓘ Digite um valor p/ continuar │
│  ┌────────────────────────────┐  │
│  │       Ver resumo →         │  │  ← CTA disabled/enabled
│  └────────────────────────────┘  │
└──────────────────────────────────┘
```

### Confirmation Phase — manter como está
### Success Phase — manter como está

## Implementação

### Arquivo: `ios/Fintech/Views/Dashboard/WiseConvertSheet.swift`
Rewrite apenas do `formView`. Toda lógica (debounce, fetchQuote, etc) permanece.

#### Header custom (substituir NavigationStack toolbar)
- Remover `navigationTitle` e toolbar ToolbarItem
- HStack: Button X (xmark.circle.fill) + Spacer + rate pill
- Rate pill: `"1 USD = {rate} BRL"` em `caption.weight(.semibold)`, bg `AppTheme.surface`, cornerRadius `.full`, shadow

#### Seção "De"
- Label "De" — `.subheadline.weight(.medium)`, `textSecondary`
- HStack: currency pill (🇺🇸 + "USD") + Spacer + TextField input
- Currency pill: HStack com flag Text + "USD" Text, bg `AppTheme.inputBackground`, cornerRadius `Radius.full`, padding h:md v:sm
- TextField: `.font(.largeTitle.weight(.bold).monospacedDigit())`, right-aligned, `textPrimary`
- Abaixo: "Disponível: X.XXX USD" — `.caption`, `AppTheme.accent`, right-aligned
- Saldo USD: buscar via `/api/wise/quote?amountUsd=0.01` no init (sourceAmount devolve o total) — **não**, mais simples: adicionar `availableUsd` ao backend no GET /exchange-rates/analysis

#### Divider com swap icon
- ZStack: Rectangle divider (1pt, `AppTheme.divider`) + circle com `arrow.up.arrow.down`
- Circle: 32pt, bg `AppTheme.surface`, shadow, icon `textTertiary`

#### Seção "Para"
- Label "Para" — mesma style de "De"
- HStack: currency pill (🇧🇷 + "BRL") + Spacer + valor
- Valor: se loading → ProgressView; se quote → valor em `AppTheme.positive`, `.largeTitle.weight(.bold).monospacedDigit()`; se zero → "0,00" em `textTertiary`
- Abaixo: se quote → "Fee: US$ {fee} (incl. IOF)" em `.caption`, `textTertiary`; se erro → erro em `danger`

#### Bottom area
- Spacer
- Info text: "Digite um valor para continuar" ou vazio quando quote ok
- Button "Ver resumo →": full width, `.body.weight(.semibold)`, bg `primary`/`divider`, fg `white`/`textTertiary`

### Arquivo: `backend/src/routes/exchange-rates.ts`
- No endpoint GET /exchange-rates/analysis: buscar balances da Wise e retornar `availableUsd`
- Adicionar ao response: `availableUsd: usdBalance?.amount?.value ?? null`

### Arquivo: `ios/Fintech/Models/Transaction.swift`
- Adicionar `let availableUsd: Double?` ao `CurrencyAnalysis`

## O que NÃO muda
- Lógica de fetch quote (debounce, API calls) — só refatora o layout
- Confirmation phase e Success phase — mantêm visual atual
- Backend endpoints wise/quote e wise/convert

## Verificação
1. Build iOS: `cd ios && xcodebuild -scheme Fintech -destination 'platform=iOS Simulator,id=F3C54875-7D32-4EEA-B186-9CCCFB67FF30' build`
2. Instalar e verificar visualmente no simulador
3. Testar flow completo: digitar valor → quote atualiza → Ver resumo → Converter
