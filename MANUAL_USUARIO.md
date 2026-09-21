# Manual de usuario

## Desarrollo con recarga inmediata

Desde `C:\Users\nelso\Documents\Docker Proyectos\sw1-2-26\Primer-Parcial-sw1` ejecutá el compose raíz:

```bash
docker compose --env-file .env up
```

Abrí `http://localhost:8080`. El frontend corre con Vite dentro del contenedor; la carpeta `frontend` está montada y los cambios aparecen mediante HMR sin reconstruir la imagen. Las solicitudes REST y WebSocket de `/api` se envían al servicio `backend`, por lo que las URLs WebSocket del navegador siguen siendo válidas.

El primer inicio instala las dependencias en el volumen Docker `frontend_node_modules`. Los cambios en archivos fuente no requieren rebuild. Si cambiás `frontend/package.json` o `package-lock.json`, recreá ese volumen o eliminálo antes de iniciar nuevamente para instalar dependencias actualizadas.

## Producción con Nginx

El perfil `production` conserva el camino de producción:

```bash
docker compose --env-file .env --profile production up --build
```

Este comando compila el frontend y lo sirve con Nginx en `http://localhost:8081`, sin conflicto con Vite en `8080`. La salud del backend está en `http://localhost:8000/health`.

Los cambios del código fuente del frontend aparecen mediante HMR y no requieren rebuild. Si cambiás código Python del backend, sus dependencias o `backend/Dockerfile`, ejecutá `docker compose --env-file .env up --build backend`. Para validar un bundle nuevo, reconstruí el perfil `production` si cambian `frontend/Dockerfile` o `frontend/nginx.conf`.

En otra terminal, iniciá Proyecto Alex sin detener este stack:

```bash
cd "Proyecto Alex\\uml-ai-tool"
docker compose --env-file .env up --build
```

Alex queda disponible en `http://localhost:8090` y su salud en `http://localhost:9000/health`. En ambos proyectos el navegador usa el proxy same-origin `/api`; Nginx también reenvía WebSockets.

## Acceso y flujo

Usá `demo@uml.local` y `demo123` (el seed es idempotente y se controla con `SEED_DEMO`). Después de iniciar sesión se muestra `#/dashboard`, la página **Proyectos**: desde allí podés crear un proyecto, abrir uno existente o eliminarlo con confirmación. El login nunca abre una pizarra automáticamente.

Todas las pantallas autenticadas muestran una barra lateral izquierda. **Proyectos** vuelve al dashboard; **Gestión de usuarios** aparece únicamente para administradores y abre `#/gestion-usuarios`; **Cerrar sesión** elimina la sesión y vuelve al login. La barra puede contraerse mediante el botón de menú y en pantallas pequeñas permanece como una navegación compacta con íconos y etiquetas accesibles mediante tooltip. La barra superior queda reservada para el título contextual, volver desde el editor, acciones de la pizarra y el cambio de tema.

### Administración de usuarios

La administración de usuarios vive en la página `#/gestion-usuarios` y su enlace aparece únicamente para cuentas con rol `admin`, tanto en la barra lateral como en el control de ruta. El backend también verifica este rol en cada solicitud; ocultar la sección del frontend no reemplaza la autorización del servidor. El usuario inicial `demo@uml.local` tiene rol administrador. Un usuario no administrador que intente abrir la ruta es redirigido a Proyectos.

Desde la sección **Usuarios**, un administrador puede crear cuentas indicando nombre, correo, contraseña, rol y estado activo. La contraseña es obligatoria al crear y opcional al editar: si se deja vacía durante una edición, se conserva la contraseña actual. También puede editar estos datos o eliminar una cuenta, siempre confirmando la eliminación.

Los roles disponibles son `admin` (administración completa), `editor` (uso de las herramientas de modelado según los permisos del proyecto) y `viewer` (acceso de consulta). Los correos se normalizan a minúsculas y no pueden repetirse. Las contraseñas se almacenan mediante bcrypt y nunca se muestran ni se devuelven por la API.

