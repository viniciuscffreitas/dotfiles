# Flutter Web Frontend — Cisne Branco Pet Shop

## Context

O backend Spring Boot está 100% completo e em produção (`https://api.petshopcisnebranco.com.br/api/`). Agora precisamos do frontend para consumir a API.

**Decisões do usuário:**
- **Stack**: Flutter Web (você já domina Dart, compila para web/tablet)
- **Auth**: HttpOnly cookies (mais seguro que localStorage contra XSS)
- **Real-time**: Server-Sent Events (SSE) para updates de status de OS
- **Deploy**: Mesma VPS via Nginx Proxy Manager
- **Design**: Tema azul marinho do logo (simples e clean)

**Justificativa técnica:**
- Flutter Web permite código compartilhado entre web (recepção) e potencial app mobile/tablet (tosadoras)
- HttpOnly cookies + SameSite=Lax protegem contra XSS e CSRF em mesmo domínio
- SSE é mais simples que WebSocket e suficiente para updates unidirecionais (backend → frontend)
- VPS única simplifica infraestrutura e reduz custos

---

## Arquitetura

```
petshopcisnebranco.com.br (Flutter Web)
├── Riverpod 3.0 (state management)
├── Dio + BrowserHttpClientAdapter (HTTP client com cookie support)
├── EventFlux ou XMLHttpRequest (SSE client para Web)
├── go_router (navegação)
├── Build: flutter build web --wasm --web-renderer skwasm
└── Deploy: Docker container Nginx Alpine

api.petshopcisnebranco.com.br (Spring Boot - já existe)
├── SSE Endpoint: SseEmitter (novo)
├── CORS: allowCredentials=true, allowedOrigins=https://petshopcisnebranco.com.br
├── Cookie config: httpOnly=true, secure=true, sameSite=Lax
└── JWT em httpOnly cookie (não expor no corpo da resposta)
```

---

## Implementação — Fases

### Fase 1: Setup Inicial + Auth (Semana 1)

#### 1.1 Criar projeto Flutter Web

```bash
flutter create cisnebranco_web --platforms=web
cd cisnebranco_web
```

**Dependências em `pubspec.yaml`:**
```yaml
dependencies:
  flutter:
    sdk: flutter

  # State management
  flutter_riverpod: ^2.6.1
  riverpod_annotation: ^2.5.0

  # HTTP
  dio: ^5.7.0

  # SSE
  eventflux: ^3.2.0

  # Navegação
  go_router: ^14.6.2

  # UI
  flutter_svg: ^2.0.16
  google_fonts: ^6.2.1

dev_dependencies:
  flutter_test:
    sdk: flutter
  flutter_lints: ^5.0.0
  riverpod_generator: ^2.5.0
  build_runner: ^2.4.14
  custom_lint: ^0.7.0
  riverpod_lint: ^2.5.0
```

#### 1.2 Configurar API client com cookies

**`lib/core/api/api_client.dart`:**
```dart
import 'package:dio/dio.dart';
import 'package:dio/browser.dart';
import 'package:flutter/foundation.dart' show kIsWeb;

class ApiClient {
  static const baseUrl = String.fromEnvironment(
    'API_URL',
    defaultValue: 'https://api.petshopcisnebranco.com.br/api',
  );

  late final Dio _dio;

  ApiClient() {
    _dio = Dio(BaseOptions(
      baseUrl: baseUrl,
      connectTimeout: const Duration(seconds: 30),
      receiveTimeout: const Duration(seconds: 30),
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
    ));

    // CRÍTICO: habilitar cookies em Flutter Web
    if (kIsWeb) {
      (_dio.httpClientAdapter as BrowserHttpClientAdapter).withCredentials = true;
    }

    _setupInterceptors();
  }

  void _setupInterceptors() {
    _dio.interceptors.add(
      InterceptorsWrapper(
        onError: (error, handler) async {
          if (error.response?.statusCode == 401) {
            // Cookie expirado, redirecionar para login
            // Implementar com go_router
          }
          return handler.next(error);
        },
      ),
    );
  }

  Dio get dio => _dio;
}
```

