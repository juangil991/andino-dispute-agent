# Spec: Bloquear una tarjeta de un cliente verificado por sospecha de fraude

| Campo | Valor |
|---|---|
| Feature | `005-card-block` |
| Versión | 0.1.0 |
| Estado | Aprobada |
| Fecha | 2026-10-17 |
| Origen | Issue [#30](https://github.com/juangil991/andino-dispute-agent/issues/30) del backlog (P0) |
| Plan | [plan.md](./plan.md) |
| Tareas | [tasks.md](./tasks.md) |
| Constitución | [docs/constitution.md](../../docs/constitution.md) |

---

## 1. Contexto y problema

Con `buscar_cliente` (spec 001), `verificar_identidad` (spec 002), `consultar_transacciones` (spec 003) e `iniciar_disputa` (spec 004), el agente ya puede identificar al cliente, revisar sus movimientos y abrir disputas. Pero cuando hay sospecha de fraude, o el cliente reporta su tarjeta perdida o robada, el core simulado no ofrece forma de impedir que la tarjeta se siga usando.

Esta feature añade la herramienta `bloquear_tarjeta` (catálogo de la constitución §3.4). Bloquea una tarjeta activa del cliente verificado e indica un motivo de un catálogo cerrado. El servidor valida que la conversación esté verificada (Art. 7, defensa en profundidad). La herramienta es segura ante reintentos gracias a una clave de idempotencia (`mcp-tools.md` §9), responde igual ante una tarjeta ajena que ante una inexistente, no deja la tarjeta a medias ante una falla y audita cada invocación (Art. 8). Solo ejecuta el bloqueo: no decide si hay fraude (eso lo hará `DisputePolicy`, Art. 5), no abre disputas, no escala y no desbloquea.

## 2. Objetivos

- Exponer la herramienta MCP `bloquear_tarjeta` en `core_banking_mcp` con el contrato de §7.
- Registrar en el core simulado los bloqueos (fecha y motivo) y las claves de reintento usadas.
- Rechazar con `IDENTITY_NOT_VERIFIED` toda solicitud de una conversación no verificada en el servidor (Art. 7).
- Bloquear solo tarjetas activas del cliente verificado; informar sin error que una tarjeta ya bloqueada lo estaba y rechazar con `CARD_NOT_BLOCKABLE` las tarjetas canceladas.
- Garantizar que repetir la misma solicitud con la misma clave de reintento no registre un segundo bloqueo.
- Responder `NOT_FOUND` de forma idéntica ante una tarjeta ajena o inexistente, sin revelar datos de otros clientes.
- Rechazar entradas inválidas con `INVALID_INPUT` y, ante una falla inesperada, devolver `INTERNAL` no reintentable sin cambiar la tarjeta (Art. 10).
- Auditar el 100 % de las invocaciones sin registrar números completos de tarjeta ni documentos (Art. 8).

### Fuera de alcance

- Cambios en `dispute_agent`: operación en `BankingToolsPort`, adaptador MCP, loop LLM y chat (spec propia).
- Decidir si hay sospecha de fraude o si corresponde bloquear (`DisputePolicy`, Art. 5).
- Desbloquear, cancelar o reemplazar tarjetas, y consultar el historial de bloqueos.
- Abrir disputas (`iniciar_disputa`, spec 004) y ejecutar escalamientos (`escalar_a_analista`): esta feature solo indica cuándo derivar.
- Efectos del bloqueo sobre transacciones, disputas o autorizaciones futuras: el core simulado no procesa pagos.
- Cambios en `buscar_cliente`, `verificar_identidad`, `consultar_transacciones` e `iniciar_disputa`.

## 3. Historias de usuario

| ID | Como | Quiero | Para |
|---|---|---|---|
| HU-005-01 | agente de disputas | bloquear una tarjeta activa del cliente verificado indicando el motivo | que la tarjeta deje de poder usarse ante un posible fraude o una pérdida |
| HU-005-02 | agente de disputas | que repetir una solicitud por un corte o reintento no registre un segundo bloqueo | poder reintentar sin miedo a duplicar la operación |
| HU-005-03 | agente de disputas | saber si la tarjeta ya estaba bloqueada o si no se puede bloquear porque está cancelada | informar al cliente sin cambiar nada |
| HU-005-04 | cliente de Banco Andino | que nadie bloquee mis tarjetas sin haberse verificado como yo, ni pueda averiguar si una tarjeta existe | proteger mi cuenta |
| HU-005-05 | agente de disputas | saber cuándo debo derivar el caso a un analista porque el sistema falló | no dejar al cliente sin respuesta |
| HU-005-06 | responsable de auditoría | que cada solicitud quede registrada con su conversación, momento, tarjeta enmascarada, motivo y resultado | tener trazabilidad total sin exponer datos personales |

## 4. Reglas de negocio

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-005-01 | La solicitud indica la tarjeta por su `card_id`, el identificador opaco que devuelve `consultar_transacciones` (RN-003-12); además indica el motivo (`reason`) y una clave de reintento (`idempotency_key`) generada por el consumidor. | Issue #30; clarificación 2026-10-17; `mcp-tools.md` §9 |
| RN-005-02 | El motivo es un código de un catálogo cerrado que distingue mayúsculas: `FRAUD_SUSPECTED` (sospecha de fraude) y `LOST_OR_STOLEN` (tarjeta perdida o robada). Cualquier otro valor, vacío o ausente ⇒ `INVALID_INPUT`. | Issue #30; clarificación 2026-10-17 |
| RN-005-03 | La herramienta exige que la conversación esté verificada en el servidor (estado de RN-002-13). Se rechaza con `IDENTITY_NOT_VERIFIED` toda conversación sin verificación exitosa, desconocida o bloqueada por agotar sus intentos. La verificación no se traslada: estar verificada en otra conversación no cuenta. | Art. 7; issue #30; `mcp-tools.md` §5 |
| RN-005-04 | La tarjeta debe pertenecer al cliente verificado en la conversación. Si no es así, porque es de otro cliente o porque no existe, se devuelve `NOT_FOUND` con un mensaje fijo, **idéntico** en ambos casos y sin datos de ningún cliente. | Issue #30; RN-003-04; RN-004-04 |
| RN-005-05 | Una tarjeta tiene uno de estos estados: `ACTIVE`, `BLOCKED` o `CANCELLED`. Según su estado previo: `ACTIVE` ⇒ pasa a `BLOCKED` y se registra el bloqueo; `BLOCKED` ⇒ respuesta exitosa con `already_blocked = true` y los datos del bloqueo original, sin registrar otro bloqueo ni cambiar nada; `CANCELLED` ⇒ error `CARD_NOT_BLOCKABLE`, sin cambiar nada. | Issue #30; clarificación 2026-10-17 |
| RN-005-06 | Un bloqueo nuevo registra `blocked_at`, igual al instante del reloj inyectado en ISO 8601 con la zona de Bogotá (`−05:00`), y el `reason` recibido. Si una tarjeta ya bloqueada no tiene un bloqueo registrado (p. ej. por semilla), la respuesta trae `blocked_at = null` y `reason = null`. | Issue #30; clarificación 2026-10-17; §5.3.6; RN-002-08 |
| RN-005-07 | La clave de reintento es única **dentro de cada conversación** y solo se registra cuando se crea un bloqueo nuevo. Si la conversación ya usó la clave con la **misma** tarjeta y el **mismo** motivo, se devuelve el resultado de esa solicitud (mismo `blocked_at` y `already_blocked = false`) sin registrar otro bloqueo. Si la usó con otra tarjeta u otro motivo, se rechaza con `INVALID_INPUT` y no se cambia nada. La misma clave en otra conversación es una solicitud independiente. | Issue #30; clarificación 2026-10-17; RN-004-08 |
| RN-005-08 | Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar; `card_id` obligatorio, de 1 a 64 caracteres tras recortar; `idempotency_key` obligatoria, de 1 a 64 caracteres tras recortar; `reason` obligatorio y del catálogo de RN-005-02. Toda violación ⇒ `INVALID_INPUT`, sin cambiar ninguna tarjeta. | Issue #30; RN-004-09 |
| RN-005-09 | Las comprobaciones se evalúan en este orden y se devuelve el primer resultado: (1) validación de entrada → `INVALID_INPUT`; (2) identidad verificada → `IDENTITY_NOT_VERIFIED`; (3) clave de reintento ya usada en la conversación → el bloqueo existente (misma solicitud) o `INVALID_INPUT` (solicitud distinta); (4) tarjeta del cliente verificado → `NOT_FOUND`; (5) estado de la tarjeta → `CARD_NOT_BLOCKABLE` (cancelada), `already_blocked` (bloqueada) o bloqueo nuevo (activa). | Clarificación 2026-10-17 |
| RN-005-10 | La respuesta exitosa contiene **solo** `card_id`, `masked_card` (`**** ` seguido de los 4 últimos dígitos, RN-001-09), `status` (`BLOCKED`), `blocked_at`, `reason` y `already_blocked`. | Issue #30; clarificación 2026-10-17 |
| RN-005-11 | La respuesta nunca contiene el número completo de ninguna tarjeta, el documento del cliente ni su nombre, ni datos de otros clientes. | Issue #30; Art. 7; `mcp-tools.md` §8 |
| RN-005-12 | Bloquear una tarjeta solo cambia el estado de esa tarjeta y registra el bloqueo y la clave de reintento. No cambia las demás tarjetas del cliente, sus transacciones, sus disputas ni el estado de verificación de la conversación. No decide si hay fraude, no abre disputas ni escala. | Issue #30; Art. 5 |
| RN-005-13 | Ante una falla inesperada (p. ej. el repositorio de tarjetas no responde al bloquear), la herramienta devuelve `INTERNAL` con `retryable = false` y sin detalles internos (trazas, SQL, texto de la excepción). La operación es atómica: la tarjeta conserva su estado anterior y no queda registrado ningún bloqueo ni clave de reintento. | Art. 10; issue #30; `mcp-tools.md` §7 |
| RN-005-14 | Cada invocación genera exactamente un registro de auditoría con: `conversation_id` (vacío si no llegó); fecha y hora del reloj inyectado; `tool = "bloquear_tarjeta"`; el `card_id`, el `reason` y la `idempotency_key` recibidos (cada uno vacío si no es válido según RN-005-08, para no registrar lo que se haya escrito en ese campo); `masked_card` de la tarjeta solo si pertenece al cliente verificado (vacío en otro caso); y el resultado. El resultado es `blocked`, `replayed`, `already_blocked` o el código de error (`INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND`, `CARD_NOT_BLOCKABLE`, `INTERNAL`). Como `card_id` e `idempotency_key` son texto libre, toda secuencia de 13 a 19 dígitos seguidos que contengan se registra sustituida por `[REDACTED]`. El registro **nunca** contiene el número completo de una tarjeta ni el documento del cliente. | Art. 8; issue #30; RN-004-16 |

## 5. Tabla de decisión de `DisputePolicy`

No aplica: esta feature solo ejecuta el bloqueo. La decisión de bloquear por sospecha de fraude queda para la spec de `DisputePolicy` (Art. 5).

## 6. Criterios de aceptación

Estas condiciones aplican a todos los criterios, salvo que se indique otra cosa:

- El reloj inyectado marca `2026-10-17T15:00:00Z` (hoy es 17 de octubre de 2026 en Bogotá).
- Existe la cliente `C-0001` "Laura Méndez", con documento `D-1001` y la tarjeta `CARD-L1`, `ACTIVE`, número `4111111111114321` (terminada en `4321`).
- La conversación `A` está verificada para `C-0001`.
- La solicitud se hace en la conversación `A` con `card_id = "CARD-L1"`, `reason = "FRAUD_SUSPECTED"` e `idempotency_key = "K-1"`.

Los datos de prueba se construyen con builders (§5.3.7), no con las semillas.

### AC-005-01 — Bloquear una tarjeta activa

Cubre: HU-005-01, RN-005-01, RN-005-05, RN-005-06, RN-005-10

- **When** se invoca `bloquear_tarjeta`
- **Then** la respuesta trae `card_id = "CARD-L1"`, `masked_card = "**** 4321"`, `status = "BLOCKED"`, `blocked_at = "2026-10-17T10:00:00-05:00"`, `reason = "FRAUD_SUSPECTED"` y `already_blocked = false`
- **And** la tarjeta `CARD-L1` queda en estado `BLOCKED` con exactamente 1 bloqueo registrado con esa fecha y ese motivo

### AC-005-02 — Motivos permitidos

Cubre: HU-005-01, RN-005-02

- **When** se invoca `bloquear_tarjeta` con `reason = <motivo>`
- **Then** la tarjeta queda `BLOCKED` y la respuesta trae `reason = <motivo>`

| motivo |
|---|
| `FRAUD_SUSPECTED` |
| `LOST_OR_STOLEN` |

### AC-005-03 — Motivo inválido

Cubre: RN-005-02, RN-005-08

- **When** se invoca `bloquear_tarjeta` con `<motivo>`
- **Then** se devuelve el error `INVALID_INPUT` con `retryable = false`
- **And** la tarjeta `CARD-L1` sigue `ACTIVE` y no se registra ningún bloqueo

| motivo |
|---|
| `reason = "STOLEN"` (no está en el catálogo) |
| `reason = "fraud_suspected"` (en minúsculas) |
| `reason = "sospecha de fraude"` (texto en lugar del código) |
| `reason = ""` |
| `reason` ausente o `null` |

### AC-005-04 — Estado previo de la tarjeta

Cubre: HU-005-01, HU-005-03, RN-005-05, RN-005-06, RN-005-12

- **Given** la tarjeta `CARD-L1` está en `<estado previo>`
- **When** se invoca `bloquear_tarjeta`
- **Then** `<resultado>`

| estado previo | resultado |
|---|---|
| `ACTIVE` | la tarjeta queda `BLOCKED`, con 1 bloqueo registrado y `already_blocked = false` |
| `BLOCKED`, bloqueada con `bloquear_tarjeta` el `2026-10-15T09:00:00-05:00` con `LOST_OR_STOLEN` y la clave `K-0` | respuesta exitosa con `status = "BLOCKED"`, `already_blocked = true`, `blocked_at = "2026-10-15T09:00:00-05:00"` y `reason = "LOST_OR_STOLEN"` (el bloqueo original); la tarjeta sigue con 1 solo bloqueo registrado |
| `BLOCKED`, sin bloqueo registrado (semilla) | respuesta exitosa con `status = "BLOCKED"`, `already_blocked = true`, `blocked_at = null` y `reason = null`; no se registra ningún bloqueo |
| `CANCELLED` | error `CARD_NOT_BLOCKABLE` con `retryable = false`; la tarjeta sigue `CANCELLED` y no se registra ningún bloqueo |

### AC-005-05 — Repetir la misma solicitud no duplica el bloqueo

Cubre: HU-005-02, RN-005-07, RN-005-09

- **Given** en la conversación `A` ya se invocó `bloquear_tarjeta` con `CARD-L1`, `FRAUD_SUSPECTED` y `K-1`, que bloqueó la tarjeta con `blocked_at = "2026-10-17T10:00:00-05:00"`
- **When** se vuelve a invocar `bloquear_tarjeta` en `A` con `CARD-L1`, `FRAUD_SUSPECTED` y `K-1`, con el reloj una hora después
- **Then** la respuesta es idéntica a la primera: `already_blocked = false` y `blocked_at = "2026-10-17T10:00:00-05:00"`
- **And** `CARD-L1` sigue con exactamente 1 bloqueo registrado

### AC-005-06 — Una clave de reintento reutilizada con otros datos se rechaza

Cubre: HU-005-02, RN-005-07

- **Given** `C-0001` tiene otra tarjeta `CARD-L2`, `ACTIVE`, terminada en `8765`
- **And** en la conversación `A` ya se invocó `bloquear_tarjeta` con `CARD-L1`, `FRAUD_SUSPECTED` y `K-1`
- **When** se invoca `bloquear_tarjeta` en `A` con `idempotency_key = "K-1"` y `<datos>`
- **Then** se devuelve el error `INVALID_INPUT` con `retryable = false`
- **And** `CARD-L2` sigue `ACTIVE` y no se registra ningún bloqueo adicional

| datos |
|---|
| `card_id = "CARD-L2"`, `reason = "FRAUD_SUSPECTED"` (otra tarjeta) |
| `card_id = "CARD-L1"`, `reason = "LOST_OR_STOLEN"` (otro motivo) |

### AC-005-07 — La clave de reintento pertenece a su conversación

Cubre: RN-005-07

- **Given** en la conversación `A` ya se invocó `bloquear_tarjeta` con `CARD-L1`, `FRAUD_SUSPECTED` y `K-1`, que bloqueó la tarjeta
- **And** la conversación `B` también está verificada para `C-0001`
- **When** se invoca `bloquear_tarjeta` en `B` con `CARD-L1`, `FRAUD_SUSPECTED` y `K-1`
- **Then** la respuesta es exitosa con `already_blocked = true` y el `blocked_at` del bloqueo de `A` (la clave de `A` no aplica en `B`)
- **And** `CARD-L1` sigue con exactamente 1 bloqueo registrado

### AC-005-08 — Una tarjeta ajena o inexistente recibe la misma respuesta

Cubre: HU-005-04, RN-005-04, RN-005-11

- **Given** existe el cliente `C-0002` "Pedro Ríos" con la tarjeta `CARD-P1`, `ACTIVE`, terminada en `1234`
- **And** no existe ninguna tarjeta `CARD-9999`
- **When** se invoca `bloquear_tarjeta` con `card_id = "CARD-P1"` y, en otra invocación con `idempotency_key = "K-2"`, con `card_id = "CARD-9999"`
- **Then** ambas devuelven el error `NOT_FOUND` con `retryable = false`
- **And** las dos respuestas son idénticas campo a campo (mismo código, mensaje y `retryable`)
- **And** `CARD-P1` sigue `ACTIVE`, sin bloqueos registrados, y ningún dato de `C-0002` aparece en la respuesta

### AC-005-09 — No se bloquea una tarjeta sin la identidad verificada

Cubre: HU-005-04, RN-005-03, RN-005-12

- **Given** `<situación>`
- **When** se invoca `bloquear_tarjeta` en esa conversación
- **Then** se devuelve el error `IDENTITY_NOT_VERIFIED` con `retryable = false`
- **And** `CARD-L1` sigue `ACTIVE` y no se registra ningún bloqueo
- **And** el estado de verificación de la conversación (cliente verificado e intentos fallidos) no cambia

| situación |
|---|
| la conversación nunca ha invocado `verificar_identidad` |
| la conversación acumula 1 intento fallido de verificación y ningún éxito |
| la conversación agotó sus intentos de verificación (bloqueada) |
| la conversación `A` está verificada para `C-0001` y la solicitud se hace en la conversación `B`, no verificada |

### AC-005-10 — Datos de la solicitud inválidos

Cubre: RN-005-08

- **When** se invoca `bloquear_tarjeta` con `<dato>` (el resto de campos válidos)
- **Then** se devuelve el error `INVALID_INPUT` con `retryable = false`
- **And** ninguna tarjeta cambia de estado y no se registra ningún bloqueo

| dato |
|---|
| `card_id` ausente o `null` |
| `card_id = ""` o solo espacios |
| `card_id` de 65 caracteres |
| `idempotency_key` ausente o `null` |
| `idempotency_key = ""` o solo espacios |
| `idempotency_key` de 65 caracteres |
| `conversation_id` ausente, vacío o solo espacios |

### AC-005-11 — Orden de las comprobaciones

Cubre: RN-005-09

- **Given** `<situación>`
- **When** se invoca `bloquear_tarjeta` con `<entrada>`
- **Then** el resultado es `<resultado>`

| situación | entrada | resultado |
|---|---|---|
| la conversación no está verificada | `reason = "STOLEN"` | `INVALID_INPUT` |
| la conversación no está verificada | `card_id = "CARD-9999"` (no existe) | `IDENTITY_NOT_VERIFIED` |
| en `A` ya se usó `K-1` con `CARD-L1` | `card_id = "CARD-9999"`, `idempotency_key = "K-1"` | `INVALID_INPUT` |
| `CARD-P1` de `C-0002` está `CANCELLED` | `card_id = "CARD-P1"` | `NOT_FOUND` |
| en `A` se usó `K-1` para bloquear `CARD-L1` y después la tarjeta pasó a `CANCELLED` | (entrada por defecto) | respuesta exitosa del bloqueo original (`already_blocked = false`) |

### AC-005-12 — Bloquear una tarjeta no afecta a las demás

Cubre: RN-005-12

- **Given** `C-0001` tiene otra tarjeta `CARD-L2`, `ACTIVE`, terminada en `8765`
- **When** se invoca `bloquear_tarjeta`
- **Then** `CARD-L1` queda `BLOCKED`
- **And** `CARD-L2` sigue `ACTIVE`, sin bloqueos registrados

### AC-005-13 — La respuesta protege los datos personales

Cubre: HU-005-04, RN-005-10, RN-005-11

- **When** se invoca `bloquear_tarjeta`
- **Then** la respuesta contiene exactamente los campos `card_id`, `masked_card`, `status`, `blocked_at`, `reason` y `already_blocked`
- **And** `masked_card = "**** 4321"` y `card_id` no contiene `4111111111114321`
- **And** en ninguna parte de la respuesta aparecen `4111111111114321`, `D-1001` ni `Laura Méndez`

### AC-005-14 — Una falla al bloquear no deja la tarjeta a medias

Cubre: HU-005-05, RN-005-13

- **Given** el repositorio de tarjetas falla de forma inesperada al registrar el bloqueo
- **When** se invoca `bloquear_tarjeta`
- **Then** se devuelve el error `INTERNAL` con `retryable = false`
- **And** el mensaje no contiene trazas, SQL ni el texto de la excepción original
- **And** `CARD-L1` sigue `ACTIVE` y no queda ningún bloqueo registrado
- **And** cuando el repositorio vuelve a funcionar, la misma solicitud con `K-1` bloquea la tarjeta con `already_blocked = false` (la clave no quedó registrada)

### AC-005-15 — Cada solicitud queda registrada sin datos personales

Cubre: HU-005-06, RN-005-14

- **Given** un reloj inyectado fijo
- **When** se invoca `bloquear_tarjeta` produciendo `<caso>`
- **Then** queda exactamente 1 registro de auditoría con `conversation_id`, la fecha y hora del reloj, `tool = "bloquear_tarjeta"`, el `card_id`, el `reason` y la `idempotency_key` recibidos, el `masked_card` de RN-005-14 y `<resultado registrado>`
- **And** el registro no contiene `4111111111114321` ni `D-1001`

| caso | resultado registrado |
|---|---|
| un bloqueo nuevo | `blocked` y `masked_card = "**** 4321"` |
| una repetición de la solicitud | `replayed` y `masked_card = "**** 4321"` |
| una tarjeta que ya estaba bloqueada | `already_blocked` y `masked_card = "**** 4321"` |
| una tarjeta cancelada | código `CARD_NOT_BLOCKABLE` y `masked_card = "**** 4321"` |
| una tarjeta no encontrada (`CARD-P1` de `C-0002`) | código `NOT_FOUND` y `masked_card` vacío |
| datos inválidos (`reason = "STOLEN"`) | código `INVALID_INPUT` y `reason` vacío |
| `card_id = "4111111111114321"` (número de tarjeta en el campo) | código `NOT_FOUND`, `card_id = "[REDACTED]"` y `masked_card` vacío |
| `idempotency_key = "bloqueo-4111111111114321"` | `blocked` e `idempotency_key = "bloqueo-[REDACTED]"` |
| sin verificación | código `IDENTITY_NOT_VERIFIED` y `masked_card` vacío |
| una falla inesperada | código `INTERNAL` |

## 7. Contratos de herramientas MCP

### `bloquear_tarjeta`

- **Propósito:** bloquear una tarjeta del cliente verificado e indicar el motivo, para que deje de poder usarse.
- **Cuándo usarla / cuándo no:** solo **después** de que `verificar_identidad` haya respondido `verified = true` en la conversación, y con un `card_id` devuelto por `consultar_transacciones`. Traducir lo que dice el cliente a uno de los códigos de motivo. Generar una `idempotency_key` nueva por cada bloqueo que se quiera hacer y reutilizarla **solo** para reintentar esa misma solicitud. La herramienta no decide si hay fraude, no abre disputas, no escala y no desbloquea. Cómo actuar según la respuesta:
  - `already_blocked = true`: informar al cliente que la tarjeta ya estaba bloqueada.
  - `CARD_NOT_BLOCKABLE`: explicar que una tarjeta cancelada no se puede bloquear.
  - `NOT_FOUND`: revisar con el cliente de qué tarjeta se trata.
  - `INTERNAL`: no reintentar y derivar a un analista.
- **Precondiciones:** identidad verificada en el servidor para la conversación (Art. 7, RN-005-03). Exige `conversation_id`.
- **Efectos secundarios:** pasa la tarjeta de `ACTIVE` a `BLOCKED` y registra el bloqueo y la clave de reintento usada, todo de forma atómica; además, un registro de auditoría. Es idempotente por `(conversation_id, idempotency_key)` (RN-005-07).

**Entrada**

| Campo | Tipo | Obligatorio | Descripción / validación |
|---|---|---|---|
| `conversation_id` | `string` | Sí | Identificador de correlación; no vacío tras recortar. |
| `card_id` | `string` | Sí | `card_id` devuelto por `consultar_transacciones`; 1–64 caracteres tras recortar. |
| `reason` | `string` (enum) | Sí | `FRAUD_SUSPECTED` o `LOST_OR_STOLEN` (RN-005-02). |
| `idempotency_key` | `string` | Sí | Clave de reintento generada por el consumidor; 1–64 caracteres tras recortar; única por conversación (RN-005-07). |

**Salida** (no admite campos adicionales)

| Campo | Tipo | Descripción |
|---|---|---|
| `card_id` | `string` | Identificador opaco de la tarjeta en el core, no derivado de su número. |
| `masked_card` | `string` | `**** ` seguido de los 4 últimos dígitos. |
| `status` | `string` | `BLOCKED`. |
| `blocked_at` | `string \| null` | Instante del bloqueo en ISO 8601 con zona de Bogotá (p. ej. `2026-10-17T10:00:00-05:00`); `null` si la tarjeta ya estaba bloqueada sin un bloqueo registrado (RN-005-06). |
| `reason` | `string \| null` | Código del motivo del bloqueo (RN-005-02); `null` en el mismo caso que `blocked_at`. |
| `already_blocked` | `boolean` | `true` si la tarjeta ya estaba bloqueada antes de esta solicitud; `false` en un bloqueo nuevo o en su repetición (RN-005-05, RN-005-07). |

Ejemplos:

- Bloqueo nuevo o repetición: `{"card_id": "...", "masked_card": "**** 4321", "status": "BLOCKED", "blocked_at": "2026-10-17T10:00:00-05:00", "reason": "FRAUD_SUSPECTED", "already_blocked": false}`
- Ya bloqueada sin registro: `{"card_id": "...", "masked_card": "**** 4321", "status": "BLOCKED", "blocked_at": null, "reason": null, "already_blocked": true}`

**Errores** (formato `{code, message, retryable}`, `mcp-tools.md` §7; se evalúan en el orden de RN-005-09)

| Código | Tipo | Reintentable | Cuándo ocurre |
|---|---|---|---|
| `INVALID_INPUT` | validación | No | Entrada que viola RN-005-08, o clave de reintento ya usada en la conversación con otra tarjeta u otro motivo (RN-005-07). |
| `IDENTITY_NOT_VERIFIED` | permisos | No | La conversación no está verificada en el servidor (RN-005-03). |
| `NOT_FOUND` | negocio | No | La tarjeta no pertenece al cliente verificado o no existe; mensaje fijo, idéntico en ambos casos (RN-005-04). |
| `CARD_NOT_BLOCKABLE` | negocio | No | La tarjeta está `CANCELLED` (RN-005-05). |
| `INTERNAL` | interno | No | Falla inesperada del core; la tarjeta no cambia (RN-005-13). El consumidor debe escalar (Art. 10). |

## 8. Casos de escalamiento

Esta feature no ejecuta escalamientos (`escalar_a_analista` está fuera de alcance); solo le indica al consumidor cuándo debe derivar.

| Condición | Motivo | Datos del resumen estructurado |
|---|---|---|
| `bloquear_tarjeta` devuelve `INTERNAL` (`retryable = false`) | Falla no recuperable del core al bloquear la tarjeta (Art. 10, RN-005-13) | Lo definirá la spec de `escalar_a_analista`; como mínimo `conversation_id`, tarjeta enmascarada, motivo del bloqueo y código de error. Nunca el número completo de la tarjeta ni el documento. |

## 9. Clarificaciones

| Fecha | Pregunta | Respuesta | Secciones afectadas |
|---|---|---|---|
| 2026-10-17 | ¿Cómo indica la solicitud qué tarjeta bloquear? | Con el `card_id` opaco que devuelve `consultar_transacciones`. | RN-005-01, RN-005-08, AC-005-10, §7 |
| 2026-10-17 | ¿Cómo se envía y se devuelve el motivo del bloqueo? | Como código de un enum cerrado en inglés: `FRAUD_SUSPECTED`, `LOST_OR_STOLEN`. | RN-005-02, AC-005-02, AC-005-03, §7 |
| 2026-10-17 | Si la tarjeta ya estaba bloqueada, ¿qué devuelve la herramienta? | Respuesta exitosa con `already_blocked = true` y los datos del bloqueo original; no registra otro bloqueo. | RN-005-05, AC-005-04, AC-005-07, §7 |
| 2026-10-17 | Si la tarjeta está cancelada, ¿qué error se devuelve? | `CARD_NOT_BLOCKABLE` (negocio, no reintentable). | RN-005-05, AC-005-04, §7 |
| 2026-10-17 | ¿Cómo funciona la clave de reintento? | Igual que en `iniciar_disputa`: única por conversación y registrada solo al crear un bloqueo nuevo. Misma clave, tarjeta y motivo ⇒ se devuelve el bloqueo existente. Misma clave con otra tarjeta u otro motivo ⇒ `INVALID_INPUT`. | RN-005-07, AC-005-05, AC-005-06, AC-005-07, §7 |
| 2026-10-17 | ¿Qué informa una tarjeta ya bloqueada sin un bloqueo registrado (p. ej. por semilla)? | `blocked_at = null` y `reason = null`, con `already_blocked = true`. | RN-005-06, AC-005-04, §7 |
| 2026-10-17 | ¿En qué orden se evalúan las comprobaciones? | Validación → identidad → clave de reintento → tarjeta del cliente → estado de la tarjeta. | RN-005-09, AC-005-11, §7 |
| 2026-10-17 | ¿Qué campos devuelve una respuesta exitosa? | `card_id`, `masked_card`, `status`, `blocked_at`, `reason` y `already_blocked`. | RN-005-10, AC-005-01, AC-005-13, §7 |

## 10. Preguntas abiertas

Ninguna.

## 11. Historial de cambios

| Versión | Fecha | Cambio | Autor |
|---|---|---|---|
| 0.1.0 | 2026-10-17 | Versión inicial a partir de la issue #30 | Juangiov (con Claude Code) |
| 0.1.0 | 2026-10-17 | Spec aprobada por el usuario | Juangiov |

---

## Gate de salida

- [x] No quedan preguntas abiertas.
- [x] Cada clarificación está reflejada en las secciones afectadas.
- [x] Todos los criterios de aceptación tienen ID y formato Given/When/Then.
- [x] Cada regla de negocio está cubierta por al menos un criterio de aceptación.
- [x] Contratos MCP y casos de escalamiento completos o marcados "No aplica".
- [x] Estado cambiado a **Aprobada**.
