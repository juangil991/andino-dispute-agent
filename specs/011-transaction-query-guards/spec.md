# Spec: Guardas en la consulta de transacciones: tarjeta propia, rango de 90 días y fecha actual

| Campo | Valor |
|---|---|
| Feature | `011-transaction-query-guards` |
| Versión | 0.1.3 |
| Estado | Aprobada |
| Fecha | 2026-10-19 |
| Plan | [plan.md](./plan.md) |
| Tareas | [tasks.md](./tasks.md) |
| Constitución | [docs/constitution.md](../../docs/constitution.md) |

---

## 1. Contexto y problema

En el chat real (conversaciones `2035a885790a4cf89eebdea14e77c458` y `1b01686e91e744e9860b40e9b5e4ce97`, 2026-10-19) dos clientas verificadas, ambas con tarjetas `4321` y `8765`, disputaron un cargo de 185.000 del 2026-09-05. Las dos conversaciones terminaron derivadas a un analista (`ESC-000012`, `ESC-000013`) por defectos del agente, no por un caso complejo. Hay tres defectos:

1. **Rango de fechas fuera del límite.** El LLM pidió `consultar_transacciones` con `2026-07-21..2026-10-19` y luego `2026-06-21..2026-09-19`. Ambos rangos abarcan 91 días contando ambos extremos y el core admite como máximo 90 (RN-003-06, AC-003-07): `date_to - date_from ≤ 89`. El LLM no conoce ese detalle: el esquema de la herramienta del agente y el prompt dicen «90 días» sin precisar el cómputo, y el error de la spec 010 solo informa `date_range`. Tras los dos rechazos el LLM dejó de consultar y preguntó a la clienta por el año.
2. **Fecha actual ausente al redactar.** El LLM afirmó a la clienta que el `2026-09-05` «está en el futuro» y le pidió «confirmar el año», cuando hoy es `2026-10-19`. El prompt de decisión lleva `Fecha actual` (RN-007-44, AC-007-58), pero el prompt con el que se redacta la respuesta final (spec 009) no.
3. **Tarjeta mal tecleada y derivación por un error de negocio.** El LLM envió `card_last4 = "4231"` en vez de `4321`. El agente no comprueba que la tarjeta sea una de las de la clienta (las conoce desde `buscar_cliente`). El core respondió `NOT_FOUND` (RN-003-04) y el agente lo trató como falla irrecuperable (RN-007-21): derivó con `UNRECOVERABLE_SYSTEM_FAILURE`, cerró la conversación e informó a la clienta de que su caso «es complejo». Es un error de **negocio** (`agent-behavior.md`, regla 19): se comunica y se corrige, no se deriva. La propia descripción de la herramienta lo dice (spec 003: «si responde `NOT_FOUND`, pedir al cliente que revise los dígitos»).

Esta spec corrige el agente, no el core. Enmienda la spec 007 (RN-007-21, RN-007-44) y amplía la spec 010 (RN-010-03).

## 2. Objetivos

- El LLM conoce el límite exacto del rango (`date_to - date_from ≤ 89` días, 90 contando ambos extremos) desde el esquema de la herramienta y desde el prompt de decisión, y parte de `hoy - 89` como `date_from` mínimo.
- El prompt con el que se redacta la respuesta final lleva la fecha actual, de modo que el LLM no trate como futura una fecha pasada.
- Una tarjeta que no es de la clienta nunca llega al core: el agente lo detecta, devuelve al LLM un error corregible con las tarjetas enmascaradas de la clienta y no deriva.
- Un `NOT_FOUND` de `consultar_transacciones` se devuelve al LLM como error de negocio para que pida a la clienta revisar los dígitos; no deriva ni cierra la conversación.
- La corrección está acotada: las guardas comparten el tope de 2 correcciones por mensaje de la spec 010.
- `INTERNAL`, tiempo límite y respuesta fuera de esquema siguen derivando (RN-007-21).

### Fuera de alcance

- Cambios en el servidor MCP: validaciones, mensajes y contrato de errores no cambian. Spec 010 §2 sigue vigente.
- Validar el rango de fechas en el agente antes de llamar al core (lo corrige el LLM con el esquema y el error de la spec 010).
- `NOT_FOUND` de otras herramientas (`iniciar_disputa`, `bloquear_tarjeta`) y de `buscar_cliente` (RN-007-02, RN-007-05).
- Cambios en `DisputePolicy` y en las reglas de decisión.
- Cambios en el prompt de decisión salvo el texto del límite (la fecha actual en él ya es RN-007-44).