**Provider Riverpod:**
```dart
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'api_client.g.dart';

@riverpod
ApiClient apiClient(ApiClientRef ref) {
  return ApiClient();
}
```

#### 1.3 Implementar AuthService

**`lib/features/auth/data/auth_repository.dart`:**
```dart
import 'package:dio/dio.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';
import '../../../core/api/api_client.dart';

part 'auth_repository.g.dart';

class AuthRepository {
  final Dio _dio;

  AuthRepository(this._dio);

  Future<Map<String, dynamic>> login(String username, String password) async {
    final response = await _dio.post('/auth/login', data: {
      'username': username,
      'password': password,
    });

    // Cookie é automaticamente armazenado pelo browser
    // Retornar apenas dados do usuário (sem JWT no body)
    return response.data as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> getCurrentUser() async {
    // Cookie é automaticamente enviado
    final response = await _dio.get('/users/me');
    return response.data as Map<String, dynamic>;
  }

  Future<void> logout() async {
    await _dio.post('/auth/logout');
  }
}

@riverpod
AuthRepository authRepository(AuthRepositoryRef ref) {
  final dio = ref.watch(apiClientProvider).dio;
  return AuthRepository(dio);
}
```

**`lib/features/auth/domain/auth_state.dart`:**
```dart
import 'package:freezed_annotation/freezed_annotation.dart';

part 'auth_state.freezed.dart';

@freezed
class AuthState with _$AuthState {
  const factory AuthState.unauthenticated() = Unauthenticated;
  const factory AuthState.loading() = Loading;
  const factory AuthState.authenticated({
    required String username,
    required String role,
    int? groomerId,
  }) = Authenticated;
  const factory AuthState.error(String message) = AuthError;
}
```

**Controller:**
```dart
import 'package:riverpod_annotation/riverpod_annotation.dart';
import '../data/auth_repository.dart';
import '../domain/auth_state.dart';

part 'auth_controller.g.dart';

@riverpod
class AuthController extends _$AuthController {
  @override
  AuthState build() {
    _checkAuthStatus();
    return const AuthState.loading();
  }

  Future<void> _checkAuthStatus() async {
    try {
      final repo = ref.read(authRepositoryProvider);
      final user = await repo.getCurrentUser();
      state = AuthState.authenticated(
        username: user['username'],
        role: user['role'],
        groomerId: user['groomerId'],
      );
    } catch (e) {
      state = const AuthState.unauthenticated();
    }
  }

  Future<void> login(String username, String password) async {
    state = const AuthState.loading();
    try {
      final repo = ref.read(authRepositoryProvider);
      final user = await repo.login(username, password);
      state = AuthState.authenticated(
        username: user['username'],
        role: user['role'],
        groomerId: user['groomerId'],
      );
    } catch (e) {
      state = AuthState.error(e.toString());
    }
  }

  Future<void> logout() async {
    final repo = ref.read(authRepositoryProvider);
    await repo.logout();
    state = const AuthState.unauthenticated();
  }
}
```

#### 1.4 Tela de Login

**`lib/features/auth/presentation/login_screen.dart`:**
```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../application/auth_controller.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final authState = ref.watch(authControllerProvider);

    return Scaffold(
      backgroundColor: const Color(0xFF1A237E), // Azul marinho
      body: Center(
        child: Card(
          margin: const EdgeInsets.all(32),
          child: Container(
            constraints: const BoxConstraints(maxWidth: 400),
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                // Logo
                Text(
                  'Cisne Branco',
                  style: Theme.of(context).textTheme.headlineMedium,
                ),
                const SizedBox(height: 32),

                // Username
                TextField(
                  controller: _usernameController,
                  decoration: const InputDecoration(
                    labelText: 'Usuário',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 16),

                // Password
                TextField(
                  controller: _passwordController,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: 'Senha',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 24),

                // Login button
                authState.maybeWhen(
                  loading: () => const CircularProgressIndicator(),
                  error: (msg) => Column(
                    children: [
                      Text(msg, style: const TextStyle(color: Colors.red)),
                      const SizedBox(height: 16),
                      _buildLoginButton(),
                    ],
                  ),
                  orElse: _buildLoginButton,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildLoginButton() {
    return ElevatedButton(
      onPressed: () {
        ref.read(authControllerProvider.notifier).login(
          _usernameController.text,
          _passwordController.text,
        );
      },
      child: const Padding(
        padding: EdgeInsets.symmetric(vertical: 12, horizontal: 48),
        child: Text('Entrar'),
      ),
    );
  }
}
```