Por seguridad, no se puede eliminar ni desactivar al propio administrador, ni quitarle a sí mismo el rol de administrador. Tampoco se puede eliminar, desactivar o degradar al último administrador activo: primero debe existir otro administrador activo.

Dentro de una pizarra, `＋ Clase` en la barra superior agrega una clase al lienzo. No hay un panel permanente de herramientas a la izquierda: el lienzo queda libre para modelar. Arrastre una tarjeta para moverla; la posición se guarda. Seleccione una clase para editar su nombre, atributos y métodos desde el inspector derecho. Los nombres y tipos se guardan al salir del campo (blur) o presionar Enter; después de agregar, editar o eliminar un elemento el inspector se sincroniza con la respuesta actual del servidor y no conserva filas eliminadas. Los atributos ofrecen únicamente `string`, `integer`, `long`, `decimal`, `boolean`, `date`, `datetime`, `uuid` y `Custom` bajo la etiqueta `Tipo de atributo`. Los métodos tienen un catálogo independiente bajo `Tipo de retorno`, con `void` y tipos de retorno (`string`, `integer`, `long`, `decimal`, `boolean`, `date`, `datetime`, `uuid`) más `Custom`. Seleccione `Custom` para escribir y guardar otro tipo.

### Navegación y zoom del lienzo

Los controles `−`, `+` y `Restablecer` están fijos en la esquina inferior derecha del lienzo. El zoom va de 25% a 200% y se conserva por pizarra en este navegador. La rueda del mouse hace zoom directamente, sin `Ctrl`, y no desplaza la página. El punto que estaba bajo el cursor (o el centro visible al usar los botones) permanece anclado, por lo que las clases y relaciones siguen siendo alcanzables.

Para desplazar la pizarra, mantenga presionado el botón derecho y arrastre sobre el lienzo. Esta acción mueve la vista, no las clases ni sus posiciones guardadas, y no hay scrollbars ni paneo con la rueda. El menú contextual del lienzo se bloquea siempre para reservar el botón derecho a la navegación. El botón izquierdo conserva su función: arrastrar clases, seleccionar clases o seleccionar relaciones; una tarjeta tiene prioridad si tapa una línea.

En una pantalla táctil, arrastre una tarjeta con un dedo para moverla. Un dedo sobre el fondo no mueve clases. Use dos dedos en cualquier zona: el movimiento paralelo de ambos desplaza la vista horizontal o verticalmente sin cambiar el zoom; cuando predomina el cambio de distancia entre los dedos, el gesto se clasifica como pellizco y acerca o aleja alrededor del punto medio. El lienzo usa un umbral pendiente antes de clasificar el gesto; si un dedo se retira, el estado se limpia y se vuelve a establecer la base cuando queda otro dedo. El gesto cancela cualquier arrastre de tarjeta, mantiene el punto medio como ancla y respeta el rango de 25% a 200%. El navegador no aplica zoom ni menú contextual sobre el lienzo. El paneo y zoom de la vista no se transmiten a otros colaboradores.

En la barra superior, el botón `☼ Claro` o `☾ Oscuro` cambia el tema de toda la aplicación. La elección se guarda en el navegador y se conserva al volver a ingresar.