## 3. Historias de usuario

| ID | Como | Quiero | Para |
|---|---|---|---|
| HU-011-01 | Clienta verificada | que el agente consulte mis transacciones con un rango válido a la primera | no perder tiempo con preguntas de fechas que no me corresponden |
| HU-011-02 | Clienta verificada | que el agente no me diga que una fecha pasada es futura | confiar en lo que me responde y no corregir lo que ya dije bien |
| HU-011-03 | Clienta verificada | que, si el agente se equivoca con los dígitos de mi tarjeta, los corrija o me los confirme | no ser derivada ni perder mi conversación por un error de tecleo |
| HU-011-04 | Analista | recibir solo los casos que de verdad requieren a una persona | no revisar derivaciones causadas por errores del agente |
| HU-011-05 | Auditor | que cada tarjeta rechazada y cada `NOT_FOUND` devuelto al LLM queden registrados | reconstruir el incidente solo con el registro (Art. 8) |

## 4. Reglas de negocio

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-011-01 | La descripción de `consultar_transacciones` que ve el LLM (`date_from`, `date_to`) y el prompt de decisión declaran el límite como «`date_to` como máximo 89 días después de `date_from` (90 días contando ambos extremos)» e indican que, sin fechas de la clienta, `date_from` es `hoy - 89` y `date_to` es hoy. El texto «últimos 90 días» sin esta precisión deja de usarse. | RN-003-06; `agent-behavior.md` §17, §18; RN-007-44 |
| RN-011-02 | El prompt con el que se redacta la respuesta final (spec 009) incluye la línea `Fecha actual: AAAA-MM-DD (formato AAAA-MM-DD).` con la fecha del reloj inyectado en Bogotá (RN-002-08). Aplica a la redacción en streaming y a la no streaming. | RN-009-03; RN-007-44; Art. 8 (reloj inyectado) |
| RN-011-03 | Guarda previa a la ejecución: si la clienta está verificada, el agente conoce al menos una tarjeta suya y el `card_last4` pedido por el LLM a `consultar_transacciones` son exactamente 4 dígitos y no coincide exactamente con los últimos 4 dígitos de ninguna de ellas, el agente **no llama al core** y devuelve al LLM el error `unknown_card` (§7.1) con las tarjetas de la clienta enmascaradas. No deriva ni cierra la conversación. Si el agente no conoce ninguna tarjeta, la guarda no actúa y decide el core. Tampoco actúa si el valor no son exactamente 4 dígitos: llega al core, que responde `INVALID_INPUT` (campo `card_last4`) y se aplica la spec 010 (AC-010-01). | `agent-behavior.md` §4, §5, §19; Art. 7; RN-003-04 |
| RN-011-04 | El texto del error `unknown_card` es **fijo** (§7.1) y solo incluye datos de la propia clienta: los últimos 4 dígitos de sus tarjetas. No incluye el valor que envió el LLM ni datos de otras clientas. | RN-010-02; RN-003-04; Art. 1 |
| RN-011-05 | Si `consultar_transacciones` responde `NOT_FOUND`, el agente no aplica RN-007-21: devuelve al LLM el error de negocio `not_found` (§7.2) para que pida a la clienta revisar los dígitos de la tarjeta, y no reintenta por sí mismo. No deriva ni cierra la conversación. | `agent-behavior.md` §19; spec 003 §7; clarificación 2026-10-19 |
| RN-011-06 | Los rechazos de RN-011-03 y de RN-011-05 cuentan en el **mismo contador** que los `INVALID_INPUT` de la spec 010 (RN-010-03): máximo 2 correcciones por mensaje de la clienta, el contador vuelve a 0 con cada mensaje nuevo. El 1.º y el 2.º rechazo del mensaje se devuelven al LLM; el 3.º, de cualquiera de los tres tipos, se deriva según RN-011-07. | RN-010-03; clarificación 2026-10-19; RN-007-23 |
| RN-011-07 | Con el 3.er rechazo del mensaje por RN-011-03 o RN-011-05, el agente deriva con `INSUFFICIENT_OR_CONTRADICTORY_INFO` y cierra la conversación, igual que RN-010-04, con el texto fijo `ESCALATED` sin transacción. La nota de la derivación es `RN-011-07: consultar_transacciones <UNKNOWN_CARD \| NOT_FOUND> tras 2 correcciones`. El resumen es completo sin transacción ni tarjeta. | Art. 10; RN-010-04; RN-007-24 |
| RN-011-08 | Un rechazo por RN-011-03 o RN-011-05 no da nada por hecho: no registra transacciones como vistas, no genera los `outcomes` `NO_TRANSACTIONS_FOUND` ni `REFINEMENT_REQUIRED` y no cuenta como búsqueda sin coincidencias ni como intento fallido de identidad. | RN-010-05; RN-007-13; RN-007-41 |
| RN-011-09 | Cada rechazo corregible genera un registro `tool_call` con `conversation_id`, marca de tiempo del reloj, `tool = "consultar_transacciones"`, la entrada filtrada (RN-007-26), la salida `{error: <UNKNOWN_CARD \| NOT_FOUND>, correction: <n>, of: 2}`, la regla `RN-011-03` o `RN-011-05` y un motivo fijo. En el caso de la guarda el registro no incluye los 4 dígitos pedidos. | Art. 8; RN-007-28; RN-010-07 |
| RN-011-10 | No cambia: `INTERNAL`, tiempo límite y respuesta fuera de esquema de `consultar_transacciones` derivan con `UNRECOVERABLE_SYSTEM_FAILURE` (RN-007-21); `NOT_FOUND` de `iniciar_disputa` y `bloquear_tarjeta` sigue RN-007-21; el `INVALID_INPUT` de la spec 010 sigue igual, incluido el texto de §7.2 de esa spec. | RN-007-21; RN-010-09 |