#### 1.5 Navegação com go_router

**`lib/core/router/app_router.dart`:**
```dart
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../features/auth/presentation/login_screen.dart';
import '../../features/auth/application/auth_controller.dart';
import '../../features/dashboard/presentation/dashboard_screen.dart';

final appRouterProvider = Provider<GoRouter>((ref) {
  final authState = ref.watch(authControllerProvider);

  return GoRouter(
    initialLocation: '/login',
    redirect: (context, state) {
      final isAuthenticated = authState is Authenticated;
      final isLoginRoute = state.matchedLocation == '/login';

      if (!isAuthenticated && !isLoginRoute) {
        return '/login';
      }
      if (isAuthenticated && isLoginRoute) {
        return '/';
      }
      return null;
    },
    routes: [
      GoRoute(
        path: '/login',
        builder: (context, state) => const LoginScreen(),
      ),
      GoRoute(
        path: '/',
        builder: (context, state) => const DashboardScreen(),
      ),
      // Mais rotas...
    ],
  );
});
```

---

### Fase 2: Backend — SSE Endpoint (Semana 1)

#### 2.1 Criar SseController no Spring Boot

**`src/main/java/com/cisnebranco/controller/SseController.java`:**
```java
@RestController
@RequestMapping("/sse")
@RequiredArgsConstructor
@Slf4j
public class SseController {

    private final SseEmitterService sseEmitterService;

    @GetMapping(value = "/notifications", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    @PreAuthorize("isAuthenticated()")
    public SseEmitter streamNotifications(@AuthenticationPrincipal UserPrincipal principal) {
        log.info("SSE connection opened for user: {}", principal.getUsername());
        return sseEmitterService.createEmitter(principal.getId());
    }
}
```

**`src/main/java/com/cisnebranco/service/SseEmitterService.java`:**
```java
@Service
@Slf4j
public class SseEmitterService {

    private final Map<Long, SseEmitter> emitters = new ConcurrentHashMap<>();

    public SseEmitter createEmitter(Long userId) {
        SseEmitter emitter = new SseEmitter(Long.MAX_VALUE); // No timeout

        emitter.onCompletion(() -> {
            log.info("SSE completed for user: {}", userId);
            emitters.remove(userId);
        });

        emitter.onTimeout(() -> {
            log.warn("SSE timeout for user: {}", userId);
            emitters.remove(userId);
        });

        emitter.onError((e) -> {
            log.error("SSE error for user: {}", userId, e);
            emitters.remove(userId);
        });

        emitters.put(userId, emitter);

        // Send initial connection success event
        try {
            emitter.send(SseEmitter.event()
                .name("connected")
                .data("Connected to notifications stream"));
        } catch (IOException e) {
            log.error("Failed to send initial SSE event", e);
        }

        return emitter;
    }

    public void sendToUser(Long userId, String eventName, Object data) {
        SseEmitter emitter = emitters.get(userId);
        if (emitter != null) {
            try {
                emitter.send(SseEmitter.event().name(eventName).data(data));
            } catch (IOException e) {
                log.error("Failed to send SSE event to user: {}", userId, e);
                emitters.remove(userId);
            }
        }
    }

    public void sendToAll(String eventName, Object data) {
        emitters.forEach((userId, emitter) -> {
            try {
                emitter.send(SseEmitter.event().name(eventName).data(data));
            } catch (IOException e) {
                log.error("Failed to send SSE event to user: {}", userId, e);
                emitters.remove(userId);
            }
        });
    }
}
```

