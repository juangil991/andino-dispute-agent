# Spec: Ver la respuesta del agente palabra por palabra mientras se genera

| Campo | Valor |
|---|---|
| Feature | `009-streaming-agent-reply` |
| Versión | 0.2.0 |
| Estado | Aprobada |
| Fecha | 2026-10-18 |
| Origen | Issue [#42](https://github.com/juangil991/andino-dispute-agent/issues/42) del backlog (P2) |
| Plan | [plan.md](./plan.md) |
| Tareas | [tasks.md](./tasks.md) |
| Constitución | [docs/constitution.md](../../docs/constitution.md) |

---

## 1. Contexto y problema

Hoy la página de chat (spec 008) envía el mensaje a `POST /api/chat` (spec 007 §7.3) y no muestra nada hasta que el agente termina el turno completo: identificar, consultar, decidir, actuar y redactar. La cliente solo ve `El agente está escribiendo…` y luego el texto de golpe. La issue #42 pide que la respuesta aparezca palabra por palabra mientras se redacta, como en una conversación con una persona.

Hay una restricción: la constitución exige que el dominio decida y el LLM solo converse (Art. 5) y que ante la duda se escale (Art. 10). Por eso solo se muestra palabra por palabra la **redacción final**. Las decisiones y las acciones del turno ya se tomaron y se registraron antes de la primera palabra, y lo que se escribe nunca las cambia ni dispara acciones nuevas.

Con la API de Claude, la razón de parada (`end_turn` o `tool_use`) solo se conoce al final de cada respuesta. No se puede saber de antemano si un texto es la redacción final. Por eso el ciclo de decisión de la spec 007 sigue igual y sin mostrar nada. Cuando termina, el agente hace **una llamada de redacción** al LLM, sin herramientas, y esa sí se transmite en tiempo real (clarificación 2026-10-18).

### Relación con specs existentes

Esta spec amplía, sin romper sus contratos:

- **Spec 007**: añade el endpoint `POST /api/chat/stream` (§7.1). `POST /api/chat` no cambia (AC-007-31 sigue vigente). Amplía RN-007-28 con un quinto tipo de evento de auditoría (RN-009-11). La llamada de redacción no cuenta en el máximo de RN-007-23.
- **Spec 008**: la página pasa a usar `POST /api/chat/stream` en lugar de `POST /api/chat` (enmienda RN-008-01 y §7.1). La espera de 60 s de RN-008-16 b se mide desde la última palabra recibida (RN-009-21). Se añade el texto fijo `Incompleto` a §7.2 de 008.

## 2. Objetivos

- Mostrar la respuesta redactada por el agente palabra por palabra, a medida que se genera, sin cambiar las decisiones ni las acciones del turno.
- No mostrar texto mientras el agente decide y consulta información.
- Garantizar que el texto final mostrado sea exactamente el texto filtrado (RN-007-26), sin palabras partidas, sin interpretarse como código y sin datos sin enmascarar en ningún momento.
- Derivar a un analista y cerrar la conversación si la redacción se interrumpe por una falla, conservando lo ya mostrado como incompleto.
- Mantener la accesibilidad: lector de pantalla y preferencia de reducir movimiento.
- Registrar si cada respuesta terminó completa o interrumpida, con su texto filtrado y los `outcomes` del turno, para revisión.

### Fuera de alcance

- Transmitir en tiempo real el texto de las llamadas del ciclo de decisión (antes de `end_turn`).
- Detectar automáticamente, por palabras, si el texto afirma acciones no realizadas (RN-007-33). Solo se registra para revisión humana (RN-009-11).
- Cambios en `POST /api/chat`, en `DisputePolicy`, en las herramientas MCP o en el servidor MCP.
- Reanudar una respuesta interrumpida desde donde quedó.
- Bandeja del analista para revisar los registros (§1.3).

## 3. Historias de usuario

| ID | Como | Quiero | Para |
|---|---|---|---|
| HU-009-01 | cliente de Banco Andino | ver la respuesta del agente formarse palabra por palabra | sentir que converso con una persona y no esperar en blanco |
| HU-009-02 | cliente de Banco Andino | saber que el agente está trabajando mientras consulta, sin ver textos provisionales | no leer algo que luego cambie |
| HU-009-03 | cliente que usa lector de pantalla o prefiere reducir el movimiento | recibir cada respuesta completa una sola vez | entenderla sin ruido ni animaciones |
| HU-009-04 | cliente de Banco Andino | saber qué pasó si la respuesta se corta y que una persona continuará | no quedar sin atención |
| HU-009-05 | Banco Andino | que las decisiones y acciones se tomen antes de mostrar el texto, que el texto no dispare acciones y que quede registro de lo mostrado | cumplir los Art. 5, 8 y 10 |

## 4. Reglas de negocio

### 4.1 Ciclo del agente y llamada de redacción

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-009-01 | El agente expone `POST /api/chat/stream` (§7.1), con la misma entrada y las mismas validaciones que `POST /api/chat` (spec 007 §7.3). Responde `422` o `404` como error HTTP antes de transmitir nada. Si la entrada es válida, responde `200` con un flujo de eventos. `POST /api/chat` no cambia. Ambos endpoints comparten las conversaciones. | Clarificación 2026-10-18; spec 007 §7.3 |
| RN-009-02 | En `POST /api/chat/stream`, el agente emite el evento `start` con el `conversation_id` y ejecuta el turno igual que en la spec 007 (guardas, `DisputePolicy`, herramientas MCP, derivaciones, cierre y auditoría, RN-007-01 a RN-007-36), **sin enviar texto a la cliente**. El texto de la respuesta `end_turn` del ciclo no se envía: lo sustituye la llamada de redacción (RN-009-03). | Art. 5; issue #42; clarificación 2026-10-18 |
| RN-009-03 | Si el ciclo termina con una respuesta `end_turn` válida (RN-007-32), el agente hace **exactamente una** llamada de redacción al LLM, y solo cuando todas las decisiones, acciones y registros de auditoría del turno ya terminaron. La llamada recibe el historial de la conversación y los `outcomes` del turno, **no ofrece ninguna herramienta** y sus instrucciones piden redactar la respuesta en español a partir de los `outcomes`, sin afirmar acciones que no figuren en ellos. No cuenta en el máximo de 8 llamadas de RN-007-23. | Clarificación 2026-10-18; Art. 5; RN-007-33 |
| RN-009-04 | Cuando la spec 007 fija el `reply` como texto fijo, no hay llamada de redacción: el agente envía el texto completo en el evento `end`, sin eventos `word`. Son los casos de `ITERATION_LIMIT` y `LLM_FAILURE` del ciclo (spec 007 §7.3), el de conversación ya cerrada (RN-007-24) y, desde la spec 007 v0.3.0, todo turno que termina sin identidad verificada (RN-007-38, textos fijos de 007 §7.4). | Spec 007 §7.3 y §7.4; issue #42; issue #45 |
| RN-009-05 | El texto de la llamada de redacción nunca se interpreta para ejecutar acciones ni para darlas por hechas (RN-007-33). Ninguna acción del turno se ejecuta, cambia ni se deshace por lo que diga ese texto, ni completo ni parcial. | Art. 5; RN-007-33; issue #42 |

### 4.2 Transmisión palabra por palabra

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-009-06 | Una **palabra** es una secuencia de caracteres sin espacios en blanco. El agente envía la redacción en eventos `word`. Cada uno lleva un fragmento con **una** palabra completa y el espacio en blanco (espacios, tabuladores, saltos de línea) que la precede. Nunca envía parte de una palabra. Envía cada palabra en cuanto está completa: cuando llega el espacio en blanco que la sigue o cuando termina la redacción. | Issue #42 |
| RN-009-07 | El filtro de RN-007-26 se aplica **antes** de enviar cada fragmento. El agente retiene las palabras mientras puedan formar parte de un texto que el filtro sustituiría (p. ej. grupos de dígitos que podrían completar una secuencia de 13 a 19 dígitos, o un documento aportado por el cliente). Las envía ya filtradas cuando eso se resuelve. Ningún fragmento contiene un texto que el filtro habría sustituido. | Art. 7; RN-007-26 |
| RN-009-08 | La concatenación, en orden, de los fragmentos enviados es **exactamente** el `reply` del evento `end`, que es el texto completo de la redacción tras el filtro. Se conservan los caracteres Unicode y los saltos de línea. | Issue #42; RN-008-09 |

### 4.3 Interrupción de la redacción

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-009-09 | La redacción termina **completa** solo si el LLM responde con razón de parada `end_turn`, sin peticiones de herramientas y con texto que no es vacío ni solo espacios. Se **interrumpe** si: (a) el LLM lanza un error (`LLM_ERROR`); (b) pasan **30 s** (configurable) sin texto nuevo del LLM, contados desde el inicio de la llamada o desde el último texto recibido (`LLM_TIMEOUT`); (c) la salida es inválida: otra razón de parada (`max_tokens`, `refusal`, `pause_turn`, `stop_sequence`, otra o ninguna), alguna petición de herramienta, o texto vacío (`LLM_INVALID_OUTPUT`, como RN-007-34/35); (d) el agente sufre una falla interna inesperada durante la redacción (`INTERNAL_ERROR`). | Art. 10; RN-007-34; RN-007-35; clarificaciones 2026-10-18 |
| RN-009-10 | Ante una interrupción de RN-009-09, el agente deja de enviar palabras (no retracta las ya enviadas) y no ejecuta ninguna acción nueva por el texto. Deriva **una vez** con `escalar_a_analista` y `reason = "UNRECOVERABLE_SYSTEM_FAILURE"`, con resumen completo sin transacción si la identidad está verificada, o limitado si no (spec 007 §8). Emite el evento `interrupted` con `reply` igual al mensaje fijo de `LLM_FAILURE` (`Tuvimos un problema al procesar tu solicitud. Una persona continuará la atención.`), `status = "ESCALATED"` y `outcomes` con los del turno más `LLM_FAILURE` (regla `RN-009-10`). Cierra la conversación (RN-007-24). Si la derivación falla, se aplica RN-007-22. | Art. 10; issue #42; RN-007-24 |
| RN-009-11 | Al terminar cada redacción, completa o interrumpida, queda un registro de auditoría de un quinto tipo de evento (amplía RN-007-28): **respuesta mostrada**. Lleva `conversation_id`, la marca de tiempo del reloj inyectado, el resultado (`COMPLETE` o `INTERRUPTED`), la causa si se interrumpió (`LLM_ERROR`, `LLM_TIMEOUT`, `LLM_INVALID_OUTPUT`, `INTERNAL_ERROR`, `CLIENT_DISCONNECTED`), el texto enviado a la cliente (la concatenación de los fragmentos, ya filtrada) y el `kind` y la `rule` de cada `outcome` del turno, para que un revisor compare lo afirmado con lo realizado. La llamada de redacción también genera su registro de respuesta del LLM (RN-007-36), con la regla `RN-009-03` si es completa o `RN-009-09` si no. Ningún registro contiene datos sin enmascarar (RN-007-26). | Art. 8; clarificación 2026-10-18; issue #42 |
| RN-009-12 | Si la conexión con la página se cierra antes del evento final, el agente deja de redactar y no llama más al LLM en ese turno. Registra la respuesta mostrada como `INTERRUPTED` con causa `CLIENT_DISCONNECTED`. No deriva ni cierra la conversación: las decisiones del turno ya se tomaron y la cliente puede reintentar (RN-008-17). | Art. 8; RN-008-17 |

### 4.4 Página de chat

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-009-13 | La página envía cada mensaje a `POST /api/chat/stream` y a ningún otro endpoint del agente (enmienda RN-008-01, cuyo resto no cambia: sin controles que salten al agente). De los eventos solo usa `conversation_id`, el fragmento de `word`, `reply` y `status`. No muestra `outcomes`. | Clarificación 2026-10-18; RN-008-01; RN-008-10 |
| RN-009-14 | Desde el envío hasta la primera palabra, la página muestra `El agente está escribiendo…` y ninguna palabra de la respuesta. Cuando aparece la primera palabra, el indicador deja de mostrarse. Si el turno termina sin palabras (RN-009-04), el indicador desaparece al llegar `end`. | Issue #42; RN-008-07 |
| RN-009-15 | La página añade cada fragmento a la burbuja del agente apenas lo recibe, siempre como texto plano (RN-008-09). Al llegar `end`, el texto de la burbuja es exactamente `reply`. | Issue #42; RN-008-09; RN-008-10 |
| RN-009-16 | Mientras la respuesta está en curso (desde el envío hasta `end`, `interrupted` o un aviso de RN-009-22 o RN-009-23), la caja de texto y `Enviar` no envían otro mensaje (amplía RN-008-07). Al llegar `end` con `status = "ACTIVE"`, la caja vuelve a aceptar envíos y recibe el foco. | Issue #42; RN-008-07; RN-008-20 |
| RN-009-17 | Con `status = "ESCALATED"` en `end`, el aviso de derivación de 008 §7.2 aparece debajo de la respuesta solo después de la última palabra, y la conversación se cierra como en RN-008-13. | Issue #42; RN-008-13 |
| RN-009-18 | Al llegar `interrupted`, la burbuja con el texto parcial, si la hay, se conserva y se marca `Incompleto`. Debajo aparece una burbuja del `Agente` con `reply` completo al instante y el aviso de derivación, y la conversación se cierra como en RN-008-13. | Issue #42; clarificación 2026-10-18 |
| RN-009-19 | Las palabras intermedias no se anuncian a los lectores de pantalla. Cada respuesta del agente se anuncia **una sola vez**, completa, al terminar (con `end`, con `interrupted` o al cortarse por un aviso), y su texto accesible empieza por `Agente`. | Issue #42; RN-008-21 |
| RN-009-20 | Si el dispositivo tiene activada la preferencia de reducir movimiento (`prefers-reduced-motion: reduce`), la página no muestra las palabras a medida que llegan. Mantiene el indicador y muestra la respuesta completa al llegar `end`. Las demás reglas no cambian (la espera de RN-009-21 se reinicia igual con cada palabra recibida). | Issue #42 |
| RN-009-21 | Solo la respuesta redactada por el agente aparece palabra por palabra. El saludo, los mensajes de la cliente, los avisos de 008 §7.2 y los textos fijos de RN-009-04 y RN-009-18 aparecen completos al instante. | Issue #42 |

### 4.5 Demoras, conexión y fallas en la página

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-009-22 | La página espera como máximo **60 s** sin recibir una palabra nueva, contados desde el envío y reiniciados con cada `word` recibido (enmienda RN-008-16 b). Al cumplirse: deja de esperar el flujo, oculta el indicador y muestra el aviso de demora y `Reintentar`. | Issue #42; RN-008-16 |
| RN-009-23 | Si el navegador queda sin conexión durante la respuesta, la página deja de esperar el flujo y muestra el aviso de sin conexión y `Reintentar`. Si el flujo falla de otro modo, muestra el aviso de servicio no disponible y `Reintentar`. Eso incluye una respuesta distinta de `200` y `404`, un flujo que se cierra sin `end` ni `interrupted`, o un evento que no es válido (§7.1). Un `404` se trata como en RN-008-15. | RN-008-15; RN-008-16 |
| RN-009-24 | En los casos de RN-009-22 y RN-009-23, se conservan los mensajes anteriores y el de la cliente. Si ya había palabras de la respuesta, la burbuja parcial se conserva marcada `Incompleto` y el mensaje de la cliente no se marca `No enviado`. Si no había palabras, el mensaje de la cliente se marca `No enviado` como en 008. `Reintentar` reenvía el mismo texto a la misma conversación (RN-008-17), y la respuesta nueva aparece debajo. | Clarificación 2026-10-18; RN-008-17 |
| RN-009-25 | Una vez que una respuesta termina (`end`, `interrupted`, aviso de RN-009-22/23), la página ignora cualquier evento posterior de ese flujo. Recargar la página o pulsar `Iniciar una conversación nueva` abandona el flujo en curso. Después solo se muestra el saludo, sin texto de la respuesta anterior, y el siguiente mensaje inicia una conversación nueva (RN-008-12, RN-008-14). | Issue #42; RN-008-12; RN-008-14 |

### 4.6 Protección de datos

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-009-26 | La llamada de redacción no tiene herramientas y solo recibe el historial de la conversación y los `outcomes` del turno. Antes de verificar la identidad (Art. 7), las guardas de la spec 007 impiden que ese historial contenga datos de la cuenta. Por eso la respuesta transmitida no contiene datos de la cuenta, transacciones ni tarjetas, sino solo lo necesario para identificar a la cliente. | Art. 7; RN-007-01 a RN-007-03 |

## 5. Tabla de decisión de `DisputePolicy`

No aplica: la feature no cambia las decisiones sobre disputas. `DisputePolicy` decide en el ciclo de la spec 007, antes de la redacción (RN-009-02, RN-009-05).

## 6. Criterios de aceptación

Estas condiciones aplican a todos los criterios, salvo que se indique otra cosa:

- **Agente (AC-009-01 a AC-009-14):** `POST /api/chat/stream` se prueba con un `FakeLLM` guionizado que, para la llamada de redacción, entrega el texto en trozos con demoras controladas, y luego su razón de parada. El reloj es inyectado. Las herramientas son fakes de `BankingToolsPort`, salvo en AC-009-14. Ningún criterio llama a Claude.
- **Página (AC-009-15 a AC-009-30):** la página se carga en `GET /` en un navegador real (Chromium) dirigido por los tests. Las respuestas de `POST /api/chat/stream` están **guionizadas**: el test fija el código HTTP, los eventos y la demora entre ellos.
- "El agente redacta X" significa que el flujo trae `start` con `conv-1`, los eventos `word` de X según RN-009-06 y `end` con `reply = X` y `status = "ACTIVE"`, salvo que se indique otro `status`.
- La cliente está verificada (`D-1001`), salvo que se indique otra cosa.

### AC-009-01 — La redacción llega palabra por palabra

Cubre: HU-009-01, RN-009-01, RN-009-03, RN-009-06, RN-009-08

- **Given** el ciclo termina con `end_turn` y el guion de la redacción entrega los trozos `"Abrimos tu dis"`, `"puta por "`, `"85.000 COP."` con 1 s entre ellos y luego `end_turn`
- **When** la cliente envía un mensaje a `POST /api/chat/stream`
- **Then** responde `200` con eventos `start` (`conv-1`), `word` `"Abrimos"`, `word` `" tu"`, `word` `" disputa"`, `word` `" por"`, `word` `" 85.000"`, `word` `" COP."` y `end`
- **And** cada `word` se emite en cuanto la palabra está completa: `" disputa"` sale con el 2.º trozo, antes del 3.º
- **And** `end` trae `reply = "Abrimos tu disputa por 85.000 COP."`, igual a la concatenación de los fragmentos
- **And** hubo exactamente una llamada de redacción y no ofreció ninguna herramienta

### AC-009-02 — Mientras el agente consulta no se envía texto

Cubre: HU-009-02, RN-009-02, RN-009-03

- **Given** el ciclo hace 3 llamadas al LLM: dos `tool_use` (`consultar_transacciones`, `evaluar_disputa`) con texto `"Voy a revisar…"` y una `end_turn` con texto `"Listo."`
- **When** la cliente envía un mensaje al endpoint de streaming
- **Then** entre `start` y el primer `word` no hay ningún otro evento
- **And** ningún fragmento contiene `"Voy a revisar"` ni `"Listo."`. Los fragmentos son solo los de la llamada de redacción

### AC-009-03 — Las decisiones y acciones se toman antes de la primera palabra

Cubre: HU-009-05, RN-009-02, RN-009-03, RN-009-05

- **Given** la cliente disputa `TX-L1` (85.000 COP, nacional) y el ciclo abre la disputa (DP-007-05)
- **When** la redacción entrega `"Abrimos tu disputa."`
- **Then** la llamada a `iniciar_disputa`, la decisión de `DisputePolicy` y sus registros de auditoría ocurren antes que la llamada de redacción
- **And** el primer `word` se emite después de esos registros
- **And** `end.outcomes` trae `DISPUTE_OPENED` con la regla `DP-007-05`, igual que `POST /api/chat` en el mismo escenario

### AC-009-04 — El texto de la redacción no ejecuta ni cambia acciones

Cubre: HU-009-05, RN-009-05, RN-009-11

- **Given** el ciclo no ejecutó ninguna acción (`outcomes` vacío)
- **When** la redacción entrega `"Ya bloqueé tu tarjeta y abrí la disputa."` y `end_turn`
- **Then** no se invoca `bloquear_tarjeta`, `iniciar_disputa` ni ninguna otra herramienta después de la redacción
- **And** `end.outcomes` sigue vacío
- **And** el registro de respuesta mostrada trae `COMPLETE`, ese texto y una lista de `outcomes` vacía

Además, las instrucciones de la llamada de redacción piden no afirmar acciones que no figuren en los `outcomes` (RN-009-03).

### AC-009-05 — Las palabras no se parten ni se alteran

Cubre: HU-009-01, RN-009-06, RN-009-08

- **Given** la redacción entrega `<contenido>` partido en trozos de 3 caracteres
- **When** el agente transmite la respuesta
- **Then** cada fragmento contiene exactamente una palabra completa con su espacio en blanco previo
- **And** la concatenación de los fragmentos y `end.reply` son exactamente `<contenido>`

| contenido |
|---|
| `Tildes, ñandú y emojis 😀` |
| `Línea 1\nLínea 2` |
| `Mira ` + una palabra de 80 caracteres sin espacios |
| `<b>texto</b> con marcas de código` |

### AC-009-06 — El filtro se aplica antes de enviar cada palabra

Cubre: HU-009-05, RN-009-07, RN-009-08

- **Given** la cliente aportó el documento `D-1001` en la conversación
- **When** la redacción entrega `<texto>` en trozos de 2 caracteres
- **Then** ningún fragmento contiene `<nunca aparece>`
- **And** `end.reply` es `<reply>`

| texto | nunca aparece | reply |
|---|---|---|
| `Tu tarjeta 4111 1111 1111 4321 fue bloqueada.` | `4111` | `Tu tarjeta [REDACTED] fue bloqueada.` |
| `Tu documento D-1001 está verificado.` | `D-1001` | `Tu documento` + la forma enmascarada de `D-1001` (RN-001-09) + ` está verificado.` |
| `Bloqueamos tu tarjeta **** 4321.` | — | `Bloqueamos tu tarjeta **** 4321.` |

### AC-009-07 — Respuestas fijas sin redacción

Cubre: RN-009-04, RN-009-21

- **Given** `<caso>`
- **When** la cliente envía un mensaje al endpoint de streaming
- **Then** no hay llamada de redacción ni eventos `word`
- **And** el flujo es `start` y `end` con `reply = <reply fijo>` y `status = "ESCALATED"`

| caso | reply fijo |
|---|---|
| el ciclo supera el límite de 8 llamadas (RN-007-23) | `No pudimos completar tu solicitud automáticamente. Una persona continuará la atención.` |
| el ciclo recibe `max_tokens` (RN-007-34) | `Tuvimos un problema al procesar tu solicitud. Una persona continuará la atención.` |
| la conversación ya estaba cerrada (RN-007-24) | `Tu caso ya fue derivado a un analista. Una persona continuará la atención.` |

### AC-009-08 — Validación de la entrada antes de transmitir

Cubre: RN-009-01

- **When** se envía a `POST /api/chat/stream` `<entrada>`
- **Then** responde `<código>` como error HTTP, sin flujo de eventos y sin llamar al LLM

| entrada | código |
|---|---|
| `{"message": "   "}` | `422` |
| `message` de 2001 caracteres | `422` |
| `{"conversation_id": "no-existe", "message": "hola"}` | `404` |

### AC-009-09 — La redacción se interrumpe a mitad de la respuesta

Cubre: HU-009-04, RN-009-09, RN-009-10, RN-009-05

- **Given** el ciclo abrió la disputa de `TX-L1` y la redacción ya envió `"Abrimos"` y `" tu"`
- **When** ocurre `<falla>`
- **Then** no se envía ningún `word` más y se emite `interrupted` con `reply = "Tuvimos un problema al procesar tu solicitud. Una persona continuará la atención."` y `status = "ESCALATED"`
- **And** `interrupted.outcomes` trae `DISPUTE_OPENED` y `LLM_FAILURE` (regla `RN-009-10`)
- **And** se invoca una sola vez `escalar_a_analista` con `reason = "UNRECOVERABLE_SYSTEM_FAILURE"` y no se invoca ninguna otra herramienta
- **And** la conversación queda cerrada: un mensaje posterior recibe el texto fijo de RN-007-24
- **And** el registro de respuesta mostrada trae `INTERRUPTED`, la causa `<causa>` y el texto `"Abrimos tu"`

| falla | causa |
|---|---|
| el LLM lanza un error | `LLM_ERROR` |
| el LLM no entrega texto nuevo en 30 s | `LLM_TIMEOUT` |
| la redacción termina con `max_tokens` | `LLM_INVALID_OUTPUT` |
| la redacción trae una petición de herramienta (`bloquear_tarjeta`) | `LLM_INVALID_OUTPUT` |
| el agente sufre una falla interna inesperada | `INTERNAL_ERROR` |

En la fila de la petición de herramienta, `bloquear_tarjeta` no se invoca.

### AC-009-10 — Espera máxima del agente a la redacción

Cubre: RN-009-09

- **Given** la redacción entregó `"Hola "` y el LLM no entrega nada más durante `<segundos>` segundos, tras los cuales entrega `"Ana."` y `end_turn`
- **When** pasa el tiempo
- **Then** `<resultado>`

| segundos | resultado |
|---|---|
| 29 | se emiten `word` `" Ana."` y `end`; no hay derivación |
| 30 | a los 30 s se emite `interrupted` con causa `LLM_TIMEOUT` y se deriva |

Y con la espera configurada en 10 s, la interrupción ocurre a los 10 s.

### AC-009-11 — Redacción vacía o inválida sin palabras enviadas

Cubre: HU-009-04, RN-009-09, RN-009-10

- **Given** el ciclo termina con `end_turn`
- **When** la llamada de redacción `<respuesta>`
- **Then** no se emite ningún `word`, se emite `interrupted` con el mensaje fijo de `LLM_FAILURE` y `status = "ESCALATED"`, y se deriva con `UNRECOVERABLE_SYSTEM_FAILURE`

| respuesta |
|---|
| termina con `end_turn` y texto `"   "` |
| termina con `refusal` sin texto |
| lanza un error antes de entregar texto |

### AC-009-12 — Registro de cada respuesta mostrada

Cubre: HU-009-05, RN-009-11

- **Given** un reloj inyectado fijo y la cliente aportó `D-1001`
- **When** `<caso>`
- **Then** queda un registro de respuesta mostrada con `conversation_id`, la marca del reloj, `<resultado>`, `<causa>`, el texto enviado y el `kind`/`rule` de cada `outcome` del turno
- **And** el registro de respuesta del LLM de la llamada de redacción trae la regla `<regla>`
- **And** ningún registro contiene `4111111111114321` ni `D-1001`

| caso | resultado | causa | regla |
|---|---|---|---|
| la redacción `"Tu tarjeta 4111111111114321 y tu documento D-1001."` termina con `end_turn` | `COMPLETE` | — | `RN-009-03` |
| la redacción se corta con `max_tokens` | `INTERRUPTED` | `LLM_INVALID_OUTPUT` | `RN-009-09` |

### AC-009-13 — La página se desconecta durante la redacción

Cubre: RN-009-12

- **Given** la redacción ya envió dos palabras
- **When** la conexión del flujo se cierra desde la página
- **Then** el agente no vuelve a llamar al LLM en ese turno y no invoca `escalar_a_analista`
- **And** queda un registro de respuesta mostrada `INTERRUPTED` con causa `CLIENT_DISCONNECTED`
- **And** la conversación sigue `ACTIVE`: el siguiente mensaje a `conv-1` se atiende normalmente

### AC-009-14 — Sin identidad verificada no se transmiten datos de la cuenta (e2e)

Cubre: HU-009-05, RN-009-04, RN-009-26

- **Given** el servidor MCP real por stdio con las semillas, y una cliente que aún no verificó su identidad y solo escribió `No reconozco un cobro`
- **When** el ciclo termina con `end_turn` sin que la cliente quede verificada
- **Then** no hay llamada de redacción ni eventos `word`: el flujo es `start` y `end` con el texto fijo `REMINDER_LOCATE` de la spec 007 §7.4 (RN-007-38) y `status = "ACTIVE"`
- **And** el flujo no contiene transacciones, tarjetas (`****`) ni datos personales

### AC-009-15 — La respuesta aparece palabra por palabra en la página

Cubre: HU-009-01, RN-009-13, RN-009-15

- **Given** la página está cargada
- **When** la cliente envía `Hola` y el agente redacta `Abrimos tu disputa por 85.000 COP.`, con 500 ms entre palabras
- **Then** tras la primera palabra la burbuja del `Agente` muestra `Abrimos` y no el texto completo
- **And** la burbuja crece palabra a palabra y nunca muestra una palabra a medias
- **And** al llegar `end` muestra exactamente `Abrimos tu disputa por 85.000 COP.`
- **And** la única petición de la página al agente fue a `POST /api/chat/stream`, con `{"message": "Hola"}`

### AC-009-16 — El indicador se muestra hasta la primera palabra

Cubre: HU-009-02, RN-009-14

- **Given** la cliente envió un mensaje y el flujo trae `start` y, 3 s después, la primera palabra
- **When** todavía no llega ninguna palabra
- **Then** la página muestra `El agente está escribiendo…` y no hay burbuja de respuesta del agente
- **And** cuando llega la primera palabra, el indicador deja de mostrarse

### AC-009-17 — El contenido se muestra como texto y exacto

Cubre: HU-009-01, RN-009-15, RN-008-09

- **Given** la cliente envió un mensaje
- **When** el agente redacta `<contenido>`
- **Then** la burbuja muestra exactamente `<contenido>`, con sus saltos de línea
- **And** la conversación no contiene elementos creados a partir del texto, no se abre ningún diálogo del navegador y no hay desplazamiento horizontal

| contenido |
|---|
| `Tildes, ñandú y emojis 😀` |
| `Línea 1\nLínea 2` |
| `Mira ` + una palabra de 80 caracteres sin espacios |
| `<b>texto</b> con marcas de código` |
| `<img src=x onerror=alert(1)>` |

### AC-009-18 — Los datos enmascarados se muestran tal como llegan

Cubre: HU-009-01, RN-009-13, RN-008-10

- **When** el agente redacta `Bloqueamos tu tarjeta **** 4321.` y `end` trae en `outcomes` `masked_card = "**** 4321"` y `rule = "RN-007-14"`
- **Then** la burbuja muestra exactamente `Bloqueamos tu tarjeta **** 4321.`
- **And** la página no muestra `RN-007-14` ni otro campo de `outcomes`

### AC-009-19 — No se envía otro mensaje mientras la respuesta aparece

Cubre: HU-009-01, RN-009-16

- **Given** la respuesta del agente está apareciendo (llegaron 2 de 5 palabras)
- **When** la cliente escribe `otro` y pulsa Enter y `Enviar`
- **Then** no se hace ninguna petición nueva
- **And** al llegar `end` la caja de texto vuelve a aceptar envíos y tiene el foco

### AC-009-20 — El aviso de derivación aparece al terminar el texto

Cubre: HU-009-04, RN-009-17

- **Given** la cliente envió un mensaje
- **When** el agente redacta `Derivamos tu caso a un analista.` con 500 ms entre palabras, y `end` trae `status = "ESCALATED"`
- **Then** mientras aparecen las palabras no se muestra el aviso de derivación ni `Iniciar una conversación nueva`
- **And** tras la última palabra se muestra debajo el aviso de derivación, la caja de texto y `Enviar` quedan deshabilitados y aparece `Iniciar una conversación nueva`

### AC-009-21 — Respuesta interrumpida en la página

Cubre: HU-009-04, RN-009-18

- **Given** el agente envió `Abrimos tu`
- **When** llega `interrupted` con `reply = "Tuvimos un problema al procesar tu solicitud. Una persona continuará la atención."` y `status = "ESCALATED"`
- **Then** la burbuja `Abrimos tu` se conserva y se marca `Incompleto`
- **And** debajo aparece, completa al instante, una burbuja del `Agente` con ese `reply`, y luego el aviso de derivación
- **And** la conversación se cierra y se ofrece `Iniciar una conversación nueva`

### AC-009-22 — Un lector de pantalla anuncia cada respuesta una sola vez

Cubre: HU-009-03, RN-009-19

- **Given** la cliente usa un lector de pantalla
- **When** el agente redacta `Abrimos tu disputa.` palabra por palabra
- **Then** mientras llegan las palabras no se añade ni cambia texto en ninguna región viva (`aria-live`)
- **And** al llegar `end`, la región viva recibe una sola vez el mensaje completo, cuyo texto accesible empieza por `Agente`

### AC-009-23 — Con reducir movimiento la respuesta aparece al terminar

Cubre: HU-009-03, RN-009-20

- **Given** el navegador emula `prefers-reduced-motion: reduce`
- **When** el agente redacta `Abrimos tu disputa.` con 500 ms entre palabras
- **Then** mientras llegan las palabras se muestra `El agente está escribiendo…` y ninguna palabra
- **And** al llegar `end` aparece de una vez la burbuja con `Abrimos tu disputa.`

### AC-009-24 — Solo la redacción del agente aparece palabra por palabra

Cubre: RN-009-21

- **When** la cliente abre la página, envía `Hola` y el agente responde un texto fijo (flujo `start` y `end` sin `word`) con `status = "ESCALATED"`
- **Then** el saludo está completo desde la carga, el mensaje `Hola` aparece completo al enviarse y la respuesta fija y el aviso de derivación aparecen completos de una vez

### AC-009-25 — Espera máxima sin palabras nuevas

Cubre: HU-009-02, RN-009-22, RN-009-24

- **Given** la cliente envió un mensaje, el agente envió `Abrimos` y no llega ninguna palabra nueva durante `<segundos>` segundos
- **When** se cumple ese tiempo
- **Then** `<resultado>`

| segundos | resultado |
|---|---|
| 59 | la página sigue esperando y no muestra ningún aviso de demora; luego llegan las palabras restantes y `end` y se muestra la respuesta completa |
| 60 | se muestra el aviso de demora, desaparece `El agente está escribiendo…`, aparece `Reintentar` y `Abrimos` queda marcado `Incompleto` |
| 61 | igual que 60, a los 60 s; las palabras que llegan después no se muestran |

### AC-009-26 — Cada palabra reinicia la espera

Cubre: RN-009-22, RN-009-24

- **Given** la cliente envió un mensaje
- **When** el agente envía 4 palabras con 50 s entre cada una y luego `end` (más de 60 s en total)
- **Then** no se muestra el aviso de demora y se muestra la respuesta completa

Y si el agente no envía ninguna palabra en 60 s desde el envío, se muestra el aviso de demora y el mensaje de la cliente se marca `No enviado` (RN-009-24).

### AC-009-27 — Se pierde la conexión mientras la respuesta aparece

Cubre: HU-009-04, RN-009-23, RN-009-24

- **Given** la cliente intercambió un mensaje con el agente (`conv-1`), envió `¿Sigues ahí?` y el agente envió `Sí,`
- **When** el navegador queda sin conexión
- **Then** se muestra el aviso de sin conexión y `Reintentar`
- **And** se conservan los mensajes anteriores, `¿Sigues ahí?` sigue visible sin la marca `No enviado` y `Sí,` queda marcado `Incompleto`
- **And** al volver la conexión y pulsar `Reintentar`, se envía `{"conversation_id": "conv-1", "message": "¿Sigues ahí?"}` y la respuesta nueva aparece debajo, sin repetir la burbuja de la cliente

### AC-009-28 — El flujo falla sin llegar a terminar

Cubre: RN-009-23, RN-009-24

- **Given** la cliente envió un mensaje y el agente envió `Abrimos`
- **When** `<falla>`
- **Then** se muestra el aviso de servicio no disponible y `Reintentar`, sin códigos ni detalles técnicos, y `Abrimos` queda marcado `Incompleto`

| falla |
|---|
| el flujo se cierra sin `end` ni `interrupted` |
| llega un evento cuyo contenido no es JSON válido |

Y si `POST /api/chat/stream` responde `503` antes de transmitir, se muestra el aviso de servicio no disponible. Si responde `404`, la página actúa como en AC-008-20.

### AC-009-29 — Recargar o empezar de nuevo no deja texto residual

Cubre: RN-009-25

- **Given** la respuesta del agente está apareciendo y quedan palabras por llegar
- **When** `<acción>`
- **Then** el único mensaje de la conversación es el saludo y no aparece ninguna palabra de la respuesta anterior, tampoco 2 s después
- **And** al enviar `hola`, la petición no lleva `conversation_id`

| acción |
|---|
| la cliente recarga la página |
| llega `interrupted`, el flujo sigue enviando eventos `word` y la cliente pulsa `Iniciar una conversación nueva` |

### AC-009-30 — Sin identidad verificada, la página no muestra datos de la cuenta

Cubre: RN-009-13, RN-009-26, RN-008-11

- **Given** la cliente aún no fue identificada
- **When** envía `No reconozco un cobro` y el agente redacta `Para ayudarte necesito tu número de documento.`
- **Then** la página muestra solo el saludo, el mensaje de la cliente y esa respuesta, sin transacciones, tarjetas ni datos personales
- **And** la única petición fue a `POST /api/chat/stream`

## 7. Contratos de herramientas MCP

No aplica: la feature no crea ni modifica herramientas MCP.

### 7.1 API HTTP del agente: `POST /api/chat/stream`

No es una herramienta MCP. Es un endpoint nuevo de `dispute_agent`. `POST /api/chat` (spec 007 §7.3) no cambia.

**Entrada** (JSON): igual que `POST /api/chat` (`conversation_id` opcional, `message` de 1 a 2000 caracteres tras recortar).

**Errores HTTP** (antes de transmitir, sin flujo): `422` (cuerpo inválido o `message` fuera de rango) y `404` (`conversation_id` que no existe), como en spec 007 §7.3.

**Salida** (`200`, `text/event-stream`): una secuencia de eventos Server-Sent Events, cada uno con `event: <tipo>` y `data: <JSON>`, en este orden: un `start`, cero o más `word` y exactamente un evento final (`end` o `interrupted`).

| Evento | `data` | Cuándo |
|---|---|---|
| `start` | `{"conversation_id": string}` | Al aceptar la petición, antes del ciclo (RN-009-02). |
| `word` | `{"text": string}` | Un fragmento: una palabra completa con su espacio en blanco previo, ya filtrado (RN-009-06, RN-009-07). |
| `end` | `{"conversation_id": string, "reply": string, "status": "ACTIVE" \| "ESCALATED", "outcomes": list[Outcome]}` | La respuesta terminó completa. `reply` es la concatenación de los `word` (RN-009-08) o el texto fijo (RN-009-04). `Outcome` es el de spec 007 §7.3. |
| `interrupted` | `{"conversation_id": string, "reply": string, "status": "ESCALATED", "outcomes": list[Outcome]}` | La redacción se interrumpió (RN-009-09, RN-009-10). `reply` es el mensaje fijo de `LLM_FAILURE`. |

Un evento con un tipo distinto, un `data` que no es JSON válido o sin `conversation_id`, `reply` y `status` válidos es inválido para la página (RN-009-23). `outcomes` lo envía siempre el servidor, pero la página no lo usa (RN-009-13) y no lo valida: su ausencia no invalida el evento. Las fallas del LLM y del core durante el flujo no son errores HTTP.

Cómo trata la página cada resultado:

| Resultado | Comportamiento |
|---|---|
| `word` | Añade el fragmento (RN-009-15), oculta el indicador (RN-009-14) y reinicia la espera (RN-009-22). |
| `end` con `ACTIVE` | Fija el texto de la burbuja a `reply` y habilita la caja (RN-009-16). |
| `end` con `ESCALATED` | Fija el texto y luego muestra el aviso de derivación y cierra (RN-009-17). |
| `interrupted` | Marca `Incompleto`, muestra `reply`, el aviso de derivación y cierra (RN-009-18). |
| `404` | RN-008-15. |
| 60 s sin `word` | Aviso de demora y `Reintentar` (RN-009-22, RN-009-24). |
| Sin conexión | Aviso de sin conexión y `Reintentar` (RN-009-23, RN-009-24). |
| Otro código, flujo cortado o evento inválido | Aviso de servicio no disponible y `Reintentar` (RN-009-23, RN-009-24). |

### 7.2 Textos fijos nuevos de la página

Se añaden a los de la spec 008 §7.2:

| Elemento | Texto |
|---|---|
| Marca de respuesta incompleta | `Incompleto` |

### 7.3 Configuración nueva del agente

| Parámetro | Valor por defecto | Regla |
|---|---|---|
| Espera máxima sin texto nuevo en la llamada de redacción | 30 s | RN-009-09 |

## 8. Casos de escalamiento

| Condición | Motivo | Datos del resumen estructurado | Cierra la conversación |
|---|---|---|---|
| La redacción se interrumpe por error del LLM, 30 s sin texto nuevo, salida inválida o falla interna del agente (RN-009-09, RN-009-10) | `UNRECOVERABLE_SYSTEM_FAILURE` | Completo sin transacción si está verificada, limitado si no (spec 007 §8). Nota con la causa (`LLM_ERROR`, `LLM_TIMEOUT`, `LLM_INVALID_OUTPUT` o `INTERNAL_ERROR`), sin detalles internos ni texto del LLM | Sí |

La desconexión de la página (RN-009-12) **no** deriva. Las derivaciones del ciclo de decisión siguen la spec 007 §8 sin cambios. Ningún resumen ni nota contiene el número completo de una tarjeta, el documento ni el nombre del cliente (RN-006-13, RN-007-26).

## 9. Clarificaciones

| Fecha | Pregunta | Respuesta | Secciones afectadas |
|---|---|---|---|
| 2026-10-18 | ¿Cómo se garantiza que solo se muestre palabra por palabra la redacción final, si la razón de parada solo se conoce al terminar cada respuesta del LLM? | El ciclo de 007 decide y actúa sin mostrar nada. Al terminar con `end_turn`, el agente hace una llamada de redacción al LLM sin herramientas, que se transmite en tiempo real. | §1, RN-009-02, RN-009-03, AC-009-01 a AC-009-03 |
| 2026-10-18 | ¿Cómo recibe la página las palabras, si 008 fija que solo usa `POST /api/chat` sin cambios? | Endpoint nuevo de streaming. `POST /api/chat` queda intacto y se enmienda RN-008-01. | §1, RN-009-01, RN-009-13, §7.1, AC-009-08, AC-009-15 |
| 2026-10-18 | ¿Cuánto espera el agente a la llamada de redacción sin texto nuevo antes de derivar? | 30 s, configurable. | RN-009-09, §7.3, AC-009-09, AC-009-10 |
| 2026-10-18 | ¿Cómo se registra que el texto afirme una acción no realizada, si RN-007-33 prohíbe interpretar el texto por palabras? | Al terminar cada respuesta se audita su texto filtrado junto a los `outcomes` del turno, sin detección automática, para revisión humana. El sistema nunca ejecuta acciones por el texto. | §2 fuera de alcance, RN-009-05, RN-009-11, AC-009-04, AC-009-12 |
| 2026-10-18 | ¿Qué pasa con el texto parcial si se pierde la conexión o salta el aviso de demora? | Se conserva marcado `Incompleto`. `Reintentar` reenvía el mismo mensaje a la misma conversación y la respuesta nueva aparece debajo. | RN-009-24, §7.2, AC-009-25, AC-009-27, AC-009-28 |
| 2026-10-18 | ¿Cómo se interpreta «el servicio de consulta falla de forma no recuperable», si la redacción no consulta el core? | Como una falla interna del agente durante la redacción, con el mismo tratamiento que las fallas del LLM. | RN-009-09 (d), AC-009-09 |
| 2026-10-18 | ¿La llamada de redacción cuenta en el máximo de 8 llamadas de RN-007-23? | No. Siempre es una llamada adicional cuando el ciclo termina con `end_turn`. Si el ciclo deriva por límite o falla, no hay redacción. | RN-009-03, RN-009-04, AC-009-07 |
| 2026-10-18 | (v0.1.1, auditoría de AC) ¿La página debe exigir `outcomes` en los eventos `end` e `interrupted`, o basta con `reply` y `status`? | Basta con `conversation_id`, `reply` y `status`: la página no usa `outcomes` (RN-009-13), así que no lo valida y su ausencia no invalida el evento. El servidor lo sigue enviando siempre. | §7.1, RN-009-23, AC-009-29 |

## 10. Preguntas abiertas

Ninguna.

## 11. Historial de cambios

| Versión | Fecha | Cambio | Autor |
|---|---|---|---|
| 0.1.0 | 2026-10-18 | Versión inicial a partir de la issue #42 | Juangiov (con Claude Code) |
| 0.1.0 | 2026-10-18 | Spec aprobada por el usuario | Juangiov |
| 0.1.1 | 2026-10-18 | Enmienda PATCH tras la auditoría de AC (decisión del usuario): §7.1 aclara que la página no valida `outcomes`; AC-009-26 incorpora RN-009-24 en `Cubre:`. Sin cambio de comportamiento ni del plan. | Juangiov (con Claude Code) |
| 0.2.0 | 2026-10-19 | Alineación con la spec 007 v0.3.0 (issue #45): RN-009-04 incluye los turnos que terminan sin identidad verificada (texto fijo, sin redacción) y AC-009-14 espera `REMINDER_LOCATE` en `end`, sin `word`. Aprobada por el usuario junto con la 007 v0.3.0. | Juangiov (con Claude Code) |

---

## Gate de salida

- [x] No quedan preguntas abiertas.
- [x] Cada clarificación está reflejada en las secciones afectadas.
- [x] Todos los criterios de aceptación tienen ID y formato Given/When/Then.
- [x] Cada regla de negocio está cubierta por al menos un criterio de aceptación.
- [x] Contratos MCP y casos de escalamiento completos o marcados "No aplica".
- [x] Estado cambiado a **Aprobada**.
