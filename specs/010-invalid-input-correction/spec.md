# Spec: Corregir los argumentos que el core rechaza en lugar de derivar el caso

| Campo | Valor |
|---|---|
| Feature | `010-invalid-input-correction` |
| Versión | 0.1.0 |
| Estado | Aprobada |
| Fecha | 2026-10-19 |
| Plan | [plan.md](./plan.md) |
| Tareas | [tasks.md](./tasks.md) |
| Constitución | [docs/constitution.md](../../docs/constitution.md) |

---

## 1. Contexto y problema

El agente de disputas (spec 007) deriva a un analista y cierra la conversación cuando una herramienta del core falla de forma no recuperable (RN-007-21). Hoy esa regla alcanza, en la práctica, a **cualquier** error de herramienta, incluido `INVALID_INPUT`: un error de validación que no es una falla del sistema, sino el core diciendo que los argumentos de la petición no son válidos.

Incidente observado (conversación `d5f3bb05dc194f938990541eb8bd4612`, derivación `ESC-000010`, 2026-10-19): una cliente verificada pidió disputar `TX-000001`. El LLM pidió `consultar_transacciones` con argumentos que el core rechazó con `INVALID_INPUT` (no reintentable). El agente lo trató como `UNRECOVERABLE_SYSTEM_FAILURE`: derivó el caso, cerró la conversación y le dijo a la cliente que su caso requería la revisión de una persona, cuando bastaba con que el LLM corrigiera el argumento (por ejemplo una fecha posterior a hoy o un rango de más de 90 días).

Hay dos defectos:

1. **Comportamiento.** `.claude/rules/agent-behavior.md` (regla 19) distingue cuatro categorías de error; ante un error de **validación** el LLM corrige los argumentos. El agente ya lo hace con `verificar_identidad` (RN-007-40), pero no con `consultar_transacciones` ni `buscar_cliente`, cuyos argumentos forma o extrae el LLM. La spec 007 es silenciosa: RN-007-21 solo exceptúa el `INVALID_INPUT` de `verificar_identidad`.
2. **Diagnóstico.** Antes de derivar por RN-007-21 el agente no audita qué herramienta falló ni con qué código y campo; ese dato solo queda en el motivo de `conversation_closed`, y sin el campo inválido.

Esta spec corrige el comportamiento para las dos lecturas con argumentos del LLM, acota la corrección con un tope y cierra el hueco de auditoría. Enmienda la spec 007 (RN-007-21, RN-007-28, RN-007-38, §7.4 y §8).

## 2. Objetivos

- Un `INVALID_INPUT` de `consultar_transacciones` o de `buscar_cliente` no deriva ni cierra la conversación: el LLM recibe un error de validación y puede corregir los argumentos y reintentar.
- La corrección está acotada: como máximo 2 correcciones por mensaje de la cliente; al agotarlas se deriva con `INSUFFICIENT_OR_CONTRADICTORY_INFO`.
- Un `INVALID_INPUT` nunca se da por un resultado: no localiza a la cliente, no registra transacciones vistas y no cuenta como búsqueda sin coincidencias.
- Cada `INVALID_INPUT` y cada derivación por falla del sistema (RN-007-21) dejan registro de la herramienta, el código y, si lo hay, el campo inválido.
- La spec 007 queda coherente con este comportamiento.

### Fuera de alcance

- `iniciar_disputa` y `bloquear_tarjeta`: sus argumentos los fija el sistema, así que un `INVALID_INPUT` ahí es un defecto del sistema y sigue derivando (RN-007-21).
- `verificar_identidad`: sigue como en RN-007-40 (`INVALID_DATES`, sin derivar).
- `INTERNAL`, tiempo límite y respuesta que no cumple el esquema: siguen derivando con `UNRECOVERABLE_SYSTEM_FAILURE` (RN-007-21).
- Cambios en el servidor MCP: sus validaciones y su contrato de errores no cambian.
- Validar en el agente, antes de llamar al core, el rango de fechas o los dígitos de la tarjeta.
- Cambios en `DisputePolicy` y en las reglas de decisión.

## 3. Historias de usuario

