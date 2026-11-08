# Fase 5 — App móvil informativa: guion de implementación

> Para quien implemente esta parte (no necesita haber tocado el resto del proyecto).
> Todo lo que dice este documento sobre el backend fue verificado leyendo el código y, donde hay tests, ejecutándolos.

---

## 0. Resumen en 12 líneas

1. El proyecto es un **editor colaborativo de diagramas de clases UML**. En él, una **IA es un integrante más del equipo**: se le pide algo por chat con `@ia` y responde, revisa, explica y hasta edita el diagrama.
2. Ya están hechos (backend + web): chat persistente, registro de actividad, cerebro de la IA, "novedades desde tu última visita".
3. La app móvil (Flutter, carpeta `mobile/`) hoy habla con **otro backend** (una API Spring Boot generada, protocolo UAP). **No** sabe nada del editor.
4. **Tu tarea:** agregar a la app una sección nueva, **"Equipo"**, que se conecta al backend del editor y permite:
   - iniciar sesión,
   - ver la lista de diagramas,
   - **ver** un diagrama (clases, atributos, métodos, relaciones),
   - **leer y escribir en el chat del equipo** (incluida la IA con `@ia`),
   - ver las **novedades** desde la última visita,
   - todo en **tiempo real** (WebSocket).
5. **La app móvil NO edita el diagrama** (lo pidió el profesor: es informativa). Solo consulta, lee el chat y le pregunta a la IA.
6. No hace falta tocar el backend para empezar (salvo una mejora opcional, ver §2 D3).
7. No toques el código existente de `HomePage` ni del asistente local/UAP: la sección nueva va aparte.
8. Sin dependencias nuevas (se puede todo con `http` + `dart:io` + `shared_preferences`, que ya están).
9. Orden de trabajo: §7 (hitos M0 a M7). Cada hito se puede probar solo.
10. Estimación honesta: **2 a 3 jornadas** para un desarrollador con Flutter intermedio.
11. Antes de empezar, hay **5 decisiones** en §2: confirmarlas con el dueño del repo (traen recomendación).
12. Al final (§11) hay una checklist de entrega.

---

## 1. Contexto y alcance

### 1.1 Qué pidió el profesor (resumen)
- Una IA **compartida** que atiende a varios usuarios a la vez, **contesta por nombre** y mantiene el **contexto del grupo** (como un chat grupal; no hay conversaciones privadas).
- La IA actúa **solo cuando alguien se lo pide**.
- Todo lo que la IA hace se **dibuja en el diagrama compartido**.
- La **app móvil es informativa**: ver el diagrama, ver el chat y poder preguntarle a la IA. **No es para editar.**
- Sesiones continuas: al volver, hay que poder ver qué pasó mientras no estabas.

### 1.2 Dentro del alcance (hacer)
| # | Funcionalidad |
|---|---|
| 1 | Login contra el backend del editor (email + contraseña) |
| 2 | Lista de diagramas (propios y compartidos) |
| 3 | Vista del diagrama **solo lectura** (clases, atributos, métodos, relaciones) |
| 4 | Chat del equipo: historial, enviar, responder a un mensaje, paginar hacia atrás |
| 5 | Preguntarle a la IA (`@ia ...`), con indicador "la IA está respondiendo…" |
| 6 | Novedades "Desde tu última visita" + botón para pedir resumen a la IA |
| 7 | Tiempo real por WebSocket (mensajes nuevos y cambios del diagrama) |
| 8 | Mostrar los límites de la IA (estado: activa / no puede editar / desactivada) |

### 1.3 Fuera del alcance (NO hacer)
- Editar clases, atributos, relaciones, moverlas, borrarlas. **Ni siquiera con gestos.**
- Crear, borrar o compartir diagramas; gestionar miembros; ajustes de IA (eso es del dueño en la web).
- Exportar, generar código, desplegar, SQL, importar XMI.
- Voz en esta sección (la voz existente del asistente UAP sigue como está).
- Modo offline completo con cola de operaciones (ver D4).

