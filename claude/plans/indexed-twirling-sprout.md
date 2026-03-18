# Plano: Automatizar release iOS (App Store Review) e Android (produção)

## Contexto
Hoje o CI faz o build e sobe o artefato, mas não completa o release:
- **iOS**: sobe para TestFlight com `skip_waiting_for_build_processing: true` e para aí. Submission para App Store Review é manual.
- **Android**: sobe o AAB para a track `internal`. Promoção para `production` é manual.

O objetivo é fazer com que um push de tag `v*` resulte no app publicado nas lojas sem nenhuma ação manual.

---

## Mudanças

### 1. Android — `android/fastlane/Fastfile`

Trocar `track: "internal"` por `track: "production"` e adicionar `rollout: "1.0"`.

**Antes:**
```ruby
upload_to_play_store(
  track: "internal",
  aab: aab_path,
  ...
)
```

**Depois:**
```ruby
upload_to_play_store(
  track: "production",
  rollout: "1.0",
  aab: aab_path,
  ...
)
```

**Arquivo:** `android/fastlane/Fastfile` — apenas 2 linhas mudam.

---

### 2. iOS — `ios/fastlane/Fastfile`

Trocar `upload_to_testflight` por `upload_to_app_store` com submit automático.

**Antes:**
```ruby
upload_to_testflight(
  api_key: api_key,
  ipa: ipa_path,
  app_identifier: "com.momeasenow.app",
  skip_waiting_for_build_processing: true,
)
```

**Depois:**
```ruby
upload_to_app_store(
  api_key: api_key,
  ipa: ipa_path,
  app_identifier: "com.momeasenow.app",
  submit_for_review: true,
  automatic_release: true,
  force: true,
  skip_metadata: true,
  skip_screenshots: true,
)
```

**Parâmetros explicados:**
- `submit_for_review: true` — submete automaticamente após processamento
- `automatic_release: true` — após aprovação da Apple, vai ao ar sem ação manual
- `force: true` — pula prompts interativos no CI
- `skip_metadata/skip_screenshots: true` — não há pasta `metadata/` no iOS fastlane
- Remove `skip_waiting_for_build_processing: true` — precisa esperar o Apple processar o build antes de submeter

**Impacto no tempo de CI:** o iOS workflow vai ficar 15-30 minutos mais lento (aguarda Apple processar o IPA). Isso é inevitável — a Apple não aceita submission sem o build estar processado.

**Arquivo:** `ios/fastlane/Fastfile` — apenas o bloco `upload_to_testflight` é substituído.

---

## Arquivos modificados
- `android/fastlane/Fastfile`
- `ios/fastlane/Fastfile`

Nenhuma mudança nos workflows `.github/workflows/` — os secrets e o fluxo permanecem os mesmos.

---

## Verificação
1. Fazer merge de uma mudança qualquer em `main` (ou trigger manual via `workflow_dispatch`)
2. Confirmar no Google Play Console que o release aparece na track `production` com 100% rollout
3. Confirmar no App Store Connect que o build está em "Waiting for Review"