| ID | Como | Quiero | Para |
|---|---|---|---|
| HU-010-01 | Cliente verificada | que, si el agente se equivoca al armar la consulta de mis transacciones, la corrija solo | no perder mi conversación ni ser derivada por un error que el agente puede resolver |
| HU-010-02 | Cliente que aún no se ha identificado | que un dato mal formado no cierre mi conversación y se me pida de nuevo | poder identificarme sin tener que empezar otra vez |
| HU-010-03 | Analista | que, si el caso llega derivado por datos que no se lograron formar, la nota diga qué herramienta falló y en qué campo | saber qué ocurrió sin acceder a la conversación |
| HU-010-04 | Auditor | que cada argumento rechazado y cada derivación por falla queden registrados con herramienta, código y campo | reconstruir el incidente solo con el registro (Art. 8) |

## 4. Reglas de negocio

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-010-01 | Si `consultar_transacciones` o `buscar_cliente` responden `INVALID_INPUT`, el agente no lo trata como falla del sistema: no aplica RN-007-21, no deriva y no cierra la conversación. Devuelve al LLM un error de validación `invalid_input` con el campo que el servidor señala (§7.2) para que corrija los argumentos y vuelva a pedir la herramienta. El agente nunca reenvía por sí mismo los mismos argumentos. | `agent-behavior.md` §19; `mcp-client.md` §4; RN-007-40 |
| RN-010-02 | El texto que recibe el LLM en ese error es **fijo** y lo redacta el agente (§7.2); no es el texto del servidor. No incluye los valores enviados (documento, nombre, tarjeta, fechas) ni detalles internos. Indica cuántas correcciones quedan en el mensaje. | RN-007-27; Art. 1; `mcp-client.md` §6 |
| RN-010-03 | Como máximo **2** correcciones por mensaje de la cliente: se cuentan los `INVALID_INPUT` de `consultar_transacciones` y de `buscar_cliente` juntos y el contador vuelve a 0 con cada mensaje nuevo de la cliente. El 1.º y el 2.º `INVALID_INPUT` del mensaje se devuelven al LLM; el 3.º no se corrige y se aplica RN-010-04. | Clarificación 2026-10-19; RN-007-23 (el tope de 8 llamadas sigue vigente) |
| RN-010-04 | Con el 3.º `INVALID_INPUT` del mensaje el agente deriva con `INSUFFICIENT_OR_CONTRADICTORY_INFO`, informa a la cliente con el texto fijo `ESCALATED` sin transacción (§7.3 de la spec 007) y cierra la conversación (RN-007-24). La nota de la derivación es `RN-010-04: <herramienta> INVALID_INPUT (campo: <campo>) tras 2 correcciones`. El resumen es completo sin transacción ni tarjeta si la cliente está verificada (`consultar_transacciones`) y limitado si no lo está (`buscar_cliente`). Al LLM se le devuelve el mismo resultado de cierre que en RN-007-21. | Art. 10; clarificación 2026-10-19; RN-006-13; RN-007-24 |
| RN-010-05 | Un `INVALID_INPUT` no da nada por hecho: no localiza a la cliente, no registra transacciones como vistas, no genera los `outcomes` `NO_TRANSACTIONS_FOUND` ni `REFINEMENT_REQUIRED` y no cuenta como búsqueda sin coincidencias ni como intento fallido (RN-007-05, RN-007-41). | Art. 5; RN-007-13; RN-007-41 |
| RN-010-06 | Si al terminar el turno la cliente no está verificada y el último resultado de identificación del turno es un `INVALID_INPUT` de `buscar_cliente`, el `reply` es el texto fijo `INVALID_SEARCH` (§7.4). Se añade a la regla de elección de RN-007-38 en el paso (2). | RN-007-38; clarificación 2026-10-19 |
| RN-010-07 | Cada `INVALID_INPUT` corregible genera un registro `tool_call` con `conversation_id`, marca de tiempo del reloj, la herramienta, su entrada filtrada (RN-007-26), la salida `{error: INVALID_INPUT, field, correction: <n>, of: 2}`, la regla `RN-010-01` y el motivo `argumentos rechazados por el core; se devuelven al LLM para corregirlos`. | Art. 8; `mcp-client.md` §5; RN-007-28 |
| RN-010-08 | Antes de derivar por RN-007-21, el agente registra un `tool_call` con la herramienta, el código del error y, si es `INVALID_INPUT`, el campo inválido (el de `iniciar_disputa` y `bloquear_tarjeta`, que siguen derivando), con la regla `RN-007-21`. El motivo de `conversation_closed` y la nota de la derivación incluyen también el campo cuando el código es `INVALID_INPUT`. | Art. 8; HU-010-03; HU-010-04 |
| RN-010-09 | No cambia: `INVALID_INPUT` de `iniciar_disputa` y `bloquear_tarjeta` deriva con `UNRECOVERABLE_SYSTEM_FAILURE` (RN-007-21); `verificar_identidad` con `INVALID_INPUT` sigue RN-007-40; `INTERNAL`, tiempo límite y respuesta fuera de esquema de cualquier herramienta siguen derivando con RN-007-21. | RN-007-21; RN-007-40 |