---

## 2. Decisiones a confirmar ANTES de empezar

Pregúntaselas al dueño del repo. Todas traen una **recomendación**; si no responde, usá esa.

| ID | Pregunta | Recomendación | Por qué |
|---|---|---|---|
| **D1** | La regla `.claude/rules/mobile.md` dice "inteligencia solo local: sin LLM en la nube". La IA del equipo corre en el **backend** (hoy Gemini, nube). ¿Se permite? | **Sí, con matiz**: la app **nunca** llama a un proveedor de LLM; solo escribe en el chat y el backend decide. El asistente local (llamadart) queda intacto. Actualizar esa regla con una línea que lo diga. | Es exactamente lo que pidió el profesor ("preguntarle a la IA"). |
| **D2** | ¿Dónde vive la sección nueva? | Un botón **"Equipo"** en la `HomePage` actual que hace `Navigator.push` a `TeamHomePage`. | Cero riesgo de romper lo existente. |
| **D3** | Si un usuario con rol **editor** le pide a la IA desde el móvil "creá una clase X", la IA **sí edita** (tiene los permisos de quien pregunta). Eso contradice "móvil informativo". | **Enviar siempre `"ai_read_only": true`** en el POST del chat desde el móvil, El backend **ya lo respeta**: con `ai_read_only: true` la IA solo responde y, si le piden cambiar algo, contesta "no cambié el diagrama porque esta aplicación es solo de consulta". Es por pedido (no queda guardado) y por defecto es `false`, así que la web no cambia. Está cubierto por tests. | Cumple "no editar" de punta a punta, sin depender de que el usuario se porte bien. |
| **D4** | ¿Offline? | **Solo lectura en memoria** (no persistir). Si no hay red: banner "Sin conexión" y botón reintentar. Opcional al final: guardar el último diagrama en `shared_preferences`. **No uses la cola/outbox existente** para el chat. | El chat requiere servidor; encolar mensajes de IA confunde. |
| **D5** | URL del backend desde el teléfono | Campo editable en la pantalla de login (guardado en `shared_preferences`), con valor por defecto `http://10.0.2.2:8000` (emulador). | Cada persona prueba en un entorno distinto (emulador, USB, LAN). Ver §10. |

---

## 3. Cómo está la app hoy (mapa)

```
mobile/lib/
  main.dart                    → MaterialApp, home: HomePage
  features/home_page.dart      → 997 líneas, StatefulWidget enorme: NO refactorizar
  uap/client.dart              → cliente HTTP del backend GENERADO (UAP). NO reutilizar para el editor
  config/api_config.dart       → URLs públicas (no secretos)
  config/backend_preferences.dart → patrón de guardar la URL en shared_preferences (copiá el estilo)
  assistant/, local_llm/, voice/, speech/, offline/   → asistente local; NO tocar
test/                          → assistant, models, offline, speech, url, widget
```

- Dependencias disponibles: `http`, `shared_preferences`, `connectivity_plus`, `path_provider`. **No agregues paquetes**: para WebSocket usá `dart:io` (`WebSocket.connect`).
- Estado: la app usa `StatefulWidget` + `setState`/`Timer`. Seguí el mismo estilo (`ChangeNotifier` simple si necesitás compartir estado). **Sin Provider/Riverpod/Bloc.**
- UI en español, identificadores y comentarios en inglés.
- Reglas del repo que aplican: `UapClient.invoke` es la única vía de mutación **del asistente UAP**. La sección nueva **no muta nada** salvo enviar mensajes de chat y marcar "visto" (ambas son del propio usuario).

---

## 4. Arquitectura propuesta

