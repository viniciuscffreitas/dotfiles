# Otimizar deploy do frontend: build no GitHub Actions

## Contexto

O deploy do frontend leva ~2.5min porque o Flutter é compilado **na VPS** a cada push (via Docker multi-stage build). O CI já compila o mesmo código no GitHub Actions e descarta o resultado. O objetivo é compilar no GitHub Actions (CPUs mais rápidos, cache do Flutter SDK) e transferir apenas os arquivos estáticos (~5MB) para a VPS.

**Resultado esperado:** deploy de ~2.5min → ~30s após o build (o build em si roda no GH Actions em paralelo).

## Mudanças

### 1. `cisnebranco-bt/docker-compose.yml` — Web service: image + volumes

Substituir `build: ../cisnebranco-web` por `image: nginx:alpine` com volume mounts. O container passa a servir arquivos do host diretamente, sem build Docker.

```yaml
web:
  profiles: ["web"]
  image: nginx:alpine
  container_name: cisnebranco-web
  restart: unless-stopped
  volumes:
    - ../cisnebranco-web/build/web:/usr/share/nginx/html:ro
    - ../cisnebranco-web/nginx.conf:/etc/nginx/conf.d/default.conf:ro
  ports:
    - "8092:80"
  networks:
    - npm_network
```

### 2. `cisnebranco_web/.github/workflows/deploy.yml` — Build no GH Actions + SCP

Novo pipeline:
1. Checkout + Flutter setup (com cache)
2. `flutter build web --release`
3. Tar do build para transferência atômica
4. SCP do tar para VPS
5. SSH: extrair, substituir build antigo, reload nginx

```yaml
steps:
  - uses: actions/checkout@v4
  - uses: subosito/flutter-action@v2
    with: { channel: stable, cache: true }
  - run: flutter pub get
  - run: flutter build web --release
  - run: tar czf build.tar.gz -C build web     # tar para transferência atômica
  - name: Upload build
    uses: appleboy/scp-action@v0.1.7
    with:
      source: "build.tar.gz,nginx.conf"
      target: "/tmp/cisnebranco-deploy"
  - name: Activate
    uses: appleboy/ssh-action@v1
    with:
      script: |
        DEST=~/www/cisnebranco-web
        rm -rf "$DEST/build/web"
        mkdir -p "$DEST/build"
        tar xzf /tmp/cisnebranco-deploy/build.tar.gz -C "$DEST/build"
        cp /tmp/cisnebranco-deploy/nginx.conf "$DEST/nginx.conf"
        rm -rf /tmp/cisnebranco-deploy
        cd ~/www/cisnebranco-bt
        docker compose --profile web up -d web
        docker exec cisnebranco-web nginx -s reload
```

### 3. `cisnebranco-bt/.github/workflows/deploy.yml` — Remover frontend do backend deploy

- Remover o bloco de `git pull` do frontend
- Remover `--profile web` do `docker compose` (backend não gerencia mais o web container)
- Manter apenas o deploy do backend

### 4. `cisnebranco_web/.github/workflows/ci.yml` — Sem mudanças

O CI continua como está (analyze + build para validação de PRs).

## Arquivos modificados

| Repo | Arquivo | Mudança |
|------|---------|---------|
| `cisnebranco-bt` | `docker-compose.yml` | web: image + volumes em vez de build |
| `cisnebranco-bt` | `.github/workflows/deploy.yml` | Remove frontend, só backend |
| `cisnebranco_web` | `.github/workflows/deploy.yml` | Build no GH Actions + SCP + reload |

## Ordem de deploy após merge

1. **Primeiro**: merge no backend (`cisnebranco-bt`) — atualiza docker-compose.yml na VPS
2. **Segundo**: merge no frontend (`cisnebranco_web`) — primeiro deploy com novo pipeline

## Verificação

1. Push para `main` do frontend → GitHub Actions deve: build + SCP + reload
2. Verificar que o deploy leva <2min total (build ~90s + transfer ~10s + reload ~5s)
3. Acessar `petshopcisnebranco.com.br` e confirmar que o app carrega
4. Verificar que o backend deploy não toca mais no web container