Cada tarjeta tiene el botón `＋ Relation`. Al pulsarlo se abre un modal estilo Enterprise Architect/StarUML sin seleccionar ni arrastrar la clase. Allí elegís clase origen y destino, el extremo de cada lado (clase, atributo o método), asociación, agregación, composición, herencia/generalización o dependencia, multiplicidades y una etiqueta opcional. El destino es obligatorio y no se permiten relaciones de una clase consigo misma ni duplicados. Las líneas conservan estilos y marcadores distintos por tipo. Las relaciones paralelas entre las mismas clases se dibujan como curvas con offsets deterministas y cada curva tiene su propia zona de click. El canvas no muestra etiquetas de tipo ni cajas flotantes: solo muestra la multiplicidad de origen y destino junto a los extremos de cada línea. Al pasar el cursor por una relación se resalta la línea, las dos tarjetas involucradas y, si corresponde, la fila exacta del atributo o método conectado en cada tarjeta. El resaltado desaparece al salir con el cursor; hacer click sigue seleccionando la relación y abre el inspector derecho. Los endpoints de clase resaltan únicamente la tarjeta. Si el servidor rechaza un formulario, los errores de validación de FastAPI se muestran con el campo y el mensaje legibles, en vez de `[object Object]`. La colaboración se anuncia por WebSocket y distribuye eventos mediante Redis entre procesos; el MVP no implementa cursores ni edición simultánea de texto.

`Exportar ZIP` descarga un archivo autenticado con el diagrama original y un proyecto Maven Spring Boot completo: entidades JPA, repositorios, servicios, controladores CRUD, DTOs, configuración PostgreSQL, Dockerfile, Docker Compose y README. El servidor verifica que el diagrama pertenezca al usuario antes de exportar.

### SQL Editor

El `SQL Editor` es un panel lateral derecho deslizante sobre el lienzo. Al pulsar el botón `SQL Editor` de la pizarra se abre directamente en tamaño parcial, ocupa aproximadamente el 55% de la ventana, deja visible parte del UML y usa scroll interno para documentos DDL extensos. Mientras está abierto, el mismo botón cambia a `Ocultar SQL` y oculta el panel sin dejar una pestaña lateral colapsada. `⌃ Expandir` lo amplía y `⌄ Reducir` vuelve al tamaño parcial; al volver a abrirlo se inicia nuevamente en parcial. `#/board/<id>/sql` abre directamente el mismo panel en tamaño parcial.

El botón `Cerrar` del inspector oculta el panel derecho y el lienzo recupera todo el ancho disponible. Hacer click en una clase o relación vuelve a abrirlo y selecciona ese elemento.

`SQL Editor` abre un panel deslizante desde la derecha sobre el lienzo, sin reemplazarlo. El botón de la pizarra lo abre directamente en tamaño parcial, donde ocupa aproximadamente el 55% de la ventana y deja visible una porción del diagrama; en pantallas pequeñas se acerca al ancho completo. Cuando está abierto, `Ocultar SQL` usa el mismo botón para ocultarlo por completo, sin pestaña lateral colapsada. `⌃ Expandir` lo amplía y `⌄ Reducir` vuelve al tamaño parcial. El contenido usa scroll interno para SQL extenso. La ruta anterior `#/board/<id>/sql` abre el mismo panel directamente en tamaño parcial.

`SQL Editor` abre un editor de DDL asociado a la pizarra. El editor muestra un gutter con números de línea sincronizado con el desplazamiento del texto para ubicar errores. `Generar desde UML` carga el DDL determinista del modelo actual. `Validar / Vista previa` analiza el texto y muestra errores con línea y columna, advertencias y el resumen del diagrama resultante. No existe un ejecutor de consultas: el SQL nunca se envía a PostgreSQL ni se ejecuta contra una base real.

El subconjunto seguro soporta `CREATE TABLE`, columnas `UUID`, `VARCHAR(n)`, `TEXT`, `INTEGER`, `BIGINT`, `NUMERIC`/`DECIMAL`, `BOOLEAN`, `DATE` y `TIMESTAMP`, además de `PRIMARY KEY`, `NOT NULL`, `UNIQUE`, literales seguros en `DEFAULT` y claves foráneas de tabla o inline con `REFERENCES`. También acepta wrappers PostgreSQL `CONSTRAINT nombre` para `FOREIGN KEY`, `PRIMARY KEY` y `UNIQUE`; el nombre se conserva en el SQL de entrada pero no se representa en el UML. Se rechazan `DROP`, `TRUNCATE`, `ALTER`, `SELECT`, `INSERT`, `UPDATE`, `DELETE`, `DO`, `COPY`, funciones, triggers, tipos no soportados, expresiones de default y sentencias mal formadas.

