# Plano: Criar Task VIN no Linear via API Direta

## Contexto
O MCP plugin `mcp__plugin_linear_linear__*` está autenticado no workspace **Moonshot Partners**,
não no workspace pessoal **Vinicius Freitas** (team VIN). Por isso, `list_teams` retorna
Mom Ease / SchoolsOut / Moonshot e `create_issue` falha.

A API key correta para o workspace Vinicius Freitas já está no settings.json:
`__LINEAR_API_KEY__`

## Abordagem: curl direto na API GraphQL do Linear

### Passo 1 — Descobrir UUID do team VIN
```bash
curl -s -X POST https://api.linear.app/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer __LINEAR_API_KEY__" \
  -d '{"query": "{ teams { nodes { id name key } } }"}'
```
Esperado: retorna `{ id: "...", name: "Vinicius Freitas", key: "VIN" }`

### Passo 2 — Descobrir IDs dos labels existentes (Feature, Backend, Frontend, AI)
```bash
curl -s -X POST https://api.linear.app/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer __LINEAR_API_KEY__" \
  -d '{"query": "{ issueLabels { nodes { id name } } }"}'
```

### Passo 3 — Criar a issue VIN-31 via mutation GraphQL
```bash
curl -s -X POST https://api.linear.app/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer __LINEAR_API_KEY__" \
  -d '{
    "query": "mutation CreateIssue($input: IssueCreateInput!) { issueCreate(input: $input) { success issue { id identifier url } } }",
    "variables": {
      "input": {
        "teamId": "<UUID_DO_STEP_1>",
        "title": "feat: AI Smart Scheduling — Hybrid Auto-Balancer + Fallback",
        "priority": 2,
        "labelIds": ["<label_Feature>", "<label_Backend>", "<label_Frontend>"],
        "description": "<SPEC_COMPLETA>"
      }
    }
  }'
```

### Passo 4 (opcional) — Criar sub-tasks (Phase 1, 2, 3)
Após criar a issue pai, criar 3 sub-tasks linkadas com `parentId`.

## Spec da Issue

**Título:** `feat: AI Smart Scheduling — Hybrid Auto-Balancer + Fallback`
**Prioridade:** High (2)
**Labels:** Feature, Backend, Frontend

**Descrição completa:** (ver design aprovado no brainstorming)
- 6 variáveis de cálculo (Size, Coat, Complexity, Breed, Combo, Cumulative)
- Approach 3: Normal → auto-recommendation (1 click) / Apertado → TOP 3 slots
- 3 phases: Foundation, Smart Balancing, Continuous Learning
- Critérios de aceite: ≤15% erro, 80%+ test coverage, 1-click approve

## Verificação
- Issue criada no board VIN: https://linear.app/vinicius-freitas/team/VIN/all
- Identifier deve ser VIN-31 (ou próximo disponível)
- Labels e prioridade corretos