## 5. Tabla de decisión de `DisputePolicy`

No aplica. Esta feature no cambia ninguna decisión de disputa; solo el manejo de errores de lectura (Art. 5: el dominio decide, el LLM conversa).

## 6. Criterios de aceptación

### AC-010-01 — El LLM corrige una consulta de transacciones rechazada

Cubre: HU-010-01, RN-010-01, RN-010-05

- **Given** la cliente está verificada, la fecha actual es `2026-10-19` y el `FakeLLM` pide `consultar_transacciones` con `<argumentos>`
- **When** el core responde `INVALID_INPUT` con el campo `<campo>` y el `FakeLLM` pide la misma herramienta con argumentos válidos (`card_last4 = "1111"`, `date_from = "2026-09-19"`, `date_to = "2026-10-19"`)
- **Then** el primer resultado que recibe el LLM es un error `invalid_input` con el campo `<campo>`
- **And** el segundo se atiende con normalidad y las transacciones quedan disponibles para evaluar
- **And** la conversación sigue `ACTIVE`, no se invoca `escalar_a_analista` y no hay `outcomes` de derivación

| `<argumentos>` | `<campo>` |
|---|---|
| `date_to = "2026-10-20"` (posterior a hoy) | `date_to` |
| `date_from = "2026-06-01"`, `date_to = "2026-10-19"` (más de 90 días) | `date_range` |
| `date_from = "2026-10-19"`, `date_to = "2026-10-01"` (`date_from` posterior a `date_to`) | `date_range` |
| `card_last4 = "11"` (no son 4 dígitos) | `card_last4` |

### AC-010-02 — El LLM corrige una búsqueda de cliente rechazada

Cubre: HU-010-02, RN-010-01, RN-010-05

- **Given** la cliente no está localizada y el `FakeLLM` pide `buscar_cliente` con `card_last4 = "12"`
- **When** el core responde `INVALID_INPUT` con el campo `card_last4` y el `FakeLLM` vuelve a pedir `buscar_cliente` con `card_last4 = "1111"`
- **Then** el primer resultado que recibe el LLM es un error `invalid_input` con el campo `card_last4`
- **And** la segunda búsqueda se atiende con normalidad y, con una sola coincidencia, la cliente queda localizada
- **And** la conversación sigue `ACTIVE` y no se invoca `escalar_a_analista`

### AC-010-03 — El LLM recibe un texto fijo, sin datos de la cliente

Cubre: HU-010-01, RN-010-02

- **Given** la cliente aportó el documento `1020304050` y el core responde `INVALID_INPUT` con un mensaje de texto libre que contiene ese documento
- **When** el agente devuelve el error al LLM
- **Then** el contenido del resultado es el texto fijo de §7.2 con la herramienta, el campo y las correcciones que quedan
- **And** no contiene el texto del servidor, el documento ni ningún valor enviado

### AC-010-04 — Tercer rechazo en `consultar_transacciones`: se deriva

Cubre: HU-010-01, HU-010-03, RN-010-03, RN-010-04

- **Given** la cliente está verificada y el core responde `INVALID_INPUT` (campo `date_to`) a tres peticiones seguidas de `consultar_transacciones` del mismo mensaje
- **When** el LLM pide por tercera vez `consultar_transacciones`
- **Then** las dos primeras se devuelven al LLM (`correction` 1 de 2 y 2 de 2)
- **And** con la tercera se invoca `escalar_a_analista` con `reason = "INSUFFICIENT_OR_CONTRADICTORY_INFO"`, resumen completo sin `transaction_id` ni `card_id` y la nota `RN-010-04: consultar_transacciones INVALID_INPUT (campo: date_to) tras 2 correcciones`
- **And** `outcomes` trae un único `ESCALATED` sin transacción con la regla `RN-010-04`, y la conversación queda `status = "ESCALATED"`

### AC-010-05 — Tercer rechazo en `buscar_cliente` sin verificar: resumen limitado

