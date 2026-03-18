# Redesign Dashboard — Menos Ruído, Mais Pareto

## Contexto

A tela inicial tem **10 seções** que exigem ~3 scrolls completos. Pelo princípio de Pareto, 80% do valor vem de: patrimônio, resumo do mês e gastos por categoria. O resto é ruído ou acesso secundário.

**Problemas atuais:**
- 5 contas listadas (3 com saldo zero) ocupam uma tela inteira
- Grid 2x2 de atalhos com texto quebrado ("Investimen-tos")
- Resumo mensal (o mais útil!) fica abaixo de 2+ telas de scroll
- "Gastos Manuais R$0,00" não agrega valor visual
- Carga cognitiva alta — muitos cards competindo por atenção

## Abordagem: Compactar + Reordenar

Nova hierarquia visual (de cima para baixo):

```
1. Saudação compacta (sem emoji)
2. Patrimônio card (mantém — é o hero)
3. Contas (só saldo > 0, sem header separado)
4. Seletor de mês + Receitas/Despesas
5. Gastos por categoria (top 5)
6. Orçamento (se existir)
7. Insights IA (se existir)
8. Metas (se existir)
```

**Eliminado:** Grid 2x2 de atalhos → menu discreto no toolbar (3-dot ou similar).

## Arquivos

- `ios/Fintech/Views/Dashboard/DashboardView.swift` — reestruturar body, mover grid para toolbar
- `ios/Fintech/Views/Dashboard/DashboardViewModel.swift` — filtrar contas com saldo zero

## Tasks

### Task 1: Grid de atalhos → menu no toolbar

Remover `quickAccessGrid` do body. Adicionar `Menu` no toolbar com NavigationLinks para Projeção, Recorrentes, Contas e Investimentos.

### Task 2: Esconder contas com saldo zero

Em `DashboardViewModel.activeAccounts`, filtrar `Double(balance) != 0`. Isso remove automaticamente Wise BRL (R$0), Wise EUR (€0), Wise GBP (£0) e Gastos Manuais (R$0). Se nenhuma conta tiver saldo, manter o empty state.

### Task 3: Reordenar seções

Nova ordem no `body`:
```swift
greetingHeader
patrimonyCard
accountsSection  // agora compacto (só saldo > 0)
monthSelector
monthlySummaryCard
spendingCategoriesSection
budgetSection
insightsSection
goalsSection
```

### Task 4: Compactar saudação

Remover emoji 👋. Fonte menor (`.title2` em vez de `size: 28`).

### Task 5: Deploy + instalar

Build iOS + devicectl install.

## Verificação

1. Tela inicial cabe em ~1.5 scrolls (vs 3+ antes)
2. Contas com saldo zero não aparecem
3. Menu "..." no toolbar tem os 4 atalhos
4. Resumo do mês visível com no máximo 1 scroll leve
5. VoiceOver navega todos os elementos com labels corretos