## 5. Tabla de decisión de `DisputePolicy`

No aplica. Esta feature no cambia ninguna decisión de disputa; solo el manejo de errores de lectura y los textos que recibe el LLM (Art. 5: el dominio decide, el LLM conversa).

## 6. Criterios de aceptación

### AC-011-01 — El LLM conoce el límite exacto del rango

Cubre: HU-011-01, RN-011-01

- **Given** el catálogo de herramientas que el agente entrega al LLM y el prompt de decisión del día `2026-10-19`
- **When** se leen la descripción de `consultar_transacciones` y el prompt de decisión
- **Then** la descripción de `date_to` dice que es como máximo 89 días después de `date_from` y que el rango es de 90 días contando ambos extremos
- **And** el prompt de decisión dice lo mismo e indica que sin fechas `date_from = hoy - 89`
- **And** ninguno de los dos contiene «últimos 90 días» sin esa precisión

### AC-011-02 — El prompt de redacción lleva la fecha actual

Cubre: HU-011-02, RN-011-02

- **Given** el reloj fijado en `2026-10-19` y la clienta que escribió «el cargo fue el 2026-09-05»
- **When** el agente redacta la respuesta final `<modo>`
- **Then** el prompt de esa llamada al LLM incluye `Fecha actual: 2026-10-19 (formato AAAA-MM-DD).`

| `<modo>` |
|---|
| en streaming |
| sin streaming |

### AC-011-03 — Una tarjeta que no es de la clienta no llega al core

Cubre: HU-011-03, RN-011-03, RN-011-08

- **Given** la clienta verificada con tarjetas `4321` y `8765`, y el `FakeLLM` que pide `consultar_transacciones` con `card_last4 = "4231"`
- **When** el agente atiende la petición
- **Then** no se invoca `consultar_transacciones` en el core
- **And** el resultado que recibe el LLM es el error `unknown_card` con `cards_last4 = ["4321", "8765"]` y `corrections_remaining = 1`
- **And** la conversación sigue `ACTIVE`, no se invoca `escalar_a_analista` y no hay `outcomes` `NO_TRANSACTIONS_FOUND` ni `REFINEMENT_REQUIRED`

### AC-011-04 — El LLM corrige la tarjeta y la consulta sigue

Cubre: HU-011-03, RN-011-03

- **Given** el caso de AC-011-03
- **When** el `FakeLLM` pide a continuación `consultar_transacciones` con `card_last4 = "4321"` y un rango de 90 días contando ambos extremos
- **Then** la segunda petición se atiende con normalidad y las transacciones quedan disponibles para evaluar
- **And** la conversación sigue `ACTIVE` y no hay derivación

### AC-011-05 — La guarda no actúa sin tarjetas conocidas

Cubre: RN-011-03