`Aplicar al UML` exige permiso de propietario o editor y confirmación explícita. Primero valida en memoria y solo después persiste el modelo UML en una transacción; nunca ejecuta DDL. Las tablas se convierten en clases y las FK en asociaciones con la heurística `0..*` en el origen y `0..1` en el destino. Se conservan posiciones y métodos cuando coincide el nombre de la clase, y se informa si desaparecen clases. Las clases o atributos que no estén en el SQL se eliminan únicamente como parte de esta acción explícita de reemplazo del modelo. Un Viewer puede abrir, generar y previsualizar, pero no aplicar.

El ZIP generado incluye `src/main/resources/schema.sql`, producido por la misma función UML→DDL. Es un artefacto reproducible para revisar o aplicar manualmente; la aplicación generada mantiene `spring.jpa.hibernate.ddl-auto=update` y no se configura para destruir datos al iniciar.

El backend generado se ejecuta desde la carpeta `generated-spring-backend` del ZIP con `docker compose up --build`. Sin Docker, iniciá PostgreSQL con la base `uml_db`, usuario `postgres` y contraseña `postgres`, y ejecutá `mvn spring-boot:run`. La API queda disponible en `http://localhost:8080`.

### Colaboración y miembros

El propietario puede abrir `Miembros` en la barra superior, escribir el correo de una cuenta existente y agregarla inmediatamente como `Editor` o `Viewer`. No se envían correos: este MVP trabaja únicamente con usuarios registrados. Si el correo no existe, primero hay que crear la cuenta en **Gestión de usuarios**.

Cuando el propietario agrega un miembro, la persona invitada recibe un modal en tiempo real con el nombre de la pizarra, el rol asignado y las acciones **Abrir pizarra** y **Cerrar**. **Abrir pizarra** navega directamente al diagrama; **Cerrar** solo descarta esa invitación. Si la persona está en **Proyectos**, la lista se actualiza automáticamente y la nueva pizarra compartida aparece sin recargar manualmente. La invitación funciona mientras el sitio está abierto y autenticado mediante WebSocket dentro de la aplicación: no es una notificación push del sistema operativo o del navegador, no usa Push API, service worker, historial ni proveedor externo.

El propietario conserva control total, incluida la eliminación de la pizarra y la administración de miembros. Un Editor puede consultar y modificar clases, detalles y relaciones. Un Viewer puede consultar el diagrama y recibir actualizaciones en tiempo real, pero cualquier operación de escritura es rechazada por el backend con `403`. El propietario puede cambiar roles o quitar miembros. La exportación ZIP permanece reservada al propietario.

### Movimiento colaborativo y cursores

Para probar la colaboración del lienzo, abrí la misma pizarra en dos ventanas del navegador con dos cuentas autenticadas (por ejemplo, propietario y editor). Al mover una clase, la otra ventana recibe cada posición en vivo antes de soltarla; al soltar, la posición se guarda mediante PATCH. El puntero de cada participante aparece con un color, flecha y nombre, y desaparece al desconectarse o quedar inactivo.

Los movimientos y cursores son efímeros: no se guardan en PostgreSQL ni actualizan la fecha del proyecto. La interfaz agrupa la actualización visual en un máximo de un render por frame y la red envía como máximo el último evento pendiente de cada flujo cada 16 ms, aproximadamente 60 eventos por segundo. Esto reduce la latencia percibida, pero implica más tráfico de red y uso de CPU cuando participan muchas personas; la latencia real también depende del navegador, la red y Redis, y no se promete una medición fija. El guardado durable ocurre únicamente al soltar la tarjeta. No hay resolución de conflictos, historial ni deshacer: para una misma clase, la posición más reciente recibida gana (last-write-wins), y un refresco estructural o reconexión puede reemplazar el estado efímero.