```
mobile/lib/team/
  team_config.dart        → URL por defecto y clave de preferencias
  team_session.dart       → token + usuario (shared_preferences), login/logout
  team_api.dart           → cliente REST (http) con Authorization: Bearer
  team_socket.dart        → WebSocket con reconexión (dart:io)
  models/
    team_user.dart, diagram_summary.dart, diagram_data.dart (clases/relaciones),
    chat_message.dart, activity_item.dart, digest.dart, ai_settings.dart
  chat/chat_controller.dart   → ChangeNotifier: mensajes, enviar, paginar, thinking
  diagram/diagram_controller.dart → ChangeNotifier: carga + refresco
  digest/digest_controller.dart
  pages/
    team_login_page.dart
    team_home_page.dart        → lista de diagramas
    team_diagram_page.dart     → 3 pestañas: Diagrama | Chat | Novedades
  widgets/
    class_card.dart, relation_tile.dart, chat_bubble.dart, ai_message_body.dart,
    thinking_indicator.dart, digest_card.dart, connection_banner.dart
mobile/test/team/…           → pruebas (ver §8)
```

Reglas de diseño:
- **Modelos puros** (`fromJson`), sin Flutter: se prueban sin emulador.
- Un **solo `TeamApi`** inyectable (recibe `http.Client`) → se prueba con `MockClient` (`package:http/testing.dart`, ya viene con `http`).
- Un **solo `TeamSocket` por diagrama abierto**: se abre al entrar a `TeamDiagramPage`, se cierra al salir.
- Las tres pestañas comparten el mismo socket vía un controlador padre (no abras 3 sockets).

---

## 5. Contrato del backend (verificado en el código)

**Base URL:** `http://<host>:8000` (backend directo). Si pasás por el frontend/Nginx de producción, todo va bajo el prefijo `/api` (`https://<dominio>/api/...`); en ese caso el WebSocket es `wss://<dominio>/api/diagrams/{id}/ws?token=...`.
**Formato:** JSON. **Errores:** `{"detail": "mensaje en español"}` (en 422 de validación `detail` puede ser una lista). Mostrá `detail` tal cual cuando sea texto.
**Auth:** `Authorization: Bearer <token>`. El token **vence a las 8 horas** y **no hay refresh**: ante `401` → volver al login.

### 5.1 REST

| Método y ruta | Para qué | Request | Response (200/201) |
|---|---|---|---|
| `POST /auth/sign-in` | Login | `{"email","password"}` | `{"access_token","user":{"id","email","name","role","active"}}` — error `400 "Credenciales inválidas"` |
| `GET /auth/me` | Validar token guardado | — | `user` |
| `GET /diagrams` | Mis diagramas | — | `[{"id","title","updated_at","is_owner","member_role"}]` (`member_role` es `null` si sos dueño, o `"editor"`/`"viewer"`) |
| `GET /diagrams/{id}` | Diagrama completo | — | ver 5.2 |
| `GET /diagrams/{id}/members` | Equipo | — | `[{"id","email","name","role":"owner\|editor\|viewer","is_owner"}]` |
| `GET /diagrams/{id}/chat?channel=<diseno\|desarrollo\|test>&before=<ISO>&limit=<1..200>` | Historial (orden **ascendente**) de **un** chat. Cada diagrama tiene **3 chats fijos** (Diseño, Desarrollo, Test), colaborativos y con la misma IA; no hay historial de chats ni se crean nuevos | `channel` por defecto `diseno` (otro valor → `422`); `limit` por defecto 50; `before` = `created_at` del mensaje más viejo que ya tenés (**url-encode** el `+` de la zona horaria) | `[ChatMessage]` |
| `POST /diagrams/{id}/chat` | Enviar mensaje | `{"content": "1..2000 chars", "reply_to_id": "uuid\|null", "ai_read_only": true, "channel": "diseno\|desarrollo\|test"}` (`channel` por defecto `diseno`; `reply_to_id` debe ser de ese mismo chat) | `ChatMessage` (201). Si el texto contiene `@ia` (o respondés a un mensaje de la IA), el backend despierta a la IA en segundo plano |
| `GET /diagrams/{id}/ai-settings` | Estado de la IA | — | `{"ai_enabled": bool, "ai_can_edit": bool}` |
| `GET /diagrams/{id}/digest` | Novedades desde la última visita (**no** mueve el marcador) | — | `{"since": ISO\|null, "activity": [ActivityItem], "activity_total": n, "chat_total": n, "by_actor": {"Beto": 2, "IA": 1}}` |
| `POST /diagrams/{id}/seen` | Marcar diagrama como visto | — | `{"last_seen_at": ISO}` |
| `GET /diagrams/{id}/activity?before=&limit=` | Bitácora completa | igual que chat | `[ActivityItem]` (más nuevo primero) |
| `GET /health` | ¿Backend vivo? | — | 200 |