#### 2.2 Emitir eventos quando OS muda de status

**Modificar `TechnicalOsService.updateStatus()`:**
```java
@Transactional
public TechnicalOsResponse updateStatus(Long osId, OsStatusUpdateRequest request) {
    TechnicalOs os = findEntityById(osId);
    // ... existing validation ...

    os.setStatus(newStatus);
    TechnicalOs saved = osRepository.save(os);

    // Emitir evento SSE para todos os usuários conectados
    sseEmitterService.sendToAll("os-status-changed", Map.of(
        "osId", osId,
        "status", newStatus.name(),
        "petName", os.getPet().getName()
    ));

    return osMapper.toResponse(saved);
}
```

#### 2.3 Atualizar SecurityConfig para permitir SSE

```java
@Bean
public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
    http
        // ... existing config ...
        .authorizeHttpRequests(auth -> auth
            .requestMatchers("/auth/**").permitAll()
            .requestMatchers("/sse/**").authenticated() // SSE requer auth
            .anyRequest().authenticated()
        );
    return http.build();
}
```

#### 2.4 Modificar AuthService para não retornar JWT no body

**Atualmente `AuthResponse` tem `accessToken` e `refreshToken`. Mudar para:**
```java
public record AuthResponse(
    String role,
    Integer groomerId,
    String username
) {}

@Transactional
public ResponseEntity<AuthResponse> login(LoginRequest request, HttpServletResponse response) {
    Authentication authentication = authenticationManager.authenticate(
        new UsernamePasswordAuthenticationToken(request.username(), request.password())
    );

    UserPrincipal principal = (UserPrincipal) authentication.getPrincipal();
    String accessToken = tokenProvider.generateAccessToken(principal);
    String refreshToken = createRefreshToken(principal.getId());

    // Set httpOnly cookie
    Cookie jwtCookie = new Cookie("jwt", accessToken);
    jwtCookie.setHttpOnly(true);
    jwtCookie.setSecure(true); // HTTPS only
    jwtCookie.setPath("/");
    jwtCookie.setMaxAge(3600); // 1 hour
    jwtCookie.setSameSite("Lax");
    response.addCookie(jwtCookie);

    Cookie refreshCookie = new Cookie("refresh_token", refreshToken);
    refreshCookie.setHttpOnly(true);
    refreshCookie.setSecure(true);
    refreshCookie.setPath("/");
    refreshCookie.setMaxAge(604800); // 7 days
    refreshCookie.setSameSite("Lax");
    response.addCookie(refreshCookie);

    return ResponseEntity.ok(new AuthResponse(
        principal.getRole().name(),
        principal.getGroomerId(),
        principal.getUsername()
    ));
}
```

#### 2.5 Modificar JwtAuthenticationFilter para ler cookie

```java
@Override
protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain) {
    try {
        String jwt = extractJwtFromCookie(request);

        if (jwt != null && tokenProvider.validateToken(jwt)) {
            // ... existing validation ...
        }
    } catch (Exception e) {
        logger.error("Cannot set user authentication", e);
    }

    filterChain.doFilter(request, response);
}

private String extractJwtFromCookie(HttpServletRequest request) {
    Cookie[] cookies = request.getCookies();
    if (cookies != null) {
        for (Cookie cookie : cookies) {
            if ("jwt".equals(cookie.getName())) {
                return cookie.getValue();
            }
        }
    }
    return null;
}
```

---

### Fase 3: SSE Client no Flutter (Semana 2)

#### 3.1 SSE Service

