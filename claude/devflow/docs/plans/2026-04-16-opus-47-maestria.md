# Opus 4.7 Maestria — devflow toolchain

**Data:** 2026-04-16
**Status:** DRAFT — aguardando aprovação
**Escopo:** `~/.claude/devflow/` (toolchain, não Paperweight)

## Contexto

Opus 4.7 lançou com preço idêntico ao 4.6 ($5/$25 per MTok) mas introduziu:
- **Novo tokenizer** que pode inflar contagem em até 1.35x pro mesmo conteúdo
- **Sem Fast mode** (que existe no 4.6 a 6x preço)
- Benchmarks melhores em coding/vision

Antes de adotar 4.7 no devflow, a exploração revelou **bugs sérios** que precisam ser corrigidos independentemente da migração:

### Achados críticos (exploração)

**B1. `hooks/cost_tracker.py` tem pricing obsoleto há meses**

Linhas 26-39 declaram:
| Modelo | No código | Real (Anthropic docs) | Erro |
|---|---|---|---|
| `claude-opus-4-6` | $15 in / $75 out | $5 in / $25 out | **3x over-reporting** |
| `claude-sonnet-4-6` | $3 in / $15 out | $3 in / $15 out | ok |
| `claude-haiku-4-5-20251001` | $0.80 in / $4 out | $1 in / $5 out | **25% under-reporting** |

Todo custo reportado via `[devflow:cost] ... $X` nos últimos meses em sessões Opus está 3x inflado. Tests em `hooks/tests/test_cost_tracker.py:74` encodificam o erro (`test_cost_opus` assertou $90 pra 1M+1M, real seria $30).

**B2. Nenhuma entrada pra `claude-opus-4-7`**

`CLAUDE_PRICING` dict não reconhece 4.7 → fallback para `_FALLBACK_MODEL = "claude-sonnet-4-6"` → custos de sessão Opus 4.7 são reportados como se fossem Sonnet (silenciosamente errados).

**B3. `telemetry/store.py` não tem coluna `model`**

Schema em `_COLUMNS` (linhas 20-40): 39 colunas, nenhuma captura qual modelo foi usado. `cost_usd` é persistido, mas sem context — impossível answering "quanto custei em Opus vs Sonnet essa semana?" apenas com o banco.

**B4. `devflow-model-routing` SKILL está desatualizado**

`skills/devflow-model-routing/SKILL.md` afirma "Opus is ~5x more expensive" — era verdade quando Opus = $15/$75 e Sonnet = $3/$15. Hoje (Opus 4.5/4.6/4.7 = $5/$25) vs Sonnet 4.6 = $3/$15 → ratio é **1.67x**, não 5x. Guidance desvia decisões.

Zero menção a Opus 4.7 ou aos trade-offs dele (tokenizer novo, sem Fast mode).

**B5. Nenhum ponto de integração direto ao Anthropic SDK**

`judge/evaluator.py:154`, `hooks/instinct_capture.py`, `agents/firewall.py` — todos chamam Claude via `claude -p` subprocess (Claude Code CLI). Portanto **cache_control é gerenciado pelo Claude Code, não pelo devflow**. Nosso único lever é:
1. Shaping de prompts pra maximizar auto-caching
2. Observação via telemetry (que hoje é cega a `cache_read_input_tokens`/`cache_creation_input_tokens` por modelo)

## Goals

1. **Corrigir pricing** pra refletir realidade (bug fix, urgente).
2. **Adicionar Opus 4.7** como modelo conhecido com pricing correto.
3. **Rastrear `model`** por execução → análise por modelo vira possível.
4. **Atualizar guidance** no skill de routing pra refletir pricing atual + decisão 4.6 vs 4.7.
5. **Documentar policy** de migração 4.6 → 4.7 com critérios objetivos.

## Non-goals

- Implementar caching direto (Claude Code faz isso por nós — única mudança seria usar SDK direto, blast radius enorme).
- Fetch dinâmico de pricing via API (YAGNI — pricing muda raramente).
- UI dashboard de telemetry por modelo (CLI é suficiente).
- Tocar em Paperweight (escopo separado).

---

## Workstreams

### W1 — Fix pricing em cost_tracker (bug crítico)

**Arquivo:** `hooks/cost_tracker.py`

**Mudanças:**
- Atualizar `CLAUDE_PRICING` pros preços reais:
  ```python
  "claude-opus-4-7":  {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_creation": 6.25}
  "claude-opus-4-6":  {"input": 5.00, "output": 25.00, "cache_read": 0.50, "cache_creation": 6.25}
  "claude-sonnet-4-6": {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_creation": 3.75}
  "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00, "cache_read": 0.10, "cache_creation": 1.25}
  ```