> `ai_read_only` (ver D3): si es `true`, la IA no edita en ese pedido aunque quien pregunta sea editor o dueño. Enviarlo **siempre** desde el móvil.

### 5.2 Formas de los objetos

```jsonc
// ChatMessage
{ "id":"uuid", "diagram_id":"uuid", "author_user_id": 3 /*null si es la IA o usuario borrado*/,
  "author_name":"Beto" /*null si es la IA*/, "author_kind":"user" | "ai",
  "content":"texto", "reply_to_id":"uuid|null", "channel":"diseno|desarrollo|test", "created_at":"2026-11-07T15:04:05.123456+00:00" }

// ActivityItem
{ "id","diagram_id","actor_user_id","actor_name","actor_kind":"user|ai",
  "action":"class.created|class.renamed|class.deleted|attribute.created|attribute.updated|attribute.deleted|method.*|relation.*|association_class.created",
  "entity_type","entity_id","summary":"Beto creó la clase Cliente","created_at" }

// Diagrama
{ "id","title",
  "classes":[{ "id","name","x","y","is_association":false,
               "attributes":[{"id","name","type"}], "methods":[{"id","name","type"}] }],
  "relations":[{ "id","source_id","target_id","from":"NombreOrigen","to":"NombreDestino",
                 "type":"association|aggregation|composition|inheritance|dependency",
                 "label":null,"source_multiplicity":null,"target_multiplicity":null,
                 "association_class_id":null }] }
```
Los objetos traen **más campos** de los listados (extremos de relación, etc.): **ignorá lo desconocido** en `fromJson` (no falles por campos extra ni por `null`).

### 5.3 WebSocket

`ws://<host>:8000/diagrams/{id}/ws?token=<jwt>` (en producción `wss://<dominio>/api/diagrams/{id}/ws?token=...`).
- Cierre con código **1008** = token inválido/vencido o sin acceso → ir al login.
- El servidor te envía JSON de una línea por mensaje: `{"event": "...", ...campos}`.
- **No envíes nada** por el socket (en móvil no hay cursores ni edición).

| `event` | Campos | Qué hacer en la app |
|---|---|---|
| `chat.message` | `message: ChatMessage` | Agregar al chat (**deduplicar por `id`**: tu propio POST también devuelve el mensaje) |
| `ai.thinking` | `requester` (nombre), `message_id` (id de la pregunta), `channel` (el chat donde se preguntó; mostrarlo solo en ese chat) | Mostrar "La IA está respondiendo a *requester*…" |
| `ai.done` | `message_id` (id de la respuesta), `trigger_id` (id de la pregunta), `applied` (n), `changed_class_ids[]`, `changed_relation_ids[]` | Quitar el indicador cuyo `message_id == trigger_id`; resaltar 6 s esas clases/relaciones en la pestaña Diagrama |
| `ai.settings` | `ai_enabled`, `ai_can_edit` | Actualizar el estado de la IA |
| `class.created`, `class.updated`, `class.deleted`, `relation.created`, `relation.updated`, `relation.deleted`, `member.*` | (varios) | **Refrescar** `GET /diagrams/{id}` (con *debounce* de ~300 ms; lo hace igual la web) |
| `presence.join`, `presence.leave`, `cursor.move`, `class.move` | — | **Ignorar** |

