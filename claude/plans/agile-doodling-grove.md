# CI/CD com GitHub Actions — Plano

## Contexto
O projeto PrimeLeague tem 1,256 testes passando mas zero automação de CI/CD. Qualquer PR pode ser mergeado sem rodar testes. Precisamos de um pipeline que garanta qualidade automaticamente.

## O que será criado

**Arquivo único:** `.github/workflows/ci.yml`

## Pipeline

### Triggers
- Push em `develop` e `main`
- Pull requests para `develop` e `main`

### Steps
1. **Checkout** — `actions/checkout@v4`
2. **JDK 21** — `actions/setup-java@v4` com Temurin (Gradle 8.5 requer JDK 17+, compila para Java 8 bytecode)
3. **Setup Gradle** — `gradle/actions/setup-gradle@v3` (cache automático de `~/.gradle`, build scan)
4. **Build + Test** — `./gradlew build --no-daemon --parallel --stacktrace`
5. **Upload test reports** — Apenas em falha, retenção 7 dias
6. **Upload shadow JAR** — Apenas em push (não em PRs), retenção 30 dias

### Decisões-chave
- **JDK 21** (não 8): Gradle 8.5 + Mockito 5.x requerem JDK 17+; o `sourceCompatibility = 1.8` garante bytecode Java 8
- **`cache-read-only` em PRs**: PRs não poluem o cache; só `develop`/`main` atualizam
- **`--no-daemon`**: Runners são efêmeros, daemon é desperdício
- **Concurrency control**: Cancela runs redundantes por branch/PR
- **Permissions mínimas**: Apenas `contents: read`
- **Sem matrix strategy**: Apenas um target (Java 8, Linux)
- **`build` em vez de `test`**: Um único Gradle invocation roda compile + test + shadowJar

## Verificação
```bash
# Após criar o arquivo:
# 1. Validar YAML syntax
# 2. Push e verificar que o workflow aparece na tab Actions do GitHub
# 3. Criar PR de teste para ver o pipeline rodar
```

## Arquivos
- Criar: `.github/workflows/ci.yml`
- Referência: `build.gradle.kts` (shadow JAR output), `gradle.properties` (parallel + cache flags)