- **Given** la clienta verificada para la que el agente no conoce ninguna tarjeta
- **When** el `FakeLLM` pide `consultar_transacciones` con `card_last4 = "4231"`
- **Then** la petición llega al core y no se devuelve `unknown_card`

### AC-011-05b — La guarda no actúa con un valor que no son 4 dígitos

Cubre: RN-011-03, RN-010-01

- **Given** la clienta verificada con tarjetas `4321` y `8765`
- **When** el `FakeLLM` pide `consultar_transacciones` con `card_last4 = "11"` (o con un número de tarjeta de 16 dígitos)
- **Then** la petición llega al core, que responde `INVALID_INPUT` (campo `card_last4`), y el LLM recibe `invalid_input` como en la spec 010
- **And** no se devuelve `unknown_card`

### AC-011-06 — El texto de `unknown_card` es fijo y sin datos ajenos

Cubre: HU-011-03, RN-011-04

- **Given** la clienta verificada con tarjetas `4321` y `8765`, y el `FakeLLM` que pide `consultar_transacciones` con `card_last4 = "9999"` (tarjeta de otra clienta del seed)
- **When** el agente devuelve el error al LLM
- **Then** el contenido es el texto fijo de §7.1 con los últimos 4 dígitos de las tarjetas de la clienta
- **And** no contiene `9999` ni datos de ninguna otra clienta

### AC-011-07 — `NOT_FOUND` se devuelve al LLM como error de negocio

Cubre: HU-011-03, HU-011-04, RN-011-05, RN-011-08

- **Given** la clienta verificada y el core que responde `NOT_FOUND` a `consultar_transacciones` (tarjeta que el agente tenía por propia)
- **When** el agente atiende la petición
- **Then** el LLM recibe el error `not_found` de §7.2 con `corrections_remaining = 1`
- **And** no se aplica RN-007-21: no se invoca `escalar_a_analista`, la conversación sigue `ACTIVE` y no hay `outcomes` de derivación
- **And** no hay `outcomes` `NO_TRANSACTIONS_FOUND` ni `REFINEMENT_REQUIRED`

### AC-011-08 — El tope de 2 correcciones es compartido

Cubre: HU-011-03, HU-011-04, RN-011-06, RN-011-07

- **Given** la clienta verificada y, en un mismo mensaje, `<rechazos>` a tres peticiones seguidas de `consultar_transacciones`
- **When** el LLM pide por tercera vez la herramienta
- **Then** los dos primeros rechazos se devuelven al LLM (`corrections_remaining` 1 y 0)
- **And** con el tercero se invoca `escalar_a_analista` con `reason = "INSUFFICIENT_OR_CONTRADICTORY_INFO"`, resumen completo sin `transaction_id` ni `card_id` y la nota `<nota>`
- **And** `outcomes` trae un único `ESCALATED` sin transacción y la conversación queda `status = "ESCALATED"`

| `<rechazos>` | `<nota>` |
|---|---|
| tres tarjetas ajenas (guarda) | `RN-011-07: consultar_transacciones UNKNOWN_CARD tras 2 correcciones` |
| tres `NOT_FOUND` del core | `RN-011-07: consultar_transacciones NOT_FOUND tras 2 correcciones` |
| `INVALID_INPUT`, tarjeta ajena y `NOT_FOUND` (mezcla) | `RN-011-07: consultar_transacciones NOT_FOUND tras 2 correcciones` (nombra el tipo del 3.º) |

### AC-011-09 — El contador se reinicia con cada mensaje

Cubre: RN-011-06

- **Given** la clienta verificada que recibió dos rechazos (`unknown_card` y `not_found`) en un mensaje
- **When** la clienta envía un mensaje nuevo y el LLM vuelve a pedir `consultar_transacciones` con una tarjeta ajena
- **Then** el rechazo se devuelve al LLM como la 1.ª corrección (`corrections_remaining = 1`) y no hay derivación

### AC-011-10 — Cada rechazo corregible queda auditado

Cubre: HU-011-05, RN-011-09

- **Given** `<situación>`
- **When** el agente devuelve el rechazo al LLM
- **Then** queda un registro `tool_call` con `conversation_id`, la marca de tiempo del reloj, `tool = "consultar_transacciones"`, la entrada filtrada, la salida `<salida>` y `rule = <regla>`
- **And** el registro no contiene los 4 dígitos pedidos (guarda), documentos completos ni el texto del servidor