Detalles que importan:
- Los eventos originados por REST llegan **a todos, incluido el que los causó**. Por eso: deduplicá por `id`.
- El servidor **no reenvía** el estado perdido durante una desconexión: al reconectar, volvé a pedir `GET chat` (último página) y `GET diagram`.
- La IA tarda típicamente **2 a 15 s**. El POST devuelve enseguida; la respuesta llega después por WS.

---

## 6. Pantallas

### 6.1 Login (`TeamLoginPage`)
```
┌──────────────────────────────┐
│  Equipo                      │
│  Servidor: [http://10.0.2.2:8000]  ← editable
│  Correo:   [______________]  │
│  Clave:    [______________]  │
│  [ Ingresar ]                │
│  (error en rojo si falla)    │
└──────────────────────────────┘
```
- Guardar `token`, `user` y URL en `shared_preferences`. Al abrir "Equipo": si hay token, validar con `GET /auth/me`; si da 401 → mostrar login.
- Botón "Cerrar sesión" en la lista de diagramas.
- **Nunca** imprimir el token en logs.

### 6.2 Lista de diagramas (`TeamHomePage`)
- `ListTile` por diagrama: título, "Dueño" o rol ("editor"/"viewer"), hora de actualización. Pull-to-refresh.
- Vacío: "Todavía no participás en ningún diagrama. Pedile al dueño que te agregue desde la web."

### 6.3 Diagrama (`TeamDiagramPage`) con 3 pestañas

**Pestaña "Diagrama" (solo lectura)**
- v1 (obligatoria): lista de **tarjetas de clase** (nombre, atributos `nombre: tipo`, métodos `nombre(): tipo`) y debajo la lista de **relaciones** en texto: `Cliente —composición→ Pedido  (1..*)`. Las clases con `is_association` llevan la etiqueta «association».
- v2 (opcional, si sobra tiempo): `InteractiveViewer` + `CustomPainter` dibujando cajas en `(x, y)` y líneas entre ellas (zoom/pan con gestos; **sin** arrastrar cajas).
- Resaltado de 6 s con borde de color para los ids de `ai.done`.
- Banner de estado de la IA: "La IA está desactivada en este diagrama" / "La IA responde, pero no puede editar".

**Pestaña "Chat"**
- Lista de burbujas (más nuevo abajo), nombre + hora. Mensajes propios a la derecha.
- Mensajes de la IA: etiqueta "asistente" y, si el texto trae secciones **`Hecho:`** o **`No hice:`** con viñetas `• ...`, mostrarlas como listas (verde / amarillo). Mismo parseo que la web: separar por líneas en blanco; un bloque cuya primera línea sea exactamente `Hecho:` o `No hice:` y tenga más líneas es una lista.
- Campo de texto + botón enviar. Límite 2000 caracteres. Al escribir `@` ofrecer la sugerencia `@ia` (un chip tocable que inserta `@ia `).
- Mantener presionado un mensaje → "Responder" (manda `reply_to_id`).
- Arriba: "Cargar mensajes anteriores" (usa `before`).
- Indicador "La IA está respondiendo a Ana…" mientras haya `ai.thinking` sin su `ai.done`. **Seguro anti-cuelgue:** si pasan 90 s sin `ai.done`, quitarlo.
- Todo el contenido se muestra como **texto plano**. Prohibido renderizar HTML o abrir enlaces que vengan de un mensaje.

**Pestaña "Novedades"**
- Al abrir el diagrama: `GET digest`. Si `since != null` y (`activity_total > 0` o `chat_total > 0`) mostrar la tarjeta **"Desde tu última visita (hace 2 h)"**: "3 cambios y 2 mensajes · IA (2), Beto (1)", últimos 6 resúmenes y "y N más…".
- Botones: **"Resumir con la IA"** (envía `@ia resumí lo que pasó desde mi última visita` con `ai_read_only: true`) y **"Entendido"** (`POST seen`).
- Regla del marcador (importante, igual que la web):
  - Leer el digest **no** mueve el marcador.
  - Se marca visto al tocar "Entendido", o cuando no había nada que mostrar, o al salir del diagrama **habiendo atendido** la tarjeta.
  - Si usó "Resumir con la IA": **no** marcar en el momento (la IA lee lo que te perdiste justo después); marcar al salir.
  - Si cierra la app sin atender la tarjeta: no marcar (la verá la próxima vez).