## Detener, resetear y resolver problemas

## Asistente local de voz y texto

### Aplicación móvil Flutter

La aplicación `mobile/` instala automáticamente el modelo incluido `assistant.gguf` al iniciar por primera vez. No es necesario seleccionar, descargar ni eliminar un modelo desde Ajustes; allí solo se informa su estado y el endpoint UAP. El modelo pequeño usa un contrato resumido y acotado para evitar prompts demasiado largos; pedidos muy extensos deben dividirse en acciones breves.

La pantalla permite cambiar entre **History**, con historial y compositor compacto, y **Alexa**, con un único botón de micrófono grande, estado de escucha/carga/error, última respuesta y una alternativa de texto sin salir del modo. Las lecturas informan lo encontrado y las mutaciones indican qué se realizó o muestran explícitamente que no se realizó ninguna acción si se cancela o falla.

En Android, el micrófono solicita `RECORD_AUDIO` y usa `SpeechRecognizer` para una frase en español. La disponibilidad depende de los servicios de reconocimiento instalados en el teléfono: no se afirma que sea completamente offline ni se usa una API cloud. Si no hay servicio o se rechaza el permiso, el campo de texto continúa disponible.

En el editor aparece un único botón verde flotante **Asistente** en la esquina inferior izquierda del lienzo, separado de la superficie escalable. Al activarlo se abre el chat unificado sin iniciar el micrófono automáticamente. El chat conserva el historial, permite escribir o usar el micrófono dentro del compositor y muestra una vista previa antes de ejecutar, con confirmación para acciones destructivas.

Escribí un pedido o usá el botón de micrófono dentro del compositor y elegí **Enviar**. El frontend usa `/assistant/parse`, muestra una respuesta en español y una vista previa de la acción, y usa `/assistant/execute` únicamente al confirmar. El historial se conserva localmente por pizarra, con un máximo de 30 mensajes y sin enviarse como contexto adicional al backend. Se borra según las políticas normales del almacenamiento del navegador.

El micrófono requiere permiso del navegador y un contexto seguro (localhost o HTTPS). La vista previa en vivo usa `SpeechRecognition`/`webkitSpeechRecognition`, con español, resultados intermedios y modo continuo cuando el navegador lo ofrece. Esta vista previa puede depender del navegador o de su proveedor: no se afirma que sea completamente local. Si no está disponible, el panel lo informa y continúa grabando para usar Whisper al detener. La primera transcripción final descarga el modelo `base` de `faster-whisper`; puede tardar y consume espacio y memoria. El modelo se carga de forma diferida, se ejecuta en CPU con `int8` por defecto y queda en el volumen Docker `whisper_models`. No se descarga durante el arranque. Se pueden ajustar `WHISPER_MODEL`, `WHISPER_DEVICE` y `WHISPER_COMPUTE_TYPE` en `.env`; no se exige GPU.

Los comandos admitidos son: crear clase; renombrar o eliminar clase; agregar atributo tipado; agregar método con retorno; crear relación entre dos clases; cambiar el tipo de relación; y eliminar una relación resoluble entre dos clases. Ejemplos: `creá una clase Usuario`, `agregá un atributo email de tipo string a Usuario`, `agregá un método autenticar que devuelva boolean a Usuario`, `relacioná Usuario con Pedido mediante una composición`, `cambiá la relación entre Usuario y Pedido a herencia` y `eliminá la clase Cliente`.

La interpretación usa exactamente este stack local y sin LLM: `faster-whisper` para audio a texto, `spaCy blank("es")` con `Matcher`/`EntityRuler` validados para detectar patrones y entidades UML, y un esquema Pydantic determinista para construir el comando. No se descarga ni requiere `es_core_news_sm` u otro modelo estadístico. El pipeline spaCy se cachea por proceso y, si no puede inicializarse, se usa la gramática regex segura existente.