**`lib/core/sse/sse_service.dart`:**
```dart
import 'dart:async';
import 'package:eventflux/eventflux.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'sse_service.g.dart';

class SseService {
  final String baseUrl;
  StreamController<Map<String, dynamic>>? _controller;

  SseService({required this.baseUrl});

  Stream<Map<String, dynamic>> connect() {
    _controller = StreamController<Map<String, dynamic>>.broadcast();

    EventFlux.instance.connect(
      ConnectionType.get,
      '$baseUrl/sse/notifications',
      autoReconnect: true,
      reconnectConfig: ReconnectConfig(
        mode: ReconnectMode.exponential,
        interval: const Duration(seconds: 5),
        maxAttempts: 10,
      ),
      onSuccessCallback: (response) {
        response.stream?.listen((event) {
          if (event.event == 'os-status-changed') {
            _controller?.add(jsonDecode(event.data as String));
          }
        });
      },
      onError: (error) {
        print('SSE Error: $error');
      },
    );

    return _controller!.stream;
  }

  void disconnect() {
    EventFlux.instance.disconnect();
    _controller?.close();
  }
}

@riverpod
SseService sseService(SseServiceRef ref) {
  final service = SseService(
    baseUrl: 'https://api.petshopcisnebranco.com.br/api',
  );

  ref.onDispose(() {
    service.disconnect();
  });

  return service;
}

@riverpod
Stream<Map<String, dynamic>> osNotificationStream(OsNotificationStreamRef ref) {
  final sseService = ref.watch(sseServiceProvider);
  return sseService.connect();
}
```

#### 3.2 Widget que escuta SSE

```dart
class OsListScreen extends ConsumerWidget {
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final notificationStream = ref.watch(osNotificationStreamProvider);

    // Listen to SSE updates
    notificationStream.when(
      data: (notification) {
        // Atualizar estado local ou refetch lista de OS
        final osId = notification['osId'];
        final status = notification['status'];

        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('OS #$osId: status → $status')),
        );

        // Refetch lista
        ref.invalidate(osListProvider);
      },
      loading: () {},
      error: (err, stack) => print('SSE Error: $err'),
    );

    // Resto do widget...
    return Scaffold(/* ... */);
  }
}
```

---

### Fase 4: Telas Principais (Semanas 2-3)

#### Prioridade de telas:

1. **Dashboard** (Semana 2)
   - Card com total de OS WAITING / IN_PROGRESS / READY
   - Lista das OS mais recentes
   - Atalhos para check-in e agendamento

2. **Check-in de Pet** (Semana 2)
   - Buscar cliente
   - Selecionar pet
   - Selecionar serviços
   - Atribuir groomer (opcional)
   - Criar OS

3. **Lista de OS** (Semana 2)
   - Filtros (status, groomer, data, cliente)
   - Tabela com paginação
   - Atualização real-time via SSE

4. **Detalhes de OS** (Semana 3)
   - Ver informações completas
   - Atualizar status (WAITING → IN_PROGRESS → READY → DELIVERED)
   - Upload de fotos
   - Health checklist
   - Pagamentos

5. **Agendamento** (Semana 3)
   - Calendar view com available slots
   - Criar appointment
   - Converter appointment → OS no check-in

6. **Relatórios** (Semana 3)
   - Receita diária
   - Desempenho de groomers
   - Top clientes
   - Export CSV/PDF

7. **Gestão de Clientes/Pets** (Semana 4)
   - CRUD clientes
   - CRUD pets
   - Soft delete

---

### Fase 5: Deploy (Semana 4)

#### 5.1 Estrutura no VPS

```
~/www/
├── cisnebranco-bt/              # Backend (já existe)
│   └── docker-compose.yml
└── cisnebranco-web/             # Frontend (novo)
    ├── Dockerfile
    ├── nginx.conf
    └── (código Flutter)
```

#### 5.2 Dockerfile para Flutter Web