### 6.4 Reconexión y estados
- `ConnectionBanner`: "Reconectando…" / "Sin conexión". Reintentos del socket con *backoff* 1, 2, 5, 10, 30 s (tope 30 s). Al reconectar: refrescar chat (última página) y diagrama.
- Mientras el socket esté caído y esperes respuesta de la IA, **hacé polling** de `GET chat?limit=20` cada 3 s hasta 60 s.
- Observá el ciclo de vida (`WidgetsBindingObserver`): al pasar a segundo plano cerrar el socket; al volver, reabrir y refrescar.

---

## 7. Plan por hitos

Cada hito termina con algo que se **ve funcionando** y con sus pruebas verdes.

| Hito | Qué | Hecho cuando… | Tiempo |
|---|---|---|---|
| **M0** Preparación | Levantar el stack (§9), crear usuarios de prueba, ejecutar `flutter pub get`, correr la app actual en emulador. Habilitar *Developer Mode* en Windows si hace falta para `flutter test`. | La app actual abre y `flutter test` corre. | 1–2 h |
| **M1** Base | `team_config`, `TeamSession`, `TeamApi` (login, `me`, `diagrams`), modelos básicos, `TeamLoginPage`, botón "Equipo" en `HomePage`. | Login real contra el backend y lista de diagramas visible. | 3–4 h |
| **M2** Diagrama | `GET diagram`, `GET members`, pestaña Diagrama v1 (tarjetas + relaciones), estado de IA. | Un diagrama creado en la web se ve idéntico en datos. | 3 h |
| **M3** Chat | Historial, enviar, responder, paginar, burbujas, `AiMessageBody`. (Aún sin tiempo real: refresco manual.) | Lo escrito en la web aparece al refrescar, y viceversa. | 4 h |
| **M4** Tiempo real | `TeamSocket` con reconexión, eventos `chat.message`, refresco del diagrama, `ai.thinking`/`ai.done`, resaltado. | Escribir en la web aparece en el móvil **sin tocar nada**; `@ia` muestra el indicador y luego la respuesta. | 4–5 h |
| **M5** Novedades | `digest`, `seen`, tarjeta, reglas del marcador, botón "Resumir con la IA". | Se cumple el escenario de §8.3. | 3 h |
| **M6** Robustez | Manejo de 401/1008, offline, reintentos, polling de respaldo, ciclo de vida, textos de error. | Se cumple la tabla de fallos de §8.4. | 3 h |
| **M7** Cierre | Pruebas, `flutter analyze` limpio, actualizar `mobile/README.md` (sección "Equipo") y `.claude/rules/mobile.md` (D1), checklist §11. | Todo verde + demo móvil ensayada. | 2–3 h |
| *(opcional)* **M8** | Lienzo con `CustomPainter` (v2), caché del último diagrama. | — | 4–6 h |

Sugerencia de commits: uno por hito (`feat(mobile): team login and diagram list`, etc.), con sus pruebas dentro del mismo commit.

---

## 8. Pruebas

### 8.1 Automáticas (obligatorias)
Carpeta `mobile/test/team/`. Comandos desde `mobile/`: `flutter analyze` y `flutter test test/team`.