Cubre: HU-010-02, HU-010-03, RN-010-03, RN-010-04

- **Given** la cliente no está localizada ni verificada y el core responde `INVALID_INPUT` (campo `document`) a tres peticiones seguidas de `buscar_cliente` del mismo mensaje
- **When** el LLM pide por tercera vez `buscar_cliente`
- **Then** se invoca `escalar_a_analista` con `reason = "INSUFFICIENT_OR_CONTRADICTORY_INFO"`, resumen limitado (sin datos del cliente) y la nota `RN-010-04: buscar_cliente INVALID_INPUT (campo: document) tras 2 correcciones`
- **And** el `reply` es el texto fijo de cierre `ESCALATED` de §7.4 y la conversación queda `status = "ESCALATED"`

### AC-010-06 — El tope es combinado y se reinicia con cada mensaje

Cubre: HU-010-01, HU-010-02, RN-010-03

- **Given** la cliente verificada, y en un mismo mensaje el core responde `INVALID_INPUT` una vez a `buscar_cliente` y una vez a `consultar_transacciones`
- **When** el LLM pide una tercera herramienta que también recibe `INVALID_INPUT`
- **Then** las dos primeras se devuelven al LLM y la tercera deriva (RN-010-04), aunque cada herramienta solo haya fallado una o dos veces
- **And** en otro caso, si la cliente envía un mensaje nuevo tras dos `INVALID_INPUT` en el mensaje anterior, el contador vuelve a 0 y el siguiente `INVALID_INPUT` se devuelve al LLM como la 1.ª corrección

### AC-010-07 — Un rechazo no se da por resultado

Cubre: HU-010-01, HU-010-02, RN-010-05

- **Given** `<situación>`
- **When** el core responde `INVALID_INPUT` a la última petición del turno y el LLM pide después `evaluar_disputa` para `TX-L1`
- **Then** `<resultado>`

| `<situación>` | `<resultado>` |
|---|---|
| cliente verificada y `consultar_transacciones` rechazada | `evaluar_disputa` responde `transaction_not_listed`; no hay `outcomes` `NO_TRANSACTIONS_FOUND` ni `REFINEMENT_REQUIRED` |
| cliente sin localizar y `buscar_cliente` rechazada | la cliente sigue sin localizar y sin verificar |
| dos `buscar_cliente` rechazadas y una tercera sin coincidencias, de un mismo cliente | la conversación sigue `ACTIVE`: las rechazadas no cuentan como búsquedas sin coincidencias (RN-007-05, RN-007-41) |

### AC-010-08 — Texto fijo `INVALID_SEARCH` si la cliente sigue sin verificar

Cubre: HU-010-02, RN-010-06

- **Given** la cliente no está verificada y `buscar_cliente` responde `INVALID_INPUT` como último resultado de identificación del turno
- **When** el LLM termina el turno con `end_turn`
- **Then** el `reply` es el texto fijo `INVALID_SEARCH` de §7.4, sin llamar al LLM para redactarlo
- **And** la conversación sigue `ACTIVE` y no cuenta como búsqueda sin coincidencias ni como intento fallido

### AC-010-09 — Cada rechazo corregible queda auditado

Cubre: HU-010-04, RN-010-07

- **Given** el core responde `INVALID_INPUT` (campo `date_to`) a `consultar_transacciones` con `date_to = "2026-10-20"`
- **When** el agente devuelve el error al LLM
- **Then** queda un registro `tool_call` con `conversation_id`, la marca de tiempo del reloj, `tool = "consultar_transacciones"`, la entrada filtrada, la salida `{"error": "INVALID_INPUT", "field": "date_to", "correction": 1, "of": 2}`, `rule = "RN-010-01"` y el motivo fijo de RN-010-07
- **And** el registro no contiene el texto del servidor ni documentos completos (RN-007-26)

### AC-010-10 — La derivación por falla deja el rastro de la herramienta, el código y el campo

Cubre: HU-010-03, HU-010-04, RN-010-08

- **Given** la cliente está verificada y `<falla>`
- **When** la cliente pide disputar un cargo y el agente llega a esa herramienta
- **Then** antes de `escalation` y `conversation_closed` queda un registro `tool_call` con `tool = <herramienta>`, `rule = "RN-007-21"` y la salida `<salida>`
- **And** el motivo de `conversation_closed` y la nota de la derivación `<incluyen>`

