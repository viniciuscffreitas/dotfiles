# Avatar WebP + Skeleton Loading

## Context
Dois problemas de performance/UX identificados:
1. **Avatares lentos**: Upload gera `-avatar.webp` (256×256) mas a URL retornada é `.jpg` — DB armazena URL do JPEG grande, nunca usa o WebP otimizado
2. **Navegação lenta**: Sem `loading.tsx` em nenhuma rota — Server Components bloqueiam render até queries do DB completarem, dando sensação de que o botão não registrou o toque

## Fix 1: Avatar URL

### 1a. Corrigir upload route
**Arquivo:** `src/app/api/upload/route.ts` (linha 62)

Antes: sempre retorna `.jpg`
Depois: retorna `-avatar.webp` quando `type === "avatar"`

```ts
const responseUrl = type === "avatar"
  ? `/api/images/${baseName}-avatar.webp`
  : `/api/images/${filename}`;
return NextResponse.json({ url: responseUrl });
```

### 1b. Migração dos avatares existentes
**Arquivo:** `src/lib/db.ts` (após linha 129, antes do `export`)

```sql
UPDATE usuarios
SET avatar_url = REPLACE(avatar_url, '.jpg', '-avatar.webp')
WHERE avatar_url LIKE '%/api/images/%.jpg'
  AND avatar_url NOT LIKE '%-avatar.webp';
```

Idempotente — roda em todo boot mas o WHERE evita re-aplicação. Os `-avatar.webp` já existem em disco.

### 1c. Fix cleanup ao trocar avatar
**Arquivo:** `src/app/api/user/avatar/route.ts` (linhas 22-23)

Problema: com URL `-avatar.webp`, `oldBaseName` vira `1234-abc-avatar` e o loop não deleta `.jpg` nem `-thumb.webp`.

Fix: extrair o baseName real removendo sufixo `-avatar`:
```ts
const oldFilename = path.basename(user.avatarUrl);
const oldBaseName = oldFilename.replace(/\.[^.]+$/, "").replace(/-avatar$/, "");
```

Depois o loop existente funciona corretamente para todas as variantes.

## Fix 2: Skeleton Loading (5 arquivos)

Todos são Server Components simples (sem "use client"). Usam `bg-surface-hover animate-pulse` para shimmer. Cada skeleton replica **exatamente** o layout da página real.

### 2a. Feed — `src/app/(main)/feed/loading.tsx`
- Header sticky com placeholder do logo + 2 botões (search/ranking) w-9 h-9
- Count label (px-5 pb-3)
- LookDoDiaCard skeleton: mx-4 mb-5, label area, aspect-[3/4] photo
- 2× LookCard skeleton: avatar w-9, username, price, aspect-[3/4] photo, 3 pieces, 5 reaction circles, bookmark

### 2b. Profile — `src/app/(main)/profile/loading.tsx`
- Header h-13: "perfil" placeholder + gear icon w-9
- Avatar w-[72px] h-[72px] + name/meta
- Stats grid cols-5 (5 cards bg-surface rounded-2xl)
- Tabs (2 buttons com border-b)
- Calendar grid placeholder (7×4)

### 2c. Profile/[id] — `src/app/(main)/profile/[id]/loading.tsx`
- Header h-13: back button w-11 + name placeholder
- Mesmo layout do profile (avatar, stats, calendar)
- Sem tabs (OtherProfile não tem "salvos")

### 2d. Ranking — `src/app/(main)/ranking/loading.tsx`
- Header h-12: "ranking" placeholder
- 3 filter tabs (rounded-full)
- Hero #1: avatar 52×52, name text-[16px], stat grande
- #2-#3: avatar 40×40
- #4-#6: avatar 40×40, compact

### 2e. Settings — `src/app/(main)/settings/loading.tsx`
- Header h-13: back button + "ajustes"
- Seção "conta": label estático + card com avatar w-10, nome row, turma row
- Seção "notificações": label estático + 3 rows com toggle w-12 h-7

## Arquivos Modificados

| Arquivo | Ação |
|---------|------|
| `src/app/api/upload/route.ts` | Edit L62 |
| `src/lib/db.ts` | Add migration after L129 |
| `src/app/api/user/avatar/route.ts` | Edit L22-23 |
| `src/app/(main)/feed/loading.tsx` | Create |
| `src/app/(main)/profile/loading.tsx` | Create |
| `src/app/(main)/profile/[id]/loading.tsx` | Create |
| `src/app/(main)/ranking/loading.tsx` | Create |
| `src/app/(main)/settings/loading.tsx` | Create |

## Dev Workflow
1. `git checkout develop && git checkout -b fix/avatar-and-skeletons`
2. Implementar Fix 1 (3 edits)
3. Implementar Fix 2 (5 creates)
4. `npm run build` para verificar
5. Merge develop → main → deploy

## Verificação
- Build: `npm run build` deve passar sem erros
- Avatar: após deploy, avatares devem carregar visivelmente mais rápido (256×256 WebP vs JPEG grande)
- Skeletons: navegação entre telas deve mostrar skeleton instantaneamente em vez de tela em branco
- Teste no Safari iOS PWA para garantir safe-area-inset funciona nos headers dos skeletons