| Qué probar | Cómo |
|---|---|
| `fromJson` de `ChatMessage`, `Diagram`, `Digest`, `ActivityItem`, `DiagramSummary` | Fixtures JSON (copiá ejemplos reales desde `/docs` del backend). Incluir campos `null` y campos extra. |
| Dedupe y orden de mensajes (por `id`, luego por `created_at`) | Test unitario del `ChatController` |
| `parseAiMessage` (`Hecho:` / `No hice:` → listas) | Mismos casos que la web: texto + 2 listas; título sin ítems = texto; vacío = nada |
| Detección de `@`/`@ia` para la sugerencia | `@`, `@i`, `@ia` → abre; `mail@`, `@ia ` → cierra |
| `TeamApi` | `MockClient`: login OK/400, 401 → excepción tipada `Unauthorized`, `before` con `+` codificado, `ai_read_only` presente en el POST |
| Lógica del indicador "pensando" | `ai.thinking` suma, `ai.done` (por `trigger_id`) resta, 90 s lo apaga |
| Regla del marcador de novedades | Tabla de casos de §6.3 |
| Backoff de reconexión | Función pura: intento n → 1, 2, 5, 10, 30, 30… |
| Widget: login muestra el error del backend; lista vacía muestra el texto | `testWidgets` |

### 8.2 Manual (con la web abierta al lado)
Hacerlo con dos personas/dispositivos o dos usuarios (uno en la web, otro en el móvil).

### 8.3 Escenario de aceptación de "Novedades"
1. Con el usuario móvil, entrá a un diagrama y salí (queda "visto").
2. Con otro usuario (web): crear una clase `Zeta` y escribir un mensaje.
3. Entrar de nuevo con el móvil → aparece la tarjeta: "1 cambio y 1 mensaje · Beto (1)" y "Beto creó la clase Zeta".
4. "Resumir con la IA" → la IA contesta mencionando a Zeta.
5. Salir y volver a entrar → la tarjeta **ya no** aparece.

### 8.4 Fallos que deben estar manejados
| Situación | Resultado esperado |
|---|---|
| Servidor apagado / URL mala | Mensaje claro, botón reintentar, sin crash |
| Token vencido (HTTP 401) | Vuelve al login con aviso |
| WebSocket cierra con 1008 | Igual que 401 |
| WebSocket se corta | Banner "Reconectando…", reintentos, y al volver se refresca todo |
| IA tarda o falla | El indicador se apaga solo (90 s); si la IA contesta "no pude usar el modelo…" se muestra como un mensaje más |
| Mensaje > 2000 caracteres | El botón se deshabilita y se muestra el contador |
| Usuario `viewer` | Puede leer y chatear; la UI nunca muestra controles de edición |
| Diagrama borrado mientras lo miro | Error 404/403 → volver a la lista |

---

## 9. Cómo levantar el backend para trabajar

Desde la raíz del repo (necesitás un archivo `.env` válido, ver `.env.example`; **nunca** lo subas):
```
docker compose --env-file .env up -d --build
```
- Web: http://localhost:8080 — API: http://localhost:8000 (docs interactivas en `/docs`).
- Usuario de demo (administrador): `demo@uml.local` / `demo123`.
- Crear más usuarios: en la web, **Gestión de usuarios → Nuevo usuario**. Para compartir un diagrama: abrirlo → **Miembros** → agregar por correo con rol editor o viewer.
- Crear usuarios de prueba sugeridos: uno `editor`, uno `viewer`, y comprobar ambos desde el móvil.
- **Prohibido** (puede borrar datos): `docker compose down -v`, `docker volume rm/prune`, `docker system prune`. No tocar los despliegues de la web.

URLs desde el teléfono:
| Entorno | URL del servidor |
|---|---|
| Emulador Android | `http://10.0.2.2:8000` |
| Teléfono por USB | `adb reverse tcp:8000 tcp:8000` y usar `http://127.0.0.1:8000` |
| Teléfono por Wi‑Fi | `http://<IP-de-tu-PC>:8000` (mismo Wi‑Fi; abrir el puerto 8000 en el firewall de Windows) |
| Producción con HTTPS | `https://<dominio>/api` (preguntar al dueño cuál es el dominio vigente) |

---

## 10. Problemas comunes

