# Collaborative UML Editor

MVP basado en el dominio del proyecto de referencia, reconstruido en la raíz con FastAPI, React/Vite, PostgreSQL, Redis y Nginx.

## Development with HMR

The SQL Editor is a right-side sliding panel over the board, approximately 55vw wide, with partial and expanded modes. It keeps part of the UML canvas visible and uses internal scrolling for large DDL documents. The route `#/board/<id>/sql` opens this same panel.

The root compose file runs the frontend with Vite and HMR by default:

```bash
docker compose --env-file .env up
```

Open `http://localhost:8080/#/dashboard`. Vite runs inside the frontend container, `./frontend` is mounted into it, and changes are applied immediately through HMR. Vite uses polling because Windows bind mounts do not reliably forward filesystem events into Linux containers, so source edits do not require a browser reload. REST requests and browser WebSocket connections under `/api` are proxied to the `backend` service.

Las rutas hash son `#/dashboard` para **Proyectos**, `#/board/<id>` para el editor de pizarras, `#/board/<id>/sql` para abrir el panel SQL en esa pizarra y `#/gestion-usuarios` para **Gestión de usuarios**. La última ruta y su enlace solo están disponibles para administradores; el backend sigue siendo la autoridad para `/admin/users`.

Desde una pizarra, el botón superior `SQL Editor` abre el panel lateral derecho directamente en modo parcial, ocupa aproximadamente el 55% de la ventana y deja visible parte del diagrama. Mientras está abierto, el mismo botón cambia a `Ocultar SQL` y oculta el panel sin dejar una pestaña lateral colapsada. `⌃ Expandir` lo amplía y `⌄ Reducir` vuelve al tamaño parcial; al volver a abrirlo se inicia nuevamente en parcial. El contenido tiene scroll interno para trabajar con DDL extenso. Incluye `Generar desde UML`, `Validar / Vista previa` y `Aplicar al UML`; solo analiza DDL seguro mediante la API existente y nunca ejecuta SQL. Los Viewers pueden generar y validar, pero no aplicar cambios. La ruta anterior `#/board/<id>/sql` abre directamente el mismo panel de la pizarra en modo parcial.

Class and relation inspectors have an explicit `Cerrar` control. Closing removes the right column so the canvas uses the available width. Clicking any class or relation reopens the inspector and selects that element, preserving editing, hover highlighting, collaboration, and responsive behavior.

### Canvas controls

On the board, the mouse wheel is used only for zoom (25%-200%) and does not scroll the page. Hold the right mouse button and drag to pan the canvas. The left mouse button selects and drags classes, and selects relations. Zoom controls remain fixed at the bottom-right of the board viewport; zoom is persisted per board in the browser.

The first start installs frontend dependencies into the `frontend_node_modules` Docker volume. If `frontend/package.json` or `package-lock.json` changes, recreate that volume or remove it before starting again; source edits do not require a rebuild.

## Production with Nginx

```bash
docker compose --env-file .env --profile production up --build
```

The `production` profile builds the frontend bundle and serves it with Nginx at `http://localhost:8081`, avoiding the development port. API health: `http://localhost:8000/health`. Demo credentials: `demo@uml.local` / `demo123`.

Frontend source changes use HMR and do not require a rebuild. Run `docker compose --env-file .env up --build backend` after changing backend Python source, backend dependencies, or the backend Dockerfile. Rebuild the production profile when changing the production frontend Dockerfile/Nginx configuration or when explicitly testing a fresh production bundle.

Refreshing the browser while using the development URL (`http://localhost:8080`) also does not require a rebuild: the frontend source is bind-mounted and Vite serves the current files. A full refresh reloads the board from `GET /api/diagrams/<id>`; it must show the committed PostgreSQL state. If backend code changed, rebuild/recreate only the backend before testing the refresh. The production URL (`http://localhost:8081`) serves a built bundle and therefore requires `--profile production up --build` after frontend source changes.

In a second terminal, from `Proyecto Alex/uml-ai-tool`, run:

```bash
docker compose --env-file .env up --build
```

Alex is available at `http://localhost:8090`, with backend health at `http://localhost:9000/health`. Both frontends use their same-origin Nginx `/api` proxy for REST and WebSocket traffic.

The API requires JWT authentication for diagrams and exports. WebSockets use the JWT as a query parameter and publish events through Redis; a client receives its own persisted mutation once through the Redis subscriber and does not direct-echo it.