Se aceptan variantes de orden acotadas como `crear una clase llamada Cliente`, `cambiar el nombre de Usuario por Cuenta`, `añadir el campo email tipo texto a Usuario` y sinónimos de atributo/campo/propiedad, método/función, tipo y relación, respetando acentos. No se hace interpretación aproximada: parámetros de métodos, nombres implícitos, referencias por posición, frases con dos intenciones o nombres que no puedan segmentarse de forma inequívoca se rechazan y muestran una aclaración. Las clases se resuelven por nombre exacto normalizado dentro del diagrama activo; nunca se adivina un objetivo destructivo. El frontend muestra la acción interpretada antes de ejecutar. Renombrar, cambiar/eliminar relaciones y eliminar clases requieren confirmación explícita; el backend vuelve a validar esa confirmación, el diagrama y el permiso de propietario/editor. Las mutaciones pasan por PostgreSQL y emiten los eventos normales de WebSocket/Redis.

El asistente no ejecuta SQL, no acepta rutas arbitrarias y no funciona para Viewer. Si el navegador no soporta `MediaRecorder` o el formato disponible no es compatible, el panel informa el problema y se puede continuar escribiendo en el mismo chat. El chat no es un LLM ni una conversación abierta: solo interpreta los prompts soportados por el parser determinista. El MVP no incluye parámetros de métodos, deshacer, ni interpretación aproximada.

```bash
docker compose down
docker compose down -v   # elimina también la base persistida
docker compose logs backend
docker compose ps
```

Si falla la migración, confirmá que `db` esté healthy y repetí `docker compose up`. Si el navegador no conecta, usá `8080` para el proyecto raíz y `8090` para Alex; no uses el puerto de backend en el navegador. Nginx resuelve `/api/` y las actualizaciones WebSocket.

### Multiplicidades UML 2.5

Al crear o editar una relación, las multiplicidades de origen y destino se seleccionan entre `1`, `0..1`, `*`, `1..*` y `0..*`. Elegí `Personalizada` para escribir otro valor UML, por ejemplo `2..5`. El valor personalizado se guarda como texto y el inspector lo conserva al recargar la pizarra; se envía al servidor al salir del campo o presionar Enter, no en cada tecla.

## UML 2.5 soportado y límites

Al seleccionar una relación, el inspector muestra para ambos extremos la clase real, el tipo de extremo y el nombre. En endpoints de atributo muestra el tipo de dato y en endpoints de método muestra el tipo de retorno, también en modo Viewer.

El MVP soporta diagramas de clases: nombre de clase, atributos tipados, métodos con retorno, posiciones y relaciones de asociación, agregación, composición, herencia y dependencia, con persistencia PostgreSQL y exportación a un proyecto Spring Boot. Los identificadores inválidos se normalizan en el código generado y el diagrama original se conserva en `diagram.json`. Diagramas vacíos generan solo el endpoint de salud. La generación todavía no modela parámetros o visibilidad de métodos, interfaces, enums, paquetes, casos de uso, secuencias, undo/redo, permisos por colaborador ni mapeos DTO personalizados; esos datos se conservan en JSON o quedan fuera del alcance.
# Despliegue local del backend

Desde una pizarra propia, seleccione **Desplegar** en la navegación superior. El panel muestra `queued`, `building`, `starting`, `running`, `failed` o `stopped`. Use **Desplegar / reconstruir** para generar nuevamente el proyecto Spring Boot, **Abrir API** para abrir la URL en otra pestaña y **Detener** para retirar el contenedor y su ruta. La exportación ZIP continúa disponible.

La URL tiene el formato `http://localhost/deployments/<slug>` (por ejemplo, `http://localhost/deployments/inventario-1234abcd`). Si el puerto 80 no está disponible, defina `DEPLOY_GATEWAY_PORT=8088` en `.env`; la URL incluirá ese puerto. El gateway es el servicio Nginx `deploy-gateway`, distinto del Nginx frontend de producción.