| Síntoma | Causa y solución |
|---|---|
| `Cleartext HTTP traffic not permitted` | Android bloquea `http://` en builds **release**. En *debug* ya está permitido (`android/app/src/debug/AndroidManifest.xml`). Para release: usar HTTPS o agregar `android:usesCleartextTraffic="true"` en el manifest principal **solo si el dueño lo aprueba**. |
| El emulador no conecta a `localhost` | En el emulador `localhost` es el propio emulador. Usá `10.0.2.2`. |
| Conecta por navegador del PC pero no desde el teléfono | Firewall de Windows o distinta red Wi‑Fi. |
| `flutter test` se detiene pidiendo "Developer Mode" | Activar *Modo desarrollador* de Windows (necesario para symlinks). |
| `flutter` reescribe `analysis_options.yaml` / `pubspec.lock` | Revisá `git status` y revertí lo que no hayas querido cambiar. |
| `CERTIFICATE_VERIFY_FAILED` | Certificado de prueba sin confiar. No desactives la validación de certificados en el código. |
| El WebSocket cierra al instante con 1008 | Token vencido/ausente o sin acceso al diagrama. Volver al login. |
| Llegan mensajes duplicados | Falta deduplicar por `id` (§5.3). |
| La paginación repite o salta mensajes | El `+` de la zona horaria no está URL-encoded en `before`. |
| La IA "no responde" | Mirá `docker compose logs backend`. Si contesta "no pude usar el modelo…" es la clave/servicio de Gemini del backend, no la app. |

---

## 11. Checklist de entrega

- [ ] Botón "Equipo" en `HomePage`; el resto de `HomePage` **sin cambios** (ver `git diff mobile/lib/features/home_page.dart`: solo el botón y el import).
- [ ] Login, lista, diagrama (solo lectura), chat, novedades, tiempo real.
- [ ] Ningún control que edite el diagrama en ninguna pantalla.
- [ ] `ai_read_only: true` en **todos** los POST de chat desde el móvil.
- [ ] Mensajes mostrados como texto plano (sin HTML, sin abrir enlaces).
- [ ] Token solo en `shared_preferences`; no aparece en logs ni en commits.
- [ ] Sin dependencias nuevas (o, si se agregó una, justificada en el PR).
- [ ] `flutter analyze` sin errores nuevos; `flutter test test/team` verde.
- [ ] `mobile/README.md` con una sección "Equipo" (cómo configurar la URL y probar).
- [ ] `.claude/rules/mobile.md` actualizado según D1 (una línea).
- [ ] `git status` limpio de cambios accidentales en `pubspec.lock` y `analysis_options.yaml`.
- [ ] Demo móvil ensayada (guion abajo).

### Guion de demo móvil (2 minutos)
1. Abrir "Equipo" → login → elegir el diagrama.
2. Pestaña Diagrama: mostrar clases y relaciones.
3. Desde la **web**, pedirle a la IA "creá una clase Pedido con total decimal": en el móvil aparece el indicador "La IA está respondiendo…", luego la respuesta con la lista **Hecho**, y la clase nueva resaltada.
4. Desde el móvil, escribir `@ia ¿qué problemas ves en el diagrama?` → la IA contesta por nombre, y se ve en la web también.
5. Pestaña Novedades: mostrar el resumen y "Resumir con la IA".
6. Remarcar: el móvil solo consulta; no hay forma de editar desde ahí.

---

## 12. Si falta algo del lado del backend (tareas para el dueño del repo)

| Tarea | Detalle | Tamaño |
|---|---|---|
| ~~Respetar `ai_read_only`~~ | **Hecho** (campo en `ChatIn`, pasa a `brain.handle_turn`; 4 tests en `test_ai_brain.py`). | — |
| (Opcional) Endpoint ligero de "digest" por varios diagramas | Para mostrar un punto rojo en la lista. No es necesario para el examen. | ~1 h |

Si el backend cambia el contrato de §5, avisar para actualizar este documento.
