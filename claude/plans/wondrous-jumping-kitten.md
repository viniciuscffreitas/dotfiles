# Plano: Uniformizar altura dos cards do Kanban

## Context
Os cards do `_KanbanCard` têm altura variável por dois motivos:
1. O `IconButton` de avanço usa `SizedBox(48, 48)`, dominando a Row 1 (48px vs ~20px sem botão — diferença de ~28px)
2. A Row 2 (nome do cliente) é condicional — cards sem cliente são mais curtos em ~18px

O objetivo é eliminar toda variação de altura, tornando todos os cards idênticos, sem botão gigante.

## Arquivo a modificar
`/Users/vini/Desktop/cisnebranco_web/lib/features/os/presentation/os_list_screen.dart`
Método: `_KanbanCard._buildCard` (linhas 561–741)

## Mudanças (3 cirúrgicas)

### 1. Fixar Row 1 em 24px
Envolver o Row do topo em `SizedBox(height: 24)` — altura suficiente para `titleSmall` (20px line-height) e para o botão compacto.

```dart
// ANTES
Row(
  children: [...],
),

// DEPOIS
SizedBox(
  height: 24,
  child: Row(
    crossAxisAlignment: CrossAxisAlignment.center,
    children: [...],
  ),
),
```

### 2. Botão compacto (inline, sem SizedBox gigante)
Remover `SizedBox(width: 48, height: 48)`. Usar `IconButton` com `constraints: const BoxConstraints()` para zerar o min-size padrão do Material (48px), e `iconSize: 14`.

```dart
// ANTES
SizedBox(
  width: 48,
  height: 48,
  child: IconButton(padding: EdgeInsets.zero, iconSize: 18, ...),
),

// DEPOIS
IconButton(
  padding: EdgeInsets.zero,
  constraints: const BoxConstraints(),  // remove min 48px do Material
  iconSize: 14,
  tooltip: _nextActionLabel(columnStatus),
  icon: Icon(Icons.arrow_forward_rounded, color: ...),
  onPressed: () => onStatusChange(id, nextStatus),
),
```

### 3. Client name sempre renderizado
Remover o `if (clientName != null && clientName.isNotEmpty)`. Renderizar sempre — `Text('')` ocupa a mesma line-height que `Text('João Silva')`.

```dart
// ANTES
if (clientName != null && clientName.isNotEmpty) ...[
  const SizedBox(height: 2),
  Text(clientName, ...),
],

// DEPOIS
const SizedBox(height: 2),
Text(
  clientName ?? '',
  style: Theme.of(context).textTheme.bodySmall?.copyWith(color: Colors.grey.shade600),
  overflow: TextOverflow.ellipsis,
),
```

## Altura resultante (todos os cards)
| Elemento | Altura |
|---|---|
| padding top | 12px |
| Row 1 (fixo) | 24px |
| SizedBox | 2px |
| Row 2 (bodySmall) | ~16px |
| SizedBox | 8px |
| Row 3 (bodySmall) | ~16px |
| padding bottom | 12px |
| **Total** | **~90px sempre** |

## Verificação
- Hot reload no browser e checar cards de diferentes colunas (WAITING com botão vs DELIVERED sem botão)
- Checar card com e sem `clientName` preenchido — ambos devem ter mesma altura
- Drag feedback (desktop) não é afetado — usa o mesmo `card` widget