Cada backend generado se ejecuta en la red Docker `uml-generated`, con PostgreSQL y volumen propios. No usa la base PostgreSQL ni Redis de la aplicación principal. Los backends no publican puertos del host: Nginx es el único acceso local.

Si el estado queda en `failed`, el panel conserva la etapa y el código de salida del comando (por ejemplo, `build.compiler`, `exit_code=1`) junto con una salida acotada de Maven/Docker. Un error como `duplicate field` o `variable ... is already defined` indica que el diagrama tiene un atributo y una relación con el mismo rol; el generador renombra de forma segura el campo Java de la relación y conserva la columna FK. Los nombres de tablas, clases y relaciones se limpian para que no aparezcan genéricos como `List<...>` ni caracteres `>`. La limpieza elimina los recursos generados fallidos y **Desplegar / reconstruir** permite reintentar.

**Advertencia crítica:** para construir y administrar contenedores, el backend monta Docker Socket. Ese socket equivale a control del host. Este flujo es únicamente un MVP local/dev: no lo exponga a Internet ni lo use como despliegue multi-tenant de producción. El frontend no puede enviar comandos, imágenes, volúmenes o puertos arbitrarios; el servidor usa Dockerfile, red, límites y nombres fijos.

## Cliente universal Flutter y UAP

Cada ZIP y cada despliegue generado desde una pizarra incluye el contrato **Universal Assistant Protocol v1**, producido a partir del mismo UML normalizado que genera las entidades y las rutas CRUD. Sus endpoints son:

```text
GET  /uap/v1/manifest
GET  /uap/v1/schema
GET  /uap/v1/tools
GET  /uap/v1/permissions
GET  /uap/v1/business-rules
POST /uap/v1/tools/{toolId}/invoke?confirmation=true
```

`manifest` identifica el servicio y sus enlaces; `schema` describe clases, campos y entradas de creación/edición; `tools` publica únicamente `list`, `get`, `create`, `update` y `delete`, junto con método, ruta, permisos, efectos y confirmación; `permissions` declara que este MVP local no tiene autenticación; `business-rules` deja explícito que los métodos UML no son herramientas ejecutables. El dispatcher solo llama servicios CRUD generados, rechaza herramientas, campos, IDs y operaciones desconocidas, y rechaza mutaciones sin confirmación explícita. No acepta URLs, SQL, shell, reflexión ni nombres de métodos.

El cliente está en `mobile/` y se ejecuta así:

```bash
cd mobile
flutter pub get
flutter analyze
flutter test
flutter run
```

La app móvil es únicamente un asistente conversacional: la pantalla principal muestra el chat compacto y un solo botón primario **Talk / give an order**. La URL, el manifiesto, el esquema, los permisos y las herramientas están en **Configuración y detalles**, no en la pantalla de inicio. El texto es siempre el fallback disponible.

### LLM local sin conexión en Android