During collaborative editing, cursor and class movement events are coalesced latest-only per stream and sent at a stable 16 ms interval, approximately 60 Hz. Rendering remains bounded by `requestAnimationFrame`, and class positions are persisted only on pointer release. The higher event rate reduces perceived motion latency, but can use more network traffic and CPU when many collaborators are active.
# Despliegue local de backends

Además de `Exportar ZIP`, el propietario de un diagrama puede usar `Desplegar` en la barra superior. El sistema genera el backend Spring Boot actual, construye una imagen fija, crea un PostgreSQL exclusivo y publica la API mediante el gateway Nginx en una URL como `http://api-inventario-1234abcd.localhost`.

## Gateway y aislamiento

El servicio `deploy-gateway` es Nginx independiente del Nginx del perfil frontend de producción. Escucha `DEPLOY_GATEWAY_PORT` (80 por defecto) y comparte una configuración administrada por el backend. Las aplicaciones generadas escuchan internamente en 8080 sin publicar ese puerto y se conectan a la red `uml-generated`. Cada despliegue tiene su propio PostgreSQL y volumen de datos; PostgreSQL publica un puerto asignado por Docker exclusivamente en `127.0.0.1`, nunca en todas las interfaces del host.

Si el puerto 80 está ocupado, configure `DEPLOY_GATEWAY_PORT=8088` y la URL devuelta incluirá `:8088`. En Windows, `*.localhost` suele resolver en navegadores actuales; si no lo hace, agregue el host `127.0.0.1 api-<slug>.localhost` al archivo hosts o use `http://localhost:8088` solo como fallback si se configura un proxy equivalente.

## Seguridad y alcance

Este es un MVP local/dev, no un sistema de despliegue multi-tenant de producción. El backend necesita `/var/run/docker.sock` para ejecutar una lista fija y validada de operaciones Docker. El socket equivale a control del host: ejecútelo solo en una máquina de desarrollo confiable y no exponga la API a Internet. No se aceptan comandos, imágenes, volúmenes ni puertos desde el frontend; los nombres se derivan de slug seguro y UUID.

`Desplegar / reconstruir` detiene y reemplaza los contenedores generados, `Abrir API` requiere un clic explícito y `Detener despliegue` quita los contenedores, la ruta Nginx y el volumen PostgreSQL. Una reconstrucción también elimina ese volumen: los datos del backend generado son efímeros. Mientras el estado sea `running`, el bloque **Integraciones** permite obtener credenciales PostgreSQL derivadas para ese despliegue y descargar una colección Postman basada en el snapshot desplegado. Ninguna de las dos respuestas se almacena en caché; las credenciales no forman parte del estado normal ni de la colección. El ZIP se conserva como fallback descargable. Solo el propietario puede consultar o administrar el despliegue; viewers y editors reciben 403.

Como configuración avanzada opcional, `DEPLOY_CREDENTIAL_SECRET` separa la derivación de credenciales de la rotación de `JWT_SECRET`. Si se omite, el backend usa `JWT_SECRET` como fallback; cambiar cualquiera de las claves efectivas requiere reconstruir los despliegues existentes.

## Universal Assistant Protocol (UAP) and Flutter

Every generated Spring backend includes a versioned UAP v1 contract derived from the normalized UML metadata used for its entities and CRUD routes:

- `GET /uap/v1/manifest`
- `GET /uap/v1/schema`
- `GET /uap/v1/tools`
- `GET /uap/v1/permissions`
- `GET /uap/v1/business-rules`
- `POST /uap/v1/tools/{toolId}/invoke?confirmation=true`

Tools are limited to generated list/get/create/update/delete operations. The dispatcher rejects unknown tools, fields, IDs and operations, and requires explicit confirmation for mutations. UML methods are not executable tools. Generated backends are unauthenticated in this local MVP; production deployments need authentication and authorization.

The universal Flutter client lives in `mobile/`:

```bash
cd mobile
flutter pub get
flutter run
```

The app is assistant-first: one primary Talk / give an order action opens the conversational composer; connection, model, settings and raw UAP details are secondary. It is offline-first for intelligence: no cloud LLM or cloud speech API is used. Edit `mobile/lib/config/api_config.dart` and replace `backendBaseUrl` with the URL returned by **Deploy** before building. The app normalizes trailing slashes and discovers UAP automatically at startup; Settings can provide a one-time optional override. `UapClient.invoke` remains the only tool execution seam.

### Offline Android model

