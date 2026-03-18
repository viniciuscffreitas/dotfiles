# Plan: Kanban WCAG + Visual Redesign

## Context
O Kanban atual usa 4 cores saturadas (amber, blue, green, purple) que: (1) falham WCAG 1.4.3 por contraste insuficiente, (2) competem visualmente entre si criando fadiga, (3) não seguem o design system navy-dominant. Além disso há problemas de font size (11sp), touch targets (44px vs 56px), sem navegação por teclado no drag-and-drop, e count badge sem contraste suficiente.

## Arquivo a modificar
`/Users/vini/Desktop/cisnebranco_web/lib/features/os/presentation/os_list_screen.dart`

Apenas este arquivo. Todas as mudanças são self-contained.

---

## 1. Nova paleta de status (WCAG-compliant, dark muted)

Substituir as 4 cores saturadas por variantes escuras que passam WCAG AA (mínimo 4.5:1):

```dart
const _columns = [
  _ColumnConfig(
    status: 'WAITING',
    label: 'Aguardando',
    color: Color(0xFF92400E),   // amber-800 — contraste 7.1:1 ✓ AAA
    icon: Icons.schedule_rounded,
  ),
  _ColumnConfig(
    status: 'IN_PROGRESS',
    label: 'Em Andamento',
    color: Color(0xFF1E3A8A),   // design system secondary — 10.7:1 ✓ AAA
    icon: Icons.content_cut_rounded,
  ),
  _ColumnConfig(
    status: 'READY',
    label: 'Prontas',
    color: Color(0xFF065F46),   // emerald-800 — 7.7:1 ✓ AAA
    icon: Icons.check_circle_outline_rounded,
  ),
  _ColumnConfig(
    status: 'DELIVERED',
    label: 'Entregues',
    color: Color(0xFF374151),   // gray-700 neutro — 10.8:1 ✓ AAA
    icon: Icons.done_all_rounded,
  ),
];
```

Remover campo `selectedColor` de `_ColumnConfig` — não é mais necessário.

---

## 2. Cabeçalho de coluna neutro

- Ícone: `config.color` (agora escuro, passa WCAG)
- Label: `Theme.of(context).textTheme.titleSmall` sem override de cor
- Count badge: background `AppTheme.surfaceLight` (`#F0F4FF`) + texto `Color(0xFF0F1B4C)` (navy primary) → contraste ~15:1 ✓

---

## 3. Coluna sem tinting de cor

- Fundo padrão: `Colors.transparent` (sem tint colorido por coluna)
- Drag target ativo: `AppTheme.surfaceLight` com borda sutil (navy 15% opacity)
- Remove a dependência visual de cor no background das colunas

---

## 4. Card com left border stripe (padrão Linear/Jira)

Trocar `Card` por `Container` com `clipBehavior: Clip.antiAlias`:

```dart
Container(
  decoration: BoxDecoration(
    color: Colors.white,
    borderRadius: BorderRadius.circular(16),
  ),
  clipBehavior: Clip.antiAlias,
  child: Material(
    color: Colors.transparent,
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Container(width: 3, color: config.color),  // stripe de status
        Expanded(child: InkWell(onTap: ..., child: content)),
      ],
    ),
  ),
)
```

O stripe é clipped ao borderRadius — cantos arredondados funcionam corretamente.

---

## 5. Botão de avançar — visível em desktop também (WCAG 2.1.1)

**Problema:** `LongPressDraggable` não tem alternativa de teclado (falha WCAG 2.1.1).
**Fix:** Remover a condição `if (isMobile && canAdvance)` — mostrar o botão de seta em todos os breakpoints quando `canAdvance`. Drag continua como UX adicional no desktop.

```dart
// Antes:
if (isMobile && canAdvance && nextStatus != null) ...[...]

// Depois:
if (canAdvance && nextStatus != null) ...[...]
```

Touch target: `SizedBox(width: 48, height: 48)` (era 44×44, agora >= mínimo WCAG 2.5.5).

---

## 6. Font sizes mínimo 12sp

- `#id`: `fontSize: 11` → `fontSize: 12`
- Tempo relativo: `fontSize: 11` → `fontSize: 12`

---

## 7. Mobile FilterChip: selectedColor neutro

Usar `Color(0xFF0F1B4C)` (navy primary) para todos os chips selecionados — elimina as 4 cores competindo nos tabs mobile.

---

## 8. Drop indicator sem layout shift

`_buildDropIndicator()` atualmente insere um widget acima da lista, causando layout shift.
Fix: usar `Positioned` overlay dentro de `Stack` no `_buildColumnBody`, ou simplesmente remover o indicador de texto e deixar apenas o fundo + borda (já comunica o drop zone).

---

## Verificação

1. `flutter run -d chrome` → verificar contraste visualmente
2. Tab navigation no browser → cards devem ser focáveis e o botão de seta acessível
3. Verificar que long-press drag ainda funciona no desktop
4. Mobile: tabs neutros (todos navy quando selecionado)
5. Verificar font size com zoom do browser a 200% (WCAG 1.4.4)