**`~/www/cisnebranco-web/Dockerfile`:**
```dockerfile
# Stage 1: Build Flutter Web
FROM ubuntu:22.04 AS build

RUN apt-get update && apt-get install -y \
    curl git unzip xz-utils zip libglu1-mesa \
    && rm -rf /var/lib/apt/lists/*

RUN git clone https://github.com/flutter/flutter.git -b stable /flutter
ENV PATH="/flutter/bin:${PATH}"

WORKDIR /app
COPY pubspec.* ./
RUN flutter pub get

COPY . .
RUN flutter build web --release --wasm --base-href=/

# Stage 2: Serve with Nginx
FROM nginx:alpine

COPY --from=build /app/build/web /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

#### 5.3 nginx.conf

**`~/www/cisnebranco-web/nginx.conf`:**
```nginx
server {
    listen 80;
    server_name localhost;
    root /usr/share/nginx/html;
    index index.html;

    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_min_length 1000;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/wasm;

    # Client-side routing (todas as rotas → index.html)
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Cache static assets
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot|wasm)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Don't cache index.html
    location = /index.html {
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }
}
```

#### 5.4 Adicionar ao docker-compose.yml do backend

**Modificar `~/www/cisnebranco-bt/docker-compose.yml`:**
```yaml
services:
  cisnebranco-api:
    # ... existing config ...

  cisnebranco-db:
    # ... existing config ...

  cisnebranco-web:
    build:
      context: ../cisnebranco-web
      dockerfile: Dockerfile
    container_name: cisnebranco-web
    restart: unless-stopped
    ports:
      - "8092:80"
    networks:
      - npm_default

networks:
  npm_default:
    external: true
```

#### 5.5 Configurar NPM (Nginx Proxy Manager)

No NPM UI:
1. **Criar Proxy Host** para `petshopcisnebranco.com.br`
2. Forward to: `cisnebranco-web:80` (nome do container)
3. Habilitar SSL com Let's Encrypt
4. Access List: nenhum (público)
5. Advanced: (deixar vazio, já está no nginx.conf)

**Resultado:**
- Frontend: `https://petshopcisnebranco.com.br` → container cisnebranco-web:80
- Backend: `https://api.petshopcisnebranco.com.br` → container cisnebranco-api:8080 (já existe)

#### 5.6 GitHub Actions CI/CD

**`.github/workflows/deploy-web.yml`:**
```yaml
name: Deploy Flutter Web

on:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  deploy:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Deploy to VPS via SSH
        uses: appleboy/ssh-action@v1.0.0
        with:
          host: vinicius.xyz
          username: vinicius
          key: ${{ secrets.VPS_SSH_KEY }}
          script: |
            cd ~/www/cisnebranco-web
            git pull origin main
            cd ~/www/cisnebranco-bt
            docker-compose build cisnebranco-web
            docker-compose up -d cisnebranco-web
```

---

## Arquivos Críticos