El razonamiento es local y no existe fallback a nube: la aplicación no usa API de LLM ni API de voz cloud. El modelo incluido es `mobile/assets/models/assistant.gguf`, una cuantización real `Gemma 3 1B IT Q4_K_M` de [bartowski en Hugging Face](https://huggingface.co/bartowski/google_gemma-3-1b-it-GGUF), distribuida bajo los **Gemma Terms of Use** de Google. Tiene aproximadamente 806 MB y está orientada a una mejor comprensión de órdenes en un Snapdragon 720G. Al iniciar, Android lo copia automáticamente por streaming a `files/local-models/assistant.gguf`, usando un archivo temporal y renombrado atómico; el primer inicio necesita aproximadamente 806 MB libres adicionales. No se descarga de Internet durante la ejecución.

El código usa `llamadart 0.8.23` para la inferencia GGUF real en el teléfono. Si el asset no está incluido o no puede copiarse, Configuración muestra el estado y un error claro; no se simula inferencia. El contexto está limitado a 2048 tokens y la salida a 32-256 tokens. Q4 usa CPU y puede ser lento o calentar un Snapdragon 720G.

La voz offline depende de los servicios instalados en cada teléfono Android; se informa esa limitación y el campo de texto continúa disponible en el modo Historial. El flujo es: LLM local para interpretar la intención general, parser UAP determinista para validar entidad, operación, campos y valores, confirmación y ejecución segura. Acepta únicamente `{"answer":"..."}` o `{"tool":"TOOL_ID","input":{...}}`; si el JSON falla, el parser intenta resolver solo órdenes españolas inequívocas contra el contrato UAP. Rechaza herramientas desconocidas, campos extra y solicitudes ambiguas; nunca admite URL arbitrarias, SQL, shell o reflexión. Las herramientas de escritura exigen confirmación antes de `UapClient.invoke`.

Para configurar la API, editá `mobile/lib/config/api_config.dart`. La configuración USB verificada para el teléfono `133a1127` es:

```bash
adb reverse tcp:8080 tcp:80
```

Dejá activo `activeBackendUrl = usbTestBackendUrl`, cuya URL efectiva es `http://127.0.0.1:8080`, y `backendHostHeader = 'api-gymnasio-bab1fac.localhost'`. El cliente conecta por loopback al puerto invertido y envía ese `Host` exacto a Nginx. Para volver a LAN/emulador/despliegue normal, cambiá `activeBackendUrl` a `deployedBackendUrl` (`http://api-gymnasio-bab1fac.localhost`) o a una URL LAN alcanzable; en ese modo no se fuerza un `Host` personalizado. La app descubre UAP automáticamente al arrancar y el campo de Settings es solo un override de esa sesión.

### Trabajo sin conexión y sincronización

El teléfono guarda registros genéricos, el último snapshot completo del contrato UAP, el cursor, el estado del backend y la última sincronización en SQLite local versionado, nunca en Redis. Al reiniciar sin backend restaura el snapshot y muestra **Backend desconectado · usando datos locales**. Sin snapshot, el asistente local todavía responde consultas generales, pero el CRUD offline queda bloqueado hasta conectar una vez. Cada alta, edición o baja validada contra el contrato cacheado se aplica primero a SQLite, conserva IDs numéricos o UUID y queda en una outbox durable con un único `operationId`; las bajas conservan tombstone. La interfaz distingue `Backend conectado`, `Backend desconectado`, `Usando datos locales`, `Sincronizando`, `Pendiente de sincronización`, `Conflicto` y `Fallido`.

El backend generado es la autoridad. `GET /uap/v1/sync/changes?since=<cursor>` descarga cambios y `POST /uap/v1/sync/push` recibe hasta 50 operaciones con `operationId`, `entity`, `operation`, `recordId`, `payload` y `baseVersion`. Los duplicados son idempotentes. Si la versión base quedó vieja, el estado es `conflict` y no se pisa silenciosamente el dato del servidor. Si el backend no tiene esos endpoints, la app muestra **Protocolo de sincronización no disponible** y las invocaciones UAP online siguen funcionando.

La reconexión automática escucha cambios de `connectivity_plus` y el resume de la aplicación, pero siempre verifica con una solicitud real de descubrimiento UAP. Usa backoff acotado de 1, 2, 5, 10 y 30 segundos, una sola sincronización concurrente y como máximo cinco intentos por evento. Solo mantiene un timer de dos minutos en primer plano si hay operaciones pendientes. WebSocket no es necesario para la consistencia offline; podría usarse en el futuro únicamente para avisar que conviene despertar este mismo flujo. **Sincronizar ahora** permanece como fallback manual.

USB exacto: en la PC ejecutá `adb reverse tcp:8080 tcp:80`; en el teléfono usá `http://127.0.0.1:8080/deployments/<slug>`. El socket del teléfono llega por USB al gateway de la PC y la ruta selecciona el despliegue. No es una conexión cloud ni cambia el almacenamiento SQLite local.