| falla | herramienta | salida | incluyen |
|---|---|---|---|
| `consultar_transacciones` responde `INTERNAL` | `consultar_transacciones` | `{"error": "INTERNAL"}` | herramienta y código, sin campo |
| `iniciar_disputa` responde `INVALID_INPUT` (campo `transaction_id`) | `iniciar_disputa` | `{"error": "INVALID_INPUT", "field": "transaction_id"}` | herramienta, código y campo |
| `bloquear_tarjeta` responde `INVALID_INPUT` (campo `card_id`) | `bloquear_tarjeta` | `{"error": "INVALID_INPUT", "field": "card_id"}` | herramienta, código y campo |
| `consultar_transacciones` no responde dentro del tiempo límite | `consultar_transacciones` | `{"error": "UNAVAILABLE"}` | herramienta y código, sin campo |

### AC-010-11 — Lo que no cambia sigue derivando o corrigiendo como antes

Cubre: HU-010-01, RN-010-09

- **Given** la cliente está verificada (o, en la última fila, localizada) y `<falla>`
- **When** el agente llega a esa herramienta
- **Then** `<resultado>`

| `<falla>` | `<resultado>` |
|---|---|
| `iniciar_disputa` responde `INVALID_INPUT` | se deriva con `UNRECOVERABLE_SYSTEM_FAILURE` (RN-007-21) y la conversación se cierra; no se devuelve al LLM para corregir |
| `bloquear_tarjeta` responde `INVALID_INPUT` | se deriva con `UNRECOVERABLE_SYSTEM_FAILURE` y la conversación se cierra |
| `consultar_transacciones` responde `INTERNAL` | se deriva con `UNRECOVERABLE_SYSTEM_FAILURE` (AC-007-23) |
| `verificar_identidad` responde `INVALID_INPUT` | no se deriva; la cliente recibe `INVALID_DATES` (RN-007-40, AC-007-49) |

### AC-010-12 — Fecha futura con el servidor real (e2e)

Cubre: HU-010-01, HU-010-04, RN-010-01, RN-010-07

- **Given** el agente con el servidor MCP real por stdio, la cliente verificada y el `FakeLLM` que pide `consultar_transacciones` con `date_to` posterior a hoy y después con una fecha válida
- **When** la cliente pide revisar un cobro
- **Then** el servidor responde `INVALID_INPUT` con el campo `date_to` y el agente lo devuelve al LLM
- **And** la segunda consulta devuelve transacciones, la conversación sigue `ACTIVE` y no se crea ninguna derivación
- **And** el registro de auditoría contiene el `tool_call` de RN-010-07 con el campo `date_to`

## 7. Contratos de herramientas MCP

### 7.1 Herramientas del servidor

No aplica. Ninguna herramienta MCP cambia de entrada, salida ni errores. Se usa el error `INVALID_INPUT` ya definido (no reintentable) en `consultar_transacciones` (spec 003, RN-003-06) y en `buscar_cliente` (spec 001, RN-001-05).

### 7.2 Resultado de herramienta hacia el LLM (agente)

Cambia el resultado que el agente devuelve al LLM para `consultar_transacciones` y `buscar_cliente`. Es el `tool_result` de error (`is_error = true`), no un `outcome` de la API.

| Campo | Tipo | Descripción |
|---|---|---|
| `error` | `string` | Siempre `invalid_input`. |
| `field` | `string \| null` | Campo que el servidor señala como inválido (p. ej. `date_to`, `date_range`, `card_last4`, `document`); `null` si no lo informa. |
| `corrections_remaining` | `integer` | Correcciones que quedan en el mensaje: `1` tras el 1.º rechazo y `0` tras el 2.º (RN-010-03). |
| `message` | `string` | Texto fijo (RN-010-02): `Los datos enviados a <herramienta> no son válidos (campo: <campo>). Corrígelos y vuelve a llamar a la herramienta; si no puedes formarlos con lo que dijo la cliente, pídeselos.` Sin `(campo: …)` si `field` es `null`. |

Con el 3.º rechazo no se devuelve este resultado: se devuelve el de cierre de RN-007-21 (`system_unavailable` con los `outcomes`), tras derivar (RN-010-04).

### 7.3 Evento de auditoría (RN-010-07, RN-010-08)

Se reutiliza el tipo `tool_call` de RN-007-28; no hay un tipo nuevo.

