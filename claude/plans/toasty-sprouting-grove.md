# Plano: Recuperação de Conta

## Contexto
Se um usuário perder o cookie, perde a conta. O campo "email de recuperação" no perfil não faz nada. Solução: código de recuperação gerado no cadastro + endpoint admin via CLI para gerar códigos temporários para quem perdeu.

## Mudanças

### 1. Schema
- **`src/lib/schema.ts`**:
  - Adicionar `codigoRecuperacao: text("codigo_recuperacao")` em `usuarios`
  - Remover campo `email` (não é usado)
  - Nova tabela `codigosTemporarios`: `id`, `usuarioId`, `codigo`, `criadoEm`, `usado` (integer 0/1)
- **`src/lib/db.ts`**: atualizar init SQL

### 2. Gerar código no registro
- **`src/lib/auth.ts`**: nova função `generateRecoveryCode()` → formato `XXXX-XXXX` (uppercase alfanumérico)
- **`src/app/api/auth/route.ts`**: gerar e salvar código no insert. Retornar na response.

### 3. Tela pós-registro — mostrar o código
- **`src/app/login/page.tsx`**: novo step após registro. Mostra código grande, botão "copiar", aviso para salvar. Botão "continuar" leva ao feed.

### 4. Recuperação por código
- **`src/app/login/page.tsx`**: link "já tenho conta" na tela inicial → input de código → chama endpoint.
- **`src/app/api/auth/recover/route.ts`** (NOVO): recebe `{ codigo }`, busca em `codigosTemporarios` (não usado) ou `usuarios.codigoRecuperacao`. Seta cookie e retorna sucesso.

### 5. Endpoint admin via CLI
- **`src/app/api/admin/recover/route.ts`** (NOVO): protegido por header `Authorization: Bearer <ADMIN_SECRET>`.
  - `GET ?nome=xxx` → lista usuários que batem com o nome (retorna id, nome, turma, avatar, nº looks)
  - `POST { userId }` → gera código temporário de uso único, retorna o código
- Env var `ADMIN_SECRET` no docker-compose (default: `fitcheck-admin-2026`)
- Uso: `curl -H "Authorization: Bearer fitcheck-admin-2026" "https://fitcheck.vinicius.xyz/api/admin/recover?nome=João"` para buscar, depois `curl -X POST -H "Authorization: Bearer fitcheck-admin-2026" -d '{"userId":5}' "https://fitcheck.vinicius.xyz/api/admin/recover"` para gerar código temp.

### 6. Código visível no perfil
- **`src/app/(main)/profile/ProfileClient.tsx`**: remover email, mostrar código de recuperação com botão copiar no lugar.
- **`src/lib/actions.ts`**: remover `updateEmail`.
- **`src/app/(main)/profile/page.tsx`**: passar `codigoRecuperacao` para o client.

## Arquivos
| Arquivo | Ação |
|---------|------|
| `src/lib/schema.ts` | add `codigoRecuperacao`, add tabela `codigosTemporarios`, remove `email` |
| `src/lib/db.ts` | atualizar init SQL |
| `src/lib/auth.ts` | add `generateRecoveryCode()` |
| `src/app/api/auth/route.ts` | gerar código no registro |
| `src/app/api/auth/recover/route.ts` | NOVO — endpoint de recuperação |
| `src/app/api/admin/recover/route.ts` | NOVO — endpoint CLI admin |
| `src/app/login/page.tsx` | add step código + fluxo "já tenho conta" |
| `src/app/(main)/profile/ProfileClient.tsx` | remover email, mostrar código |
| `src/app/(main)/profile/page.tsx` | passar código ao client |
| `src/lib/actions.ts` | remover `updateEmail` |
| `docker-compose.yml` | add env `ADMIN_SECRET` |

## Verificação
1. Cadastrar → ver código → copiar → logout → recuperar com código
2. `curl` no endpoint admin → buscar usuário → gerar código temp → usar para logar → confirmar que só funciona 1x
3. Perfil mostra código com botão copiar
4. Build + deploy (deletar DB no servidor por causa das mudanças de schema)