| `<situación>` | `<salida>` | `<regla>` |
|---|---|---|
| tarjeta ajena (guarda), 1.º rechazo del mensaje | `{"error": "UNKNOWN_CARD", "correction": 1, "of": 2}` | `RN-011-03` |
| `NOT_FOUND` del core, 2.º rechazo del mensaje | `{"error": "NOT_FOUND", "correction": 2, "of": 2}` | `RN-011-05` |

### AC-011-11 — Lo que no cambia sigue derivando

Cubre: HU-011-04, RN-011-10

- **Given** la clienta verificada y `<falla>`
- **When** el agente llega a esa herramienta
- **Then** `<resultado>`

| `<falla>` | `<resultado>` |
|---|---|
| `consultar_transacciones` responde `INTERNAL` | se deriva con `UNRECOVERABLE_SYSTEM_FAILURE` y la conversación se cierra (AC-007-23) |
| `consultar_transacciones` no responde dentro del tiempo límite | se deriva con `UNRECOVERABLE_SYSTEM_FAILURE` y la conversación se cierra |
| `consultar_transacciones` devuelve una respuesta que no cumple su esquema | se deriva con `UNRECOVERABLE_SYSTEM_FAILURE` y la conversación se cierra |
| `iniciar_disputa` responde `NOT_FOUND` | se deriva con `UNRECOVERABLE_SYSTEM_FAILURE` (RN-007-21) |
| `consultar_transacciones` responde `INVALID_INPUT` | se devuelve al LLM como en la spec 010 (`invalid_input`, AC-010-01) |

### AC-011-12 — Tarjeta equivocada con el servidor real (e2e)

Cubre: HU-011-03, HU-011-05, RN-011-03, RN-011-09

- **Given** el agente con el servidor MCP real por stdio, la clienta verificada del seed con dos tarjetas y el `FakeLLM` que pide `consultar_transacciones` con los dígitos de la tarjeta intercambiados y después con los correctos
- **When** la clienta pide disputar un cargo
- **Then** el servidor no recibe la primera petición y el LLM recibe `unknown_card`
- **And** la segunda consulta devuelve transacciones, la conversación sigue `ACTIVE` y no se crea ninguna derivación
- **And** el registro de auditoría contiene el `tool_call` de RN-011-09

## 7. Contratos de herramientas MCP

No aplica a las herramientas del servidor: ninguna cambia de entrada, salida ni errores. Cambian dos cosas del agente: el texto de la descripción de `consultar_transacciones` que ve el LLM (RN-011-01, en el catálogo `LLM_TOOLS`) y los resultados de error que el agente devuelve al LLM (§7.1 y §7.2). Son `tool_result` de error (`is_error = true`), no `outcomes` de la API.

### 7.1 Resultado `unknown_card` (guarda de tarjeta)

| Campo | Tipo | Descripción |
|---|---|---|
| `error` | `string` | Siempre `unknown_card`. |
| `cards_last4` | `string[]` | Últimos 4 dígitos de las tarjetas de la clienta, en el orden en que el agente las conoce. |
| `corrections_remaining` | `integer` | Correcciones que quedan en el mensaje: `1` tras el 1.º rechazo y `0` tras el 2.º (RN-011-06). |
| `message` | `string` | Texto fijo (RN-011-04): `Esa tarjeta no está entre las de la clienta (terminadas en <últimos 4 de cada una>). Usa una de ellas o pregúntale a la clienta cuál es; no repitas los mismos dígitos.` |

### 7.2 Resultado `not_found` (negocio)

| Campo | Tipo | Descripción |
|---|---|---|
| `error` | `string` | Siempre `not_found`. |
| `corrections_remaining` | `integer` | Igual que en §7.1. |
| `message` | `string` | Texto fijo: `No se encontró esa tarjeta. Pídele a la clienta que revise los últimos 4 dígitos antes de volver a consultar.` |

Con el 3.er rechazo del mensaje no se devuelve ninguno de los dos: se deriva (RN-011-07) y se devuelve el resultado de cierre de RN-007-21.

### 7.3 Evento de auditoría

Se reutiliza el tipo `tool_call` de RN-007-28; no hay un tipo nuevo.

