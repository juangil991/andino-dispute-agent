# Spec: Conversar con el agente de disputas desde una página de chat

| Campo | Valor |
|---|---|
| Feature | `008-chat-web-page` |
| Versión | 0.1.0 |
| Estado | Aprobada |
| Fecha | 2026-10-18 |
| Origen | Issue [#34](https://github.com/juangil991/andino-dispute-agent/issues/34) del backlog (P1) |
| Plan | [plan.md](./plan.md) |
| Tareas | [tasks.md](./tasks.md) |
| Constitución | [docs/constitution.md](../../docs/constitution.md) |

---

## 1. Contexto y problema

La spec 007 construyó el agente de disputas y lo expuso en `POST /api/chat` (spec 007 §7.3), pero solo como API JSON: un cliente de Banco Andino no tiene dónde escribirle. La constitución fija el front como HTML + CSS con JavaScript vanilla mínimo, servido por FastAPI como estáticos (§2, §3.1, §3.6).

Esta feature entrega esa página de chat. La página es un **cliente delgado**: envía lo que el cliente escribe a `POST /api/chat` y muestra lo que el agente responde. No consulta datos de la cuenta, no decide y no ejecuta acciones por su cuenta: las decisiones son de `DisputePolicy` (Art. 5) y toda acción sobre el core pasa por el agente y MCP (Art. 6). También debe proteger al cliente en el navegador: mostrar todo como texto (sin ejecutar código inyectado), no guardar la conversación en el navegador y no deshacer el enmascarado de los datos (Art. 7). Debe ser usable en celular, solo con teclado y con lector de pantalla, y estar en español (objetivo 1.2.5).

## 2. Objetivos

- Servir desde `dispute_agent` una página de chat en español que converse con el agente mediante el contrato existente de `POST /api/chat`, sin cambiarlo.
- Mostrar los mensajes en orden, indicar cuándo el agente está respondiendo y evitar envíos vacíos, duplicados o simultáneos.
- Mostrar todo el texto (del cliente y del agente) como texto plano, sin interpretarlo como HTML.
- No conservar la conversación en el navegador: recargar o reabrir la página empieza una conversación nueva.
- Cerrar la conversación en la página cuando el agente deriva el caso y ofrecer una nueva.
- Informar en español, sin detalles técnicos, las fallas del servicio, la falta de conexión y las demoras, y permitir reintentar sin perder el mensaje.
- Ser usable en escritorio y en celular (vertical y horizontal), solo con teclado y con lector de pantalla.

### Fuera de alcance

- Cambios en `POST /api/chat`, en el caso de uso del agente o en el servidor MCP (contrato de la spec 007 §7.3 sin cambios).
- Mostrar la lista estructurada `outcomes`: la página solo muestra `reply` (clarificación 2026-10-18).
- Autenticación de usuarios de la página, sesiones o cookies.
- Persistir o recuperar conversaciones entre recargas o visitas.
- Adjuntar archivos, notificaciones, varios idiomas o temas visuales.
- Bandeja del analista (§1.3).

## 3. Historias de usuario

| ID | Como | Quiero | Para |
|---|---|---|---|
| HU-008-01 | cliente de Banco Andino | abrir una página y conversar en español con el agente de disputas | reportar un cobro que no reconozco |
| HU-008-02 | cliente de Banco Andino | ver cuándo el agente está respondiendo y que una falla, una demora o la falta de conexión no me hagan perder lo que escribí | poder reintentar sin empezar de nuevo |
| HU-008-03 | cliente de Banco Andino | que la página no guarde mi conversación en el navegador ni muestre más datos de los que me entrega el agente | proteger mi información |
| HU-008-04 | cliente de Banco Andino | saber cuándo mi caso pasó a una persona y poder iniciar otra conversación | entender qué sigue |
| HU-008-05 | cliente que usa teclado o lector de pantalla | manejar el chat solo con el teclado y que el lector anuncie los mensajes | atenderme sin ayuda |
| HU-008-06 | cliente que usa el celular | leer y escribir cómodamente en vertical u horizontal | atenderme desde cualquier dispositivo |
| HU-008-07 | Banco Andino | que la página no ofrezca acciones que se salten al agente | que toda acción sobre el core la decida la política y pase por MCP |

## 4. Reglas de negocio

### 4.1 Rol de la página

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-008-01 | La página solo se comunica con el agente mediante `POST /api/chat` (spec 007 §7.3), sin cambios en su contrato. No llama a otros endpoints del agente ni a herramientas MCP. No muestra controles para abrir disputas, bloquear tarjetas, derivar casos ni consultar transacciones: toda acción ocurre por lo que el agente decide en la conversación. | Art. 5; Art. 6; issue #34 |
| RN-008-02 | El agente sirve la página en `GET /`, con sus recursos estáticos (HTML, CSS, JS), desde la misma aplicación `dispute_agent`. | §2; §3.6 |

### 4.2 Inicio y envío de mensajes

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-008-03 | Al cargar, la página muestra como primer mensaje del agente el **saludo fijo** de §7.2. Mostrarlo no llama al agente: la conversación se crea con el primer mensaje de la cliente, enviado sin `conversation_id`. Los mensajes siguientes llevan el `conversation_id` devuelto. | Clarificación 2026-10-18; issue #34 |
| RN-008-04 | El texto se recorta (espacios, tabuladores y saltos de línea al inicio y al final) antes de enviarse. Si queda vacío, no se envía nada y la conversación no cambia. Se envía y se muestra el texto recortado. | Issue #34; spec 007 §7.3 |
| RN-008-05 | La caja de texto admite como máximo **2000** caracteres: no acepta más, tampoco al pegar. Cuando quedan **200** o menos, muestra `Quedan N caracteres`. La página nunca envía un mensaje que la API rechazaría por longitud. | Clarificación 2026-10-18; spec 007 §7.3 |
| RN-008-06 | Enter envía el mensaje. Shift+Enter inserta un salto de línea. El botón `Enviar` envía el mensaje. | Clarificación 2026-10-18 |
| RN-008-07 | Hay como máximo **un** envío en curso. Mientras espera la respuesta, la página muestra `El agente está escribiendo…`, y la caja de texto y el botón `Enviar` no aceptan otro envío. Un doble clic, Enter repetido o la combinación de ambos producen **una** sola petición y **un** solo mensaje en la conversación. | Issue #34 |
| RN-008-08 | El mensaje de la cliente aparece en la conversación al enviarse. La respuesta del agente aparece debajo. La conversación conserva el orden en que se escribieron los mensajes. | Issue #34 |

### 4.3 Presentación y protección de datos

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-008-09 | Todo texto de la conversación, de la cliente y del agente, se muestra como **texto plano**: nunca se interpreta como HTML ni se ejecuta. Se conservan los saltos de línea y los caracteres Unicode (tildes, ñ, emojis). Los textos largos sin espacios se parten para no desbordar el ancho. | Issue #34; Art. 7 |
| RN-008-10 | De cada respuesta, la página muestra solo `reply`, tal como llega. No muestra `outcomes`, `rule`, `conversation_id` ni otro campo. No completa, transforma ni deshace el enmascarado (p. ej. `**** 4321` se muestra igual). Por eso, una falla que el agente informa en `reply` (p. ej. `LLM_FAILURE`, spec 007 §7.3) se muestra con su texto y sin detalles técnicos. | Clarificación 2026-10-18; Art. 7; issue #34 |
| RN-008-11 | La página no muestra datos de la cuenta por su cuenta. Fuera de los mensajes de la conversación y de los textos fijos de §7.2, no muestra transacciones, tarjetas ni datos personales. | Art. 7; issue #34 |
| RN-008-12 | El estado de la conversación (`conversation_id` y mensajes) vive solo en la memoria de la página abierta. No se guarda en `localStorage`, `sessionStorage`, IndexedDB ni cookies. Al recargar, o al cerrar y volver a abrir la página, empieza una conversación nueva: solo se muestra el saludo y el siguiente mensaje se envía sin `conversation_id`. | Issue #34; Art. 7 |

### 4.4 Cierre de la conversación

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-008-13 | Si una respuesta trae `status = "ESCALATED"`, la página muestra el `reply` y, debajo, el aviso fijo de derivación de §7.2. A partir de ahí la caja de texto y `Enviar` quedan deshabilitados y aparece el botón `Iniciar una conversación nueva`. | Issue #34; RN-007-24 |
| RN-008-14 | Al pulsar `Iniciar una conversación nueva`, la página borra los mensajes mostrados, olvida el `conversation_id`, muestra solo el saludo, habilita la caja de texto y le pasa el foco. El siguiente mensaje se envía sin `conversation_id`. | Issue #34 |
| RN-008-15 | Si `POST /api/chat` responde `404` (la conversación ya no existe), la página muestra el aviso fijo de conversación no disponible de §7.2 y se cierra igual que en RN-008-13: deshabilita la caja y ofrece `Iniciar una conversación nueva`. No reintenta ni reenvía el mensaje. | Clarificación 2026-10-18 |

### 4.5 Fallas, demoras y conexión

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-008-16 | Si el envío falla, la página muestra **uno** de los avisos fijos de §7.2, sin código HTTP, trazas, texto de excepción ni nombres internos. El mensaje de la cliente sigue visible, marcado como no enviado, y aparece el botón `Reintentar`. Los casos son: (a) **sin conexión**: el navegador está sin conexión o la petición no llega al servidor; (b) **demora**: no hay respuesta en **60 segundos**, y la página deja de esperarla; (c) **servicio no disponible**: respuesta `5xx`, `422`, otro código distinto de `200` y `404`, o un `200` cuyo cuerpo no es JSON o no trae `reply` y `status` válidos. | Issue #34; clarificaciones 2026-10-18 |
| RN-008-17 | `Reintentar` vuelve a enviar el **mismo** texto a la **misma** conversación (el mismo `conversation_id`, o ninguno si era el primer mensaje), sin añadir otra burbuja con el mensaje. Mientras el reintento está en curso aplica RN-008-07. Si tiene éxito, el aviso desaparece, el mensaje deja de estar marcado y la respuesta aparece debajo. Si el primer envío sí llegó al agente, este puede procesarlo dos veces; se acepta ese riesgo (el core ya evita disputas y bloqueos duplicados: RN-007-12, RN-007-16). | Clarificación 2026-10-18 |
| RN-008-18 | Mientras hay un aviso de falla con `Reintentar`, la caja de texto no envía mensajes nuevos: la cliente reintenta el pendiente antes de escribir otro. | Issue #34 (conservar el orden) |

### 4.6 Accesibilidad, dispositivos e idioma

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-008-19 | La página se usa sin desplazamiento horizontal y con la caja de texto y `Enviar` visibles y operables en las tres pantallas de referencia: escritorio 1280 × 800, celular vertical 360 × 740 y celular horizontal 740 × 360 (píxeles CSS). | Issue #34 |
| RN-008-20 | Todo se maneja con teclado: la caja de texto se alcanza con Tab y tiene una etiqueta accesible; tras cada respuesta del agente, el foco vuelve a la caja de texto; con la conversación cerrada, `Iniciar una conversación nueva` se alcanza con Tab y se activa con Enter. | Issue #34 |
| RN-008-21 | La conversación es una región que los lectores de pantalla anuncian automáticamente (región viva no intrusiva): se anuncian los mensajes nuevos del agente y los avisos de §7.2. Cada mensaje indica quién lo escribió con un texto accesible: `Tú` para la cliente y `Agente` para el agente. | Issue #34 |
| RN-008-22 | El documento declara el idioma español (`lang="es"`). Todos los textos fijos de la página (título, etiquetas, botones, avisos e indicadores) están en español y son los de §7.2. | Constitución §2; objetivo 1.2.5; issue #34 |

## 5. Tabla de decisión de `DisputePolicy`

No aplica: la página no toma decisiones sobre disputas (Art. 5, RN-008-01).

## 6. Criterios de aceptación

Estas condiciones aplican a todos los criterios, salvo que se indique otra cosa:

- La página se carga en `GET /` desde la aplicación `dispute_agent`, en un navegador real (Chromium) dirigido por los tests (clarificación 2026-10-18).
- Las respuestas de `POST /api/chat` están **guionizadas**: el test fija para cada petición el código HTTP, el cuerpo y la demora. Ningún criterio llama a Claude ni al servidor MCP.
- "El agente responde X" significa un `200` con `{"conversation_id": "conv-1", "reply": X, "status": "ACTIVE", "outcomes": []}`, salvo que se indique otro `status`.
- "Los mensajes de la conversación" son las burbujas visibles, en orden, con su autor (`Agente` o `Tú`) y su texto.
- La pantalla es de escritorio (1280 × 800), salvo en AC-008-21.

### AC-008-01 — Al abrir el chat el agente saluda y pide identificarse

Cubre: HU-008-01, RN-008-03, RN-008-11

- **Given** la cliente abre la página
- **When** la página termina de cargar
- **Then** el único mensaje de la conversación es del `Agente` con el saludo fijo de §7.2
- **And** no se hizo ninguna petición a `POST /api/chat`
- **And** la caja de texto está habilitada, vacía y acepta texto

### AC-008-02 — Enviar mensajes y ver las respuestas en orden

Cubre: HU-008-01, RN-008-01, RN-008-03, RN-008-08

- **Given** la página está cargada
- **When** la cliente escribe `No reconozco un cobro de mi tarjeta` y lo envía, el agente responde `Con gusto te ayudo. ¿Me indicas tu número de documento?`, luego escribe `D-1001` y el agente responde `Gracias. ¿Cuál es tu fecha de nacimiento?`
- **Then** los mensajes de la conversación son, en este orden: saludo (`Agente`), `No reconozco un cobro de mi tarjeta` (`Tú`), primera respuesta (`Agente`), `D-1001` (`Tú`), segunda respuesta (`Agente`)
- **And** la primera petición fue `{"message": "No reconozco un cobro de mi tarjeta"}` sin `conversation_id`, y la segunda `{"conversation_id": "conv-1", "message": "D-1001"}`
- **And** todas las peticiones de la página al agente fueron a `POST /api/chat`

### AC-008-03 — No se envían mensajes vacíos

Cubre: HU-008-01, RN-008-04

- **Given** la página está cargada
- **When** la cliente intenta enviar un mensaje `<mensaje>`, con Enter y con `Enviar`
- **Then** no se hace ninguna petición a `POST /api/chat`
- **And** los mensajes de la conversación no cambian

| mensaje |
|---|
| vacío (`""`) |
| con solo espacios (`"   "`) |
| con solo saltos de línea (`"\n\n"`, escritos con Shift+Enter) |

### AC-008-04 — Recorte y límite de longitud

Cubre: RN-008-04, RN-008-05

- **Given** la página está cargada
- **When** la cliente `<acción>`
- **Then** `<resultado>`

| acción | resultado |
|---|---|
| escribe `"  hola  "` y lo envía | la petición lleva `"message": "hola"` y la burbuja muestra `hola` |
| escribe 1799 caracteres | no se muestra el contador |
| escribe 1800 caracteres | se muestra `Quedan 200 caracteres` |
| pega un texto de 2001 caracteres | la caja contiene 2000 caracteres y se muestra `Quedan 0 caracteres` |
| envía un mensaje de 2000 caracteres | la petición lleva el mensaje completo de 2000 caracteres |

### AC-008-05 — Se indica que el agente está respondiendo

Cubre: HU-008-02, RN-008-07

- **Given** la cliente envió un mensaje y el agente tarda 3 segundos en responder
- **When** el agente todavía no ha respondido
- **Then** la página muestra `El agente está escribiendo…`
- **And** la caja de texto y `Enviar` no aceptan otro envío: escribir otro texto y pulsar Enter o `Enviar` no hace ninguna petición
- **And** cuando llega la respuesta, el indicador desaparece y la caja de texto vuelve a aceptar envíos

### AC-008-06 — Un doble envío no duplica el mensaje

Cubre: HU-008-01, RN-008-07

- **Given** la cliente escribió `No reconozco un cobro`
- **When** `<acción>` muy rápido
- **Then** se hace **una** sola petición a `POST /api/chat`
- **And** `No reconozco un cobro` aparece **una** sola vez en la conversación

| acción |
|---|
| hace doble clic en `Enviar` |
| pulsa Enter dos veces |
| pulsa Enter y luego hace clic en `Enviar` |

### AC-008-07 — Los mensajes de la cliente se muestran como texto

Cubre: HU-008-03, RN-008-09

- **Given** la página está cargada
- **When** la cliente escribe `<texto>` y lo envía
- **Then** la burbuja de la cliente muestra exactamente `<texto>`
- **And** la conversación no contiene elementos creados a partir del texto (ni `b`, ni `script`), no se abre ningún diálogo del navegador y el aspecto de la página no cambia

| texto |
|---|
| `<b>hola</b>` |
| `<script>alert(1)</script>` |
| `ñandú, áéíóú y 😀` |

### AC-008-08 — Los mensajes del agente se muestran como texto

Cubre: HU-008-03, RN-008-09, RN-008-10

- **Given** la cliente envió un mensaje
- **When** el agente responde `<texto>`
- **Then** la burbuja del agente muestra exactamente `<texto>`, con sus saltos de línea
- **And** la conversación no contiene elementos creados a partir del texto y no se abre ningún diálogo del navegador

| texto |
|---|
| `<img src=x onerror=alert(1)>` |
| `<a href="javascript:alert(1)">ver</a>` |
| `Línea 1\nLínea 2` |

### AC-008-09 — La página no muestra datos de la cuenta por su cuenta

Cubre: HU-008-03, RN-008-01, RN-008-11

- **Given** la identidad de la cliente no ha sido verificada
- **When** la cliente abre la página y no ha escrito nada
- **Then** la página solo hizo peticiones a `GET /` y a sus recursos estáticos
- **And** el texto visible de la página es solo el de §7.2 (título, saludo, etiqueta de la caja y `Enviar`): no hay transacciones, tarjetas ni datos personales

### AC-008-10 — La página no ofrece acciones que salten al agente

Cubre: HU-008-07, RN-008-01

- **Given** la cliente conversó con el agente y este respondió `Verificamos tu identidad. Estas son tus transacciones recientes: …`
- **When** la cliente revisa la página
- **Then** los únicos controles de la página son la caja de texto y `Enviar`
- **And** ningún control ni enlace menciona disputas, bloqueos, analistas ni transacciones
- **And** todas las peticiones hechas por la página al agente fueron a `POST /api/chat`

### AC-008-11 — Los datos se muestran tal como los entrega el agente

Cubre: HU-008-03, RN-008-10

- **Given** la cliente envió un mensaje
- **When** el agente responde con `status = "ACTIVE"`, `reply = "Bloqueamos tu tarjeta **** 4321."` y en `outcomes` un elemento con `masked_card = "**** 4321"`, `rule = "RN-007-14"` y `reference = "E-9"`
- **Then** la burbuja del agente muestra exactamente `Bloqueamos tu tarjeta **** 4321.`
- **And** la página no muestra `RN-007-14`, `E-9`, `conv-1` ni ningún otro campo de `outcomes`

### AC-008-12 — Recargar la página empieza una conversación nueva

Cubre: HU-008-03, RN-008-12

- **Given** la cliente conversó con el agente (conversación `conv-1`) y el agente le mostró sus transacciones
- **When** la cliente recarga la página
- **Then** el único mensaje de la conversación es el saludo
- **And** al enviar `hola`, la petición no lleva `conversation_id`

### AC-008-13 — El navegador no conserva la conversación

Cubre: HU-008-03, RN-008-12

- **Given** la cliente conversó con el agente
- **When** la cliente cierra la página y la vuelve a abrir en el mismo navegador
- **Then** el único mensaje de la conversación es el saludo
- **And** `localStorage` y `sessionStorage` están vacíos, no hay bases IndexedDB y no hay cookies del sitio, tanto antes de cerrar como después de reabrir

### AC-008-14 — Cuando el caso se deriva, la conversación se cierra

Cubre: HU-008-04, RN-008-13

- **Given** la cliente envió un mensaje
- **When** el agente responde con `status = "ESCALATED"` y `reply = "Derivamos tu caso a un analista."`
- **Then** la conversación muestra ese `reply` y, debajo, el aviso fijo de derivación de §7.2
- **And** la caja de texto y `Enviar` están deshabilitados y no se puede enviar otro mensaje
- **And** se muestra el botón `Iniciar una conversación nueva`

### AC-008-15 — Iniciar una conversación nueva después de un cierre

Cubre: HU-008-04, RN-008-14

- **Given** la conversación `conv-1` está cerrada porque `<causa>`
- **When** la cliente pulsa `Iniciar una conversación nueva`
- **Then** el único mensaje de la conversación es el saludo, y la caja de texto está habilitada y tiene el foco
- **And** al enviar `hola`, la petición no lleva `conversation_id`

| causa |
|---|
| el caso se derivó (`status = "ESCALATED"`) |
| la conversación ya no existía (`404`) |

### AC-008-16 — El servicio del agente no está disponible

Cubre: HU-008-02, RN-008-16, RN-008-17

- **Given** la cliente envió `No reconozco un cobro` y `POST /api/chat` responde `<respuesta>`
- **When** la respuesta llega
- **Then** la página muestra el aviso fijo de servicio no disponible de §7.2
- **And** el texto visible no contiene el código HTTP, `Error`, `Exception`, `Traceback` ni el cuerpo de la respuesta
- **And** `No reconozco un cobro` sigue visible, marcado como no enviado, y aparece `Reintentar`
- **And** al pulsar `Reintentar`, con el agente ya disponible, se envía la misma petición y aparece su respuesta, y `No reconozco un cobro` aparece una sola vez

| respuesta |
|---|
| `500` con un cuerpo `Internal Server Error` |
| `503` |
| `422` |
| `200` con un cuerpo que no es JSON |
| `200` con un JSON sin `reply` |

### AC-008-17 — Se pierde la conexión a mitad de la conversación

Cubre: HU-008-02, RN-008-16, RN-008-17, RN-008-18

- **Given** la cliente intercambió dos mensajes con el agente (`conv-1`)
- **When** el navegador queda sin conexión y la cliente envía `¿Sigues ahí?`
- **Then** la página muestra el aviso fijo de sin conexión de §7.2
- **And** se conservan todos los mensajes ya mostrados, y `¿Sigues ahí?` está marcado como no enviado
- **And** la caja de texto no envía mensajes nuevos mientras el aviso esté visible
- **And** al volver la conexión y pulsar `Reintentar`, se envía `{"conversation_id": "conv-1", "message": "¿Sigues ahí?"}` y la respuesta aparece debajo

### AC-008-18 — El agente tarda demasiado en responder

Cubre: HU-008-02, RN-008-16, RN-008-17

- **Given** la cliente envió un mensaje y el agente responde a los `<demora>`
- **When** el tiempo pasa
- **Then** `<resultado>`

| demora | resultado |
|---|---|
| 59 segundos | se muestra la respuesta y no aparece el aviso de demora |
| 61 segundos | a los 60 segundos aparece el aviso fijo de demora de §7.2 y `Reintentar`, desaparece `El agente está escribiendo…` y la respuesta tardía no se muestra |

Y al pulsar `Reintentar` tras la demora, se envía la misma petición y su respuesta aparece una sola vez.

### AC-008-19 — Una falla informada por el agente se muestra de forma clara

Cubre: HU-008-02, RN-008-10, RN-008-13

- **Given** la cliente envió un mensaje
- **When** el agente responde con `status = "ESCALATED"` y `reply = "Tuvimos un problema al procesar tu solicitud. Una persona continuará la atención."` (`LLM_FAILURE`, spec 007 §7.3)
- **Then** la burbuja del agente muestra exactamente ese texto
- **And** la página no muestra `LLM_FAILURE`, códigos ni trazas, y se cierra como en AC-008-14

### AC-008-20 — La conversación ya no existe

Cubre: HU-008-04, RN-008-15

- **Given** la cliente conversó con el agente (`conv-1`)
- **When** envía `hola` y `POST /api/chat` responde `404`
- **Then** la página muestra el aviso fijo de conversación no disponible de §7.2, sin el código `404`
- **And** la caja de texto y `Enviar` están deshabilitados, se muestra `Iniciar una conversación nueva` y no aparece `Reintentar`
- **And** no se hace ninguna otra petición

### AC-008-21 — La página se usa bien en distintos dispositivos

Cubre: HU-008-06, RN-008-09, RN-008-19

- **Given** la cliente abre el chat en `<dispositivo>`
- **When** conversa con el agente, que responde un texto de 600 caracteres que incluye una palabra de 80 caracteres sin espacios
- **Then** la página no tiene desplazamiento horizontal (el ancho del contenido no supera el de la pantalla)
- **And** la caja de texto y `Enviar` están visibles y la cliente puede escribir y enviar un mensaje

| dispositivo |
|---|
| escritorio, 1280 × 800 |
| celular en vertical, 360 × 740 |
| celular en horizontal, 740 × 360 |

### AC-008-22 — La conversación se maneja solo con teclado

Cubre: HU-008-05, RN-008-06, RN-008-20

- **Given** la cliente usa únicamente el teclado
- **When** `<acción>`
- **Then** `<resultado>`

| acción | resultado |
|---|---|
| llega a la caja de texto con la tecla Tab desde el inicio de la página | la caja tiene el foco y la cliente puede escribir su mensaje |
| pulsa Enter con un mensaje escrito | el mensaje se envía |
| pulsa Shift+Enter entre `hola` y `mundo` y luego Enter | se envía un solo mensaje `hola\nmundo` |
| recibe una respuesta del agente | el foco vuelve a la caja de texto |
| el caso se deriva y la conversación se cierra | llega con Tab al botón `Iniciar una conversación nueva` y, al pulsar Enter, empieza una conversación nueva |

### AC-008-23 — Un lector de pantalla anuncia los mensajes

Cubre: HU-008-05, RN-008-21

- **Given** la cliente usa un lector de pantalla
- **When** llega una respuesta del agente o aparece un aviso de §7.2
- **Then** el mensaje o el aviso está dentro de una región viva no intrusiva (`aria-live="polite"`), por lo que el lector lo anuncia
- **And** el texto accesible de cada mensaje de la cliente empieza por `Tú` y el de cada mensaje del agente por `Agente`
- **And** la caja de texto tiene la etiqueta accesible `Escribe tu mensaje`

### AC-008-24 — Todo el texto de la página está en español

Cubre: HU-008-01, RN-008-22

- **When** la cliente recorre la página en cada estado (inicio, respondiendo, cerrada por derivación, cada aviso de falla)
- **Then** el documento declara `lang="es"`
- **And** cada texto fijo visible o accesible (título, etiquetas, botones, avisos, indicador, contador) es uno de los textos de §7.2

### AC-008-25 — El agente sirve la página

Cubre: RN-008-02

- **When** se pide `GET /` a la aplicación `dispute_agent`
- **Then** responde `200` con `text/html` y la página de chat
- **And** cada recurso estático que la página referencia responde `200` desde la misma aplicación
- **And** `POST /api/chat` sigue cumpliendo su contrato (AC-007-31)

## 7. Contratos de herramientas MCP

No aplica: esta feature no crea ni modifica herramientas MCP.

### 7.1 Interfaz HTTP usada por la página

No es una herramienta MCP. La página consume `POST /api/chat` **sin cambios** respecto de la spec 007 §7.3 y solo lee de la respuesta `conversation_id`, `reply` y `status`. Se añade:

| Ruta | Método | Respuesta |
|---|---|---|
| `/` | `GET` | `200`, `text/html`: la página de chat (RN-008-02). |
| Recursos estáticos de la página | `GET` | `200` con el tipo de contenido de cada archivo (CSS, JS). |

Cómo trata la página cada respuesta de `POST /api/chat`:

| Respuesta | Comportamiento |
|---|---|
| `200` con `reply` y `status = "ACTIVE"` | Muestra `reply` (RN-008-10); guarda `conversation_id` en memoria. |
| `200` con `reply` y `status = "ESCALATED"` | Muestra `reply` y cierra la conversación (RN-008-13). |
| `404` | Aviso de conversación no disponible y cierre (RN-008-15). |
| Sin conexión o sin respuesta del servidor | Aviso de sin conexión y `Reintentar` (RN-008-16 a). |
| Sin respuesta en 60 s | Aviso de demora y `Reintentar` (RN-008-16 b). |
| Cualquier otra (`5xx`, `422`, otro código, `200` sin JSON válido o sin `reply`/`status` válidos) | Aviso de servicio no disponible y `Reintentar` (RN-008-16 c). |

### 7.2 Textos fijos de la página

| Elemento | Texto |
|---|---|
| Título del documento y encabezado | `Banco Andino — Asistente de disputas` |
| Saludo (primer mensaje del `Agente`) | `Hola, soy el asistente de disputas de Banco Andino. Antes de revisar tu cuenta necesito identificarte. Para empezar, indícame tu número de documento, tu nombre completo o los últimos 4 dígitos de tu tarjeta.` |
| Etiqueta accesible de la caja de texto | `Escribe tu mensaje` |
| Botón de envío | `Enviar` |
| Indicador de espera | `El agente está escribiendo…` |
| Contador (quedan ≤ 200) | `Quedan N caracteres` |
| Autor de los mensajes (texto accesible) | `Tú` / `Agente` |
| Marca de mensaje no enviado | `No enviado` |
| Aviso de derivación | `Tu caso fue derivado a un analista. Una persona continuará la atención.` |
| Aviso de conversación no disponible | `Esta conversación ya no está disponible.` |
| Botón de conversación nueva | `Iniciar una conversación nueva` |
| Aviso de sin conexión | `No hay conexión a internet. Revisa tu conexión y vuelve a intentarlo.` |
| Aviso de demora | `La respuesta está tardando más de lo normal. Puedes volver a intentarlo.` |
| Aviso de servicio no disponible | `No pudimos atenderte en este momento. Intenta de nuevo en unos minutos.` |
| Botón de reintento | `Reintentar` |

## 8. Casos de escalamiento

No aplica: la página no deriva casos. Las derivaciones las decide y registra el agente (spec 007 §8); la página solo refleja el cierre cuando `status = "ESCALATED"` (RN-008-13).

## 9. Clarificaciones

| Fecha | Pregunta | Respuesta | Secciones afectadas |
|---|---|---|---|
| 2026-10-18 | ¿De dónde sale el saludo inicial, si `POST /api/chat` exige un mensaje del cliente? | Texto fijo en la página, mostrado como mensaje del agente. No llama al backend; la conversación se crea con el primer mensaje. La API no cambia. | RN-008-03, §7.2, AC-008-01 |
| 2026-10-18 | ¿Cómo se verifican con pytest los criterios del navegador? | Con un navegador real dirigido por los tests, en la suite por defecto, contra la app con respuestas guionizadas de `POST /api/chat`. La dependencia nueva se justifica en el plan. | §6 (condiciones generales) |
| 2026-10-18 | ¿Cuánto espera la página antes de avisar que la respuesta está tardando? | 60 segundos. | RN-008-16, AC-008-18 |
| 2026-10-18 | ¿La página muestra solo `reply` o también `outcomes`? | Solo `reply`. | §2 fuera de alcance, RN-008-10, AC-008-11 |
| 2026-10-18 | ¿Qué hace "volver a intentar" tras una demora o una falla? | Reenvía el mismo texto a la misma conversación sin duplicar la burbuja. Se acepta que el agente procese dos veces un mensaje que sí llegó. | RN-008-17, AC-008-16, AC-008-17, AC-008-18 |
| 2026-10-18 | ¿Qué hace la página si `POST /api/chat` responde `404`? | Avisa que la conversación ya no está disponible, la cierra y ofrece iniciar una nueva, sin reintentar. | RN-008-15, AC-008-15, AC-008-20 |
| 2026-10-18 | ¿Cómo se maneja el límite de 2000 caracteres de la API? | La caja no admite más de 2000 caracteres y muestra los que quedan cuando faltan 200 o menos. | RN-008-05, AC-008-04 |
| 2026-10-18 | ¿Cómo se escribe un salto de línea si Enter envía? | Enter envía y Shift+Enter inserta un salto de línea. | RN-008-06, AC-008-03, AC-008-22 |

## 10. Preguntas abiertas

Ninguna.

## 11. Historial de cambios

| Versión | Fecha | Cambio | Autor |
|---|---|---|---|
| 0.1.0 | 2026-10-18 | Versión inicial a partir de la issue #34 | Juangiov (con Claude Code) |
| 0.1.0 | 2026-10-18 | Spec aprobada por el usuario | Juangiov |

---

## Gate de salida

- [x] No quedan preguntas abiertas.
- [x] Cada clarificación está reflejada en las secciones afectadas.
- [x] Todos los criterios de aceptación tienen ID y formato Given/When/Then.
- [x] Cada regla de negocio está cubierta por al menos un criterio de aceptación.
- [x] Contratos MCP y casos de escalamiento completos o marcados "No aplica".
- [x] Estado cambiado a **Aprobada**.
