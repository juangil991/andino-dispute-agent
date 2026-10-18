# Spec: Abrir una disputa sobre una transacción de un cliente verificado

| Campo | Valor |
|---|---|
| Feature | `004-open-dispute` |
| Versión | 0.2.0 |
| Estado | Aprobada |
| Fecha | 2026-10-17 |
| Origen | Issue [#29](https://github.com/juangil991/andino-dispute-agent/issues/29) del backlog (P0) |
| Plan | [plan.md](./plan.md) |
| Tareas | [tasks.md](./tasks.md) |
| Constitución | [docs/constitution.md](../../docs/constitution.md) |

---

## 1. Contexto y problema

Con `buscar_cliente` (spec 001), `verificar_identidad` (spec 002) y `consultar_transacciones` (spec 003), el agente ya puede localizar al cliente, verificarlo y mostrarle los movimientos de su tarjeta para que señale el cargo que reclama. Falta el paso que convierte ese reclamo en un caso: hoy el core simulado no guarda disputas ni ofrece ninguna forma de abrirlas.

Esta feature añade la herramienta `iniciar_disputa`, la primera que **escribe** en el core. Registra una disputa abierta sobre una transacción confirmada del cliente verificado, con un motivo de un catálogo cerrado. Valida en el servidor que la conversación esté verificada (Art. 7, defensa en profundidad). Es segura ante reintentos gracias a una clave de idempotencia (`mcp-tools.md` §9). Responde igual ante una transacción ajena que ante una inexistente, no deja disputas a medias ante una falla y audita cada invocación (Art. 8). Solo registra la disputa: la decisión de resolver, rechazar o escalar la tomará `DisputePolicy` en su propia spec (Art. 5).

## 2. Objetivos

- Exponer la herramienta MCP `iniciar_disputa` en `core_banking_mcp` con el contrato de §7.
- Incorporar las disputas al core simulado, con datos semilla ficticios y reproducibles (Art. 1).
- Rechazar con `IDENTITY_NOT_VERIFIED` toda solicitud de una conversación no verificada en el servidor (Art. 7).
- Abrir disputas solo sobre transacciones confirmadas del cliente verificado, con un máximo de una disputa abierta por transacción.
- Garantizar que repetir la misma solicitud con la misma clave de reintento no cree una segunda disputa.
- Responder `NOT_FOUND` de forma idéntica ante una transacción ajena o inexistente, sin revelar datos de otros clientes.
- Rechazar entradas inválidas con `INVALID_INPUT` y, ante una falla inesperada, devolver `INTERNAL` no reintentable sin dejar nada registrado (Art. 10).
- Auditar el 100 % de las invocaciones sin registrar números completos de tarjeta ni documentos (Art. 8).

### Fuera de alcance

- Cambios en `dispute_agent`: operación en `BankingToolsPort`, adaptador MCP, loop LLM y chat (spec propia).
- La decisión sobre la disputa (`DisputePolicy`: resolver, rechazar o escalar) y los plazos de disputa que esa política pueda fijar.
- Bloquear tarjetas (`bloquear_tarjeta`) y ejecutar escalamientos (`escalar_a_analista`): esta feature solo indica cuándo derivar.
- Cerrar, rechazar, consultar o modificar disputas existentes. Las disputas `CLOSED` y `REJECTED` solo existen en esta versión por semillas o builders.
- Descripción libre del reclamo, adjuntos o evidencia.
- Cambios en `buscar_cliente`, `verificar_identidad` y `consultar_transacciones`.

## 3. Historias de usuario

| ID | Como | Quiero | Para |
|---|---|---|---|
| HU-004-01 | agente de disputas | abrir una disputa sobre una transacción confirmada del cliente verificado, indicando el motivo | que el reclamo quede registrado y pueda seguir su curso |
| HU-004-02 | agente de disputas | que repetir una solicitud por un corte o reintento no cree disputas duplicadas | poder reintentar sin miedo a duplicar el caso |
| HU-004-03 | agente de disputas | saber si la transacción ya tiene una disputa abierta y cuál es | informar al cliente sin abrir otra |
| HU-004-04 | cliente de Banco Andino | que nadie abra disputas sobre mis transacciones sin haberse verificado como yo, ni pueda averiguar si una transacción existe | proteger mi cuenta |
| HU-004-05 | agente de disputas | saber cuándo debo derivar el caso a un analista porque el sistema falló | no dejar al cliente sin respuesta |
| HU-004-06 | responsable de auditoría | que cada solicitud quede registrada con su conversación, momento, transacción, motivo y resultado | tener trazabilidad total sin exponer datos personales |

## 4. Reglas de negocio

| ID | Regla | Fuente / justificación |
|---|---|---|
| RN-004-01 | La solicitud indica la transacción por el `transaction_id` que devuelve `consultar_transacciones`, el motivo (`reason`) y una clave de reintento (`idempotency_key`) generada por el consumidor. | Issue #29; `mcp-tools.md` §9 |
| RN-004-02 | El motivo es un código de un catálogo cerrado, sensible a mayúsculas: `UNRECOGNIZED_CHARGE` (no reconoce el cargo), `DUPLICATE_CHARGE` (cobro duplicado), `INCORRECT_AMOUNT` (monto incorrecto), `NOT_RECEIVED` (producto o servicio no recibido) y `OTHER` (otro). Cualquier otro valor, vacío o ausente ⇒ `INVALID_INPUT`. | Issue #29; clarificación 2026-10-17 |
| RN-004-03 | La herramienta exige que la conversación esté verificada en el servidor (estado de RN-002-13). Una conversación sin verificación exitosa, desconocida o bloqueada por intentos agotados se rechaza con `IDENTITY_NOT_VERIFIED`. La verificación no se traslada: estar verificada en otra conversación no cuenta. | Art. 7; issue #29; `mcp-tools.md` §5 |
| RN-004-04 | La transacción debe pertenecer a una tarjeta del cliente verificado en la conversación, **sea cual sea el estado de la tarjeta** (activa, bloqueada o cancelada). Si no es así, porque la transacción es de otro cliente o porque no existe, se devuelve `NOT_FOUND` con un mensaje fijo, **idéntico** en ambos casos, sin datos de ningún cliente. | Issue #29; clarificación 2026-10-17; RN-003-03/04 |
| RN-004-05 | Solo se puede disputar una transacción `CONFIRMED`. Una transacción `PENDING` o `REVERSED` se rechaza con `TRANSACTION_NOT_DISPUTABLE` y no se registra nada. | Issue #29 |
| RN-004-06 | No hay plazo máximo para disputar una transacción confirmada: su antigüedad no influye en esta herramienta. | Issue #29 |
| RN-004-07 | Una disputa tiene uno de estos estados: `OPEN`, `CLOSED` o `REJECTED`. Una transacción tiene **como máximo una** disputa `OPEN`. Si ya la tiene, la solicitud se rechaza con `DISPUTE_ALREADY_OPEN` cuyo `message` incluye el `dispute_id` de la disputa abierta existente, y no se registra otra. Las disputas previas `CLOSED` o `REJECTED` no impiden abrir una nueva. | Issue #29; clarificación 2026-10-17 |
| RN-004-08 | La clave de reintento es única **dentro de cada conversación**. Si la conversación ya usó la clave con la **misma** transacción y el **mismo** motivo, se devuelve la disputa que creó esa solicitud (mismo `dispute_id` y `opened_at`) sin registrar otra. Si la usó con otra transacción u otro motivo, se rechaza con `INVALID_INPUT` sin registrar nada. La misma clave en otra conversación es una solicitud independiente. | Issue #29; clarificación 2026-10-17; `mcp-tools.md` §9 |
| RN-004-09 | Validación de entrada: `conversation_id` obligatorio y no vacío tras recortar; `transaction_id` obligatorio, de 1 a 64 caracteres tras recortar; `idempotency_key` obligatoria, de 1 a 64 caracteres tras recortar; `reason` obligatorio y del catálogo de RN-004-02. Toda violación ⇒ `INVALID_INPUT`, sin disputa registrada. | Issue #29; clarificación 2026-10-17 |
| RN-004-10 | Las comprobaciones se evalúan en este orden y se devuelve el primer resultado: (1) validación de entrada → `INVALID_INPUT`; (2) identidad verificada → `IDENTITY_NOT_VERIFIED`; (3) clave de reintento ya usada en la conversación → la disputa existente (misma solicitud) o `INVALID_INPUT` (solicitud distinta); (4) transacción del cliente verificado → `NOT_FOUND`; (5) transacción confirmada → `TRANSACTION_NOT_DISPUTABLE`; (6) sin disputa abierta sobre la transacción → `DISPUTE_ALREADY_OPEN`. | Clarificación 2026-10-17 |
| RN-004-11 | Una disputa nueva queda con `status = OPEN`, un `dispute_id` opaco y único que no se deriva del número de la tarjeta, y `opened_at` igual al instante del reloj inyectado expresado en ISO 8601 con la zona de Bogotá (`−05:00`). | Issue #29; §5.3.6; RN-002-08 |
| RN-004-12 | La respuesta exitosa contiene **solo** `dispute_id`, `status`, `opened_at`, `reason` (el código) y `transaction`, con exactamente los campos de `TransactionItem` de la spec 003 (RN-003-12): `transaction_id`, `occurred_at`, `merchant`, `amount`, `currency`, `status`, `card_id`, `masked_card` y `merchant_country` (spec 007, RN-007-30). | Issue #29; clarificación 2026-10-17 |
| RN-004-13 | La respuesta nunca contiene el número completo de ninguna tarjeta, el documento del cliente ni su nombre, ni datos de otros clientes. | Issue #29; Art. 7; `mcp-tools.md` §8 |
| RN-004-14 | Abrir una disputa solo registra la disputa y la clave de reintento usada. No cambia la transacción, la tarjeta ni el estado de verificación de la conversación; no decide si la disputa procede, no bloquea tarjetas ni escala. | Issue #29; Art. 5 |
| RN-004-15 | Ante una falla inesperada (p. ej. el repositorio de disputas no responde al registrar), la herramienta devuelve `INTERNAL` con `retryable = false`, sin detalles internos (trazas, SQL, texto de la excepción). No queda ninguna disputa ni clave de reintento registrada: el registro es atómico. | Art. 10; issue #29; `mcp-tools.md` §7 |
| RN-004-16 | Cada invocación genera exactamente un registro de auditoría con `conversation_id` (o vacío si no llegó), fecha y hora del reloj inyectado, `tool = "iniciar_disputa"`, `transaction_id`, `reason` e `idempotency_key` recibidos (cada uno vacío si no es válido según RN-004-09, para no registrar lo que se haya escrito en ese campo) y resultado: `opened` con el `dispute_id` creado, `replayed` con el `dispute_id` existente, o el código de error (`INVALID_INPUT`, `IDENTITY_NOT_VERIFIED`, `NOT_FOUND`, `TRANSACTION_NOT_DISPUTABLE`, `DISPUTE_ALREADY_OPEN` con el `dispute_id` existente, `INTERNAL`). Como `transaction_id` e `idempotency_key` son texto libre, toda secuencia de 13 a 19 dígitos seguidos que contengan se registra sustituida por `[REDACTED]`. El registro **nunca** contiene el número completo de una tarjeta ni el documento del cliente. | Art. 8; issue #29 |

## 5. Tabla de decisión de `DisputePolicy`

No aplica: esta feature solo registra la disputa; la decisión sobre ella queda para la spec de `DisputePolicy` (Art. 5).

## 6. Criterios de aceptación

En todos los criterios, salvo que se indique otra cosa: el reloj inyectado marca `2026-10-17T15:00:00Z` (hoy es 17 de octubre de 2026 en Bogotá); existe la cliente `C-0001` "Laura Méndez", con documento `D-1001` y una tarjeta activa terminada en `4321` (número `4111111111114321`); la conversación `A` está verificada para `C-0001`; la tarjeta `4321` tiene la transacción `TX-L1`, `CONFIRMED`, de `85000.00 COP` en "Tienda Aurora" el `2026-10-10T12:00:00-05:00`, sin disputas; y la solicitud se hace en la conversación `A` con `transaction_id = "TX-L1"`, `reason = "UNRECOGNIZED_CHARGE"` e `idempotency_key = "K-1"`. Los datos de prueba se construyen con builders (§5.3.7), no con las semillas.

### AC-004-01 — Abrir una disputa sobre una transacción confirmada

Cubre: HU-004-01, RN-004-01, RN-004-11, RN-004-12, RN-004-14

- **When** se invoca `iniciar_disputa`
- **Then** la respuesta trae un `dispute_id` no vacío, `status = "OPEN"`, `opened_at = "2026-10-17T10:00:00-05:00"` y `reason = "UNRECOGNIZED_CHARGE"`
- **And** `transaction` trae `transaction_id = "TX-L1"`, `occurred_at = "2026-10-10T12:00:00-05:00"`, `merchant = "Tienda Aurora"`, `amount = "85000.00"`, `currency = "COP"`, `status = "CONFIRMED"`, el `card_id` de la tarjeta, `masked_card = "**** 4321"` y `merchant_country = "CO"`
- **And** queda registrada exactamente 1 disputa `OPEN` sobre `TX-L1` con ese `dispute_id`
- **And** la transacción sigue `CONFIRMED`, la tarjeta sigue activa y el estado de verificación de la conversación no cambia

### AC-004-02 — Motivos permitidos

Cubre: HU-004-01, RN-004-02

- **When** se invoca `iniciar_disputa` con `reason = <motivo>`
- **Then** la disputa queda registrada como `OPEN` y la respuesta trae `reason = <motivo>`

| motivo |
|---|
| `UNRECOGNIZED_CHARGE` |
| `DUPLICATE_CHARGE` |
| `INCORRECT_AMOUNT` |
| `NOT_RECEIVED` |
| `OTHER` |

### AC-004-03 — Motivo inválido

Cubre: RN-004-02, RN-004-09

- **When** se invoca `iniciar_disputa` con `<motivo>`
- **Then** se devuelve el error `INVALID_INPUT` con `retryable = false`
- **And** no se registra ninguna disputa

| motivo |
|---|
| `reason = "FRAUD"` (no está en el catálogo) |
| `reason = "unrecognized_charge"` (en minúsculas) |
| `reason = "no reconoce el cargo"` (texto en lugar del código) |
| `reason = ""` |
| `reason` ausente o `null` |

### AC-004-04 — Solo las transacciones confirmadas se pueden disputar

Cubre: HU-004-01, RN-004-05

- **Given** `TX-L1` está en estado `<estado>`
- **When** se invoca `iniciar_disputa`
- **Then** `<resultado>`

| estado | resultado |
|---|---|
| `CONFIRMED` | la disputa queda registrada como `OPEN` |
| `PENDING` | error `TRANSACTION_NOT_DISPUTABLE` con `retryable = false` y no se registra ninguna disputa |
| `REVERSED` | error `TRANSACTION_NOT_DISPUTABLE` con `retryable = false` y no se registra ninguna disputa |

### AC-004-05 — No hay plazo máximo para disputar

Cubre: RN-004-06

- **Given** `TX-L1` ocurrió el `<fecha>` (hace `<antigüedad>`)
- **When** se invoca `iniciar_disputa`
- **Then** la disputa queda registrada como `OPEN`

| fecha | antigüedad |
|---|---|
| `2026-10-16T12:00:00-05:00` | 1 día |
| `2026-07-19T12:00:00-05:00` | 90 días |
| `2025-09-12T12:00:00-05:00` | 400 días |

### AC-004-06 — Se pueden disputar transacciones de tarjetas en cualquier estado

Cubre: RN-004-04

- **Given** la tarjeta `4321` está en estado `<estado de la tarjeta>`
- **When** se invoca `iniciar_disputa`
- **Then** la disputa queda registrada como `OPEN`

| estado de la tarjeta |
|---|
| activa |
| bloqueada |
| cancelada |

### AC-004-07 — Disputas previas sobre la misma transacción

Cubre: HU-004-03, RN-004-07

- **Given** `TX-L1` ya tiene la disputa `D-OLD` en estado `<estado previo>`
- **When** se invoca `iniciar_disputa` con `reason = "DUPLICATE_CHARGE"` e `idempotency_key = "K-2"`
- **Then** `<resultado>`

| estado previo | resultado |
|---|---|
| `OPEN` | error `DISPUTE_ALREADY_OPEN` con `retryable = false`, cuyo `message` contiene `D-OLD`; `TX-L1` sigue con una sola disputa |
| `CLOSED` | se registra una disputa nueva `OPEN` con un `dispute_id` distinto de `D-OLD` |
| `REJECTED` | se registra una disputa nueva `OPEN` con un `dispute_id` distinto de `D-OLD` |

### AC-004-08 — Repetir la misma solicitud no duplica la disputa

Cubre: HU-004-02, RN-004-08, RN-004-10

- **Given** en la conversación `A` ya se invocó `iniciar_disputa` con `TX-L1`, `UNRECOGNIZED_CHARGE` y `K-1`, que creó la disputa `D-1`
- **When** se vuelve a invocar `iniciar_disputa` en `A` con `TX-L1`, `UNRECOGNIZED_CHARGE` y `K-1`, con el reloj una hora después
- **Then** la respuesta es exitosa y trae `dispute_id = D-1` y el mismo `opened_at` de la primera respuesta (no un error `DISPUTE_ALREADY_OPEN`)
- **And** `TX-L1` sigue con exactamente 1 disputa

### AC-004-09 — Una clave de reintento reutilizada con otros datos se rechaza

Cubre: HU-004-02, RN-004-08

- **Given** `C-0001` tiene otra transacción `TX-L2`, `CONFIRMED`, en la tarjeta `4321`
- **And** en la conversación `A` ya se invocó `iniciar_disputa` con `TX-L1`, `UNRECOGNIZED_CHARGE` y `K-1`
- **When** se invoca `iniciar_disputa` en `A` con `idempotency_key = "K-1"` y `<datos>`
- **Then** se devuelve el error `INVALID_INPUT` con `retryable = false`
- **And** no se registra ninguna disputa adicional

| datos |
|---|
| `transaction_id = "TX-L2"`, `reason = "UNRECOGNIZED_CHARGE"` (otra transacción) |
| `transaction_id = "TX-L1"`, `reason = "DUPLICATE_CHARGE"` (otro motivo) |

### AC-004-10 — La clave de reintento pertenece a su conversación

Cubre: RN-004-08

- **Given** en la conversación `A` ya se invocó `iniciar_disputa` con `TX-L1`, `UNRECOGNIZED_CHARGE` y `K-1`, que creó la disputa `D-1`
- **And** la conversación `B` también está verificada para `C-0001`
- **When** se invoca `iniciar_disputa` en `B` con `TX-L1`, `UNRECOGNIZED_CHARGE` y `K-1`
- **Then** se devuelve el error `DISPUTE_ALREADY_OPEN` cuyo `message` contiene `D-1` (la clave de `A` no aplica en `B`)
- **And** `TX-L1` sigue con exactamente 1 disputa

### AC-004-11 — Una transacción ajena o inexistente recibe la misma respuesta

Cubre: HU-004-04, RN-004-04, RN-004-13

- **Given** existe el cliente `C-0002` "Pedro Ríos" con una tarjeta terminada en `8765` y la transacción `TX-P1`, `CONFIRMED`
- **And** no existe ninguna transacción `TX-9999`
- **When** se invoca `iniciar_disputa` con `transaction_id = "TX-P1"` y, en otra invocación con `idempotency_key = "K-2"`, con `transaction_id = "TX-9999"`
- **Then** ambas devuelven el error `NOT_FOUND` con `retryable = false`
- **And** las dos respuestas son idénticas campo a campo (mismo código, mensaje y `retryable`)
- **And** no se registra ninguna disputa ni aparece en la respuesta ningún dato de `C-0002`

### AC-004-12 — No se abre una disputa sin la identidad verificada

Cubre: HU-004-04, RN-004-03, RN-004-14

- **Given** `<situación>`
- **When** se invoca `iniciar_disputa` en esa conversación
- **Then** se devuelve el error `IDENTITY_NOT_VERIFIED` con `retryable = false`
- **And** no se registra ninguna disputa
- **And** el estado de verificación de la conversación (cliente verificado e intentos fallidos) no cambia

| situación |
|---|
| la conversación nunca ha invocado `verificar_identidad` |
| la conversación acumula 1 intento fallido de verificación y ningún éxito |
| la conversación agotó sus intentos de verificación (bloqueada) |
| la conversación `A` está verificada para `C-0001` y la solicitud se hace en la conversación `B`, no verificada |

### AC-004-13 — Datos de la solicitud inválidos

Cubre: RN-004-09

- **When** se invoca `iniciar_disputa` con `<dato>` (el resto de campos válidos)
- **Then** se devuelve el error `INVALID_INPUT` con `retryable = false`
- **And** no se registra ninguna disputa

| dato |
|---|
| `transaction_id` ausente o `null` |
| `transaction_id = ""` o solo espacios |
| `transaction_id` de 65 caracteres |
| `idempotency_key` ausente o `null` |
| `idempotency_key = ""` o solo espacios |
| `idempotency_key` de 65 caracteres |
| `conversation_id` ausente, vacío o solo espacios |

### AC-004-14 — Orden de las comprobaciones

Cubre: RN-004-10

- **Given** `<situación>`
- **When** se invoca `iniciar_disputa` con `<entrada>`
- **Then** el resultado es `<resultado>`

| situación | entrada | resultado |
|---|---|---|
| la conversación no está verificada | `reason = "FRAUD"` | `INVALID_INPUT` |
| la conversación no está verificada | `transaction_id = "TX-9999"` (no existe) | `IDENTITY_NOT_VERIFIED` |
| en `A` ya se usó `K-1` con `TX-L1` | `transaction_id = "TX-9999"`, `idempotency_key = "K-1"` | `INVALID_INPUT` |
| `TX-P1` de `C-0002` está `PENDING` | `transaction_id = "TX-P1"` | `NOT_FOUND` |
| `TX-L1` está `PENDING` y tiene una disputa `OPEN` | (entrada por defecto) | `TRANSACTION_NOT_DISPUTABLE` |

### AC-004-15 — La respuesta protege los datos personales

Cubre: HU-004-04, RN-004-12, RN-004-13

- **When** se invoca `iniciar_disputa`
- **Then** la respuesta contiene exactamente los campos `dispute_id`, `status`, `opened_at`, `reason` y `transaction`, y `transaction` exactamente los campos de RN-004-12
- **And** `masked_card = "**** 4321"`, y ni `dispute_id` ni `card_id` contienen `4111111111114321`
- **And** en ninguna parte de la respuesta aparecen `4111111111114321`, `D-1001` ni `Laura Méndez`

### AC-004-16 — Una falla al registrar no deja una disputa a medias

Cubre: HU-004-05, RN-004-15

- **Given** el repositorio de disputas falla de forma inesperada al registrar
- **When** se invoca `iniciar_disputa`
- **Then** se devuelve el error `INTERNAL` con `retryable = false`
- **And** el mensaje no contiene trazas, SQL ni el texto de la excepción original
- **And** no queda ninguna disputa registrada sobre `TX-L1`
- **And** cuando el repositorio vuelve a funcionar, la misma solicitud con `K-1` registra una disputa nueva `OPEN` (la clave no quedó registrada)

### AC-004-17 — Cada solicitud queda registrada sin datos personales

Cubre: HU-004-06, RN-004-16

- **Given** un reloj inyectado fijo
- **When** se invoca `iniciar_disputa` produciendo `<caso>`
- **Then** queda exactamente 1 registro de auditoría con `conversation_id`, la fecha y hora del reloj, `tool = "iniciar_disputa"`, el `transaction_id`, el `reason` y la `idempotency_key` recibidos y `<resultado registrado>`
- **And** el registro no contiene `4111111111114321` ni `D-1001`

| caso | resultado registrado |
|---|---|
| una disputa abierta | tipo `opened` con el `dispute_id` creado |
| una repetición de la solicitud | tipo `replayed` con el `dispute_id` existente |
| una disputa duplicada | código `DISPUTE_ALREADY_OPEN` con el `dispute_id` existente |
| una transacción no disputable | código `TRANSACTION_NOT_DISPUTABLE` |
| una transacción no encontrada | código `NOT_FOUND` |
| datos inválidos (`reason = "FRAUD"`) | código `INVALID_INPUT` y `reason` vacío |
| `transaction_id = "4111111111114321"` (número de tarjeta en el campo, no existe como transacción) | código `NOT_FOUND` y `transaction_id = "[REDACTED]"` |
| `idempotency_key = "pago-4111111111114321"` | tipo `opened` e `idempotency_key = "pago-[REDACTED]"` |
| sin verificación | código `IDENTITY_NOT_VERIFIED` |
| una falla inesperada | código `INTERNAL` |

## 7. Contratos de herramientas MCP

### `iniciar_disputa`

- **Propósito:** abrir una disputa sobre una transacción confirmada del cliente verificado, indicando el motivo del reclamo.
- **Cuándo usarla / cuándo no:** solo **después** de que `verificar_identidad` haya respondido `verified = true` en la conversación, y con un `transaction_id` devuelto por `consultar_transacciones`. Traducir lo que dice el cliente a uno de los códigos de motivo. Generar una `idempotency_key` nueva por cada disputa que se quiera abrir y reutilizarla **solo** para reintentar esa misma solicitud. No decide si la disputa procede, no bloquea tarjetas ni escala. Ante `DISPUTE_ALREADY_OPEN`, informar al cliente de la disputa existente sin abrir otra. Ante `TRANSACTION_NOT_DISPUTABLE`, explicar que solo se disputan transacciones confirmadas. Ante `NOT_FOUND`, revisar con el cliente la transacción. Ante `INTERNAL`, no reintentar y derivar a un analista.
- **Precondiciones:** identidad verificada en el servidor para la conversación (Art. 7, RN-004-03). Exige `conversation_id`.
- **Efectos secundarios:** registra una disputa `OPEN` y la clave de reintento usada, de forma atómica, y un registro de auditoría. Idempotente por `(conversation_id, idempotency_key)` (RN-004-08).

**Entrada**

| Campo | Tipo | Obligatorio | Descripción / validación |
|---|---|---|---|
| `conversation_id` | `string` | Sí | Identificador de correlación; no vacío tras recortar. |
| `transaction_id` | `string` | Sí | `transaction_id` devuelto por `consultar_transacciones`; 1–64 caracteres tras recortar. |
| `reason` | `string` (enum) | Sí | `UNRECOGNIZED_CHARGE`, `DUPLICATE_CHARGE`, `INCORRECT_AMOUNT`, `NOT_RECEIVED` u `OTHER` (RN-004-02). |
| `idempotency_key` | `string` | Sí | Clave de reintento generada por el consumidor; 1–64 caracteres tras recortar; única por conversación (RN-004-08). |

**Salida** (no admite campos adicionales)

| Campo | Tipo | Descripción |
|---|---|---|
| `dispute_id` | `string` | Identificador opaco de la disputa en el core, no derivado del número de la tarjeta. |
| `status` | `string` | `OPEN` (una disputa recién abierta o devuelta por una repetición en esta versión). |
| `opened_at` | `string` | Instante de apertura en ISO 8601 con zona de Bogotá (p. ej. `2026-10-17T10:00:00-05:00`). |
| `reason` | `string` | Código del motivo (RN-004-02). |
| `transaction` | `TransactionItem` | La transacción disputada, con exactamente los campos de `TransactionItem` de la spec 003 (RN-003-12), incluido `merchant_country` (spec 007, RN-007-30). |

Ejemplo:

- Disputa abierta o repetición: `{"dispute_id": "...", "status": "OPEN", "opened_at": "2026-10-17T10:00:00-05:00", "reason": "UNRECOGNIZED_CHARGE", "transaction": {"transaction_id": "TX-L1", "occurred_at": "2026-10-10T12:00:00-05:00", "merchant": "Tienda Aurora", "amount": "85000.00", "currency": "COP", "status": "CONFIRMED", "card_id": "...", "masked_card": "**** 4321", "merchant_country": "CO"}}`

**Errores** (formato `{code, message, retryable}`, `mcp-tools.md` §7; se evalúan en el orden de RN-004-10)

| Código | Tipo | Reintentable | Cuándo ocurre |
|---|---|---|---|
| `INVALID_INPUT` | validación | No | Entrada que viola RN-004-09, o clave de reintento ya usada en la conversación con otra transacción u otro motivo (RN-004-08). |
| `IDENTITY_NOT_VERIFIED` | permisos | No | La conversación no está verificada en el servidor (RN-004-03). |
| `NOT_FOUND` | negocio | No | La transacción no pertenece a una tarjeta del cliente verificado o no existe; mensaje fijo, idéntico en ambos casos (RN-004-04). |
| `TRANSACTION_NOT_DISPUTABLE` | negocio | No | La transacción está `PENDING` o `REVERSED` (RN-004-05). |
| `DISPUTE_ALREADY_OPEN` | negocio | No | La transacción ya tiene una disputa `OPEN`; el `message` incluye su `dispute_id` (RN-004-07). |
| `INTERNAL` | interno | No | Falla inesperada del core; no queda nada registrado (RN-004-15). El consumidor debe escalar (Art. 10). |

## 8. Casos de escalamiento

Esta feature no ejecuta escalamientos (`escalar_a_analista` está fuera de alcance); solo señala al consumidor cuándo debe derivar.

| Condición | Motivo | Datos del resumen estructurado |
|---|---|---|
| `iniciar_disputa` devuelve `INTERNAL` (`retryable = false`) | Falla no recuperable del core al registrar la disputa (Art. 10, RN-004-15) | Lo definirá la spec de `escalar_a_analista`; como mínimo `conversation_id`, `transaction_id`, motivo de la disputa y código de error. Nunca el número completo de la tarjeta ni el documento. |

## 9. Clarificaciones

| Fecha | Pregunta | Respuesta | Secciones afectadas |
|---|---|---|---|
| 2026-10-17 | ¿Cómo se envía y se devuelve el motivo de la disputa? | Como código de un enum cerrado en inglés: `UNRECOGNIZED_CHARGE`, `DUPLICATE_CHARGE`, `INCORRECT_AMOUNT`, `NOT_RECEIVED`, `OTHER`. | RN-004-02, AC-004-02, AC-004-03, §7 |
| 2026-10-17 | Ante una disputa abierta sobre la misma transacción, ¿cómo se indica cuál es la existente? | Error `DISPUTE_ALREADY_OPEN` (negocio, no reintentable) con el `dispute_id` existente en el `message`; no cambia el sobre de error compartido. | RN-004-07, AC-004-07, AC-004-10, §7 |
| 2026-10-17 | ¿Qué alcance tiene la clave de reintento y qué pasa si se reutiliza con datos distintos? | Única por conversación. Misma clave, transacción y motivo ⇒ se devuelve la disputa existente. Misma clave con otra transacción u otro motivo ⇒ `INVALID_INPUT`. | RN-004-08, AC-004-08, AC-004-09, AC-004-10, §7 |
| 2026-10-17 | ¿Qué devuelve la herramienta sobre la transacción y la fecha de apertura? | `dispute_id`, `status`, `opened_at` (ISO 8601 con `−05:00`, del reloj inyectado), `reason` y `transaction` con los campos de `TransactionItem` de la spec 003. | RN-004-11, RN-004-12, AC-004-01, AC-004-15, §7 |
| 2026-10-17 | ¿En qué orden se evalúan las comprobaciones? | Validación → identidad → clave de reintento → transacción del cliente → transacción confirmada → disputa abierta. | RN-004-10, AC-004-08, AC-004-14, §7 |
| 2026-10-17 | ¿Qué validación tienen `idempotency_key` y `transaction_id`? | Obligatorios, de 1 a 64 caracteres tras recortar, sin restricción de juego de caracteres. | RN-004-09, AC-004-13, §7 |
| 2026-10-17 | ¿Qué alcance tiene la feature? | Solo el servidor MCP: herramienta, contrato, disputas persistidas con semillas, validación de identidad, idempotencia y auditoría. El agente, `DisputePolicy` y el escalamiento quedan fuera. | §2, §5, §8 |
| 2026-10-17 | ¿Se puede disputar una transacción de una tarjeta bloqueada o cancelada? | Sí: el estado de la tarjeta no importa, igual que en `consultar_transacciones`. | RN-004-04, AC-004-06 |

## 10. Preguntas abiertas

Ninguna.

## 11. Historial de cambios

| Versión | Fecha | Cambio | Autor |
|---|---|---|---|
| 0.1.0 | 2026-10-17 | Versión inicial a partir de la issue #29 | Juangiov (con Claude Code) |
| 0.1.0 | 2026-10-17 | Spec aprobada por el usuario | Juangiov |
| 0.2.0 | 2026-10-18 | Se añade `merchant_country` a `TransactionItem` en la salida (RN-004-12 y tabla de §7) (cambio compatible, spec [007](../007-dispute-resolution-agent/spec.md) §7.2, RN-007-30) | Juangiov (con Claude Code) |

---

## Gate de salida

- [x] No quedan preguntas abiertas.
- [x] Cada clarificación está reflejada en las secciones afectadas.
- [x] Todos los criterios de aceptación tienen ID y formato Given/When/Then.
- [x] Cada regla de negocio está cubierta por al menos un criterio de aceptación.
- [x] Contratos MCP y casos de escalamiento completos o marcados "No aplica".
- [x] Estado cambiado a **Aprobada**.