| Caso | `output` | `rule` | `reason` |
|---|---|---|---|
| Tarjeta ajena (guarda) | `{"error": "UNKNOWN_CARD", "correction": <n>, "of": 2}` | `RN-011-03` | `la tarjeta no es de la clienta; se devuelve al LLM para corregirla` |
| `NOT_FOUND` del core | `{"error": "NOT_FOUND", "correction": <n>, "of": 2}` | `RN-011-05` | `tarjeta no encontrada por el core; se devuelve al LLM para que la clienta revise los dígitos` |

## 8. Casos de escalamiento

| Condición | Motivo (`reason`) | Datos del resumen estructurado | Cierra la conversación |
|---|---|---|---|
| 3.er rechazo del mensaje por tarjeta ajena (RN-011-03) o `NOT_FOUND` (RN-011-05), con el contador compartido de RN-011-06 | `INSUFFICIENT_OR_CONTRADICTORY_INFO` | Nota `RN-011-07: consultar_transacciones <UNKNOWN_CARD \| NOT_FOUND> tras 2 correcciones`; completo sin transacción ni tarjeta | Sí |
| `INTERNAL`, tiempo límite o respuesta fuera de esquema de `consultar_transacciones` (RN-011-10) | `UNRECOVERABLE_SYSTEM_FAILURE` | Como en la spec 007 (RN-007-21) | Sí |

Un solo `NOT_FOUND` o una sola tarjeta ajena **ya no** derivan.

## 9. Clarificaciones

| Fecha | Pregunta | Respuesta | Secciones afectadas |
|---|---|---|---|
| 2026-10-19 | ¿La tarjeta ajena bloqueada por la guarda cuenta contra el tope de 2 correcciones por mensaje? | Sí, en el mismo contador que los `INVALID_INPUT` de la spec 010: el 3.er rechazo del mensaje deriva con `INSUFFICIENT_OR_CONTRADICTORY_INFO`. | RN-011-06, RN-011-07, AC-011-08, AC-011-09 |
| 2026-10-19 | ¿Qué hace el agente cuando el core responde `NOT_FOUND` a `consultar_transacciones`? | Lo devuelve al LLM como error de negocio con texto fijo, cuenta en el mismo contador de 2 correcciones y al 3.º deriva. | RN-011-05, RN-011-06, RN-011-07, §7.2, AC-011-07, AC-011-08 |
| 2026-10-19 | ¿Los cambios de prompt (límite de 89 días y fecha actual al redactar) van en esta spec? | Sí, todo en la spec 011. | RN-011-01, RN-011-02, AC-011-01, AC-011-02 |
| 2026-10-19 | (v0.1.2) La guarda rechazaba un `card_last4` mal formado (`"11"`) como tarjeta ajena, contra AC-010-01: ¿qué se hace? | La guarda solo actúa con exactamente 4 dígitos; un valor mal formado llega al core y recibe `INVALID_INPUT`. | RN-011-03, AC-011-05b |

## 10. Preguntas abiertas

No hay preguntas abiertas.

## 11. Historial de cambios

| Versión | Fecha | Cambio | Autor |
|---|---|---|---|
| 0.1.0 | 2026-10-19 | Versión inicial. Enmienda la spec 007 (RN-007-21 y RN-007-44) y amplía la spec 010 (RN-010-03); ambas se actualizan en el mismo cambio (Art. 2, §4.3.3). | Juangiov (con Claude Code) |
| 0.1.1 | 2026-10-19 | Spec aprobada por el usuario. | Juangiov (con Claude Code) |
| 0.1.2 | 2026-10-19 | Enmienda aprobada por el usuario durante la implementación: RN-011-03 solo actúa con `card_last4` de exactamente 4 dígitos; se añade AC-011-05b. Evita contradecir AC-010-01 (fila `card_last4 = "11"`). | Juangiov (con Claude Code) |
| 0.1.3 | 2026-10-19 | Tras la auditoría de AC (H-07): AC-011-11 enumera la respuesta fuera de esquema de `consultar_transacciones` (RN-011-10, §8). Sin cambio de comportamiento. | Juangiov (con Claude Code) |

---

## Gate de salida

- [x] No quedan preguntas abiertas.
- [x] Cada clarificación está reflejada en las secciones afectadas.
- [x] Todos los criterios de aceptación tienen ID y formato Given/When/Then.
- [x] Cada regla de negocio está cubierta por al menos un criterio de aceptación.
- [x] Contratos MCP y casos de escalamiento completos o marcados "No aplica".
- [x] Estado cambiado a **Aprobada**.