- Comment header com link pra pricing oficial e data da última revisão.
- Manter `_FALLBACK_MODEL = "claude-sonnet-4-6"` mas adicionar log de warning quando fallback é acionado (visibility pra próximo modelo desconhecido).

**Testes (atualizar `hooks/tests/test_cost_tracker.py`):**
- `test_cost_opus` — 1M+1M → $30.00 (antes $90)
- `test_cost_opus_47` (novo) — mesmo cálculo que 4.6
- `test_cost_haiku_45` — 1M+1M → $6.00 (antes $4.80)
- `test_cost_sonnet_46` — mantém $18
- `test_cache_tokens_reduce_cost` — verificar multipliers corretos
- `test_unknown_model_warns` (novo) — fallback loggado

**Acceptance:**
- Todos os testes passam.
- `python3.13 hooks/cost_tracker.py` com fixture Opus reporta valor 3x menor que antes.
- Nenhum teste antigo depende do valor errado.

---

### W2 — Adicionar coluna `model` em TelemetryStore

**Arquivos:** `telemetry/store.py`, `hooks/cost_tracker.py`

**Mudanças:**
- `_COLUMNS` e `_CREATE_TABLE`: adicionar `model TEXT`.
- `TelemetryStore._migrate()` (criar se não existe): `ALTER TABLE task_executions ADD COLUMN model TEXT` quando coluna ausente (idempotente).
- `cost_tracker.main()`: passar `"model": model` no dict do `record()`.
- `telemetry/cli.py stats`: adicionar `--by-model` flag que agrupa custo/contagem por modelo.

**Testes (`telemetry/tests/test_store.py` + `hooks/tests/test_cost_tracker.py`):**
- `test_migration_adds_model_column` — DB pré-existente ganha coluna sem erro.
- `test_record_persists_model` — `record({"model": "claude-opus-4-7", ...})` recupera corretamente.
- `test_cli_stats_by_model` — mock DB com mix, CLI imprime breakdown.

**Acceptance:**
- Session nova grava `model`.
- Sessions antigas ficam com `model = NULL` (OK).
- CLI mostra:
  ```
  model: claude-opus-4-7      runs: 12   cost: $4.32
  model: claude-opus-4-6      runs: 340  cost: $89.10
  model: claude-sonnet-4-6    runs: 1204 cost: $67.50
  model: NULL (legacy)        runs: 890  cost: $201.30
  ```

---

### W3 — Atualizar skill devflow-model-routing pra 4.7

**Arquivo:** `skills/devflow-model-routing/SKILL.md`

**Mudanças:**
- Tabela com pricing atual lado a lado com recomendação de uso.
- Corrigir "Opus is ~5x more expensive" → "Opus is ~1.67x more expensive than Sonnet per token, but tokenizer in 4.7 can use up to 1.35x more tokens for the same content — plan for 1.67×1.35 ≈ 2.25x effective cost vs Sonnet in worst case."
- Nova seção "Opus 4.6 vs 4.7":
  - 4.6 tem Fast mode (6x preço, $30/$150) pra quando latência importa
  - 4.7 melhor em benchmarks recentes, mas tokenizer novo
  - Default: 4.6 até medir inflação real no workload
- Incluir Opus 4.7 na tabela principal com ID `claude-opus-4-7`.

**Testes:** skill é markdown, sem unit test. Validação via `health_report.py` (stale detector) — adicionar timestamp de última revisão no frontmatter.

**Acceptance:**
- Claude carrega skill e cita pricing correto quando perguntado.
- Nenhuma referência a "5x more expensive" remanescente.

---

### W4 — Documentar policy de migração 4.6 → 4.7

**Arquivo novo:** `docs/opus-4-7-policy.md`

**Conteúdo:**
- **Default stance:** `claude-opus-4-6` continua default pra hooks devflow (post_task_judge, firewall, instinct_capture) até medição provar que 4.7 é ganho líquido.
- **Critério de flip:** inflação medida <15% em workload real AND benchmark/judge verdict não degrada (rodar A/B com `test_judge.py` fixtures).
- **Override per-task:** usuário pode sempre passar `--model claude-opus-4-7` manualmente ao Claude Code.
- **Como medir inflação:** usar `telemetry/cli.py stats --by-model` depois de 7 dias de uso misto.
- **Checkpoint:** revisar policy a cada 90 dias ou quando Anthropic lançar 4.8+.

**Acceptance:** doc existe, link no README (seção "Model routing" ou similar).

---

### W5 — (OPCIONAL) Observar caching automático do Claude Code

Não altera código — apenas documenta o comportamento observado depois que W1+W2 estejam rodando ≥7 dias.