The project includes the real `mobile/assets/models/assistant.gguf`, an 806,058,496-byte `Gemma 3 1B IT Q4_K_M` GGUF from [bartowski's Hugging Face repository](https://huggingface.co/bartowski/google_gemma-3-1b-it-GGUF/blob/main/google_gemma-3-1b-it-Q4_K_M.gguf). SHA-256: `12BF0FFF8815D5F73A3C9B586BD8FEE8E7B248C935DE70DEC367679873D0F29D`. It is distributed under Google's [Gemma Terms of Use](https://ai.google.dev/gemma/terms), not Apache-2.0. Android streams this asset to app-private `files/local-models/assistant.gguf` on first start using an atomic temporary file and persists the installed path; users do not select or delete it from normal Settings. The first APK is therefore about 806 MB larger and first start needs equivalent free storage; it is not downloaded at runtime.

The current mobile slice uses a 2048-token context and generation of 32-256 tokens. Prompt construction is hard-capped and summarizes only bounded service/entities/tools metadata, which avoids tokenization failures with SmolLM2-135M. Q4 inference is CPU-heavy and may be slow or warm on a Snapdragon 720G. The real `llamadart 0.8.23` runtime is packaged for the Android build. Android Spanish speech uses `SpeechRecognizer`, requires `RECORD_AUDIO`, and depends on an installed device speech service; it is not claimed to be fully offline and typing always remains available. If the asset is missing, model loading fails, or generation fails, the app reports distinct actionable messages.

The Deploy URL is generated on the PC. A hostname such as `http://api-gymnasio-bab1fac.localhost` may resolve only on that PC, not on a physical phone. For an emulator, use the host mapping such as `http://10.0.2.2:<port>`. For a physical phone, use the PC's LAN IP or LAN hostname, keep both devices on the same network, and allow the gateway port through the firewall. With USB, `adb reverse tcp:<port> tcp:<port>` can expose a host port to the phone, but the configured URL must then use `http://127.0.0.1:<port>`.

The app offers **History** and **Alexa** modes. History shows the conversation and compact composer; Alexa makes one large microphone button the focal action while keeping a text fallback. The local orchestration prompt uses a bounded contract summary rather than full metadata JSON. The model must return only `{"answer":"..."}` or `{"tool":"TOOL_ID","input":{...}}`; harmless Markdown fences are tolerated, while malformed JSON, unknown tools and extra fields are refused. Discovered UAP metadata is authoritative: deterministic Spanish parsing can override a model claim that a valid tool or field is unavailable, and create/update messages use only the schema's actual `required` fields. Write tools require an in-app confirmation before `invoke`, and confirmations/results never claim success after a failed or cancelled invocation. URLs are normalized only as the configured backend address; arbitrary URLs, SQL, shell and reflection are never accepted as model output. List results are formatted in Spanish from returned `data`; backend messages are not shown verbatim.

### Offline-first sync

The Flutter client keeps generic UAP records, the last complete UAP contract snapshot, backend status, cursor, and sync timestamp in versioned SQLite storage. On restart without a backend it restores the snapshot and shows `Backend desconectado · usando datos locales`; without a snapshot, only general local-assistant answers are available until the first successful discovery. List/get read SQLite while offline. Create/update/delete validate against the cached contract, apply a local transaction, retain numeric or UUID identifiers (including tombstone deletes), and enqueue one durable `operationId`; they report `Pendiente de sincronización` and never claim server success. Generated Spring backends expose `GET /uap/v1/sync/changes?since=<cursor>` and `POST /uap/v1/sync/push`, accept bounded operations with `operationId`, `entity`, `operation`, `recordId`, `payload`, and `baseVersion`, deduplicate operation IDs, and reject stale versions as `conflict`. Unknown entities, fields, operations, and IDs are rejected. Empty diagrams still expose the sync endpoints. The app applies server responses and pull changes to the cache and reports `Backend conectado`, `Sincronizando`, `Conflicto`, or `Fallido` truthfully.

Reconnect is event-driven: `connectivity_plus` and app resume trigger a bounded real UAP discovery/health request, followed by outbox push and cursor pull. Retries use 1, 2, 5, 10 and 30 second backoff with a single-flight lock and stop after five attempts; a two-minute foreground timer runs only after local mutations create pending outbox work. Connectivity signals are not treated as proof of backend availability. WebSocket is intentionally not used for consistency; it may be added later only as a push notification that wakes the same discovery/sync flow. `Sincronizar ahora` remains an explicit fallback. Older backends report `Sync protocol unavailable` while normal UAP invocation continues.
