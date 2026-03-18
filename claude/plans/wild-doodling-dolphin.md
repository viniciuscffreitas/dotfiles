# Image Optimization — FitCheck

## Context

Fotos do feed e perfil demoram para carregar porque:
1. Todas as imagens (look 1200x1600, avatar, thumbnail do calendário) são servidas no tamanho original (~200-400KB cada) via API route Node.js
2. Formato JPEG sem alternativas modernas (WebP/AVIF)
3. Calendário carrega ~30 imagens full-size para cells de ~50px
4. Avatares de 24-64px carregam a imagem de 1200x1600

## Solução

### 1. `next.config.ts` — config de otimização de imagens

Adicionar formatos modernos, device sizes, e cache TTL:

```ts
images: {
  localPatterns: [{ pathname: "/api/images/**" }],
  formats: ["image/avif", "image/webp"],
  deviceSizes: [390, 640, 750, 828, 1080],
  imageSizes: [32, 48, 64, 96, 128, 200],
  minimumCacheTTL: 31536000,
}
```

### 2. `/api/images/[id]/route.ts` — suporte WebP

Adicionar detecção de `.webp` no content-type.

### 3. `/api/upload/route.ts` — gerar thumbnails no upload

Após salvar o JPEG original, gerar:
- `{name}-thumb.webp` (200x267, WebP 70%) — para calendário
- Se avatar: `{name}-avatar.webp` (256x256 square crop, WebP 75%)

Aceitar campo `type` no FormData (`"look"` | `"avatar"`).

### 4. Trocar `<img>` por `<Image>` em todos os componentes

| Componente | Elemento | width | height | sizes |
|---|---|---|---|---|
| LookCard | foto | fill | fill | `100vw` |
| LookCard | avatar | 32 | 32 | `32px` |
| LookDoDiaCard | foto | fill | fill | `100vw` + priority |
| LookDoDiaCard | avatar | 24 | 24 | `24px` |
| CalendarGrid | thumbnail | 100 | 133 | `14vw` |
| ProfileClient | avatar | 64 | 64 | `64px` + priority |
| ProfileClient | fav grid | 200 | 267 | `33vw` |
| ProfileClient | fav avatar | 24 | 24 | `24px` |
| OtherProfileClient | avatar | 64 | 64 | `64px` + priority |
| RankingClient | avatar | 40 | 40 | `40px` |

Para fotos em containers com aspect-ratio, usar `<Image fill className="object-cover" />`.

### 5. Login + PostClient — enviar `type` no upload FormData

- Login (avatar upload): `formData.append("type", "avatar")`
- PostClient (look upload): `formData.append("type", "look")`

### 6. `docker-compose.yml` — persistir cache do Next.js Image

```yaml
volumes:
  - ./data:/app/data
  - nextjs-cache:/app/.next/cache
```

### 7. Script de migração para imagens existentes

`scripts/generate-thumbnails.ts` — gera `-thumb.webp` para looks existentes. Rodar uma vez no servidor.

## Arquivos modificados

- `next.config.ts`
- `src/app/api/images/[id]/route.ts`
- `src/app/api/upload/route.ts`
- `src/components/LookCard.tsx`
- `src/components/LookDoDiaCard.tsx`
- `src/components/CalendarGrid.tsx`
- `src/app/(main)/profile/ProfileClient.tsx`
- `src/app/(main)/profile/[id]/OtherProfileClient.tsx`
- `src/app/(main)/ranking/RankingClient.tsx`
- `src/app/(main)/post/PostClient.tsx`
- `src/app/login/page.tsx`
- `docker-compose.yml`
- `scripts/generate-thumbnails.ts` (novo)

## Impacto estimado

- Calendário: ~6MB → ~150KB (40x menor)
- Avatares: ~200KB → ~3KB cada (70x menor)
- Feed: ~200KB → ~50KB por foto (4x menor via WebP + resize)
- Segundo acesso: instantâneo (cache do browser + cache do Next.js)

## Verificação

1. Build local: `npm run build` sem erros
2. Verificar no DevTools Network que imagens são servidas como WebP/AVIF
3. Verificar que tamanhos das imagens correspondem ao viewport (não 1200px para avatar de 32px)
4. Deploy + testar no celular