### Backend (Spring Boot)
1. **SseController.java** (novo) — endpoint SSE
2. **SseEmitterService.java** (novo) — gerencia emitters
3. **TechnicalOsService.java** (modificar) — emitir eventos SSE
4. **AuthService.java** (modificar) — cookies httpOnly
5. **JwtAuthenticationFilter.java** (modificar) — ler cookie
6. **SecurityConfig.java** (modificar) — permitir /sse/**
7. **WebConfig.java** (modificar) — CORS allowCredentials

### Frontend (Flutter)
1. **api_client.dart** — Dio com cookies
2. **auth_repository.dart** — login/logout
3. **auth_controller.dart** — state management
4. **sse_service.dart** — SSE client
5. **app_router.dart** — navegação
6. **login_screen.dart** — tela login
7. **dashboard_screen.dart** — tela inicial
8. **Dockerfile** — build Flutter + Nginx
9. **nginx.conf** — servir static files

---

## Verificação

### Backend
1. Testar SSE: `curl -N -H "Cookie: jwt=..." https://api.petshopcisnebranco.com.br/api/sse/notifications`
2. Testar login com cookie: verificar que `Set-Cookie` está presente na resposta
3. Testar CORS: `curl -H "Origin: https://petshopcisnebranco.com.br" https://api.petshopcisnebranco.com.br/api/breeds`

### Frontend
1. Build local: `flutter build web --release --wasm`
2. Testar localmente: `flutter run -d chrome --web-port=3000`
3. Verificar cookies no DevTools: Application → Cookies
4. Testar SSE: abrir console e ver eventos chegando

### Deploy
1. Push para GitHub → CD roda automaticamente
2. Acessar `https://petshopcisnebranco.com.br`
3. Login e verificar que cookie é setado
4. Atualizar status de uma OS e ver notificação SSE na tela

---

## Timeline

| Semana | Fase | Entregas |
|---|---|---|
| 1 | Setup + Auth | Flutter project, login, auth state, SSE backend |
| 2 | SSE + Telas base | Dashboard, check-in, lista OS com real-time |
| 3 | Telas avançadas | Detalhes OS, agendamento, relatórios |
| 4 | Gestão + Deploy | CRUD clientes/pets, Docker, NPM, CD |

---

## Fontes

### Flutter Web + Cookies
- [Consuming Web APIs with Cookies in Flutter](https://medium.com/@yash22202/consuming-web-apis-with-cookies-in-flutter-without-losing-sessions-2d43fe600996)
- [Bridging Worlds: Secure Cookie Authentication with Flutter Web](https://medium.com/@edawarekaro/bridging-worlds-implementing-secure-cookie-authentication-with-net-core-and-flutter-web-f6ce504c1a8d)
- [How can I make an http request using cookies on Flutter web using Dio](https://medium.com/@mayintuji/how-can-i-make-an-http-request-using-cookies-on-flutter-web-using-dio-or-any-other-library-a198003a9757)

### SSE em Flutter
- [Actual Real-Time SSE in Flutter Web](https://medium.com/@thorsten_79724/actual-real-time-server-sent-events-sse-in-flutter-web-3e22f3d65445)
- [Server Sent Events with Flutter](https://medium.com/flutter-community/server-sent-events-sse-with-flutter-cf331f978b4f)
- [EventFlux package](https://pub.dev/packages/eventflux)
- [flutter_client_sse package](https://pub.dev/packages/flutter_client_sse)

### Deploy Flutter Web + Nginx
- [How To Host Flutter Web In Linux Using Nginx](https://medium.com/flutter-community/how-to-host-flutter-using-nginx-a71bcb11d96)
- [Easily Hosting Flutter Web App on VPS Using Nginx](https://yawarothman.medium.com/easily-hosting-your-flutter-web-app-on-a-vps-using-nginx-46576d03b30a)
- [Deploying Flutter Web App with NGINX](https://medium.com/fludev/deploying-a-flutter-web-app-with-nginx-a-complete-guide-400a4cdd8347)
- [Dockerising Flutter Web app](https://www.glukhov.org/post/2025/06/dockerising-flutter-web-app/)

### SSE em Spring Boot
- [How to Implement SSE in Spring Boot](https://medium.com/@AlexanderObregon/how-to-implement-server-sent-events-sse-in-spring-boot-620024272ccb)
- [Server-Sent Events with Spring Boot](https://thamizhelango.medium.com/server-sent-events-with-spring-boot-a-complete-guide-ff3b329d5f96)
- [Server-Sent Events in Spring | Baeldung](https://www.baeldung.com/spring-server-sent-events)

### Flutter Web Best Practices
- [Best practices for optimizing Flutter web loading speed](https://blog.flutter.dev/best-practices-for-optimizing-flutter-web-loading-speed-7cc0df14ce5c)
- [Optimizing Flutter Web for Production](https://medium.com/@reach.subhanu/optimizing-flutter-web-for-production-advanced-techniques-in-code-splitting-seo-and-hosting-a89679afe939)
- [Flutter Web renderers documentation](https://docs.flutter.dev/platform-integration/web/renderers)
- [Support for WebAssembly (Wasm)](https://docs.flutter.dev/platform-integration/web/wasm)