| Caso | `tool` | `output` | `rule` |
|---|---|---|---|
| `INVALID_INPUT` corregible | `consultar_transacciones` o `buscar_cliente` | `{"error": "INVALID_INPUT", "field": <campo \| null>, "correction": <n>, "of": 2}` | `RN-010-01` |
| Falla que deriva (RN-007-21) | herramienta que falló | `{"error": <código>}` y, si es `INVALID_INPUT`, `"field": <campo>` | `RN-007-21` |

### 7.4 Texto fijo antes de verificar la identidad

Se añade a la tabla de §7.4 de la spec 007 (lo elige RN-007-38, paso 2, como último resultado de identificación):

| Texto | Cuándo | `reply` |
|---|---|---|
| `INVALID_SEARCH` | `buscar_cliente` responde `INVALID_INPUT` (RN-010-06) | `Esos datos no son válidos. Revísalos e indícame tu número de documento, tu nombre completo o los últimos 4 dígitos de tu tarjeta.` |

## 8. Casos de escalamiento

| Condición | Motivo (`reason`) | Datos del resumen estructurado | Cierra la conversación |
|---|---|---|---|
| 3.er `INVALID_INPUT` de `consultar_transacciones` o `buscar_cliente` en un mismo mensaje (RN-010-04) | `INSUFFICIENT_OR_CONTRADICTORY_INFO` | Nota `RN-010-04: <herramienta> INVALID_INPUT (campo: <campo>) tras 2 correcciones`; completo sin transacción ni tarjeta si está verificada, limitado si no | Sí |
| `INVALID_INPUT` de `iniciar_disputa` o `bloquear_tarjeta` (RN-007-21, RN-010-09) | `UNRECOVERABLE_SYSTEM_FAILURE` | `transaction_id` o `card_id` afectado; nota con la herramienta, el código y el campo (RN-010-08) | Sí |

El resto de casos de la spec 007 no cambia.

## 9. Clarificaciones

| Fecha | Pregunta | Respuesta | Secciones afectadas |
|---|---|---|---|
| 2026-10-19 | ¿A qué herramientas se aplica la corrección? | A `consultar_transacciones` y `buscar_cliente`, las dos lecturas cuyos argumentos forma el LLM. `iniciar_disputa` y `bloquear_tarjeta` siguen derivando: sus argumentos los fija el sistema. | §2, RN-010-01, RN-010-09, AC-010-01, AC-010-02, AC-010-11 |
| 2026-10-19 | ¿Cuántas correcciones admite el agente por mensaje antes de rendirse? | 2: se cuentan juntas las de ambas herramientas y se reinician con cada mensaje de la cliente; el 3.º `INVALID_INPUT` deriva. | RN-010-03, §7.2, AC-010-04, AC-010-06 |
| 2026-10-19 | Al agotarse el tope, ¿con qué motivo se deriva? | `INSUFFICIENT_OR_CONTRADICTORY_INFO`, con una nota que nombra herramienta, código y campo (no `UNRECOVERABLE_SYSTEM_FAILURE`). | RN-010-04, §8, AC-010-04, AC-010-05 |
| 2026-10-19 | Si `buscar_cliente` responde `INVALID_INPUT` y la cliente sigue sin verificar, ¿qué texto fijo recibe? | Un texto nuevo `INVALID_SEARCH` (no `NOT_FOUND`: los datos ni llegaron a buscarse). No cuenta como búsqueda sin coincidencias. | RN-010-05, RN-010-06, §7.4, AC-010-08 |

## 10. Preguntas abiertas

No hay preguntas abiertas.

## 11. Historial de cambios

| Versión | Fecha | Cambio | Autor |
|---|---|---|---|
| 0.1.0 | 2026-10-19 | Versión inicial. Enmienda la spec 007 (RN-007-21, RN-007-28, RN-007-38, §7.4, §8) en la versión 0.4.0 de esa spec, que se actualiza en el mismo cambio (Art. 2, §4.3.3). | Juangiov (con Claude Code) |
| 0.1.1 | 2026-10-19 | Spec aprobada por el usuario. | Juangiov (con Claude Code) |

---

## Gate de salida

- [x] No quedan preguntas abiertas.
- [x] Cada clarificación está reflejada en las secciones afectadas.
- [x] Todos los criterios de aceptación tienen ID y formato Given/When/Then.
- [x] Cada regla de negocio está cubierta por al menos un criterio de aceptación.
- [x] Contratos MCP y casos de escalamiento completos o marcados "No aplica".
- [x] Estado cambiado a **Aprobada**.