**Ação:**
- Rodar queries ad-hoc na `devflow.db` olhando `cache_read_input_tokens` via... espera, isso não está no schema. **Só temos `cost_usd` agregado.**
- Pra realmente observar cache ratio, precisaríamos estender telemetry com token breakdown (input/output/cache_read/cache_creation).

**Proposta condicional:** se durante W1/W2 decidirmos que isso vale o esforço, W5 vira adicionar essas 4 colunas ao TelemetryStore e populá-las em `cost_tracker.record()`. Fica como decisão D4 abaixo.

---

## Ordem de execução

1. **W1** primeiro — bug fix urgente, merece commit atômico próprio.
2. **W2** em seguida — depende de W1 pra entender o shape do record.
3. **W3** e **W4** em paralelo — só docs, sem dependência.
4. **W5** só se aprovado em D4.

## Decisões que precisam da sua aprovação

**D1 — Source of truth para pricing**
- [A] Hardcode atualizado + link no comment (baixo custo, revisitar manualmente)
- [B] JSON file externo (`telemetry/pricing.json`), loader com fallback hardcoded
- [C] Fetch do endpoint oficial na primeira chamada + cache local

*Recomendação: [A]. Pricing muda ~1x/ano na Anthropic; over-engineer é waste.*

**D2 — Default do devflow-model-routing skill**
- [A] Continua recomendando Sonnet 4.6 como default, Opus 4.6 pra planning
- [B] Recomenda Opus 4.7 pra planning (nova versão é "melhor" em benchmarks)
- [C] Recomenda Opus 4.6 pra planning por default, 4.7 só com override explícito

*Recomendação: [C]. 4.6 tem Fast mode e tokenizer conhecido. Só pular pra 4.7 depois que W2 der dados pra decidir.*

**D3 — Backfill das rows legacy sem `model`**
- [A] Deixar NULL (honesto)
- [B] Marcar como "claude-sonnet-4-6" (default histórico)
- [C] Marcar como "unknown-pre-2026-04" (explícito)

*Recomendação: [A]. NULL é o estado real — vamos ser honestos.*

**D4 — Estender telemetry com token breakdown (W5)**
- [A] Skip — `cost_usd` é suficiente pros use cases atuais
- [B] Adicionar 4 colunas (`input_tokens`, `output_tokens`, `cache_read`, `cache_creation`)
- [C] Só adicionar `cache_read_ratio` calculada (float)

*Recomendação: [B] se W2 for smooth; [A] se quiser shippar rápido. Posso decidir depois de W1.*

**D5 — O que fazer com o branch `paperweight` que você quer otimizar também**
- Paperweight (em `/Users/vini/Developer/agents`) é um projeto separado com escopo diferente (Claude Code subprocess execution, pipeline phases, etc).
- [A] Esta spec cobre SÓ devflow; Paperweight fica pra outra sessão
- [B] Depois que devflow estiver pronto, replicar W1 (fix pricing) em `agents/budget.py` ou onde quer que Paperweight calcule custo

*Recomendação: [A]. Contexto já virou longo; Paperweight merece spec própria depois que os patterns aqui estejam validados.*

## Riscos

- **R1. Fix de pricing pode quebrar scripts/dashboards externos que dependem do valor inflado** — nenhum conhecido, mas se existir dashboard puxando `cost_usd` e comparando histórico, os dados ficam descontínuos. Mitigação: anotar data do fix no changelog.
- **R2. Migration de schema pode falhar em DB existente** — `ADD COLUMN` é idempotente em SQLite, mas teste de migração precisa cobrir "already exists" case. Tratado em W2.
- **R3. Pricing pode mudar antes do merge** — unlikely, monitorar.

## Verification checklist

- [ ] W1: `python3.13 -m pytest hooks/tests/test_cost_tracker.py -v` → green
- [ ] W1: run em fixture Opus → custo reportado é 1/3 do anterior
- [ ] W2: migration roda em DB existente sem error
- [ ] W2: `python3.13 telemetry/cli.py stats --by-model` produz output
- [ ] W3: skill tem seção "Opus 4.6 vs 4.7"
- [ ] W4: doc existe e está linkado
- [ ] Lint: `ruff check .` → clean
- [ ] Tests: `python3.13 -m pytest hooks/tests/ telemetry/tests/ -q` → 793+ passing
- [ ] Review Gate: `pr-review-toolkit:review-pr`

## Referências

- [Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing) — confirmou $5/$25 pra Opus 4.5-4.7 e tokenizer note pra 4.7
- `hooks/cost_tracker.py:26-39` — pricing table incorreta
- `telemetry/store.py:20-40` — schema sem `model`
- `skills/devflow-model-routing/SKILL.md` — guidance desatualizado
- `judge/evaluator.py:72` — default `claude-haiku-4-5-20251001`
